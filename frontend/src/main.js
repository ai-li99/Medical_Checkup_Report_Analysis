import { createApp } from 'vue'

import { setTokenSyncHandler, setUnauthorizedHandler } from '@/api/http'
import { clearAuth, syncTokens } from '@/stores/auth'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App).use(router)

// access 被静默刷新后，把新令牌同步进响应式状态（顶栏、过期预判都依赖它）。
setTokenSyncHandler((tokens) => {
  syncTokens(tokens)
})

// 登录态彻底失效（伪造 / 已吊销 / 改密作废 / 刷新失败）时：清本地状态 + 回登录页。
// 登录/注册/刷新接口自身的 401 已在 http.js 里排除，不会走到这里。
setUnauthorizedHandler(() => {
  clearAuth()
  const current = router.currentRoute.value
  if (current.name !== 'login' && current.name !== 'register') {
    router.replace({ name: 'login', query: { redirect: current.fullPath } })
  }
})

// 等首次导航（含路由守卫）完成再挂载，避免深链打开 /login 时先闪一下业务页外壳。
router.isReady().then(() => app.mount('#app'))
