"""账号密码哈希、双令牌（access + refresh）与鉴权依赖。

- 密码：PBKDF2-HMAC-SHA256（20 万次迭代，每人随机盐），只用标准库；
- access token：HMAC-SHA256 签名的自包含令牌，默认 30 分钟；
- refresh token：随机串，数据库只存 SHA-256，默认 30 天，一次性使用并轮换；
- 令牌版本号：改密码后 `users.token_version` 递增，旧 access 立即失效。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

from fastapi import Header

import auth_store
import config

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 200_000
_UNAUTHORIZED = "未登录或登录已过期"


class AuthError(Exception):
    """带业务 code 的认证错误，由 main.py 的异常处理器转成 HTTP 响应。"""

    def __init__(
        self,
        detail: str,
        status_code: int = 401,
        code: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.headers = headers or {}


class InvalidRefreshToken(Exception):
    """refresh token 不存在、已使用、已被吊销或已过期。"""


# --------------------------------------------------------------------------
# 密码
# --------------------------------------------------------------------------
def _secret() -> bytes:
    if not config.AUTH_SECRET:
        raise RuntimeError(
            "未配置 AUTH_SECRET：请在 backend/.env 中设置一个随机字符串，"
            "例如 AUTH_SECRET=<64 位随机十六进制>"
        )
    return config.AUTH_SECRET.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password: str) -> str:
    """返回 `pbkdf2_sha256$迭代次数$盐$哈希` 形式的自描述字符串。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_text, hash_text = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(hash_text)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (AttributeError, ValueError, TypeError, binascii.Error):
        return False
    return hmac.compare_digest(digest, expected)


# --------------------------------------------------------------------------
# access token
# --------------------------------------------------------------------------
def _sign(payload_text: str) -> str:
    digest = hmac.new(_secret(), payload_text.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_access_token(user_id: int, token_version: int) -> str:
    now = int(time.time())
    payload = {
        "uid": int(user_id),
        "ver": int(token_version),
        "typ": "access",
        "iat": now,
        "exp": now + max(60, int(config.AUTH_ACCESS_TTL_SECONDS)),
    }
    payload_text = _b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return f"{payload_text}.{_sign(payload_text)}"


def _decode_access(token: str) -> tuple[dict[str, Any] | None, str]:
    """返回 (payload, 原因)，原因为 '' / 'expired' / 'invalid'。"""
    if not token or "." not in token:
        return None, "invalid"
    payload_text, signature = token.split(".", 1)
    try:
        expected = _sign(payload_text)
    except RuntimeError:
        return None, "invalid"
    if not hmac.compare_digest(signature, expected):
        return None, "invalid"
    try:
        payload = json.loads(_b64decode(payload_text))
    except (ValueError, TypeError, binascii.Error):
        return None, "invalid"
    if not isinstance(payload, dict) or payload.get("typ") != "access":
        return None, "invalid"
    uid = payload.get("uid")
    ver = payload.get("ver")
    exp = payload.get("exp")
    if not isinstance(uid, int) or not isinstance(ver, int) or not isinstance(exp, int):
        return None, "invalid"
    if exp < int(time.time()):
        return None, "expired"
    return payload, ""


# --------------------------------------------------------------------------
# refresh token
# --------------------------------------------------------------------------
def _new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_tokens(user: dict[str, Any]) -> dict[str, Any]:
    """签发一对令牌（登录、注册、刷新成功后调用）。"""
    now = int(time.time())
    user_id = int(user["user_id"])
    refresh_ttl = max(60, int(config.AUTH_REFRESH_TTL_SECONDS))
    access_token = create_access_token(user_id, int(user.get("token_version") or 0))
    refresh_token = _new_refresh_token()
    auth_store.create_refresh_token(
        user_id=user_id,
        token_hash=_hash_refresh(refresh_token),
        family_id=uuid.uuid4().hex,
        expires_at=now + refresh_ttl,
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": int(config.AUTH_ACCESS_TTL_SECONDS),
        "refresh_expires_in": refresh_ttl,
    }


def rotate_refresh(refresh_token: str) -> dict[str, Any]:
    """用 refresh 换一对新令牌；检测到重放会吊销整个令牌家族。"""
    if not refresh_token:
        raise InvalidRefreshToken("缺少 refresh_token")
    row = auth_store.get_refresh_token(_hash_refresh(refresh_token))
    if row is None:
        raise InvalidRefreshToken("refresh_token 不存在")
    now = int(time.time())
    if row["revoked_at"] is not None:
        auth_store.revoke_refresh_family(row["family_id"], now)
        raise InvalidRefreshToken("refresh_token 已被吊销")
    if row["used_at"] is not None:
        # 已使用过的令牌再次出现：视为泄露，整族吊销
        auth_store.revoke_refresh_family(row["family_id"], now)
        raise InvalidRefreshToken("refresh_token 已被使用")
    if row["expires_at"] <= now:
        raise InvalidRefreshToken("refresh_token 已过期")
    user = auth_store.get_user_by_id(row["user_id"])
    if user is None:
        raise InvalidRefreshToken("用户不存在")

    auth_store.mark_refresh_used(row["id"], now)
    new_refresh = _new_refresh_token()
    auth_store.create_refresh_token(
        user_id=user["user_id"],
        token_hash=_hash_refresh(new_refresh),
        family_id=row["family_id"],
        expires_at=now + max(60, int(config.AUTH_REFRESH_TTL_SECONDS)),
    )
    return {
        "access_token": create_access_token(user["user_id"], int(user.get("token_version") or 0)),
        "refresh_token": new_refresh,
        "expires_in": int(config.AUTH_ACCESS_TTL_SECONDS),
    }


def revoke_refresh(refresh_token: str, user_id: int | None = None) -> bool:
    if not refresh_token:
        return False
    return auth_store.revoke_refresh_token(_hash_refresh(refresh_token), user_id)


def revoke_all_refresh(user_id: int) -> int:
    return auth_store.revoke_user_refresh_tokens(user_id)


def change_password(user_id: int, new_password: str) -> None:
    """改密码：更新哈希、让旧 access 失效、吊销全部 refresh。"""
    auth_store.update_password(user_id, hash_password(new_password))
    auth_store.bump_token_version(user_id)
    auth_store.revoke_user_refresh_tokens(user_id)


# --------------------------------------------------------------------------
# 登录失败限制
# --------------------------------------------------------------------------
def login_lock(username: str, ip: str) -> int | None:
    """返回锁定到期时间（epoch 秒）；未锁定返回 None。"""
    now = int(time.time())
    for scope, key in (("user", (username or "").lower()), ("ip", ip or "")):
        if not key:
            continue
        until = auth_store.get_lock(scope, key, now)
        if until is not None:
            return until
    return None


def record_login_failure(username: str, ip: str) -> int | None:
    now = int(time.time())
    lock_until: int | None = None
    if username:
        lock_until = auth_store.record_failure(
            "user",
            username.lower(),
            config.AUTH_LOGIN_WINDOW_SECONDS,
            config.AUTH_LOGIN_MAX_FAILURES,
            config.AUTH_LOGIN_LOCK_SECONDS,
            now,
        ) or lock_until
    if ip:
        lock_until = auth_store.record_failure(
            "ip",
            ip,
            config.AUTH_LOGIN_WINDOW_SECONDS,
            config.AUTH_LOGIN_IP_MAX_FAILURES,
            config.AUTH_LOGIN_LOCK_SECONDS,
            now,
        ) or lock_until
    return lock_until


def clear_login_failures(username: str, ip: str) -> None:
    if username:
        auth_store.clear_attempts("user", username.lower())
    if ip:
        auth_store.clear_attempts("ip", ip)


# --------------------------------------------------------------------------
# FastAPI 依赖
# --------------------------------------------------------------------------
def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _resolve_user(authorization: str | None) -> tuple[dict[str, Any] | None, str]:
    payload, reason = _decode_access(_bearer_token(authorization))
    if payload is None:
        return None, reason
    user = auth_store.get_user_by_id(int(payload["uid"]))
    if user is None or int(payload["ver"]) != int(user.get("token_version") or 0):
        return None, "invalid"
    return user, ""


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """需要登录的接口加 `user: dict = Depends(auth.get_current_user)` 即可。"""
    user, reason = _resolve_user(authorization)
    if user is None:
        if reason == "expired":
            raise AuthError("登录已过期", 401, "token_expired")
        raise AuthError(_UNAUTHORIZED, 401, "token_invalid")
    return user


def try_get_current_user(authorization: str | None) -> dict[str, Any] | None:
    """未登录时返回 None（用于「已登录就重置密码、未登录返回 501」这类接口）。"""
    user, _ = _resolve_user(authorization)
    return user
