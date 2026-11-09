import { http } from './http'

/**
 * 后端接口薄封装，字段与 backend/API.md 保持一致。
 * 所有函数都已统一成「成功返回响应体、失败抛出 ApiError」。
 */

/* ---------------- 认证 ---------------- */

/** POST /api/login —— 成功返回 access + refresh 双令牌。 */
export function login({ username, password }) {
  return http.post('/login', { username, password })
}

/** POST /api/register —— 注册成功即登录，返回结构与 login 一致。 */
export function register({ username, password }) {
  return http.post('/register', { username, password })
}

/** POST /api/logout —— 吊销 refresh；失败也不该阻塞本地登出，所以跳过全局 401 处理。 */
export function logout(refreshToken) {
  return http.post(
    '/logout',
    { refresh_token: refreshToken ?? '' },
    { skipAuthHandling: true },
  )
}

/**
 * POST /api/password/reset —— 已登录才能用（未登录 501 reset_requires_login）。
 * @param {{ newPassword: string, oldPassword?: string }} payload
 */
export function resetPassword({ newPassword, oldPassword }) {
  const body = { new_password: newPassword }
  if (oldPassword) body.old_password = oldPassword
  return http.post('/password/reset', body)
}

/* ---------------- 基础 ---------------- */

/** GET /api/healthy —— 健康检查，app_ready=false 说明后端未配全 Dify 密钥。 */
export function healthy() {
  return http.get('/healthy')
}

/* ---------------- 分析流程 ---------------- */

/** POST /api/upload_file —— 上传 .xlsx / .csv，返回 session_id。 */
export function uploadFile(file, { onUploadProgress } = {}) {
  const form = new FormData()
  form.append('file', file)
  return http.post('/upload_file', form, { onUploadProgress })
}

/**
 * POST /api/select_sheets —— 多工作表时选择要分析的表。
 * @param {string} sessionId
 * @param {{ mode?: 'merge_all' | 'select', sheets?: string[] }} options
 */
export function selectSheets(sessionId, { mode = 'select', sheets = [] } = {}) {
  return http.post('/select_sheets', { session_id: sessionId, mode, sheets })
}

/** POST /api/upload_message —— 提交本轮问题（此时还不返回答案）。 */
export function uploadMessage(sessionId, message) {
  return http.post('/upload_message', { session_id: sessionId, message })
}

/** POST /api/submit —— 执行查询并取回自然语言回答，最慢的接口。 */
export function submit(sessionId) {
  return http.post('/submit', { session_id: sessionId })
}

/* ---------------- 历史记录 ---------------- */

/** GET /api/history —— 会话列表（按文件分组，最近更新的在前）。 */
export function fetchHistory({ limit = 20, offset = 0 } = {}) {
  return http.get('/history', { params: { limit, offset } })
}

/** GET /api/sessions/{id}/turns —— 该会话的全部轮次摘要（时间正序）。 */
export function fetchSessionTurns(sessionId) {
  return http.get(`/sessions/${encodeURIComponent(sessionId)}/turns`)
}

/** GET /api/history/{turn_id} —— 单轮完整结果。 */
export function fetchTurnDetail(turnId) {
  return http.get(`/history/${encodeURIComponent(turnId)}`)
}

/** POST /api/sessions/{id}/resume —— 把历史会话恢复到内存，之后可继续追问。 */
export function resumeSession(sessionId) {
  return http.post(`/sessions/${encodeURIComponent(sessionId)}/resume`)
}
