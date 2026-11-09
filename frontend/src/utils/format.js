const NUMBER_FORMATTER = new Intl.NumberFormat('zh-CN')

/** 1234 -> "1,234" */
export function formatNumber(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value ?? '')
  return NUMBER_FORMATTER.format(value)
}

/** 820 -> "820 ms"；3800 -> "3.8 s"；72000 -> "1 分 12 秒" */
export function formatDuration(ms) {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes} 分 ${seconds} 秒`
}

/** 本地时间，用于对话列表：14:32 */
export function formatClock(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/** 历史记录用：09-14 14:45（跨年时带上年份） */
export function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const pad = (num) => String(num).padStart(2, '0')
  const stamp = `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  return date.getFullYear() === new Date().getFullYear()
    ? stamp
    : `${date.getFullYear()}-${stamp}`
}

/** 空单元格占位符 */
export function displayCell(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
