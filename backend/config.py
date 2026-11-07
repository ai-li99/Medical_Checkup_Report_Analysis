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
