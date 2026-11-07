import { http } from './http'

/**
 * 后端接口薄封装，字段与 backend/API.md 保持一致。
 * 所有函数都已统一成「成功返回响应体、失败抛出 ApiError」。
 */

/** GET /api/healthy —— 健康检查，app_ready=false 说明后端未配全 Dify 密钥。 */
export function healthy() {
  return http.get('/healthy')
}

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
