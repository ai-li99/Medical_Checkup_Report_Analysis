import axios from 'axios'

import { clearAuthStorage, readRefreshToken, readToken, writeTokens } from '@/utils/authStorage'

/**
 * 统一的接口错误：message 一定是可直接展示给用户的中文文案。
 * code 优先取后端返回的机器码（token_expired / refresh_invalid / login_locked …），
 * 没有时退回 axios 的传输层 code。
 */
export class ApiError extends Error {
  constructor(message, { status = 0, code = '', payload = null, retryAfter = 0 } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.payload = payload
    this.retryAfter = retryAfter
  }
}

/** FastAPI 的 detail 可能是字符串（业务错误）或数组（422 校验错误）。 */
function readDetail(data) {
  const detail = data?.detail
  if (typeof detail === 'string') return detail.trim()
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg ?? '')
      .filter(Boolean)
      .join('；')
  }
  return ''
}

function readBackendCode(response) {
  const code = response?.data?.code
  return typeof code === 'string' ? code : ''
}

function readRetryAfter(response) {
  const raw = response?.headers?.['retry-after']
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 0
}

function normalizeError(error) {
  if (error instanceof ApiError) return error

  const { code: transportCode, response } = error

  if (transportCode === 'ECONNABORTED' || transportCode === 'ETIMEDOUT') {
    return new ApiError('请求超时，请稍后重试。', { code: transportCode })
  }

  if (!response) {
    return new ApiError('无法连接后端服务，请确认后端已启动（默认 http://127.0.0.1:8000）。', {
      code: transportCode,
    })
  }

  const detail = readDetail(response.data)
  const backendCode = readBackendCode(response)
  const retryAfter = readRetryAfter(response)

  // 后端进程没起来时，dev server 的代理会直接返回 502 且没有 JSON body；
  // 真正的 Dify 502 由后端返回，一定带 detail，不会被这条命中。
  if (!detail && [502, 503, 504].includes(response.status)) {
    return new ApiError('无法连接后端服务，请确认 FastAPI 已启动（默认 http://127.0.0.1:8000）。', {
      status: response.status,
      code: backendCode || transportCode,
      payload: response.data,
      retryAfter,
    })
  }

  return new ApiError(detail || `请求失败（HTTP ${response.status}）`, {
    status: response.status,
    code: backendCode || transportCode,
    payload: response.data,
    retryAfter,
  })
}

/** 登录/注册/刷新自身的 401 是「凭据错」，不能当成登录态失效去触发全局登出。 */
const AUTH_ENDPOINTS = ['/login', '/register', '/refresh']

function isAuthEndpoint(config) {
  const url = String(config?.url ?? '')
  return AUTH_ENDPOINTS.some((endpoint) => url.endsWith(endpoint))
}

let unauthorizedHandler = null
let tokenSyncHandler = null

/** 由 main.js 注入：登录态彻底失效时清登录态并跳登录页。 */
export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = typeof handler === 'function' ? handler : null
}

/** 由 main.js 注入：access 被静默刷新后，同步回响应式的 auth store。 */
export function setTokenSyncHandler(handler) {
  tokenSyncHandler = typeof handler === 'function' ? handler : null
}

export const http = axios.create({
  baseURL: '/api',
  // 后端 /api/submit 内部调用大模型，超时上限 180s，前端留一点余量。
  timeout: 190_000,
})

// 每个请求自动带上 access token（multipart 上传同样生效）。
http.interceptors.request.use((config) => {
  const token = readToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/* ------------------------------------------------------------------ *
 * access 续期
 *
 * /api/refresh 是「一次性轮换」：每换一次，旧 refresh 立刻作废；
 * 拿用过的 refresh 再换会被判定为盗用，整族令牌被吊销。
 * 所以并发 401 必须共用同一个刷新 Promise，绝不能各刷各的。
 * ------------------------------------------------------------------ */
const refreshClient = axios.create({ timeout: 20_000 })
let refreshPromise = null

async function performRefresh() {
  const refreshToken = readRefreshToken()
  if (!refreshToken) {
    throw new ApiError('登录已过期，请重新登录', { status: 401, code: 'refresh_invalid' })
  }

  let payload
  try {
    const response = await refreshClient.post(
      '/refresh',
      { refresh_token: refreshToken },
      // 跟随主实例的 baseURL，便于后续统一改成环境变量/绝对地址。
      { baseURL: http.defaults.baseURL },
    )
    payload = response.data
  } catch (error) {
    throw normalizeError(error)
  }

  writeTokens({ token: payload.access_token, refreshToken: payload.refresh_token })
  tokenSyncHandler?.({
    token: payload.access_token,
    refreshToken: payload.refresh_token,
    expiresIn: payload.expires_in,
  })
  return payload.access_token
}

/**
 * 供 SSE 等自己发请求的场景复用：保证同一时刻只刷新一次。
 * 刷新失败会抛出 ApiError，且内部已清空本地令牌。
 */
export function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

function forceLogout(error) {
  clearAuthStorage()
  unauthorizedHandler?.(error)
}

// 直接返回响应体，调用方不必再关心 response.data。
http.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const config = error?.config
    const normalized = normalizeError(error)

    const shouldHandle =
      normalized.status === 401 && !isAuthEndpoint(config) && !config?.skipAuthHandling

    if (!shouldHandle) return Promise.reject(normalized)

    // access 过期：静默换新后重试原请求一次。
    if (normalized.code === 'token_expired' && !config?._retried) {
      let accessToken
      try {
        accessToken = await refreshAccessToken()
      } catch (refreshError) {
        forceLogout(refreshError instanceof ApiError ? refreshError : normalized)
        return Promise.reject(normalizeError(refreshError))
      }

      const retryConfig = {
        ...config,
        _retried: true,
        headers: { ...config.headers, Authorization: `Bearer ${accessToken}` },
      }
      return http.request(retryConfig)
    }

    // 伪造 / 已吊销 / 改密作废 → 直接登出。
    forceLogout(normalized)
    return Promise.reject(normalized)
  },
)
