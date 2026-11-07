/** 与后端 config.py 对齐的上传约束，做一次「后端拒绝之前」的本地校验。 */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024
export const ACCEPT_SUFFIXES = ['.xlsx', '.csv']
export const ACCEPT_ATTR = ACCEPT_SUFFIXES.join(',')

export function formatBytes(bytes) {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes)) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function fileSuffix(name) {
  const dot = String(name ?? '').lastIndexOf('.')
  if (dot < 0) return ''
  return String(name).slice(dot).toLowerCase()
}

/**
 * @param {File} file
 * @returns {{ ok: true } | { ok: false, message: string }}
 */
export function validateFile(file) {
  if (!(file instanceof File)) {
    return { ok: false, message: '请选择一个文件' }
  }
  const suffix = fileSuffix(file.name)
  if (!ACCEPT_SUFFIXES.includes(suffix)) {
    return {
      ok: false,
      message: `不支持的文件类型「${suffix || '无扩展名'}」，仅支持 .xlsx 和 .csv`,
    }
  }
  if (file.size === 0) {
    return { ok: false, message: '上传的文件内容为空' }
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      ok: false,
      message: `文件大小 ${formatBytes(file.size)} 超过 50 MB 上限`,
    }
  }
  return { ok: true }
}
