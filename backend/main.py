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
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import config
import file_store
from dify_client import DifyError, chat, extract_json_object, run_workflow
from models import (
    QueryResult,
    SelectSheetsRequest,
    SelectSheetsResponse,
    SheetInfo,
    SubmitRequest,
    SubmitResponse,
    UploadFileResponse,
    UploadMessageRequest,
    UploadMessageResponse,
)
from query_spec import SpecError, execute, format_for_llm


@asynccontextmanager
async def lifespan(_: FastAPI):
    file_store.ensure_upload_dir()
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


def _build_query_with_context(question: str, history: list[dict[str, Any]]) -> str:
    """给应用1 的 user_query 补上最近两轮上下文。

    应用1 没有开启记忆，单独看「那他们的平均年龄是多少」无法知道「他们」是谁；
    把上一轮的问题与查询规格一起带上，实测可以正确继承筛选条件。
    同时明确告诉它：独立的新问题不要沿用旧过滤条件。
    """
    recent = [item for item in history[-2:] if item.get("question")]
    if not recent:
        return question
    start_index = len(history) - len(recent) + 1
    lines = [
        f"【本轮问题】{question}",
        "",
        "【对话上下文（仅供理解「他们/这些/其中」等指代；若本轮是独立的新问题，请不要沿用上一轮的过滤条件）】",
    ]
    for offset, item in enumerate(recent):
        lines.append(f"第 {start_index + offset} 轮问题：{item['question']}")
        spec = item.get("query_spec")
        if spec:
            spec_text = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"第 {start_index + offset} 轮查询规格：{spec_text}")
    return "\n".join(lines)


@app.get("/api/healthy")
def get_health() -> dict[str, Any]:
    return {
        "healthy": True,
        "dify_base_url": config.DIFY_BASE_URL,
        "app_ready": bool(config.DIFY_APP1_KEY and config.DIFY_APP2_KEY),
    }


@app.post("/api/upload_file", response_model=UploadFileResponse)
async def upload_file(file: UploadFile = File(...)) -> UploadFileResponse:
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
        session = await run_in_threadpool(file_store.create_session, filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _upload_response(session)


@app.post("/api/select_sheets", response_model=SelectSheetsResponse)
async def select_sheets(payload: SelectSheetsRequest) -> SelectSheetsResponse:
    session = file_store.get_session(payload.session_id)
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
def upload_message(payload: UploadMessageRequest) -> UploadMessageResponse:
    session = file_store.get_session(payload.session_id)
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
async def submit(payload: SubmitRequest) -> SubmitResponse:
    started = time.perf_counter()
    session = file_store.get_session(payload.session_id)
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
        reply = await chat(question, data_text, session.conversation_id, session.user_id)
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
        }
    )
    if len(session.history) > 50:
        session.history = session.history[-50:]
    session.pending_message = ""

    elapsed_ms = int((time.perf_counter() - started) * 1000)
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
    )
