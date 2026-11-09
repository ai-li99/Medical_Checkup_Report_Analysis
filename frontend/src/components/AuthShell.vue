<script setup>
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
})

const HIGHLIGHTS = [
  { title: '自然语言提问', desc: '「年龄大于 40 岁的人有多少」直接出结果' },
  { title: '多表合并分析', desc: '多个工作表纵向合并，自动标记数据来源' },
  { title: '结论 + 明细', desc: '既有文字回答，也有可核对的查询结果表' },
]
</script>

<template>
  <div class="auth">
    <aside class="auth__aside">
      <div class="auth__brand">
        <span class="auth__mark" aria-hidden="true">MED</span>
        <span class="auth__brand-text">体检报告分析</span>
      </div>

      <div class="auth__pitch">
        <h2 class="auth__claim">用一句话，读懂整份体检数据</h2>
        <p class="auth__lead">上传表格、用中文提问，后端把问题翻译成查询并在本地执行。</p>

        <ul class="auth__points">
          <li v-for="item in HIGHLIGHTS" :key="item.title">
            <span class="auth__dot" aria-hidden="true" />
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.desc }}</p>
            </div>
          </li>
        </ul>
      </div>

      <p class="auth__meta">本地演示环境 · 数据仅保存在本机</p>
    </aside>

    <main class="auth__main">
      <section class="auth__card">
        <header class="auth__head">
          <h1 class="auth__title">{{ title }}</h1>
          <p class="auth__subtitle">{{ subtitle }}</p>
        </header>

        <slot />
      </section>

      <slot name="footer" />
    </main>
  </div>
</template>

<style scoped>
.auth {
  display: grid;
  min-height: 100vh;
  background: var(--bg);
}

@media (min-width: 960px) {
  .auth {
    grid-template-columns: minmax(0, 5fr) minmax(0, 6fr);
  }
}

.auth__aside {
  display: none;
  position: relative;
  flex-direction: column;
  justify-content: space-between;
  padding: 40px 44px;
  overflow: hidden;
  background:
    radial-gradient(120% 90% at 12% 8%, rgba(88, 152, 214, 0.42), transparent 60%),
    linear-gradient(158deg, #14345c 0%, #1c4a7c 52%, #23557f 100%);
  color: #eaf2fb;
}

@media (min-width: 960px) {
  .auth__aside {
    display: flex;
  }
}

.auth__aside::after {
  content: '';
  position: absolute;
  right: -120px;
  bottom: -140px;
  width: 360px;
  height: 360px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
}

.auth__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.auth__mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.16);
  font-size: 12px;
  letter-spacing: 0.06em;
}

.auth__claim {
  max-width: 15em;
  font-size: 30px;
  line-height: 1.32;
  letter-spacing: -0.01em;
}

.auth__lead {
  max-width: 24em;
  margin-top: 12px;
  color: rgba(234, 242, 251, 0.76);
  font-size: 14px;
}

.auth__points {
  display: grid;
  gap: 16px;
  margin-top: 34px;
}

.auth__points li {
  display: flex;
  gap: 10px;
}

.auth__dot {
  flex: none;
  width: 6px;
  height: 6px;
  margin-top: 8px;
  border-radius: 50%;
  background: #7fb6ea;
}

.auth__points strong {
  font-size: 13.5px;
}

.auth__points p {
  color: rgba(234, 242, 251, 0.68);
  font-size: 12.5px;
  line-height: 1.6;
}

.auth__meta {
  color: rgba(234, 242, 251, 0.5);
  font-size: 12px;
}

.auth__main {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}

.auth__card {
  width: 100%;
  max-width: 388px;
  padding: 30px 28px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow);
}

.auth__head {
  margin-bottom: 22px;
}

.auth__title {
  font-size: 21px;
  line-height: 1.35;
}

.auth__subtitle {
  margin-top: 6px;
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 480px) {
  .auth__card {
    padding: 24px 20px;
    border-radius: 14px;
  }
}
</style>
