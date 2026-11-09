"""后端配置：统一从 backend/.env 读取，不在代码里硬编码密钥。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# ---------- Dify ----------
DIFY_BASE_URL = _env_str("DIFY_BASE_URL", "http://47.114.83.33/v1").rstrip("/")
DIFY_APP1_KEY = _env_str("DIFY_APP1_KEY")
DIFY_APP2_KEY = _env_str("DIFY_APP2_KEY")
DIFY_APP1_PATH = "/workflows/run"
DIFY_APP2_PATH = "/chat-messages"
DIFY_TIMEOUT_SECONDS = _env_int("DIFY_TIMEOUT_SECONDS", 180)
DIFY_USER_PREFIX = "medical-report"

# 给应用1 的追问上下文：预算只约束历史轮次，当前问题总是完整发送
APP1_CONTEXT_MAX_CHARS = _env_int("APP1_CONTEXT_MAX_CHARS", 1500)
APP1_CONTEXT_QUESTION_CHARS = _env_int("APP1_CONTEXT_QUESTION_CHARS", 300)

# ---------- 上传 ----------
UPLOAD_DIR = Path(_env_str("UPLOAD_DIR", "uploads"))
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = BACKEND_DIR / UPLOAD_DIR
ALLOWED_SUFFIXES = {".xlsx", ".csv"}
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_MB", 50) * 1024 * 1024
MAX_ROWS = _env_int("MAX_ROWS", 200000)

# ---------- 结果与会话 ----------
MAX_QUERY_LIMIT = _env_int("MAX_QUERY_LIMIT", 500)
DEFAULT_QUERY_LIMIT = _env_int("DEFAULT_QUERY_LIMIT", 50)
MAX_PREVIEW_ROWS = _env_int("MAX_PREVIEW_ROWS", 100)
MAX_RESULT_ROWS_FOR_LLM = _env_int("MAX_RESULT_ROWS_FOR_LLM", 200)
MAX_SESSIONS = _env_int("MAX_SESSIONS", 100)

# 表结构卡片
SCHEMA_SAMPLE_ROWS = 3
SCHEMA_MAX_COLUMNS = 120
CELL_MAX_CHARS = 50

API_TITLE = "体检报告分析后端"

# ---------- 认证 ----------
# 令牌签名密钥：改动后所有已发出的令牌立即失效
AUTH_SECRET = _env_str("AUTH_SECRET")
AUTH_ACCESS_TTL_SECONDS = _env_int("AUTH_ACCESS_TTL_SECONDS", 30 * 60)
AUTH_REFRESH_TTL_SECONDS = _env_int("AUTH_REFRESH_TTL_SECONDS", 30 * 24 * 3600)
AUTH_PASSWORD_MIN = _env_int("AUTH_PASSWORD_MIN", 8)
AUTH_PASSWORD_MAX = _env_int("AUTH_PASSWORD_MAX", 64)

# 登录失败限制：15 分钟内「用户名+IP」失败 5 次或单 IP 失败 20 次即锁定 15 分钟
AUTH_LOGIN_MAX_FAILURES = _env_int("AUTH_LOGIN_MAX_FAILURES", 5)
AUTH_LOGIN_IP_MAX_FAILURES = _env_int("AUTH_LOGIN_IP_MAX_FAILURES", 20)
AUTH_LOGIN_WINDOW_SECONDS = _env_int("AUTH_LOGIN_WINDOW_SECONDS", 15 * 60)
AUTH_LOGIN_LOCK_SECONDS = _env_int("AUTH_LOGIN_LOCK_SECONDS", 15 * 60)

# ---------- 数据库 ----------
DB_PATH = Path(_env_str("DB_PATH", "data/app.db"))
if not DB_PATH.is_absolute():
    DB_PATH = BACKEND_DIR / DB_PATH
AUTH_DB_PATH = DB_PATH  # 兼容旧名

# ---------- 历史记录 ----------
HISTORY_PAGE_SIZE = _env_int("HISTORY_PAGE_SIZE", 20)
HISTORY_MAX_PAGE_SIZE = _env_int("HISTORY_MAX_PAGE_SIZE", 100)
HISTORY_TURNS_FOR_CONTEXT = _env_int("HISTORY_TURNS_FOR_CONTEXT", 50)
