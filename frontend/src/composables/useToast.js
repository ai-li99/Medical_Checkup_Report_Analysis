import { reactive } from 'vue'

/** 全局轻量 toast，单用户场景够用，无需引入 UI 库。 */
export const toasts = reactive([])

let seed = 0

/**
 * @param {string} message
 * @param {'info' | 'success' | 'error'} tone
 * @param {number} duration 毫秒，0 表示不自动消失
 */
export function pushToast(message, tone = 'info', duration = 4200) {
  const text = String(message ?? '').trim()
  if (!text) return 0
  const id = (seed += 1)
  toasts.push({ id, message: text, tone })
  if (duration > 0) {
    setTimeout(() => dismissToast(id), duration)
  }
  return id
}

export function dismissToast(id) {
  const index = toasts.findIndex((item) => item.id === id)
  if (index >= 0) toasts.splice(index, 1)
}

export function useToast() {
  return { toasts, pushToast, dismissToast }
}
