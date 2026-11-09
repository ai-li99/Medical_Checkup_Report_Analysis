"""会话与问答记录持久化（SQLite）。

- chat_sessions：一次「上传 + 选表」形成的会话，指向磁盘上的原始文件；
- chat_turns：该会话里的每一轮问答（问题、回答、查询规格、结果快照）。

有了这两张表，服务重启后历史记录仍可查看，历史会话也能继续追问。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

import config

ANSWER_PREVIEW_CHARS = 160

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        file_id TEXT,
        user_id INTEGER NOT NULL DEFAULT 0,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_kind TEXT NOT NULL,
        sheets TEXT,
        merged INTEGER NOT NULL DEFAULT 0,
        row_count INTEGER NOT NULL DEFAULT 0,
        column_count INTEGER NOT NULL DEFAULT 0,
        conversation_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        query_spec TEXT,
        result TEXT,
        matched_rows INTEGER NOT NULL DEFAULT 0,
        degraded INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        elapsed_ms INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_turns_session ON chat_turns(session_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_turns_user ON chat_turns(user_id, id DESC)",
)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with _connect() as connection:
        for statement in _SCHEMA:
            connection.execute(statement)


# --------------------------------------------------------------------------
# 会话
# --------------------------------------------------------------------------
def save_session(
    *,
    session_id: str,
    file_id: str,
    user_id: int | None,
    filename: str,
    file_path: str,
    file_kind: str,
    sheets: list[str],
    merged: bool,
    row_count: int,
    column_count: int,
) -> None:
    now = _now_iso()
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO chat_sessions"
            " (id, file_id, user_id, filename, file_path, file_kind, sheets, merged,"
            "  row_count, column_count, conversation_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT conversation_id"
            "  FROM chat_sessions WHERE id = ?), ''), ?, ?)",
            (
                session_id,
                file_id,
                int(user_id or 0),
                filename,
                file_path,
                file_kind,
                json.dumps(sheets, ensure_ascii=False),
                1 if merged else 0,
                int(row_count),
                int(column_count),
                session_id,
                now,
                now,
            ),
        )


def update_session_selection(
    session_id: str,
    sheets: list[str],
    merged: bool,
    row_count: int,
    column_count: int,
) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE chat_sessions SET sheets = ?, merged = ?, row_count = ?, column_count = ?,"
            " updated_at = ? WHERE id = ?",
            (
                json.dumps(sheets, ensure_ascii=False),
                1 if merged else 0,
                int(row_count),
                int(column_count),
                _now_iso(),
                session_id,
            ),
        )


def update_conversation(session_id: str, conversation_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE chat_sessions SET conversation_id = ?, updated_at = ? WHERE id = ?",
            (conversation_id or "", _now_iso(), session_id),
        )


def touch_session(session_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (_now_iso(), session_id)
        )


def get_session_row(session_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def list_sessions(user_id: int, limit: int, offset: int) -> tuple[int, list[dict[str, Any]]]:
    with _connect() as connection:
        total_row = connection.execute(
            "SELECT COUNT(*) AS total FROM chat_sessions WHERE user_id = ?", (int(user_id),)
        ).fetchone()
        rows = connection.execute(
            """
            SELECT s.id AS session_id, s.filename, s.row_count, s.column_count,
                   s.created_at, s.updated_at,
                   (SELECT COUNT(*) FROM chat_turns t WHERE t.session_id = s.id) AS turn_count,
                   (SELECT t.question FROM chat_turns t WHERE t.session_id = s.id
                     ORDER BY t.id DESC LIMIT 1) AS last_question,
                   (SELECT t.created_at FROM chat_turns t WHERE t.session_id = s.id
                     ORDER BY t.id DESC LIMIT 1) AS last_asked_at
            FROM chat_sessions s
            WHERE s.user_id = ?
            ORDER BY s.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (int(user_id), int(limit), int(offset)),
        ).fetchall()
    items = [
        {
            "session_id": row["session_id"],
            "filename": row["filename"],
            "rows": int(row["row_count"] or 0),
            "columns": int(row["column_count"] or 0),
            "turn_count": int(row["turn_count"] or 0),
            "last_question": row["last_question"] or "",
            "last_asked_at": row["last_asked_at"] or "",
            "created_at": row["created_at"] or "",
            "updated_at": row["updated_at"] or "",
        }
        for row in rows
    ]
    return int(total_row["total"] or 0), items


# --------------------------------------------------------------------------
# 问答记录
# --------------------------------------------------------------------------
def add_turn(
    *,
    session_id: str,
    user_id: int,
    question: str,
    answer: str,
    query_spec: dict[str, Any] | None,
    result: dict[str, Any] | None,
    matched_rows: int,
    degraded: bool,
    error: str,
    elapsed_ms: int,
) -> int:
    now = _now_iso()
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO chat_turns"
            " (session_id, user_id, question, answer, query_spec, result, matched_rows,"
            "  degraded, error, elapsed_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                int(user_id),
                question,
                answer,
                json.dumps(query_spec, ensure_ascii=False) if query_spec is not None else None,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                int(matched_rows),
                1 if degraded else 0,
                error or "",
                int(elapsed_ms),
                now,
            ),
        )
        turn_id = int(cursor.lastrowid or 0)
        connection.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id)
        )
    return turn_id


def list_turns(session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    query = (
        "SELECT id, question, answer, degraded, created_at FROM chat_turns"
        " WHERE session_id = ? ORDER BY id ASC"
    )
    params: list[Any] = [session_id]
    if limit is not None:
        query += " LIMIT ?"
        params.append(int(limit))
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        answer = (row["answer"] or "").strip().replace("\r", "")
        preview = " ".join(answer.split())
        if len(preview) > ANSWER_PREVIEW_CHARS:
            preview = preview[: ANSWER_PREVIEW_CHARS - 1] + "…"
        items.append(
            {
                "turn_id": int(row["id"]),
                "question": row["question"],
                "answer_preview": preview,
                "degraded": bool(row["degraded"]),
                "created_at": row["created_at"] or "",
            }
        )
    return items


def list_turns_for_context(session_id: str, limit: int) -> list[dict[str, Any]]:
    """恢复会话时重建给应用1 的追问上下文（最近的若干轮）。"""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT question, query_spec, matched_rows FROM chat_turns"
            " WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, int(limit)),
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in reversed(rows):
        spec: dict[str, Any] | None = None
        if row["query_spec"]:
            try:
                loaded = json.loads(row["query_spec"])
                spec = loaded if isinstance(loaded, dict) else None
            except (TypeError, ValueError):
                spec = None
        items.append(
            {
                "question": row["question"],
                "query_spec": spec,
                "matched_rows": int(row["matched_rows"] or 0),
            }
        )
    return items


def get_turn(turn_id: int, user_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM chat_turns WHERE id = ? AND user_id = ?",
            (int(turn_id), int(user_id)),
        ).fetchone()
    return dict(row) if row is not None else None


def count_turns(session_id: str) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM chat_turns WHERE session_id = ?", (session_id,)
        ).fetchone()
    return int(row["total"] or 0)


def delete_session(session_id: str) -> int:
    """删除会话及其全部问答记录，返回删除的轮数。"""
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM chat_turns WHERE session_id = ?", (session_id,)
        )
        turns = int(cursor.rowcount or 0)
        connection.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    return turns
