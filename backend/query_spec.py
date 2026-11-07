"""把应用1 输出的 Query Spec 翻译成 pandas 操作。

设计原则：所有行为都按字段显式分发，绝不 eval / exec 任何由 LLM 生成的字符串。
"""

from __future__ import annotations

import json
import math
import numbers
import re
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from config import (
    CELL_MAX_CHARS,
    DEFAULT_QUERY_LIMIT,
    MAX_QUERY_LIMIT,
    MAX_RESULT_ROWS_FOR_LLM,
)


class SpecError(ValueError):
    """查询规格不合法（列不存在、算子不支持、值类型不对等）。"""


_DATE_HINT = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")

OPS = ("count", "list", "aggregate", "distinct", "unsupported")
OPERATORS = (
    "==",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
    "in",
    "not_in",
    "between",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "is_null",
    "not_null",
)
FUNCS = ("count", "count_distinct", "sum", "mean", "median", "min", "max", "std", "q25", "q75")
_TEXT_OPS = ("contains", "not_contains", "starts_with", "ends_with")
_AGG_NAMES = {
    "count": "count",
    "count_distinct": "nunique",
    "sum": "sum",
    "mean": "mean",
    "median": "median",
    "min": "min",
    "max": "max",
    "std": "std",
}


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _columns_hint(frame: pd.DataFrame) -> str:
    columns = [str(column) for column in frame.columns]
    if len(columns) <= 30:
        return "、".join(columns)
    return "、".join(columns[:30]) + f"…（共 {len(columns)} 列）"


def _unique_alias(name: str, taken: list[str]) -> str:
    base = name or "结果"
    candidate = base
    index = 2
    while candidate in taken:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _resolve_star_sort(spec: dict[str, Any], target: str) -> dict[str, Any]:
    """把 sort.column == "*"（= 按统计值排序）映射到具体的统计列。"""
    sort_config = spec.get("sort")
    if not isinstance(sort_config, dict):
        return spec
    if _text(sort_config.get("column")) != "*":
        return spec
    return {**spec, "sort": {**sort_config, "column": target}}


def _align_sort_column(
    spec: dict[str, Any], frame: pd.DataFrame, group_by: list[str]
) -> dict[str, Any]:
    """排序字段名不在结果里时，若结果只有一个数值列就自动对齐到它。

    LLM 常把聚合别名写成「人数」，而实际生成的是「计数」；这类只是排序
    依据的名字对不上，不影响统计值，这里做一个无歧义时的兜底。
    """
    sort_config = spec.get("sort")
    if not isinstance(sort_config, dict):
        return spec
    column = _text(sort_config.get("column"))
    if not column or column in frame.columns:
        return spec
    numeric = [
        str(name)
        for name in frame.columns
        if name not in group_by and pd.api.types.is_numeric_dtype(frame[name])
    ]
    if len(numeric) == 1:
        return {**spec, "sort": {**sort_config, "column": numeric[0]}}
    return spec


def _cell(value: Any) -> Any:
    """把单元格值转成可 JSON 序列化的值。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.datetime64):
        return str(pd.Timestamp(value).date())
    if isinstance(value, (pd.Timestamp, datetime, date)):
        try:
            return value.strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        number = float(value)
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else round(number, 4)
    text = str(value)
    return text if len(text) <= CELL_MAX_CHARS else text[: CELL_MAX_CHARS - 1] + "…"


# --------------------------------------------------------------------------
# 过滤条件
# --------------------------------------------------------------------------
def _prepare_series(series: pd.Series, value: Any) -> tuple[str, pd.Series]:
    """把列转换成与值可比较的类型，返回 (类型, 列)。"""
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime", series
    if pd.api.types.is_bool_dtype(series.dtype):
        return "bool", series
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "number", series

    hint = value[0] if isinstance(value, list) and value else value
    non_null = int(series.notna().sum())
    if isinstance(hint, str) and _DATE_HINT.match(hint.strip()):
        parsed = pd.to_datetime(series, errors="coerce")
        if int(parsed.notna().sum()) >= max(1, int(non_null * 0.6)):
            return "datetime", parsed
    numeric = pd.to_numeric(series, errors="coerce")
    if int(numeric.notna().sum()) >= max(1, int(non_null * 0.9)):
        return "number", numeric
    return "text", series.astype("string")


def _coerce(value: Any, kind: str) -> Any:
    """把过滤值转换成与列相同的类型。"""
    if kind == "datetime":
        if isinstance(value, (datetime, date, pd.Timestamp)):
            return pd.Timestamp(value)
        parsed = pd.to_datetime(_text(value), errors="coerce")
        if pd.isna(parsed):
            raise SpecError(f"「{value}」不是有效日期")
        return parsed
    if kind == "number":
        if isinstance(value, bool):
            raise SpecError(f"「{value}」不是数字")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise SpecError(f"「{value}」不是数字") from exc
        if not math.isfinite(number):
            raise SpecError(f"「{value}」不是有效数字")
        return int(number) if number.is_integer() else number
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = _text(value).lower()
        if text in ("true", "1", "是", "yes"):
            return True
        if text in ("false", "0", "否", "no"):
            return False
        raise SpecError(f"「{value}」不是布尔值")
    return _text(value)


def _filter_mask(frame: pd.DataFrame, item: Any, index: int) -> pd.Series:
    if not isinstance(item, dict):
        raise SpecError(f"filters 第 {index} 项必须是对象")
    column = _text(item.get("column"))
    operator = _text(item.get("operator")).lower()
    if not column:
        raise SpecError(f"filters 第 {index} 项缺少 column")
    if column not in frame.columns:
        raise SpecError(f"列「{column}」不存在；可用列：{_columns_hint(frame)}")
    if operator not in OPERATORS:
        raise SpecError(f"不支持的过滤运算符「{operator or '空'}」，允许值：{'、'.join(OPERATORS)}")

    series = frame[column]
    if operator == "is_null":
        return series.isna()
    if operator == "not_null":
        return series.notna()

    if "value" not in item or item.get("value") is None:
        raise SpecError(f"过滤条件「{column} {operator}」缺少 value")
    value = item["value"]

    if operator in _TEXT_OPS:
        text_series = series.astype("string")
        target = _text(value)
        if operator == "contains":
            return text_series.str.contains(target, regex=False, na=False)
        if operator == "not_contains":
            return ~text_series.str.contains(target, regex=False, na=False)
        if operator == "starts_with":
            return text_series.str.startswith(target, na=False)
        return text_series.str.endswith(target, na=False)

    kind, prepared = _prepare_series(series, value)

    if operator in ("in", "not_in"):
        if not isinstance(value, list) or not value:
            raise SpecError(f"运算符 {operator} 的 value 必须是非空数组")
        targets = [_coerce(element, kind) for element in value]
        mask = prepared.isin(targets)
        return mask if operator == "in" else ~mask

    if operator == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise SpecError("运算符 between 的 value 必须是 [下限, 上限] 两元素数组")
        low = _coerce(value[0], kind)
        high = _coerce(value[1], kind)
        return (prepared >= low) & (prepared <= high)

    target = _coerce(value, kind)
    if operator == "==":
        return prepared == target
    if operator == "!=":
        return prepared != target
    if operator == ">":
        return prepared > target
    if operator == ">=":
        return prepared >= target
    if operator == "<":
        return prepared < target
    return prepared <= target


def _apply_filters(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    filters = spec.get("filters")
    if filters in (None, []):
        return frame
    if not isinstance(filters, list):
        raise SpecError("filters 必须是数组")
    logic = _text(spec.get("filter_logic")).lower() or "and"
    if logic not in ("and", "or"):
        raise SpecError("filter_logic 只能是 and 或 or")
    mask: pd.Series | None = None
    for index, item in enumerate(filters):
        current = _filter_mask(frame, item, index)
        if mask is None:
            mask = current
        elif logic == "and":
            mask = mask & current
        else:
            mask = mask | current
    if mask is None:
        return frame
    return frame.loc[mask.fillna(False).astype(bool)]


# --------------------------------------------------------------------------
# 排序 / 列选择 / 聚合
# --------------------------------------------------------------------------
def _select_columns(spec: dict[str, Any], frame: pd.DataFrame) -> list[str]:
    raw = spec.get("select_columns")
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise SpecError("select_columns 必须是数组")
    columns: list[str] = []
    for item in raw:
        name = _text(item)
        if not name:
            continue
        if name not in frame.columns:
            raise SpecError(f"列「{name}」不存在；可用列：{_columns_hint(frame)}")
        if name not in columns:
            columns.append(name)
    return columns


def _group_columns(spec: dict[str, Any], frame: pd.DataFrame) -> list[str]:
    raw = spec.get("group_by")
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise SpecError("group_by 必须是数组")
    columns: list[str] = []
    for item in raw:
        name = _text(item)
        if not name:
            continue
        if name not in frame.columns:
            raise SpecError(f"分组列「{name}」不存在；可用列：{_columns_hint(frame)}")
        if name not in columns:
            columns.append(name)
    return columns


def _apply_sort(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    sort_config = spec.get("sort")
    if not isinstance(sort_config, dict):
        return frame
    column = _text(sort_config.get("column"))
    if not column:
        return frame
    ascending_raw = sort_config.get("ascending", True)
    if isinstance(ascending_raw, bool):
        ascending = ascending_raw
    else:
        ascending = _text(ascending_raw).lower() not in ("false", "0", "desc", "降序")
    if column not in frame.columns:
        if column == "*" and len(frame.columns):
            column = str(frame.columns[-1])
        else:
            raise SpecError(
                f"排序字段「{column}」不在结果里；可用：{'、'.join(str(c) for c in frame.columns)}"
            )
    try:
        return frame.sort_values(by=column, ascending=ascending, kind="stable", na_position="last")
    except (TypeError, ValueError) as exc:
        raise SpecError(f"按「{column}」排序失败：{exc}") from exc


def _limit(spec: dict[str, Any], default: int) -> int:
    raw = spec.get("limit")
    if raw is None or raw == "":
        return default
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"limit「{raw}」不是整数") from exc
    if limit <= 0:
        return default
    return min(limit, MAX_QUERY_LIMIT)


def _finalize(
    frame: pd.DataFrame, spec: dict[str, Any], default_limit: int
) -> tuple[pd.DataFrame, int]:
    frame = _apply_sort(frame, spec)
    total = int(len(frame))
    return frame.head(_limit(spec, default_limit)), total


def _agg_func(func: str) -> Any:
    if func == "q25":
        return lambda series: series.quantile(0.25)
    if func == "q75":
        return lambda series: series.quantile(0.75)
    return _AGG_NAMES[func]


def _scalar_agg(series: pd.Series, func: str) -> Any:
    if func == "q25":
        return series.quantile(0.25)
    if func == "q75":
        return series.quantile(0.75)
    name = _AGG_NAMES[func]
    if name == "nunique":
        return int(series.nunique(dropna=True))
    if name == "count":
        return int(series.count())
    try:
        return getattr(series, name)()
    except TypeError as exc:
        raise SpecError(f"列「{series.name}」无法执行聚合 {func}：{exc}") from exc


def _frame_result(kind: str, frame: pd.DataFrame, total: int) -> dict[str, Any]:
    preview = frame.head(MAX_RESULT_ROWS_FOR_LLM)
    rows = [
        [_cell(value) for value in row]
        for row in preview.itertuples(index=False, name=None)
    ]
    return {
        "kind": kind,
        "row_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "rows": rows,
        "truncated": int(total) > int(len(frame)) or len(frame) > len(preview),
    }


# --------------------------------------------------------------------------
# 各 op 的实现
# --------------------------------------------------------------------------
def _run_count(filtered: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    # count 里如果给了 aggregations（LLM 常见写法），按聚合处理，保留它自定的别名
    aggregations = spec.get("aggregations")
    if isinstance(aggregations, list) and aggregations:
        return _run_aggregate(filtered, spec)

    group_by = _group_columns(spec, filtered)
    if not group_by:
        count = int(len(filtered))
        return {
            "kind": "count",
            "row_count": 1,
            "columns": ["计数"],
            "rows": [[count]],
            "truncated": False,
            "value": count,
            "group_by": [],
        }
    frame = filtered.groupby(group_by, dropna=False).size().reset_index(name="计数")
    spec = _resolve_star_sort(spec, "计数")
    spec = _align_sort_column(spec, frame, group_by)
    frame, total = _finalize(frame, spec, DEFAULT_QUERY_LIMIT)
    result = _frame_result("count", frame, total)
    result["group_by"] = group_by
    return result


def _run_list(filtered: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    columns = _select_columns(spec, filtered)
    if not columns:
        columns = [str(column) for column in filtered.columns[: min(len(filtered.columns), 20)]]
    ordered = _apply_sort(filtered, spec)
    frame = ordered.loc[:, columns].head(_limit(spec, DEFAULT_QUERY_LIMIT))
    return _frame_result("list", frame, int(len(filtered)))


def _run_aggregate(filtered: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    raw_aggs = spec.get("aggregations")
    if not isinstance(raw_aggs, list) or not raw_aggs:
        raise SpecError("op=aggregate 时 aggregations 必须是非空数组")
    group_by = _group_columns(spec, filtered)

    aliases: list[str] = []
    values: dict[str, Any] = {}
    for index, agg in enumerate(raw_aggs):
        if not isinstance(agg, dict):
            raise SpecError(f"aggregations 第 {index} 项必须是对象")
        column = _text(agg.get("column"))
        func = _text(agg.get("func")).lower()
        if func not in FUNCS:
            raise SpecError(f"不支持的聚合函数「{func or '空'}」，允许值：{'、'.join(FUNCS)}")
        alias = _unique_alias(_text(agg.get("alias")) or f"{column or '行数'}_{func}", aliases + group_by)
        aliases.append(alias)

        if func == "count" and column in ("", "*"):
            if group_by and not filtered.empty:
                values[alias] = filtered.groupby(group_by, dropna=False).size()
            elif group_by:
                values[alias] = pd.Series(dtype="int64")
            else:
                values[alias] = int(len(filtered))
            continue
        if column in ("", "*"):
            raise SpecError(f"聚合函数 {func} 必须指定 column")
        if column not in filtered.columns:
            raise SpecError(f"列「{column}」不存在；可用列：{_columns_hint(filtered)}")
        if group_by and not filtered.empty:
            values[alias] = filtered.groupby(group_by, dropna=False)[column].agg(_agg_func(func))
        elif group_by:
            values[alias] = pd.Series(dtype="float64")
        else:
            values[alias] = None if filtered.empty else _scalar_agg(filtered[column], func)

    if group_by:
        if filtered.empty:
            frame = pd.DataFrame(columns=[*group_by, *aliases])
        else:
            frame = pd.DataFrame(values).reset_index()
    else:
        frame = pd.DataFrame([values])

    spec = _resolve_star_sort(spec, aliases[0])
    spec = _align_sort_column(spec, frame, group_by)
    frame, total = _finalize(frame, spec, DEFAULT_QUERY_LIMIT)
    result = _frame_result("aggregate", frame, total)
    result["group_by"] = group_by
    return result


def _run_distinct(filtered: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    columns = _select_columns(spec, filtered)
    if not columns:
        raise SpecError("op=distinct 时 select_columns 必须指定要统计的列")
    column = columns[0]
    counts = filtered[column].value_counts(dropna=False)
    frame = counts.rename("出现次数").rename_axis(column).reset_index()

    spec = _resolve_star_sort(spec, "出现次数")
    spec = _align_sort_column(spec, frame, [column])
    sort_config = spec.get("sort")
    if not (isinstance(sort_config, dict) and _text(sort_config.get("column"))):
        frame = frame.sort_values("出现次数", ascending=False, kind="stable")

    frame, total = _finalize(frame, spec, DEFAULT_QUERY_LIMIT)
    result = _frame_result("distinct", frame, total)
    result["group_by"] = [column]
    return result


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def execute(frame: pd.DataFrame, spec: Any) -> dict[str, Any]:
    """按查询规格执行，返回结构化结果；规格不合法时抛 SpecError。"""
    if not isinstance(spec, dict):
        raise SpecError("查询规格必须是一个 JSON 对象")
    op = _text(spec.get("op")).lower()
    if op not in OPS:
        raise SpecError(f"不支持的 op「{op or '空'}」，允许值：{'、'.join(OPS)}")
    note = _text(spec.get("note"))

    if op == "unsupported":
        return {
            "kind": "unsupported",
            "row_count": 0,
            "matched_rows": 0,
            "columns": [],
            "rows": [],
            "truncated": False,
            "group_by": [],
            "note": note,
            "reason": _text(spec.get("reason")) or "当前数据表缺少回答该问题所需的字段",
        }

    filtered = _apply_filters(frame, spec)
    if op == "count":
        result = _run_count(filtered, spec)
    elif op == "list":
        result = _run_list(filtered, spec)
    elif op == "aggregate":
        result = _run_aggregate(filtered, spec)
    else:
        result = _run_distinct(filtered, spec)

    result["matched_rows"] = int(len(filtered))
    result["note"] = note
    return result


def _markdown_table(columns: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        if value is None:
            return ""
        text = " ".join(str(value).split())
        text = text.replace("|", "\\|")
        return text[:CELL_MAX_CHARS]

    header = "| " + " | ".join(cell(column) for column in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return "\n".join([header, separator, *body]) if body else "\n".join([header, separator, "| （无数据） |"])


def _available_columns_text(columns: list[str] | None) -> str:
    if not columns:
        return ""
    shown = [str(column) for column in columns[:60]]
    text = "、".join(shown)
    if len(columns) > len(shown):
        text += f"…（共 {len(columns)} 列）"
    return "【数据表现有列】\n" + text


def format_for_llm(
    spec: dict[str, Any] | None,
    result: dict[str, Any] | None,
    error: str | None = None,
    columns: list[str] | None = None,
) -> str:
    """把查询规格 + 执行结果整理成给应用2 的 data 文本。"""
    spec = spec or {}
    sections: list[str] = [
        "【查询规格】\n" + json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
    ]
    available = _available_columns_text(columns)
    note = _text(spec.get("note")) or _text((result or {}).get("note"))
    if note:
        sections.append("【查询说明】\n" + note)

    if error:
        if available:
            sections.append(available)
        sections.append("【执行情况】\n查询执行失败，没有拿到数据。错误信息：" + error)
        sections.append(
            "请用中文向用户说明这次查询没能完成的原因，并给出一两个更明确的替代问法；"
            "只能使用【数据表现有列】里的字段，不要编造表中没有的字段。"
        )
        return "\n\n".join(sections)

    if result is None:
        sections.append("【执行情况】\n没有结果")
        return "\n\n".join(sections)

    if result.get("kind") == "unsupported":
        if available:
            sections.append(available)
        reason = _text(result.get("reason")) or "缺少对应字段"
        sections.append("【执行情况】\n该问题无法基于当前数据表回答。原因：" + reason)
        sections.append(
            "请用中文向用户说明表里缺少哪些数据，并建议可以改问什么；"
            "替代问法只能使用【数据表现有列】里出现过的字段，绝对不要编造表中没有的指标。"
        )
        return "\n\n".join(sections)

    matched = int(result.get("matched_rows") or 0)
    returned = int(result.get("row_count") or 0)
    status = f"过滤后命中 {matched} 行；本次返回 {returned} 行"
    if result.get("truncated"):
        status += f"（结果超出返回上限，已截断为前 {returned} 行）"
    sections.append("【执行情况】\n" + status)

    scalar_count = result.get("kind") == "count" and not result.get("group_by")
    if scalar_count:
        sections.append("【统计结果】\n" + str(result.get("value")))

    columns = result.get("columns") or []
    rows = result.get("rows") or []
    if columns and not scalar_count:
        sections.append("【结果数据】\n" + _markdown_table(columns, rows))

    sections.append(
        "以上是本次查询真实命中 / 计算出的数据。请严格基于这些数据回答用户问题；"
        "数据为空或行数很少时要如实说明，不要补造数字。"
    )
    return "\n\n".join(sections)
