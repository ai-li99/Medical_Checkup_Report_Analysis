"""报告叙述：调用应用3 生成文字，并对输出做结构与数字校验。

校验不过就回退到模板文字（放弃 LLM 输出），保证 PDF 里的数字永远来自统计结果。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import dify_client
from report_stats import build_llm_payload

logger = logging.getLogger(__name__)

REQUIRED_FIELDS: dict[str, type] = {
    "summary": str,
    "key_findings": list,
    "priority_actions": list,
    "problem_insights": list,
    "group_observation": str,
    "review_plan": str,
    "management_advice": dict,
    "conclusion": str,
    "limitations": str,
}

_ADVICE_KEYS = ("short_term", "collective", "next_checkup")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    found: set[str] = set()
    for raw in _NUMBER_RE.findall(text or ""):
        found.add(raw)
        if "." in raw:
            found.add(raw.rstrip("0").rstrip("."))
    return found


def _shape_problems(narrative: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key, kind in REQUIRED_FIELDS.items():
        if not isinstance(narrative.get(key), kind):
            problems.append(f"{key} 类型错误")
    advice = narrative.get("management_advice")
    if isinstance(advice, dict):
        for key in _ADVICE_KEYS:
            if not str(advice.get(key) or "").strip():
                problems.append(f"management_advice.{key} 为空")
    insights = narrative.get("problem_insights")
    if isinstance(insights, list):
        for item in insights:
            if not isinstance(item, dict) or not str(item.get("category") or "").strip():
                problems.append("problem_insights 存在缺少 category 的条目")
    return problems


def validate_narrative(narrative: dict[str, Any], stats: dict[str, Any]) -> list[str]:
    problems = _shape_problems(narrative)

    allowed = _numbers(json.dumps(stats, ensure_ascii=False))
    used = _numbers(json.dumps(narrative, ensure_ascii=False))
    extra = sorted(used - allowed)
    if extra:
        problems.append("出现统计数据中没有的数字：" + "、".join(extra[:10]))

    focus_categories = [item["category"] for item in stats.get("focus") or []]
    got_categories = [
        item.get("category") for item in narrative.get("problem_insights") or [] if isinstance(item, dict)
    ]
    if got_categories and got_categories != focus_categories:
        problems.append("problem_insights 与 focus 的类别或顺序不一致")
    return problems


async def build_narrative(stats: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """返回 (叙述, 问题列表)；任何校验失败都会返回 None，让 PDF 用模板文字。"""
    payload = build_llm_payload(stats)
    raw = await dify_client.run_report_workflow(json.dumps(payload, ensure_ascii=False))
    narrative = dify_client.extract_json_object(raw)
    if not isinstance(narrative, dict):
        return None, ["应用3 未返回可解析的 JSON"]
    problems = validate_narrative(narrative, stats)
    if problems:
        logger.warning("报告叙述校验未通过，已回退模板文字：%s", "；".join(problems))
        return None, problems
    return narrative, []
