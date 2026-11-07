import { computed, reactive } from 'vue'

import {
  selectSheets as apiSelectSheets,
  submit as apiSubmit,
  uploadFile as apiUploadFile,
  uploadMessage as apiUploadMessage,
} from '@/api'
import { pushToast } from '@/composables/useToast'
import { validateFile } from '@/utils/file'

const SHEET_MISMATCH_KEYWORD = '列名不一致'

let messageSeed = 0

/**
 * 单用户会话：整条流程的状态都放这里。
 * stage: empty（未上传）→ needSheets（待选工作表）→ ready（可提问）
 */
export const session = reactive({
  stage: 'empty',
  uploading: false,
  uploadProgress: 0,
  selectionBusy: false,
  asking: false,
  /** 上传/选表合并后的文件信息 */
  payload: null,
  /** 本轮对话：[{ id, question, status, answer, result, querySpec, ... }] */
  messages: [],
  /** 必须重新上传才能继续的错误（如多表列名不一致） */
  blockingError: '',
})

export const canAsk = computed(
  () => session.stage === 'ready' && Boolean(session.payload) && !session.asking,
)

export function resetSession() {
  session.stage = 'empty'
  session.uploading = false
  session.uploadProgress = 0
  session.selectionBusy = false
  session.asking = false
  session.payload = null
  session.messages = []
  session.blockingError = ''
}

export function clearBlockingError() {
  session.blockingError = ''
}

function applyUpload(data) {
  session.payload = {
    sessionId: data.session_id,
    filename: data.filename,
    type: data.type,
    rows: data.rows ?? 0,
    columns: data.columns ?? [],
    sheets: data.sheets ?? [],
    selectedSheets: data.selected_sheets ?? [],
    merged: (data.selected_sheets ?? []).length > 1,
    needsSheetSelection: Boolean(data.needs_sheet_selection),
    message: data.message ?? '',
  }
  session.messages = []
  session.blockingError = ''
  session.stage = session.payload.needsSheetSelection ? 'needSheets' : 'ready'
}

/** 上传文件：前端先做一遍格式/大小校验，避免把明显不合规的文件传上去。 */
export async function uploadReport(file) {
  const checked = validateFile(file)
  if (!checked.ok) {
    pushToast(checked.message, 'error')
    return false
  }

  session.uploading = true
  session.uploadProgress = 0
  session.blockingError = ''

  try {
    const data = await apiUploadFile(file, {
      onUploadProgress: (event) => {
        if (!event?.total) return
        session.uploadProgress = Math.min(100, Math.round((event.loaded / event.total) * 100))
      },
    })
    applyUpload(data)
    return true
  } catch (error) {
    pushToast(error?.message ?? '上传失败，请重试', 'error')
    return false
  } finally {
    session.uploading = false
  }
}

/**
 * 选表：mode = 'merge_all' 合并全部；mode = 'select' 只取 sheets 指定的若干张。
 * @param {{ mode: 'merge_all' | 'select', sheets: string[] }} options
 */
export async function confirmSheets({ mode, sheets }) {
  if (!session.payload || session.selectionBusy) return false

  session.selectionBusy = true

  try {
    const data = await apiSelectSheets(session.payload.sessionId, { mode, sheets })
    session.payload.rows = data.rows ?? 0
    session.payload.columns = data.columns ?? []
    session.payload.selectedSheets = data.selected_sheets ?? []
    session.payload.merged = Boolean(data.merged) || (data.selected_sheets ?? []).length > 1
    session.payload.needsSheetSelection = false
    session.payload.message = data.message ?? ''
    session.messages = []
    session.stage = 'ready'
    pushToast(data.message || '工作表已载入，可以开始提问', 'success')
    return true
  } catch (error) {
    const message = error?.message ?? '选择工作表失败'

    if (message.includes(SHEET_MISMATCH_KEYWORD)) {
      // 无法通过改选工作表解决，只能重新上传（见 API.md §4）。
      session.blockingError = message
    } else if (error?.status === 404) {
      resetSession()
      pushToast('会话不存在或已过期，请重新上传文件', 'error')
    } else {
      pushToast(message, 'error')
    }
    return false
  } finally {
    session.selectionBusy = false
  }
}

function createMessage(question) {
  messageSeed += 1
  // 必须用 reactive 包一层：如果往 session.messages 里 push 普通对象，
  // 之后改那个「原始对象」不会触发依赖通知，卡片会永远停在 pending。
  return reactive({
    id: messageSeed,
    question,
    status: 'pending',
    startedAt: Date.now(),
    elapsedMs: 0,
    answer: '',
    result: null,
    querySpec: null,
    rawOutput: '',
    degraded: false,
    error: '',
    attempts: 1,
  })
}

function applyAnswer(message, data) {
  message.status = 'done'
  message.answer = data.answer ?? ''
  message.result = data.result ?? null
  message.querySpec = data.query_spec ?? null
  message.rawOutput = data.raw_output ?? ''
  message.degraded = Boolean(data.degraded)
  message.error = data.error ?? ''
  message.elapsedMs = data.elapsed_ms ?? Date.now() - message.startedAt
}

function handleAskError(message, error) {
  message.status = 'error'
  message.error = error?.message ?? '提问失败，请重试'
  message.elapsedMs = Date.now() - message.startedAt

  if (error?.status === 404) {
    resetSession()
    pushToast('会话不存在或已过期，请重新上传文件', 'error')
    return
  }
  pushToast(message.error, 'error')
}

/**
 * 提问：先 upload_message 暂存问题，再 submit 取回答（submit 是同步长请求）。
 * 按 API.md §5，submit 失败时问题仍保留在服务端，因此重试可以直接重跑这两步。
 */
export async function askQuestion(rawQuestion) {
  const question = String(rawQuestion ?? '').trim()
  if (!session.payload || session.stage !== 'ready' || session.asking) return false
  if (!question) {
    pushToast('请输入问题', 'error')
    return false
  }
  if (question.length > 2000) {
    pushToast('问题不能超过 2000 字', 'error')
    return false
  }

  session.messages.push(createMessage(question))
  // 取回数组里的响应式引用（而不是 push 前的局部变量），后续写回结果才会触发渲染。
  const message = session.messages[session.messages.length - 1]
  session.asking = true

  try {
    await apiUploadMessage(session.payload.sessionId, question)
    const data = await apiSubmit(session.payload.sessionId)
    applyAnswer(message, data)
  } catch (error) {
    handleAskError(message, error)
  } finally {
    session.asking = false
  }

  return true
}

/** 重试失败的提问：同一 session_id 重新走 upload_message → submit。 */
export async function retryMessage(message) {
  if (!session.payload || session.asking || !message || message.status !== 'error') return

  session.asking = true
  message.status = 'pending'
  message.startedAt = Date.now()
  message.error = ''
  message.attempts += 1

  try {
    await apiUploadMessage(session.payload.sessionId, message.question)
    const data = await apiSubmit(session.payload.sessionId)
    applyAnswer(message, data)
  } catch (error) {
    handleAskError(message, error)
  } finally {
    session.asking = false
  }
}
