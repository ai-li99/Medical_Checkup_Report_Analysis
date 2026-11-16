/**
 * 报告封面参数的本地记忆（localStorage）。
 *
 * 同一份文件再次生成报告时自动带出上次填写的内容，省得重复输入。
 * key 由「用户名 + 文件名」组成：换账号不会串数据，同名文件重新上传也能恢复。
 */

const STORAGE_KEY = 'mcr.report.covers'
const MAX_ENTRIES = 20

function safeStorage() {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function readAll() {
  const storage = safeStorage()
  if (!storage) return {}

  try {
    const raw = storage.getItem(STORAGE_KEY)
    const data = raw ? JSON.parse(raw) : null
    return data && typeof data === 'object' && !Array.isArray(data) ? data : {}
  } catch {
    return {}
  }
}

function pickString(value) {
  return typeof value === 'string' ? value : ''
}

/** @returns {{ unitName: string, preparedBy: string, reviewedBy: string, reportDate: string } | null} */
export function getReportCover(key) {
  if (!key) return null

  const entry = readAll()[key]
  if (!entry || typeof entry !== 'object') return null

  return {
    unitName: pickString(entry.unitName),
    preparedBy: pickString(entry.preparedBy),
    reviewedBy: pickString(entry.reviewedBy),
    reportDate: pickString(entry.reportDate),
  }
}

export function saveReportCover(key, cover) {
  if (!key) return

  const storage = safeStorage()
  if (!storage) return

  const all = readAll()
  all[key] = {
    unitName: pickString(cover?.unitName).trim(),
    preparedBy: pickString(cover?.preparedBy).trim(),
    reviewedBy: pickString(cover?.reviewedBy).trim(),
    reportDate: pickString(cover?.reportDate),
    savedAt: Date.now(),
  }

  // 只保留最近使用的若干条，避免长期累积
  const trimmed = Object.fromEntries(
    Object.entries(all)
      .sort((a, b) => (b[1]?.savedAt || 0) - (a[1]?.savedAt || 0))
      .slice(0, MAX_ENTRIES),
  )

  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
  } catch {
    /* 配额满等异常忽略，不影响生成 */
  }
}
