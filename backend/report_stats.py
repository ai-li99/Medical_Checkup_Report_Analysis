"""由 DataFrame 计算体检报告的统计数据（全部确定性计算，交给 LLM 的只有事实）。"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import pandas as pd

from report_rules import RULES, age_series, gender_series, unmatched_columns

AGE_GROUPS: tuple[tuple[float, float, str], ...] = (
    (18, 30, "18-29岁"),
    (30, 40, "30-39岁"),
    (40, 50, "40-49岁"),
    (50, 60, "50-59岁"),
    (60, 200, "60岁及以上"),
)

UNMATCHED_PREVIEW = 10


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def _rate(abnormal: int, valid: int) -> float:
    if valid <= 0:
        return 0.0
    return _round(abnormal / valid * 100, 1)


def _date_text(series: pd.Series | None) -> tuple[str, str]:
    if series is None:
        return "", ""
    parsed = pd.to_datetime(series, errors="coerce").dropna()
    if parsed.empty:
        return "", ""
    return parsed.min().strftime("%Y-%m-%d"), parsed.max().strftime("%Y-%m-%d")


def _age_distribution(ages: pd.Series | None, total: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if ages is None or int(ages.notna().sum()) == 0:
        return {"min": None, "max": None, "mean": None}, []
    clean = ages.dropna()
    summary = {
        "min": int(clean.min()),
        "max": int(clean.max()),
        "mean": _round(float(clean.mean()), 1),
    }
    groups: list[dict[str, Any]] = []
    for low, high, label in AGE_GROUPS:
        count = int(((clean >= low) & (clean < high)).sum())
        groups.append({"label": label, "count": count, "ratio": _rate(count, total)})
    return summary, groups


def _breakdown(frame: pd.DataFrame) -> dict[str, Any]:
    """BMI 与血糖的分级细分，用于报告说明。"""
    extras: dict[str, Any] = {}
    bmi = pd.to_numeric(frame["体质指数"], errors="coerce") if "体质指数" in frame.columns else None
    if bmi is not None and int(bmi.notna().sum()) > 0:
        extras["bmi"] = {
            "valid": int(bmi.notna().sum()),
            "overweight": int(((bmi >= 24) & (bmi < 28)).sum()),
            "obese": int((bmi >= 28).sum()),
        }
    glucose_name = next(
        (name for name in ("空腹血糖", "葡萄糖", "血糖") if name in frame.columns), None
    )
    if glucose_name is not None:
        glucose = pd.to_numeric(frame[glucose_name], errors="coerce")
        if int(glucose.notna().sum()) > 0:
            extras["glucose"] = {
                "valid": int(glucose.notna().sum()),
                "impaired": int(((glucose >= 6.1) & (glucose < 7.0)).sum()),
                "diabetic_range": int((glucose >= 7.0).sum()),
            }
    return extras


def build_report_stats(
    frame: pd.DataFrame,
    *,
    unit_name: str,
    source_file: str,
    report_date: str,
    version: str,
    total_rows: int | None = None,
    focus_min: int = 5,
    focus_max: int = 8,
    min_valid: int = 10,
) -> dict[str, Any]:
    total = int(total_rows or len(frame))
    gender = gender_series(frame)
    ages = age_series(frame)

    male = int((gender == "男").sum()) if gender is not None else None
    female = int((gender == "女").sum()) if gender is not None else None
    age_summary, age_groups = _age_distribution(ages, total)

    check_date = next(
        (frame[name] for name in ("体检日期", "检查日期") if name in frame.columns), None
    )
    period_start, period_end = _date_text(check_date)

    # ---------- 规则判定 ----------
    results: list[dict[str, Any]] = []
    masks: dict[str, pd.Series] = {}
    skipped: list[str] = []
    for rule in RULES:
        abnormal, valid = rule.evaluate(frame)
        if abnormal is None or valid is None:
            continue
        valid = valid.fillna(False).astype(bool)
        abnormal = abnormal.fillna(False).astype(bool) & valid
        valid_count = int(valid.sum())
        if valid_count == 0:
            continue
        if valid_count < min_valid:
            skipped.append(rule.category)
            continue
        abnormal_count = int(abnormal.sum())
        masks[rule.category] = abnormal

        by_gender: list[dict[str, Any]] = []
        if gender is not None:
            for label in ("男", "女"):
                group_valid = valid & (gender == label).fillna(False)
                group_abnormal = abnormal & (gender == label).fillna(False)
                group_valid_count = int(group_valid.sum())
                if group_valid_count == 0:
                    continue
                by_gender.append(
                    {
                        "label": label,
                        "valid": group_valid_count,
                        "abnormal": int(group_abnormal.sum()),
                        "rate": _rate(int(group_abnormal.sum()), group_valid_count),
                    }
                )

        by_age: list[dict[str, Any]] = []
        if ages is not None:
            for low, high, label in AGE_GROUPS:
                in_group = (ages >= low) & (ages < high)
                group_valid = valid & in_group.fillna(False)
                group_valid_count = int(group_valid.sum())
                if group_valid_count == 0:
                    continue
                group_abnormal = abnormal & in_group.fillna(False)
                by_age.append(
                    {
                        "label": label,
                        "valid": group_valid_count,
                        "abnormal": int(group_abnormal.sum()),
                        "rate": _rate(int(group_abnormal.sum()), group_valid_count),
                    }
                )

        results.append(
            {
                "key": rule.key,
                "category": rule.category,
                "group": rule.group,
                "rule": rule.rule_text,
                "source": rule.source,
                "valid_count": valid_count,
                "abnormal_count": abnormal_count,
                "rate": _rate(abnormal_count, valid_count),
                "by_gender": by_gender,
                "by_age": by_age,
            }
        )

    results.sort(key=lambda item: item["abnormal_count"], reverse=True)

    # ---------- 数据完整性 ----------
    completeness: list[dict[str, Any]] = []
    group_categories: dict[str, list[str]] = {}
    for item in results:
        group_categories.setdefault(item["group"], []).append(item["category"])
    for group, categories in group_categories.items():
        matched = [item for item in results if item["group"] == group]
        valid_count = max(item["valid_count"] for item in matched)
        completeness.append(
            {
                "category": group,
                "expected": total,
                "valid": valid_count,
                "missing": max(0, total - valid_count),
                "items": "、".join(categories),
            }
        )

    # ---------- 共现 ----------
    cooccurrence: dict[str, Any] = {"people_with_two_or_more": 0, "ratio": 0.0, "top_pairs": []}
    if masks:
        stacked = pd.DataFrame(masks).fillna(False)
        counts = stacked.sum(axis=1)
        two_or_more = int((counts >= 2).sum())
        pairs: list[dict[str, Any]] = []
        for left, right in combinations(sorted(masks), 2):
            both = int((masks[left] & masks[right]).sum())
            if both > 0:
                pairs.append({"pair": [left, right], "count": both})
        pairs.sort(key=lambda item: item["count"], reverse=True)
        cooccurrence = {
            "people_with_two_or_more": two_or_more,
            "ratio": _rate(two_or_more, total),
            "top_pairs": pairs[:3],
        }

    # ---------- 数据缺口 ----------
    missing_parts = [
        f"{item['category']}有 {item['missing']} 人无有效结果"
        for item in completeness
        if item["missing"] > 0
    ]
    if skipped:
        missing_parts.append(
            f"以下指标有效数据不足 {min_valid} 人，未纳入统计：{'、'.join(skipped)}"
        )
    raw_unmatched = unmatched_columns(frame)
    if raw_unmatched:
        preview = "、".join(raw_unmatched[:UNMATCHED_PREVIEW])
        suffix = f" 等 {len(raw_unmatched)} 列" if len(raw_unmatched) > UNMATCHED_PREVIEW else ""
        missing_parts.append(f"以下列未纳入量化判定：{preview}{suffix}")
    missing_parts.append("单次检查结果不能代替临床诊断")

    focus = results[: max(1, focus_max)] if len(results) > focus_min else results

    return {
        "meta": {
            "unit_name": unit_name,
            "report_date": report_date,
            "version": version,
            "period_start": period_start,
            "period_end": period_end,
            "source_file": source_file,
            "total": total,
        },
        "people": {
            "total": total,
            "male": male,
            "female": female,
            "age_min": age_summary["min"],
            "age_max": age_summary["max"],
            "age_mean": age_summary["mean"],
            "age_groups": age_groups,
        },
        "focus": [
            {key: item[key] for key in ("category", "rule", "source", "valid_count", "abnormal_count", "rate", "by_gender", "by_age")}
            for item in focus
        ],
        "cooccurrence": cooccurrence,
        "data_gaps": missing_parts,
        "unmatched_columns": raw_unmatched,
        # 供 PDF 使用，不发给 LLM
        "all_abnormalities": results,
        "completeness": completeness,
        "extras": _breakdown(frame),
    }


def build_llm_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """只把 LLM 需要的事实发过去，避免长尾列名干扰。"""
    unmatched = stats.get("unmatched_columns") or []
    preview = unmatched[:UNMATCHED_PREVIEW]
    return {
        "meta": stats["meta"],
        "people": stats["people"],
        "focus": stats["focus"],
        "cooccurrence": stats["cooccurrence"],
        "data_gaps": stats["data_gaps"],
        "unmatched_columns": preview,
        "unmatched_total": len(unmatched),
    }
