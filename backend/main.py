"""体检报告分析后端。

主流程：
    1. POST /api/upload_file   上传 .xlsx / .csv，落盘并解析
    2. POST /api/select_sheets 多工作表时选择「合并全部」或「指定若干个」
    3. POST /api/upload_message 提交本轮问题
    4. POST /api/submit        应用1 生成 JSON 查询规格 -> pandas 执行
                               -> 结果交给应用2 -> 返回自然语言回答

说明：查询语句完全由后端按 JSON 规格拼装，不执行任何 LLM 生成的代码。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import auth
import auth_store
import chat_store
import config
import file_store
from dify_client import DifyError, chat, extract_json_object, run_workflow
from models import (
    AuthResponse,
    HistorySessionItem,
    HistorySessionsResponse,
    LoginRequest,
    LogoutRequest,
    QueryResult,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResumeResponse,
    SelectSheetsRequest,
    SelectSheetsResponse,
    SessionTurnsResponse,
    SheetInfo,
    SubmitRequest,
    SubmitResponse,
    TokenPairResponse,
    TurnDetailResponse,
    TurnSummary,
    UploadFileResponse,
    UploadMessageRequest,
    UploadMessageResponse,
)
from query_spec import SpecError, execute, format_for_llm


@asynccontextmanager
async def lifespan(_: FastAPI):
    file_store.ensure_upload_dir()
    auth_store.init_db()
    chat_store.init_db()
    yield


app = FastAPI(title=config.API_TITLE, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DifyError)
async def _handle_dify_error(_: Any, exc: DifyError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(file_store.SessionNotFoundError)
async def _handle_session_not_found(_: Any, exc: file_store.SessionNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(auth.AuthError)
async def _handle_auth_error(_: Any, exc: auth.AuthError) -> JSONResponse:
    payload: dict[str, Any] = {"detail": exc.detail}
    if exc.code:
        payload["code"] = exc.code
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers or None)


# --------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def _validate_credentials(username: str, password: str) -> str:
    """返回空字符串表示合法，否则返回可直接展示的错误文案。"""
    if not _USERNAME_RE.match(username):
        return "用户名需为 3-32 位字母、数字或下划线"
    if len(password) < config.AUTH_PASSWORD_MIN:
        return f"密码至少 {config.AUTH_PASSWORD_MIN} 位"
    if len(password) > config.AUTH_PASSWORD_MAX:
        return f"密码最多 {config.AUTH_PASSWORD_MAX} 位"
    return ""


def _validate_new_password(password: str) -> str:
    if len(password) < config.AUTH_PASSWORD_MIN:
        return f"密码至少 {config.AUTH_PASSWORD_MIN} 位"
    if len(password) > config.AUTH_PASSWORD_MAX:
        return f"密码最多 {config.AUTH_PASSWORD_MAX} 位"
    return ""


def _auth_response(user: dict[str, Any]) -> AuthResponse:
    tokens = auth.issue_tokens(user)
    return AuthResponse(
        user_id=user["user_id"],
        username=user["username"],
        created_at=user["created_at"],
        token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type="bearer",
        expires_in=tokens["expires_in"],
    )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest) -> AuthResponse:
    username = payload.username.strip()
    error = _validate_credentials(username, payload.password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    if auth_store.get_user_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    try:
        user = auth_store.create_user(username, auth.hash_password(payload.password))
    except auth_store.UsernameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _auth_response(user)


@app.post("/api/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request) -> AuthResponse:
    username = payload.username.strip()
    ip = _client_ip(request)

    locked_until = auth.login_lock(username, ip)
    if locked_until is not None:
        raise auth.AuthError(
            "登录失败次数过多，请稍后再试",
            status_code=429,
            code="login_locked",
            headers={"Retry-After": str(max(1, locked_until - int(time.time())))},
        )

    user = auth_store.get_user_by_username(username)
    # 用户不存在与密码错误返回同一提示，避免被用来枚举账号
    if user is None or not auth.verify_password(payload.password, user["password_hash"]):
        lock_until = auth.record_login_failure(username, ip)
        if lock_until is not None:
            raise auth.AuthError(
                f"登录失败次数过多，请 {max(1, config.AUTH_LOGIN_LOCK_SECONDS // 60)} 分钟后再试",
                status_code=429,
                code="login_locked",
                headers={"Retry-After": str(max(1, lock_until - int(time.time())))},
            )
        raise auth.AuthError("用户名或密码错误", status_code=401, code="bad_credentials")

    auth.clear_login_failures(username, ip)
    return _auth_response(user)


@app.post("/api/refresh", response_model=TokenPairResponse)
def refresh_tokens(payload: RefreshRequest) -> TokenPairResponse:
    try:
        pair = auth.rotate_refresh(payload.refresh_token)
    except auth.InvalidRefreshToken as exc:
        raise auth.AuthError("登录已过期，请重新登录", status_code=401, code="refresh_invalid") from exc
    return TokenPairResponse(**pair)


@app.post("/api/logout")
def logout(
    payload: LogoutRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> dict[str, Any]:
    if payload.refresh_token:
        revoked = auth.revoke_refresh(payload.refresh_token, user["user_id"])
    else:
        revoked = auth.revoke_all_refresh(user["user_id"]) > 0
    return {"detail": "已退出登录", "revoked": bool(revoked)}


@app.post("/api/password/reset")
def reset_password(
    payload: ResetPasswordRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """同一个接口两种模式：带有效令牌=已登录直接重置；未登录=需要邮箱验证（暂未开放）。"""
    user = auth.try_get_current_user(authorization)
    if user is None:
        raise auth.AuthError(
            "未登录重置密码需邮箱验证，注册升级后开放",
            status_code=501,
            code="reset_requires_login",
        )
    if payload.old_password and not auth.verify_password(
        payload.old_password, user["password_hash"]
    ):
        raise auth.AuthError("原密码不正确", status_code=400, code="old_password_mismatch")
    error = _validate_new_password(payload.new_password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    if auth.verify_password(payload.new_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    auth.change_password(user["user_id"], payload.new_password)
    return {"detail": "密码已重置，请重新登录"}


def _upload_response(session: file_store.Session) -> UploadFileResponse:
    sheets = [SheetInfo(**info) for info in session.sheet_infos()]
    if session.df is None:
        return UploadFileResponse(
            session_id=session.session_id,
            file_id=session.file_id,
            filename=session.filename,
            type=session.kind,
            needs_sheet_selection=True,
            sheets=sheets,
            selected_sheets=[],
            rows=0,
            columns=[],
            message=f"该文件含 {len(sheets)} 个工作表，请选择要分析的工作表（合并全部或指定若干个）",
        )
    return UploadFileResponse(
        session_id=session.session_id,
        file_id=session.file_id,
        filename=session.filename,
        type=session.kind,
        needs_sheet_selection=False,
        sheets=sheets,
        selected_sheets=session.selected_sheets,
        rows=int(len(session.df)),
        columns=session.columns_info,
        message=f"已载入 {len(session.df)} 行 × {len(session.df.columns)} 列，可以开始提问",
    )


_OPERATOR_LABELS = {
    "==": "=",
    "!=": "≠",
    ">": ">",
    ">=": "≥",
    "<": "<",
    "<=": "≤",
    "contains": "包含",
    "not_contains": "不包含",
    "starts_with": "以…开头",
    "ends_with": "以…结尾",
    "in": "属于",
    "not_in": "不属于",
    "between": "介于",
}


def _describe_filters(spec: dict[str, Any] | None) -> str:
    """把规格里的 filters 拼成一句人话，作为「上一轮查询范围」的锚点。"""
    if not isinstance(spec, dict):
        return ""
    filters = spec.get("filters")
    if not isinstance(filters, list) or not filters:
        return ""
    parts: list[str] = []
    for item in filters:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column") or "").strip()
        operator = str(item.get("operator") or "").strip()
        value = item.get("value")
        if not column:
            continue
        if operator in ("is_null", "not_null"):
            parts.append(f"{column} {'为空' if operator == 'is_null' else '不为空'}")
        elif isinstance(value, list):
            joined = "、".join(str(element) for element in value)
            parts.append(f"{column} {_OPERATOR_LABELS.get(operator, operator)} [{joined}]")
        else:
            parts.append(f"{column} {_OPERATOR_LABELS.get(operator, operator)} {value}")
    logic = " 或 " if str(spec.get("filter_logic") or "and").lower() == "or" else " 且 "
    return logic.join(parts)


def _history_block(index: int, turn: dict[str, Any]) -> str:
    """把一轮历史整理成「问题 + 查询规格」：历史问题截断，查询规格完整保留。"""
    question = str(turn.get("question") or "").strip()
    limit = max(20, config.APP1_CONTEXT_QUESTION_CHARS)
    if len(question) > limit:
        question = question[: limit - 1] + "…"
    lines = [f"第 {index} 轮问题：{question}"]
    spec = turn.get("query_spec")
    if spec:
        spec_text = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
        lines.append(f"第 {index} 轮查询规格：{spec_text}")
    return "\n".join(lines)


def _scope_line(turn: dict[str, Any] | None) -> str:
    """生成「上一轮查询范围」摘要，给指代一个明确锚点。"""
    spec = (turn or {}).get("query_spec") or {}
    summary = _describe_filters(spec)
    matched = (turn or {}).get("matched_rows")
    suffix = f"（过滤后 {matched} 行）" if isinstance(matched, int) else ""
    if summary:
        return f"【上一轮查询范围】{summary}{suffix}"
    return f"【上一轮查询范围】全表，未加筛选{suffix}"


def _build_query_with_context(question: str, history: list[dict[str, Any]]) -> str:
    """给应用1 的 user_query 补上对话上下文（按字符预算截断，不按轮数）。

    应用1 没有开启记忆，单独看「那他们的平均年龄是多少」无法知道「他们」是谁；
    带上最近几轮的问题与查询规格，并附上一轮筛选范围的摘要，实测可以正确继承条件。
    预算只约束历史部分，当前问题永远完整发送。
    """
    if not history:
        return question

    budget = max(200, config.APP1_CONTEXT_MAX_CHARS)
    blocks: list[str] = []
    used = 0
    # 从最近一轮往前累加，装不下就停；最近一轮无论如何都保留
    for index in range(len(history), 0, -1):
        turn = history[index - 1]
        if not str(turn.get("question") or "").strip():
            continue
        block = _history_block(index, turn)
        if blocks and used + len(block) > budget:
            break
        blocks.insert(0, block)
        used += len(block)

    if not blocks:
        return question

    return (
        f"【本轮问题】{question}\n\n"
        "【对话上下文（问题里出现「他们/她们/这些人/其中/上面/刚才」等指代时，"
        "必须沿用上下文中最近一次的筛选条件；只有当本轮换了新的分析主题时，才不要沿用旧条件）】\n"
        + "\n".join(blocks)
        + "\n"
        + _scope_line(history[-1])
    )


@app.get("/api/healthy")
def get_health() -> dict[str, Any]:
    return {
        "healthy": True,
        "dify_base_url": config.DIFY_BASE_URL,
        "app_ready": bool(config.DIFY_APP1_KEY and config.DIFY_APP2_KEY),
    }


@app.post("/api/upload_file", response_model=UploadFileResponse)
async def upload_file(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> UploadFileResponse:
    filename = (file.filename or "upload").strip() or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in config.ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型「{suffix or '无扩展名'}」，仅支持 .xlsx 和 .csv",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的文件内容为空")
    limit_mb = config.MAX_UPLOAD_BYTES // 1024 // 1024
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"文件大小超过 {limit_mb} MB 上限")
    try:
        session = await run_in_threadpool(
            file_store.create_session, filename, data, user_id=user["user_id"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _upload_response(session)


@app.post("/api/select_sheets", response_model=SelectSheetsResponse)
async def select_sheets(
    payload: SelectSheetsRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> SelectSheetsResponse:
    session = file_store.get_session(payload.session_id, user_id=user["user_id"])
    try:
        await run_in_threadpool(
            file_store.apply_sheet_selection, session, payload.mode, payload.sheets
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    frame = session.df
    rows = int(len(frame)) if frame is not None else 0
    columns = int(len(frame.columns)) if frame is not None else 0
    return SelectSheetsResponse(
        session_id=session.session_id,
        mode=payload.mode,
        selected_sheets=session.selected_sheets,
        merged=session.merged,
        rows=rows,
        columns=session.columns_info,
        message=f"已载入 {rows} 行 × {columns} 列，可以开始提问",
    )


@app.post("/api/upload_message", response_model=UploadMessageResponse)
def upload_message(
    payload: UploadMessageRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> UploadMessageResponse:
    session = file_store.get_session(payload.session_id, user_id=user["user_id"])
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="问题不能为空")
    session.pending_message = text
    session.message_id = f"m_{uuid.uuid4().hex[:10]}"
    return UploadMessageResponse(
        session_id=session.session_id,
        message_id=session.message_id,
        message=text,
    )


@app.post("/api/submit", response_model=SubmitResponse)
async def submit(
    payload: SubmitRequest,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> SubmitResponse:
    started = time.perf_counter()
    session = file_store.get_session(payload.session_id, user_id=user["user_id"])
    frame = session.df
    if frame is None:
        raise HTTPException(
            status_code=400, detail="请先选择要分析的工作表（调用 /api/select_sheets）"
        )
    question = session.pending_message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="请先通过 /api/upload_message 提交问题")

    spec: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error = ""
    raw_output = ""

    query_for_app1 = _build_query_with_context(question, session.history)
    try:
        raw_output = await run_workflow(session.schema_card, query_for_app1)
    except DifyError as exc:
        raise DifyError(f"应用1 调用失败：{exc}") from exc

    try:
        spec = extract_json_object(raw_output)
        if spec is None:
            raise SpecError("应用1 没有返回可解析的 JSON 查询规格")
        result = await run_in_threadpool(execute, frame, spec)
    except (SpecError, ValueError) as exc:
        error = str(exc)
        result = None

    data_text = format_for_llm(
        spec, result, error=error or None, columns=[str(column) for column in frame.columns]
    )
    try:
        reply = await chat(question, data_text, session.conversation_id, session.dify_user_id)
    except DifyError as exc:
        raise DifyError(f"应用2 调用失败：{exc}") from exc

    session.conversation_id = reply["conversation_id"] or session.conversation_id
    session.history.append(
        {
            "time": time.time(),
            "question": question,
            "answer": reply["answer"],
            "query_spec": spec,
            "kind": (result or {}).get("kind", ""),
            "matched_rows": int((result or {}).get("matched_rows") or 0),
        }
    )
    if len(session.history) > 50:
        session.history = session.history[-50:]
    session.pending_message = ""

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    turn_id = chat_store.add_turn(
        session_id=session.session_id,
        user_id=user["user_id"],
        question=question,
        answer=reply["answer"],
        query_spec=spec,
        result=result,
        matched_rows=int((result or {}).get("matched_rows") or 0),
        degraded=bool(error),
        error=error,
        elapsed_ms=elapsed_ms,
    )
    chat_store.update_conversation(session.session_id, session.conversation_id)

    return SubmitResponse(
        session_id=session.session_id,
        message=question,
        answer=reply["answer"],
        query_spec=spec,
        raw_output=raw_output,
        result=QueryResult(**result) if result is not None else None,
        conversation_id=session.conversation_id,
        degraded=bool(error),
        error=error,
        elapsed_ms=elapsed_ms,
        turn_id=turn_id,
    )


# --------------------------------------------------------------------------
# 历史记录
# --------------------------------------------------------------------------
@app.get("/api/history", response_model=HistorySessionsResponse)
def list_history(
    limit: int | None = Query(default=None, ge=1, le=config.HISTORY_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> HistorySessionsResponse:
    page_size = limit or config.HISTORY_PAGE_SIZE
    total, items = chat_store.list_sessions(user["user_id"], page_size, offset)
    return HistorySessionsResponse(
        total=total, items=[HistorySessionItem(**item) for item in items]
    )


@app.get("/api/sessions/{session_id}/turns", response_model=SessionTurnsResponse)
def list_session_turns(
    session_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> SessionTurnsResponse:
    row = chat_store.get_session_row(session_id)
    if row is None or int(row["user_id"] or 0) != int(user["user_id"]):
        raise HTTPException(status_code=404, detail="会话不存在")
    turns = chat_store.list_turns(session_id)
    return SessionTurnsResponse(
        session_id=session_id,
        filename=row["filename"],
        rows=int(row["row_count"] or 0),
        columns=int(row["column_count"] or 0),
        turns=[TurnSummary(**turn) for turn in turns],
    )


@app.get("/api/history/{turn_id}", response_model=TurnDetailResponse)
def get_history_turn(
    turn_id: int,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> TurnDetailResponse:
    row = chat_store.get_turn(turn_id, user["user_id"])
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")

    spec: dict[str, Any] | None = None
    if row["query_spec"]:
        try:
            loaded = json.loads(row["query_spec"])
            spec = loaded if isinstance(loaded, dict) else None
        except (TypeError, ValueError):
            spec = None

    result: QueryResult | None = None
    if row["result"]:
        try:
            payload = json.loads(row["result"])
            result = QueryResult(**payload) if isinstance(payload, dict) else None
        except (TypeError, ValueError):
            result = None

    return TurnDetailResponse(
        turn_id=int(row["id"]),
        session_id=row["session_id"],
        question=row["question"],
        answer=row["answer"],
        query_spec=spec,
        result=result,
        degraded=bool(row["degraded"]),
        error=row["error"] or "",
        elapsed_ms=int(row["elapsed_ms"] or 0),
        created_at=row["created_at"] or "",
    )


@app.post("/api/sessions/{session_id}/resume", response_model=ResumeResponse)
def resume_session(
    session_id: str,
    user: dict[str, Any] = Depends(auth.get_current_user),
) -> ResumeResponse:
    session = file_store.get_session(session_id, user_id=user["user_id"])
    turns = chat_store.list_turns(session_id)
    frame = session.df
    return ResumeResponse(
        session_id=session.session_id,
        filename=session.filename,
        row_count=int(len(frame)) if frame is not None else 0,
        column_count=int(len(frame.columns)) if frame is not None else 0,
        columns=session.columns_info,
        conversation_id=session.conversation_id,
        turns=[TurnSummary(**turn) for turn in turns],
        message="会话已恢复，可以继续提问" if frame is not None else "请先选择要使用的工作表",
    )
