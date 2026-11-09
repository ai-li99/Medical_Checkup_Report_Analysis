"""接口的请求 / 响应模型（Pydantic）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- 认证 ----------
class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=200)


class UserInfo(BaseModel):
    user_id: int
    username: str
    created_at: str


class AuthResponse(UserInfo):
    token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LogoutRequest(BaseModel):
    refresh_token: str = ""


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=200)
    old_password: str = Field(default="", max_length=200)


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
    turn_id: int = 0


# ---------- 历史记录 ----------
class HistorySessionItem(BaseModel):
    session_id: str
    filename: str
    rows: int
    columns: int
    turn_count: int
    last_question: str = ""
    last_asked_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class HistorySessionsResponse(BaseModel):
    total: int
    items: list[HistorySessionItem] = Field(default_factory=list)


class TurnSummary(BaseModel):
    turn_id: int
    question: str
    answer_preview: str = ""
    degraded: bool = False
    created_at: str = ""


class SessionTurnsResponse(BaseModel):
    session_id: str
    filename: str
    rows: int
    columns: int
    turns: list[TurnSummary] = Field(default_factory=list)


class TurnDetailResponse(BaseModel):
    turn_id: int
    session_id: str
    question: str
    answer: str
    query_spec: dict[str, Any] | None = None
    result: QueryResult | None = None
    degraded: bool = False
    error: str = ""
    elapsed_ms: int = 0
    created_at: str = ""


class ResumeResponse(BaseModel):
    session_id: str
    filename: str
    row_count: int
    column_count: int
    columns: list[ColumnInfo] = Field(default_factory=list)
    conversation_id: str = ""
    turns: list[TurnSummary] = Field(default_factory=list)
    message: str = ""


class DeleteSessionResponse(BaseModel):
    detail: str
    session_id: str
    deleted_turns: int
    file_removed: bool
