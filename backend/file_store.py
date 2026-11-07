"""上传文件落盘、表格解析、工作表选择 / 合并、内存会话管理。"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from config import ALLOWED_SUFFIXES, MAX_ROWS, MAX_SESSIONS, UPLOAD_DIR
from schema_card import build_schema_card, column_infos
from models import ColumnInfo


class SheetMismatchError(ValueError):
    """要合并的多个工作表列名不一致。"""


class SessionNotFoundError(ValueError):
    """会话不存在或已过期。"""


SHEET_MISMATCH_MESSAGE = "选择的sheet的列名不一致，请重新上传"


@dataclass
class Session:
    session_id: str
    file_id: str
    filename: str
    kind: str
    path: Path
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
    def user_id(self) -> str:
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
        while len(_SESSIONS) > MAX_SESSIONS:
            oldest_id = min(_SESSIONS, key=lambda key: _SESSIONS[key].created_at)
            if oldest_id == session.session_id:
                break
            dropped = _SESSIONS.pop(oldest_id, None)
            if dropped is not None:
                _remove_file(dropped.path)
    return session


def get_session(session_id: str) -> Session:
    with _LOCK:
        session = _SESSIONS.get(session_id or "")
    if session is None:
        raise SessionNotFoundError("会话不存在或已过期，请重新上传文件")
    return session


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
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
def _load_frame(session: Session, frame: pd.DataFrame, sheets: list[str], merged: bool) -> None:
    session.df = frame
    session.selected_sheets = list(sheets)
    session.merged = merged
    session.columns_info = column_infos(frame)
    session.schema_card = build_schema_card(frame, session.filename, session.selected_sheets, merged)
    # 数据变了，之前的对话记忆与待提交问题都作废
    session.conversation_id = ""
    session.pending_message = ""
    session.message_id = ""
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


def create_session(filename: str, data: bytes) -> Session:
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
    return session
