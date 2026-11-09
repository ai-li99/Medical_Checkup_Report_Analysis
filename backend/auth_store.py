"""应用数据库（SQLite，标准库）：用户、刷新令牌、登录失败计数。

所有表都在同一个数据库文件里（默认 backend/data/app.db），启动时自动建表、
自动补列，不需要手工执行任何 SQL。
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import config


class UsernameTakenError(ValueError):
    """用户名已被占用（大小写不敏感）。"""


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        family_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        used_at INTEGER,
        revoked_at INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_login_attempts (
        scope TEXT NOT NULL,
        key TEXT NOT NULL,
        failures INTEGER NOT NULL DEFAULT 0,
        window_start INTEGER NOT NULL,
        locked_until INTEGER,
        PRIMARY KEY (scope, key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_refresh_family ON auth_refresh_tokens(family_id)",
    "CREATE INDEX IF NOT EXISTS idx_refresh_user ON auth_refresh_tokens(user_id)",
)


def _now() -> int:
    return int(time.time())


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def db_path():
    path = config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        yield connection
        connection.commit()
    finally:
        connection.close()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with _connect() as connection:
        for statement in _SCHEMA:
            connection.execute(statement)
        _ensure_column(
            connection, "users", "token_version", "token_version INTEGER NOT NULL DEFAULT 0"
        )


# --------------------------------------------------------------------------
# 用户
# --------------------------------------------------------------------------
def _to_user(row: sqlite3.Row) -> dict:
    return {
        "user_id": int(row["id"]),
        "username": row["username"],
        "password_hash": row["password_hash"],
        "created_at": row["created_at"],
        "token_version": int(row["token_version"] or 0),
    }


_USER_COLUMNS = "id, username, password_hash, created_at, token_version"


def get_user_by_username(username: str) -> dict | None:
    """按用户名查询（大小写不敏感，由列的 COLLATE NOCASE 保证）。"""
    with _connect() as connection:
        row = connection.execute(
            f"SELECT {_USER_COLUMNS} FROM users WHERE username = ?", (username,)
        ).fetchone()
    return _to_user(row) if row is not None else None


def get_user_by_id(user_id: int) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            f"SELECT {_USER_COLUMNS} FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
    return _to_user(row) if row is not None else None


def create_user(username: str, password_hash: str) -> dict:
    created_at = _now_iso()
    try:
        with _connect() as connection:
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, created_at),
            )
            user_id = int(cursor.lastrowid or 0)
    except sqlite3.IntegrityError as exc:
        raise UsernameTakenError("用户名已存在") from exc
    return {
        "user_id": user_id,
        "username": username,
        "created_at": created_at,
        "token_version": 0,
    }


def update_password(user_id: int, password_hash: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, int(user_id))
        )


def bump_token_version(user_id: int) -> int:
    """递增令牌版本号：所有已签发的 access token 立即失效。"""
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET token_version = token_version + 1 WHERE id = ?", (int(user_id),)
        )
        row = connection.execute(
            "SELECT token_version FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
    return int(row["token_version"]) if row is not None else 0


# --------------------------------------------------------------------------
# 刷新令牌（只存 SHA-256 哈希）
# --------------------------------------------------------------------------
def create_refresh_token(
    user_id: int, token_hash: str, family_id: str, expires_at: int
) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO auth_refresh_tokens (user_id, token_hash, family_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (int(user_id), token_hash, family_id, _now_iso(), int(expires_at)),
        )


def get_refresh_token(token_hash: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, user_id, family_id, expires_at, used_at, revoked_at"
            " FROM auth_refresh_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "family_id": row["family_id"],
        "expires_at": int(row["expires_at"]),
        "used_at": row["used_at"],
        "revoked_at": row["revoked_at"],
    }


def mark_refresh_used(token_id: int, now: int | None = None) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE auth_refresh_tokens SET used_at = ? WHERE id = ?",
            (now or _now(), int(token_id)),
        )


def revoke_refresh_family(family_id: str, now: int | None = None) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE auth_refresh_tokens SET revoked_at = ?"
            " WHERE family_id = ? AND revoked_at IS NULL",
            (now or _now(), family_id),
        )


def revoke_refresh_token(token_hash: str, user_id: int | None = None) -> bool:
    query = "UPDATE auth_refresh_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL"
    params: list = [_now(), token_hash]
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(int(user_id))
    with _connect() as connection:
        cursor = connection.execute(query, params)
        return cursor.rowcount > 0


def revoke_user_refresh_tokens(user_id: int, now: int | None = None) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE auth_refresh_tokens SET revoked_at = ?"
            " WHERE user_id = ? AND revoked_at IS NULL",
            (now or _now(), int(user_id)),
        )
        return cursor.rowcount


def purge_expired_refresh_tokens(now: int | None = None) -> None:
    with _connect() as connection:
        connection.execute(
            "DELETE FROM auth_refresh_tokens WHERE expires_at < ?", (now or _now(),)
        )


# --------------------------------------------------------------------------
# 登录失败计数
# --------------------------------------------------------------------------
def get_lock(scope: str, key: str, now: int | None = None) -> int | None:
    """返回锁定到期时间（epoch 秒），未锁定或已解锁返回 None。"""
    current = now or _now()
    with _connect() as connection:
        row = connection.execute(
            "SELECT locked_until FROM auth_login_attempts WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
    if row is None or row["locked_until"] is None:
        return None
    until = int(row["locked_until"])
    if until <= current:
        clear_attempts(scope, key)
        return None
    return until


def record_failure(
    scope: str,
    key: str,
    window_seconds: int,
    max_failures: int,
    lock_seconds: int,
    now: int | None = None,
) -> int | None:
    """记一次失败；达到阈值返回锁定到期时间，否则返回 None。"""
    current = now or _now()
    with _connect() as connection:
        row = connection.execute(
            "SELECT failures, window_start FROM auth_login_attempts WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO auth_login_attempts (scope, key, failures, window_start, locked_until)"
                " VALUES (?, ?, 1, ?, NULL)",
                (scope, key, current),
            )
            return None
        window_start = int(row["window_start"])
        if current - window_start > window_seconds:
            connection.execute(
                "UPDATE auth_login_attempts SET failures = 1, window_start = ?, locked_until = NULL"
                " WHERE scope = ? AND key = ?",
                (current, scope, key),
            )
            return None
        failures = int(row["failures"]) + 1
        locked_until = current + lock_seconds if failures >= max_failures else None
        connection.execute(
            "UPDATE auth_login_attempts SET failures = ?, locked_until = ?"
            " WHERE scope = ? AND key = ?",
            (failures, locked_until, scope, key),
        )
        return locked_until


def clear_attempts(scope: str, key: str) -> None:
    with _connect() as connection:
        connection.execute(
            "DELETE FROM auth_login_attempts WHERE scope = ? AND key = ?", (scope, key)
        )
