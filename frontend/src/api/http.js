import axios from 'axios'

/**
 * 统一的接口错误：message 一定是可直接展示给用户的中文文案。
 */
export class ApiError extends Error {
  constructor(message, { status = 0, code = '', payload = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.payload = payload
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

function normalizeError(error) {
  if (error instanceof ApiError) return error

  const { code, response } = error

  if (code === 'ECONNABORTED' || code === 'ETIMEDOUT') {
    return new ApiError('请求超时，请稍后重试。', { code })
  }

  if (!response) {
    return new ApiError('无法连接后端服务，请确认后端已启动（默认 http://127.0.0.1:8000）。', { code })
  }

  const message = readDetail(response.data)

  // 后端进程没起来时，dev server 的代理会直接返回 502 且没有 JSON body；
  // 真正的 Dify 502 由后端返回，一定带 detail，不会被这条命中。
  if (!message && [502, 503, 504].includes(response.status)) {
    return new ApiError('无法连接后端服务，请确认 FastAPI 已启动（默认 http://127.0.0.1:8000）。', {
      status: response.status,
      code,
      payload: response.data,
    })
  }

  return new ApiError(message || `请求失败（HTTP ${response.status}）`, {
    status: response.status,
    code,
    payload: response.data,
  })
}

export const http = axios.create({
  baseURL: '/api',
  // 后端 /api/submit 内部调用大模型，超时上限 180s，前端留一点余量。
  timeout: 190_000,
})

// 直接返回响应体，调用方不必再关心 response.data。
http.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(normalizeError(error)),
)
