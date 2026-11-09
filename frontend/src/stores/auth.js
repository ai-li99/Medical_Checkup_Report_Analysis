import { computed, reactive } from 'vue'

import {
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  resetPassword as apiResetPassword,
} from '@/api'
import { resetSession } from '@/stores/session'
import { clearAuthStorage, readAuthStorage, writeAuthStorage } from '@/utils/authStorage'

const stored = readAuthStorage()

export const auth = reactive({
  token: stored.token,
  refreshToken: stored.refreshToken,
  user: stored.user,
})

export const isAuthenticated = computed(() => Boolean(auth.token))

/** 本地记录的 access 过期时间（仅用于提前拦截，真实判定以后端 401 为准）。 */
export function isSessionExpired() {
  const expiresAt = auth.user?.expiresAt
  return typeof expiresAt === 'number' && expiresAt > 0 && Date.now() >= expiresAt
}

function buildUser(data) {
  return {
    id: data.user_id ?? auth.user?.id ?? null,
    username: data.username ?? auth.user?.username ?? '',
    createdAt: data.created_at ?? auth.user?.createdAt ?? '',
    expiresAt: Date.now() + (Number(data.expires_in) || 0) * 1000,
  }
}

function applySession(data) {
  const user = buildUser(data)
  auth.token = data.token
  auth.refreshToken = data.refresh_token
  auth.user = user
  writeAuthStorage({ token: auth.token, refreshToken: auth.refreshToken, user })
}

/** 由 http.js 在静默刷新后回调，把新令牌同步进响应式状态。 */
export function syncTokens({ token, refreshToken, expiresIn }) {
  auth.token = token
  auth.refreshToken = refreshToken
  if (auth.user) {
    auth.user = {
      ...auth.user,
      expiresAt: Date.now() + (Number(expiresIn) || 0) * 1000,
    }
  }
  writeAuthStorage({ token, refreshToken, user: auth.user })
}

/** 登录：POST /api/login */
export async function login(credentials) {
  const data = await apiLogin(credentials)
  applySession(data)
  return data
}

/** 注册：POST /api/register（后端「注册即登录」，直接返回双令牌） */
export async function register(credentials) {
  const data = await apiRegister(credentials)
  applySession(data)
  return data
}

/** 只清本地登录态（401 兜底、改密之后用），不发请求。 */
export function clearAuth() {
  auth.token = ''
  auth.refreshToken = ''
  auth.user = null
  clearAuthStorage()
  resetSession()
}

/** 主动退出：先让后端吊销 refresh（失败也不影响本地登出），再清本地。 */
export async function logout() {
  const { refreshToken } = auth
  if (refreshToken) {
    try {
      await apiLogout(refreshToken)
    } catch {
      /* 令牌已失效/网络异常都无所谓，本地照常清空 */
    }
  }
  clearAuth()
}

/**
 * 修改密码：成功后后端会作废所有令牌，因此这里直接清本地登录态。
 * @param {{ newPassword: string, oldPassword?: string }} payload
 */
export async function resetPassword(payload) {
  const data = await apiResetPassword(payload)
  clearAuth()
  return data
}
