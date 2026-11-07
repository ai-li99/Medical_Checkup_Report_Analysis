import { createRouter, createWebHistory } from 'vue-router'

export const routes = [
  {
    path: '/',
    name: 'workbench',
    component: () => import('@/views/WorkbenchView.vue'),
    meta: { title: '分析工作台' },
  },
  // 未匹配路径统一回首页，避免刷新出现空白页。
  { path: '/:pathMatch(.*)*', name: 'not-found', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · 体检报告分析` : '体检报告分析'
})

export default router
