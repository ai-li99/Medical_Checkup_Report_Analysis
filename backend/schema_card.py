"""把 DataFrame 转成给应用1 看的「表结构卡片」（schema_card）。

应用1 只看到表结构、看不到真实数据，所以这里要把列名、类型、缺失、
取值范围 / 样例尽量描述清楚，让 LLM 生成的查询规格不会指错列。
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from config import SCHEMA_MAX_COLUMNS, SCHEMA_SAMPLE_ROWS
from models import ColumnInfo


def _dtype_label(dtype: Any) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "布尔"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "日期"
    if pd.api.types.is_integer_dtype(dtype):
        return "整数"
    if pd.api.types.is_float_dtype(dtype):
        return "小数"
    if pd.api.types.is_numeric_dtype(dtype):
        return "数值"
    return "文本"


def _fmt_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return "无"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _value_text(value: Any, limit: int = 20) -> str:
    if hasattr(value, "strftime"):
        try:
            text = value.strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _samples(series: pd.Series, limit: int) -> list[str]:
    values: list[str] = []
    for value in series.dropna().head(200):
        text = _value_text(value)
        if text and text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def column_infos(frame: pd.DataFrame) -> list[ColumnInfo]:
    """给接口返回用的列信息。"""
    infos: list[ColumnInfo] = []
    for name in frame.columns:
        series = frame[name]
        non_null = int(series.notna().sum())
        infos.append(
            ColumnInfo(
                name=str(name),
                dtype=_dtype_label(series.dtype),
                non_null=non_null,
                missing=int(len(series)) - non_null,
                sample=_samples(series, SCHEMA_SAMPLE_ROWS),
            )
        )
    return infos


def _describe_column(series: pd.Series) -> str:
    parts = [f"非空{int(series.notna().sum())}", f"缺失{int(series.isna().sum())}"]
    non_null = int(series.notna().sum())
    if pd.api.types.is_bool_dtype(series.dtype):
        if non_null:
            counts = series.value_counts(dropna=True)
            parts.append("取值: " + ", ".join(f"{_value_text(k, 8)}({int(v)})" for k, v in counts.items()))
    elif pd.api.types.is_numeric_dtype(series.dtype):
        if non_null:
            parts.append(f"最小{_fmt_number(series.min())}")
            parts.append(f"最大{_fmt_number(series.max())}")
            parts.append(f"均值{_fmt_number(series.mean())}")
    elif pd.api.types.is_datetime64_any_dtype(series.dtype):
        if non_null:
            parts.append(f"最早{_value_text(series.min(), 12)}")
            parts.append(f"最晚{_value_text(series.max(), 12)}")
    else:
        unique = int(series.nunique(dropna=True))
        parts.append(f"唯一值{unique}")
        if 0 < unique <= 12:
            counts = series.value_counts(dropna=True).head(12)
            parts.append("取值: " + ", ".join(f"{_value_text(k, 12)}({int(v)})" for k, v in counts.items()))
        else:
            values = _samples(series, 5)
            if values:
                parts.append("示例: " + ", ".join(values))
    return " | ".join(parts)


def build_schema_card(
    frame: pd.DataFrame,
    filename: str,
    selected_sheets: list[str],
    merged: bool,
) -> str:
    """生成给应用1 的 schema_card 文本。"""
    lines: list[str] = []
    lines.append("【数据表结构】以下由系统自动生成，只描述表结构，不是完整数据。")
    lines.append("")
    lines.append(f"表名：{filename}")
    if merged:
        sheets_text = "、".join(selected_sheets)
        lines.append(f"来源：合并 {len(selected_sheets)} 个工作表（{sheets_text}）")
        lines.append("说明：合并后的数据含 `_sheet` 列，标记每行来自哪个工作表。")
    elif selected_sheets:
        lines.append(f"来源：工作表「{selected_sheets[0]}」")
    else:
        lines.append("来源：单个数据表")
    lines.append(f"总行数：{len(frame)}")
    lines.append(f"列数：{len(frame.columns)}")
    lines.append("")
    lines.append("列信息（序号 | 列名 | 类型 | 数据概况）：")
    for index, name in enumerate(frame.columns, start=1):
        if index > SCHEMA_MAX_COLUMNS:
            lines.append(f"...（共 {len(frame.columns)} 列，此处只列出前 {SCHEMA_MAX_COLUMNS} 列）")
            break
        series = frame[name]
        lines.append(f"{index}. {name} | {_dtype_label(series.dtype)} | {_describe_column(series)}")
    lines.append("")
    lines.append("提示：查询时列名必须与上表逐字一致；表里没有的指标不要编造，无法回答时用 unsupported。")
    return "\n".join(lines)
