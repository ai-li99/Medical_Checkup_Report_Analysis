<script setup>
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import ToastStack from '@/components/ToastStack.vue'
import { pushToast } from '@/composables/useToast'
import { auth, logout } from '@/stores/auth'

const route = useRoute()
const router = useRouter()

/** 登录/注册页用独立布局，不套业务页外壳。 */
const isAuthLayout = computed(() => route.meta.layout === 'auth')
const initial = computed(() => (auth.user?.username ?? '?').slice(0, 1).toUpperCase())

const loggingOut = ref(false)

async function onLogout() {
  if (loggingOut.value) return
  loggingOut.value = true
  try {
    await logout()
    pushToast('已退出登录', 'info')
    await router.replace({ name: 'login' })
  } finally {
    loggingOut.value = false
  }
}
</script>

<template>
  <RouterView v-if="isAuthLayout" />

  <div v-else class="shell">
    <header class="shell__header">
      <div class="shell__left">
        <RouterLink to="/home" class="brand">
          <span class="brand__mark" aria-hidden="true">MED</span>
          <span class="brand__text">
            <strong>体检报告分析</strong>
            <small>自然语言提问 · 自动统计</small>
          </span>
        </RouterLink>

        <nav class="nav" aria-label="主导航">
          <RouterLink to="/home" class="nav__link">工作台</RouterLink>
          <RouterLink to="/history" class="nav__link">历史记录</RouterLink>
        </nav>
      </div>

      <div v-if="auth.user" class="session">
        <RouterLink :to="{ name: 'settings' }" class="session__user" title="账号设置">
          <span class="session__avatar" aria-hidden="true">{{ initial }}</span>
          <span class="session__name">{{ auth.user.username }}</span>
        </RouterLink>
        <button class="btn btn--sm" type="button" :disabled="loggingOut" @click="onLogout">
          {{ loggingOut ? '退出中…' : '退出登录' }}
        </button>
      </div>
    </header>

    <main class="shell__main">
      <RouterView />
    </main>

    <footer class="shell__footer">本地演示环境 · 上传的数据仅保留在后端内存会话中</footer>
  </div>

  <ToastStack />
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.shell__header {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  background: rgba(255, 255, 255, 0.86);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(8px);
}

.shell__left {
  display: flex;
  align-items: center;
  gap: 22px;
  min-width: 0;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.brand__mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.brand__text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.brand__text strong {
  font-size: 15px;
}

.brand__text small {
  color: var(--muted);
  font-size: 12px;
}

.nav {
  display: flex;
  gap: 4px;
}

.nav__link {
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.nav__link:hover {
  background: var(--surface-muted);
  color: var(--text);
}

.nav__link.router-link-active {
  background: var(--primary-soft);
  color: var(--primary);
}

.session {
  display: flex;
  flex: none;
  align-items: center;
  gap: 8px;
}

.session__user {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px 4px 4px;
  border-radius: 999px;
  transition: background-color 0.15s ease;
}

.session__user:hover {
  background: var(--surface-muted);
}

.session__avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
}

.session__name {
  max-width: 12em;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.shell__main {
  flex: 1;
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: 32px 24px 48px;
}

.shell__footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 720px) {
  .shell__header {
    padding: 10px 16px;
  }

  .shell__left {
    gap: 12px;
  }

  .brand__text {
    display: none;
  }

  .shell__main {
    padding: 20px 16px 32px;
  }

  .session__name {
    display: none;
  }
}
</style>
