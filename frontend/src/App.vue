<script setup>
import { RouterLink, RouterView } from 'vue-router'

import ToastStack from '@/components/ToastStack.vue'
</script>

<template>
  <div class="shell">
    <header class="shell__header">
      <RouterLink to="/" class="brand">
        <span class="brand__mark" aria-hidden="true">MED</span>
        <span class="brand__text">
          <strong>体检报告分析</strong>
          <small>自然语言提问 · 自动统计</small>
        </span>
      </RouterLink>
    </header>

    <main class="shell__main">
      <RouterView />
    </main>

    <footer class="shell__footer">本地演示环境 · 上传的数据仅保留在后端内存会话中</footer>

    <ToastStack />
  </div>
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
  padding: 14px 24px;
  background: rgba(255, 255, 255, 0.86);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(8px);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
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

.shell__main {
  flex: 1;
  width: 100%;
  max-width: 960px;
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

@media (max-width: 640px) {
  .shell__main {
    padding: 20px 16px 32px;
  }
}
</style>
