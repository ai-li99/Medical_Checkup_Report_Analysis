"""Dify 应用1（工作流）与应用2（对话流）的调用封装。

实测要点（2026-11）：
- 应用1 输出在 data.outputs 里，键名是 message；
- 应用1 的输出、以及应用2 的 answer 都可能带 `<think>…</think>` 推理标签，
  前端展示前必须剥离；
- 应用2 复用 conversation_id 即可保持多轮记忆。
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

import httpx

from config import (
    DIFY_APP1_KEY,
    DIFY_APP1_PATH,
    DIFY_APP2_KEY,
    DIFY_APP2_PATH,
    DIFY_BASE_URL,
    DIFY_TIMEOUT_SECONDS,
    DIFY_USER_PREFIX,
)

_THINK_PAIRED = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)
_REASONING_COMMENT = re.compile(r"<!--\s*dify-deepseek-reasoning\s*-->", re.IGNORECASE)
_FENCE = re.compile(r"```[A-Za-z0-9_-]*\s*")


class DifyError(RuntimeError):
    """调用 Dify 失败（网络错误、非 2xx、执行失败等）。"""


def strip_reasoning(text: str) -> str:
    """剥离 <think> 推理段与 dify 推理标记。"""
    if not text:
        return ""
    cleaned = _THINK_PAIRED.sub("", text)
    cleaned = _THINK_OPEN.sub("", cleaned)
    cleaned = _REASONING_COMMENT.sub("", cleaned)
    return cleaned.strip()


def _json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for chunk in (text, strip_reasoning(text)):
        chunk = chunk.strip()
        if chunk and chunk not in candidates:
            candidates.append(chunk)
        unfenced = _FENCE.sub("", chunk).replace("```", "").strip()
        if unfenced and unfenced not in candidates:
            candidates.append(unfenced)
    return candidates


def extract_json_object(text: str) -> dict[str, Any] | None:
    """从文本里提取第一个能解析、且带 op 字段的 JSON 对象（失败返回 None）。"""
    if not text:
        return None
    decoder = json.JSONDecoder()
    fallback: dict[str, Any] | None = None
    for chunk in _json_candidates(text):
        for index, char in enumerate(chunk):
            if char != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(chunk[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                if "op" in obj:
                    return obj
                if fallback is None:
                    fallback = obj
    return fallback


def extract_output_text(outputs: dict[str, Any]) -> str:
    """从 outputs 里取出文本（自动兼容 message / text 等键名）。"""
    texts: list[str] = []
    for value in outputs.values():
        if isinstance(value, str) and value.strip():
            texts.append(value)
        elif isinstance(value, (dict, list)):
            texts.append(json.dumps(value, ensure_ascii=False))
    if not texts:
        return ""
    return max(texts, key=len)


def _headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise DifyError("未配置 Dify 应用密钥，请检查 backend/.env")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def _post(path: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{DIFY_BASE_URL}{path}"
    timeout = httpx.Timeout(DIFY_TIMEOUT_SECONDS, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=_headers(api_key), json=payload)
    except httpx.HTTPError as exc:
        raise DifyError(f"调用 Dify 接口失败：{exc.__class__.__name__} {exc}") from exc
    if response.status_code >= 400:
        raise DifyError(f"Dify 接口返回 {response.status_code}：{response.text[:500]}")
    try:
        return response.json()
    except ValueError as exc:
        raise DifyError("Dify 接口返回的不是合法 JSON") from exc


async def run_workflow(schema_card: str, user_query: str) -> str:
    """调用应用1：表结构 + 问题 -> 原始输出文本（可能含 <think>）。"""
    payload = {
        "inputs": {"schema_card": schema_card, "user_query": user_query},
        "response_mode": "blocking",
        "user": f"{DIFY_USER_PREFIX}-query",
    }
    body = await _post(DIFY_APP1_PATH, DIFY_APP1_KEY, payload)
    data = body.get("data") or {}
    status = data.get("status")
    if status and status != "succeeded":
        raise DifyError(f"应用1 执行未成功：{status} {data.get('error') or ''}".strip())
    return extract_output_text(data.get("outputs") or {})


async def chat(user_query: str, data_text: str, conversation_id: str, user: str) -> dict[str, Any]:
    """调用应用2：查询结果 + 问题 -> 自然语言回答。"""
    payload = {
        "inputs": {"data": data_text},
        "query": user_query,
        "response_mode": "blocking",
        "conversation_id": conversation_id or "",
        "user": user,
    }
    body = await _post(DIFY_APP2_PATH, DIFY_APP2_KEY, payload)
    return {
        "answer": strip_reasoning(str(body.get("answer") or "")),
        "conversation_id": str(body.get("conversation_id") or conversation_id or ""),
        "message_id": str(body.get("message_id") or body.get("id") or ""),
    }


async def chat_stream(
    user_query: str,
    data_text: str,
    conversation_id: str,
    user: str,
) -> AsyncIterator[tuple[str, str]]:
    """流式调用应用2，逐个产出：

    - ("conversation_id", 会话 id)
    - ("delta", 文本片段)
    - ("error", 错误信息) 由 DifyError 表达，这里不产出
    """
    payload = {
        "inputs": {"data": data_text},
        "query": user_query,
        "response_mode": "streaming",
        "conversation_id": conversation_id or "",
        "user": user,
    }
    url = f"{DIFY_BASE_URL}{DIFY_APP2_PATH}"
    # 每个分片之间允许的最长间隔
    timeout = httpx.Timeout(DIFY_TIMEOUT_SECONDS, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", url, headers=_headers(DIFY_APP2_KEY), json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "ignore")
                    raise DifyError(f"Dify 接口返回 {response.status_code}：{body[:500]}")
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue

                    conversation = str(event.get("conversation_id") or "")
                    if conversation:
                        yield "conversation_id", conversation

                    name = event.get("event")
                    if name == "message":
                        chunk = str(event.get("answer") or "")
                        if chunk:
                            yield "delta", chunk
                    elif name == "message_end":
                        break
                    elif name == "error":
                        raise DifyError(
                            f"应用2 返回错误：{event.get('message') or json.dumps(event, ensure_ascii=False)[:300]}"
                        )
    except httpx.HTTPError as exc:
        raise DifyError(f"调用 Dify 接口失败：{exc.__class__.__name__} {exc}") from exc
