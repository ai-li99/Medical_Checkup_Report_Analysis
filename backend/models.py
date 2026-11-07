"""接口的请求 / 响应模型（Pydantic）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- 文件 ----------
class SheetInfo(BaseModel):
    name: str
    rows: int
    columns: int


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    non_null: int
    missing: int
    sample: list[str] = Field(default_factory=list)


class UploadFileResponse(BaseModel):
    session_id: str
    file_id: str
    filename: str
    type: Literal["xlsx", "csv"]
    needs_sheet_selection: bool
    sheets: list[SheetInfo] = Field(default_factory=list)
    selected_sheets: list[str] = Field(default_factory=list)
    rows: int = 0
    columns: list[ColumnInfo] = Field(default_factory=list)
    message: str = ""


# ---------- 工作表选择 ----------
class SelectSheetsRequest(BaseModel):
    session_id: str = Field(min_length=1)
    mode: Literal["merge_all", "select"] = "select"
    sheets: list[str] = Field(default_factory=list)


class SelectSheetsResponse(BaseModel):
    session_id: str
    mode: Literal["merge_all", "select"]
    selected_sheets: list[str]
    merged: bool
    rows: int
    columns: list[ColumnInfo]
    message: str = ""


# ---------- 提问 / 提交 ----------
class UploadMessageRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)


class UploadMessageResponse(BaseModel):
    session_id: str
    message_id: str
    message: str


class SubmitRequest(BaseModel):
    session_id: str = Field(min_length=1)


class QueryResult(BaseModel):
    kind: str
    row_count: int
    matched_rows: int = 0
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    truncated: bool = False
    value: Any = None
    group_by: list[str] = Field(default_factory=list)
    note: str = ""
    reason: str = ""


class SubmitResponse(BaseModel):
    session_id: str
    message: str
    answer: str
    query_spec: dict[str, Any] | None = None
    raw_output: str = ""
    result: QueryResult | None = None
    conversation_id: str = ""
    degraded: bool = False
    error: str = ""
    elapsed_ms: int = 0
