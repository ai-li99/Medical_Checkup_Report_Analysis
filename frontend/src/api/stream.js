import { readToken } from '@/utils/authStorage'

import { ApiError, http, refreshAccessToken } from './http'

/**
 * SSE 流式提交。
 *
 * 为什么不用 EventSource：它不能带自定义请求头，而这里必须带 Authorization。
 * 所以用 fetch + ReadableStream 手动解析 `event:` / `data:` 块。
 *
 * 事件序列（见 API.md §15）：
 *   stage  -> { stage: 'generating_query' | 'querying' | 'answering' }
 *   result -> { query_spec, result, degraded, error }
 *   delta  -> { text }        按顺序追加即等于最终 answer
 *   done   -> 同 /api/submit 的响应体（含 turn_id / elapsed_ms）
 *   error  -> { detail, code } 出错时 HTTP 仍是 200，靠这个事件传递
 */

const STREAM_PATH = '/submit/stream'

/** 跟随主实例的 baseURL（浏览器里是 /api，可用环境变量换成绝对地址）。 */
function streamUrl() {
  const base = String(http.defaults.baseURL ?? '/api').replace(/\/$/, '')
  return `${base}${STREAM_PATH}`
}

async function safeJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

/** 解析一个 SSE 块；注释行、心跳包返回 null。 */
function parseEventBlock(raw) {
  let event = ''
  let data = ''

  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }

  if (!event || !data) return null

  try {
    return { event, payload: JSON.parse(data) }
  } catch {
    return null
  }
}

async function openStream(sessionId, signal, retried) {
  const token = readToken()
  const headers = {
    'Content-Type': 'application/json; charset=utf-8',
    Accept: 'text/event-stream',
  }
  if (token) headers.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetch(streamUrl(), {
      method: 'POST',
      headers,
      body: JSON.stringify({ session_id: sessionId }),
      signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiError('无法连接后端服务，请确认后端已启动（默认 http://127.0.0.1:8000）。', {
      code: 'network_error',
    })
  }

  if (response.status === 401) {
    const payload = await safeJson(response)
    const code = payload?.code ?? ''

    // access 过期：换新令牌后重开一次流；其余 401 一律当作登录失效。
    if (code === 'token_expired' && !retried) {
      await refreshAccessToken()
      return openStream(sessionId, signal, true)
    }

    throw new ApiError(payload?.detail ?? '登录已过期，请重新登录', {
      status: 401,
      code: code || 'token_invalid',
      payload,
    })
  }

  if (!response.ok) {
    const payload = await safeJson(response)
    throw new ApiError(payload?.detail ?? `请求失败（HTTP ${response.status}）`, {
      status: response.status,
      code: payload?.code ?? '',
      payload,
    })
  }

  return response
}

/**
 * @param {string} sessionId
 * @param {{
 *   onStage?: (stage: string) => void,
 *   onResult?: (payload: object) => void,
 *   onDelta?: (text: string) => void,
 *   signal?: AbortSignal,
 * }} handlers
 * @returns {Promise<object>} done 事件的完整响应体
 */
export async function submitStream(sessionId, { onStage, onResult, onDelta, signal } = {}) {
  const response = await openStream(sessionId, signal, false)

  if (!response.body) {
    throw new ApiError('当前浏览器不支持流式响应，请换用新版浏览器。', { code: 'stream_unsupported' })
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let donePayload = null

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      let index
      while ((index = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, index)
        buffer = buffer.slice(index + 2)

        const event = parseEventBlock(raw)
        if (!event) continue

        if (event.event === 'stage') {
          onStage?.(event.payload?.stage ?? '')
        } else if (event.event === 'result') {
          onResult?.(event.payload ?? {})
        } else if (event.event === 'delta') {
          onDelta?.(event.payload?.text ?? '')
        } else if (event.event === 'done') {
          donePayload = event.payload ?? null
        } else if (event.event === 'error') {
          await reader.cancel().catch(() => {})
          throw new ApiError(event.payload?.detail ?? '生成回答失败，请重试', {
            status: 200,
            code: event.payload?.code ?? 'stream_error',
            payload: event.payload,
          })
        }
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* 已被 cancel 时忽略 */
    }
  }

  if (!donePayload) {
    throw new ApiError('连接中断，未收到完整回答，请重试。', { code: 'stream_incomplete' })
  }

  return donePayload
}
