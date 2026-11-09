"""上传文件落盘、表格解析、工作表选择 / 合并、内存会话管理。"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

import chat_store
from config import ALLOWED_SUFFIXES, HISTORY_TURNS_FOR_CONTEXT, MAX_ROWS, MAX_SESSIONS, UPLOAD_DIR
from schema_card import build_schema_card, column_infos
from models import ColumnInfo


class SheetMismatchError(ValueError):
    """要合并的多个工作表列名不一致。"""


class SessionNotFoundError(ValueError):
    """会话不存在或已过期。"""


SHEET_MISMATCH_MESSAGE = "选择的sheet的列名不一致，请重新上传"
_SESSION_GONE = "会话不存在或已过期，请重新上传文件"


@dataclass
class Session:
    session_id: str
    file_id: str
    filename: str
    kind: str
    path: Path
    user_id: int | None = None
    sheet_frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    selected_sheets: list[str] = field(default_factory=list)
    merged: bool = False
    df: pd.DataFrame | None = None
    columns_info: list[ColumnInfo] = field(default_factory=list)
    schema_card: str = ""
    pending_message: str = ""
    message_id: str = ""
    conversation_id: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = 0.0

    @property
    def dify_user_id(self) -> str:
        """传给 Dify 的终端用户标识（按会话隔离记忆）。"""
        return f"session-{self.session_id}"

    @property
    def needs_sheet_selection(self) -> bool:
        return self.df is None

    def sheet_infos(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "rows": int(len(frame)), "columns": int(len(frame.columns))}
            for name, frame in self.sheet_frames.items()
        ]


_SESSIONS: dict[str, Session] = {}
_LOCK = threading.RLock()


# --------------------------------------------------------------------------
# 会话注册表
# --------------------------------------------------------------------------
def ensure_upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _register(session: Session) -> Session:
    with _LOCK:
        _SESSIONS[session.session_id] = session
        # 只淘汰内存缓存，不删文件：历史记录还要靠原始文件恢复会话
        while len(_SESSIONS) > MAX_SESSIONS:
            oldest_id = min(_SESSIONS, key=lambda key: _SESSIONS[key].created_at)
            if oldest_id == session.session_id:
                break
            _SESSIONS.pop(oldest_id, None)
    return session


def forget_session(session_id: str, path: Path | None = None) -> bool:
    """删除会话时调用：清掉内存缓存并删除原始文件。文件已不在时返回 False。"""
    with _LOCK:
        session = _SESSIONS.pop(session_id, None)
    target = path if path is not None else (session.path if session is not None else None)
    if target is None:
        return False
    existed = target.exists()
    _remove_file(target)
    return existed


def get_session(session_id: str, user_id: int | None = None) -> Session:
    """取会话；内存里没有时自动从数据库 + 原始文件恢复（历史会话可继续追问）。"""
    with _LOCK:
        session = _SESSIONS.get(session_id or "")
    if session is not None:
        if user_id is not None and session.user_id != user_id:
            raise SessionNotFoundError(_SESSION_GONE)
        return session
    return restore_session(session_id, user_id)


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
# 体检数据里常见 "50岁"、或化验值被存成文本（"45"）这类列：不转成数值就既不能比较大小、
# 也不能求平均。只转换「数字 + 可选单位后缀」且占比 ≥ 90% 的列。
_NUMERIC_TEXT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*\D{0,8}\s*$")
_NUMERIC_TEXT_MIN_RATIO = 0.9
_NUMERIC_TEXT_MAX_ABS = 1e15


def _coerce_numeric_text(frame: pd.DataFrame) -> pd.DataFrame:
    """把「数字 + 可选单位」的文本列转成数值。

    保护：带前导零的编号（如 "007"）与超过 1e15 的数字不转，避免丢失编号信息或丢精度。
    """
    for name in frame.columns:
        column = frame[name]
        if pd.api.types.is_numeric_dtype(column.dtype) or pd.api.types.is_datetime64_any_dtype(column.dtype):
            continue
        values = column.dropna()
        if values.empty:
            continue
        text = values.astype("string").str.strip()
        extracted = text.str.extract(_NUMERIC_TEXT, expand=False)
        if extracted.notna().mean() < _NUMERIC_TEXT_MIN_RATIO:
            continue
        numeric = pd.to_numeric(extracted, errors="coerce")
        max_abs = numeric.abs().max()
        if pd.notna(max_abs) and float(max_abs) > _NUMERIC_TEXT_MAX_ABS:
            continue
        if bool(text.str.match(r"^0\d").any()):
            continue
        frame[name] = pd.to_numeric(
            column.astype("string").str.strip().str.extract(_NUMERIC_TEXT, expand=False),
            errors="coerce",
        )
    return frame


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]

    seen: dict[str, int] = {}
    columns: list[str] = []
    for column in frame.columns:
        if column in seen:
            seen[column] += 1
            columns.append(f"{column}.{seen[column]}")
        else:
            seen[column] = 0
            columns.append(column)
    frame.columns = columns

    keep: list[str] = []
    for column in frame.columns:
        if column.lower().startswith("unnamed:") and frame[column].isna().all():
            continue
        if column == "":
            continue
        keep.append(column)
    frame = frame.loc[:, keep]
    frame = frame.dropna(how="all")
    frame = _coerce_numeric_text(frame)
    return frame.reset_index(drop=True)


def _check_frame(frame: pd.DataFrame) -> None:
    if len(frame.columns) == 0:
        raise ValueError("文件里没有可用的列")
    if len(frame) > MAX_ROWS:
        raise ValueError(f"数据行数 {len(frame)} 超过上限 {MAX_ROWS} 行")


def _read_csv(path: Path) -> pd.DataFrame:
    best: tuple[str, pd.DataFrame] | None = None
    errors: list[str] = []
    for encoding in ("utf-8-sig", "gb18030"):
        for separator in (None, ",", "\t", ";"):
            try:
                if separator is None:
                    frame = pd.read_csv(path, encoding=encoding, sep=None, engine="python")
                else:
                    frame = pd.read_csv(path, encoding=encoding, sep=separator)
            except Exception as exc:  # noqa: BLE001 - 换一种编码/分隔符重试
                errors.append(f"{encoding}/{separator or 'sniff'}: {exc}")
                continue
            if len(frame.columns) == 0:
                continue
            if best is None or len(frame.columns) > len(best[1].columns):
                best = (encoding, frame)
        if best is not None and len(best[1].columns) > 1:
            break
    if best is None:
        raise ValueError("CSV 解析失败：" + "；".join(errors[:3]))
    return _normalize_frame(best[1])


def _read_excel_sheets(path: Path) -> dict[str, pd.DataFrame]:
    try:
        sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Excel 解析失败：{exc}") from exc
    frames: dict[str, pd.DataFrame] = {}
    for name, frame in sheets.items():
        normalized = _normalize_frame(frame)
        if len(normalized.columns) == 0:
            continue
        _check_frame(normalized)
        frames[str(name)] = normalized
    return frames


# --------------------------------------------------------------------------
# 载入 / 合并
# --------------------------------------------------------------------------
def _load_frame(
    session: Session,
    frame: pd.DataFrame,
    sheets: list[str],
    merged: bool,
    reset_conversation: bool = True,
) -> None:
    session.df = frame
    session.selected_sheets = list(sheets)
    session.merged = merged
    session.columns_info = column_infos(frame)
    session.schema_card = build_schema_card(frame, session.filename, session.selected_sheets, merged)
    session.pending_message = ""
    session.message_id = ""
    if reset_conversation:
        # 数据变了，之前的对话记忆与历史都作废
        session.conversation_id = ""
        session.history.clear()


def _merge_frames(frames: dict[str, pd.DataFrame], names: list[str]) -> pd.DataFrame:
    if len(names) == 1:
        return frames[names[0]].copy()
    reference = [str(column) for column in frames[names[0]].columns]
    if "_sheet" in reference:
        raise ValueError("工作表中已存在 `_sheet` 列（系统保留列名），请先重命名该列")
    for name in names[1:]:
        if set(frames[name].columns) != set(reference):
            raise SheetMismatchError(SHEET_MISMATCH_MESSAGE)
    parts: list[pd.DataFrame] = []
    for name in names:
        part = frames[name].loc[:, reference].copy()
        part["_sheet"] = name
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def _frames_from_disk(path: Path, kind: str) -> dict[str, pd.DataFrame]:
    if kind == "csv":
        frame = _read_csv(path)
        _check_frame(frame)
        return {"CSV": frame}
    frames = _read_excel_sheets(path)
    if not frames:
        raise ValueError("文件里没有可用的工作表")
    return frames


def restore_session(session_id: str, user_id: int | None = None) -> Session:
    """从数据库与磁盘文件把历史会话恢复进内存。"""
    row = chat_store.get_session_row(session_id)
    if row is None or (user_id is not None and int(row["user_id"] or 0) != int(user_id)):
        raise SessionNotFoundError(_SESSION_GONE)
    path = Path(str(row["file_path"]))
    if not path.exists():
        raise SessionNotFoundError("原始文件已丢失，该会话只能查看历史，无法继续提问")
    try:
        frames = _frames_from_disk(path, str(row["file_kind"]))
    except ValueError as exc:
        raise SessionNotFoundError(f"原始文件无法重新读取：{exc}") from exc

    session = Session(
        session_id=row["id"],
        file_id=row["file_id"] or "",
        filename=row["filename"],
        kind=row["file_kind"],
        path=path,
        user_id=int(row["user_id"] or 0) or None,
        sheet_frames=frames,
        created_at=float(time.time()),
    )

    try:
        stored = json.loads(row["sheets"]) if row["sheets"] else []
    except (TypeError, ValueError):
        stored = []
    names = [str(name) for name in stored if str(name) in frames]
    if not names and len(frames) == 1:
        names = list(frames)
    if not names:
        # 还没选过工作表：保持「待选择」状态
        with _LOCK:
            _SESSIONS[session.session_id] = session
        return session

    merged = bool(row["merged"]) or len(names) > 1
    frame = _merge_frames(frames, names) if len(names) > 1 else frames[names[0]]
    _load_frame(session, frame, names, merged=merged, reset_conversation=False)
    session.conversation_id = row["conversation_id"] or ""
    session.history = chat_store.list_turns_for_context(
        session.session_id, HISTORY_TURNS_FOR_CONTEXT
    )
    with _LOCK:
        _SESSIONS[session.session_id] = session
    return session


def create_session(filename: str, data: bytes, user_id: int | None = None) -> Session:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的文件类型「{suffix or '无扩展名'}」，仅支持 .xlsx 和 .csv")
    ensure_upload_dir()
    file_id = f"f_{uuid.uuid4().hex[:12]}"
    path = UPLOAD_DIR / f"{file_id}{suffix}"
    path.write_bytes(data)
    session = Session(
        session_id=f"s_{uuid.uuid4().hex[:12]}",
        file_id=file_id,
        filename=filename,
        kind="csv" if suffix == ".csv" else "xlsx",
        path=path,
        user_id=user_id,
        created_at=time.time(),
    )
    try:
        if suffix == ".csv":
            frame = _read_csv(path)
            _check_frame(frame)
            session.sheet_frames = {"CSV": frame}
            _load_frame(session, frame, ["CSV"], merged=False)
        else:
            frames = _read_excel_sheets(path)
            if not frames:
                raise ValueError("Excel 文件里没有可用的工作表")
            session.sheet_frames = frames
            if len(frames) == 1:
                name = next(iter(frames))
                _load_frame(session, frames[name], [name], merged=False)
    except Exception:
        _remove_file(path)
        raise
    chat_store.save_session(
        session_id=session.session_id,
        file_id=file_id,
        user_id=user_id,
        filename=filename,
        file_path=str(path),
        file_kind=session.kind,
        sheets=session.selected_sheets,
        merged=session.merged,
        row_count=len(session.df) if session.df is not None else 0,
        column_count=len(session.df.columns) if session.df is not None else 0,
    )
    return _register(session)


def apply_sheet_selection(session: Session, mode: str, sheets: list[str]) -> Session:
    if session.kind == "csv":
        raise ValueError("CSV 文件只有一个数据表，不需要选择工作表")
    available = list(session.sheet_frames)
    if not available:
        raise ValueError("文件里没有可用的工作表，请重新上传")
    if mode not in ("merge_all", "select"):
        raise ValueError("mode 只能是 merge_all 或 select")

    if mode == "merge_all":
        names = available
    else:
        raw_names = [str(name).strip() for name in (sheets or []) if str(name).strip()]
        if not raw_names:
            raise ValueError("mode=select 时必须通过 sheets 指定要使用的工作表")
        unknown = [name for name in raw_names if name not in available]
        if unknown:
            raise ValueError(f"工作表「{'、'.join(unknown)}」不存在；可用工作表：{'、'.join(available)}")
        names = []
        for name in raw_names:
            if name not in names:
                names.append(name)

    frame = _merge_frames(session.sheet_frames, names)
    _check_frame(frame)
    _load_frame(session, frame, names, merged=len(names) > 1)
    chat_store.update_session_selection(
        session.session_id,
        session.selected_sheets,
        session.merged,
        len(session.df) if session.df is not None else 0,
        len(session.df.columns) if session.df is not None else 0,
    )
    return session
