/**
 * 登录态的本地持久化。
 *
 * 刻意做成「零依赖」的叶子模块：http.js 和 stores/auth.js 都要读写它，
 * 这样不会因为互相 import 形成环。
 *
 * 存三样东西：
 *   - access token（30 分钟，业务接口用）
 *   - refresh token（30 天，只用来换新 access）
 *   - 用户信息（用于顶栏展示与本地过期预判）
 */

const TOKEN_KEY = 'mcr.auth.token'
const REFRESH_KEY = 'mcr.auth.refresh'
const USER_KEY = 'mcr.auth.user'

function safeLocalStorage() {
  try {
    return window.localStorage
  } catch {
    // 隐私模式 / 被禁用时降级为不持久化，功能仍可用。
    return null
  }
}

/** @returns {{ token: string, refreshToken: string, user: object | null }} */
export function readAuthStorage() {
  const storage = safeLocalStorage()
  if (!storage) return { token: '', refreshToken: '', user: null }

  try {
    const token = storage.getItem(TOKEN_KEY) || ''
    const refreshToken = storage.getItem(REFRESH_KEY) || ''
    const rawUser = storage.getItem(USER_KEY)
    const user = rawUser ? JSON.parse(rawUser) : null
    return {
      token,
      refreshToken,
      user: user && typeof user === 'object' ? user : null,
    }
  } catch {
    return { token: '', refreshToken: '', user: null }
  }
}

export function readToken() {
  return readAuthStorage().token
}

export function readRefreshToken() {
  return readAuthStorage().refreshToken
}

export function writeTokens({ token, refreshToken }) {
  const storage = safeLocalStorage()
  if (!storage) return
  try {
    storage.setItem(TOKEN_KEY, token ?? '')
    storage.setItem(REFRESH_KEY, refreshToken ?? '')
  } catch {
    /* 配额满等异常忽略即可 */
  }
}

export function writeAuthStorage({ token, refreshToken, user }) {
  const storage = safeLocalStorage()
  if (!storage) return
  try {
    storage.setItem(TOKEN_KEY, token ?? '')
    storage.setItem(REFRESH_KEY, refreshToken ?? '')
    storage.setItem(USER_KEY, JSON.stringify(user ?? null))
  } catch {
    /* 忽略 */
  }
}

export function clearAuthStorage() {
  const storage = safeLocalStorage()
  if (!storage) return
  try {
    storage.removeItem(TOKEN_KEY)
    storage.removeItem(REFRESH_KEY)
    storage.removeItem(USER_KEY)
  } catch {
    /* 忽略 */
  }
}
