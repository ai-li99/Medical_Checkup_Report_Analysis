import { createRouter, createWebHistory } from 'vue-router'

import { clearAuth, isAuthenticated, isSessionExpired } from '@/stores/auth'

export const routes = [
  {
    path: '/',
    name: 'root',
    // 未登录进登录页，已登录直接进业务页。
    redirect: () => (isAuthenticated.value ? { name: 'home' } : { name: 'login' }),
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', layout: 'auth', guestOnly: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { title: '注册', layout: 'auth', guestOnly: true },
  },
  {
    path: '/home',
    name: 'home',
    component: () => import('@/views/WorkbenchView.vue'),
    meta: { title: '分析工作台', requiresAuth: true },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
    meta: { title: '历史记录', requiresAuth: true },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: '账号设置', requiresAuth: true },
  },
  // 未匹配路径统一回首页，由 / 再按登录态分发。
  { path: '/:pathMatch(.*)*', name: 'not-found', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  // 本地已知过期就先清掉，免得上传完才发现 401。
  if (isAuthenticated.value && isSessionExpired()) {
    clearAuth()
  }

  const authed = isAuthenticated.value

  // 业务页需要登录；带上原始地址，登录后可以回到原处。
  if (to.meta.requiresAuth && !authed) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  // 已登录还访问登录/注册页，直接进业务页。
  if (to.meta.guestOnly && authed) {
    return { name: 'home' }
  }

  return true
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · 体检报告分析` : '体检报告分析'
})

export default router
