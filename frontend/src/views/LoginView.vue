<script setup>
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import AuthShell from '@/components/AuthShell.vue'
import { pushToast } from '@/composables/useToast'
import { login } from '@/stores/auth'

const USERNAME_RE = /^[A-Za-z0-9_]{3,32}$/

const router = useRouter()
const route = useRoute()

const form = ref({ username: '', password: '' })
const error = ref('')
const busy = ref(false)
const showPassword = ref(false)

const canSubmit = computed(
  () => !busy.value && form.value.username.trim().length > 0 && form.value.password.length > 0,
)

/** 从「账号设置」改密成功后跳回来时带 ?reset=1，提示用新密码登录。 */
const showResetNotice = computed(() => route.query.reset === '1')

/** 登录只做「非空 + 用户名格式」的轻校验，密码正确与否交给后端判定。 */
function validate() {
  if (!USERNAME_RE.test(form.value.username.trim())) {
    return '用户名需为 3-32 位字母、数字或下划线'
  }
  if (form.value.password.length === 0) {
    return '请输入密码'
  }
  return ''
}

/** 只接受站内路径，避免 ?redirect= 被拿来做开放重定向。 */
function resolveRedirect() {
  const target = route.query.redirect
  if (typeof target === 'string' && target.startsWith('/') && !target.startsWith('//')) {
    return target
  }
  return '/home'
}

async function submit() {
  if (busy.value) return

  error.value = validate()
  if (error.value) return

  busy.value = true
  try {
    await login({
      username: form.value.username.trim(),
      password: form.value.password,
    })
    pushToast('登录成功', 'success')
    await router.replace(resolveRedirect())
  } catch (err) {
    error.value = err?.message ?? '登录失败，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthShell title="登录" subtitle="登录后即可上传体检表并开始提问">
    <p v-if="showResetNotice" class="notice notice--info reset-notice">
      密码已重置，请用新密码重新登录。
    </p>

    <form class="form" novalidate @submit.prevent="submit">
      <div class="auth-field">
        <label class="auth-label" for="login-username">用户名</label>
        <input
          id="login-username"
          v-model="form.username"
          class="auth-input"
          type="text"
          name="username"
          autocomplete="username"
          spellcheck="false"
          placeholder="3-32 位字母、数字或下划线"
          :disabled="busy"
          :aria-invalid="Boolean(error)"
        />
      </div>

      <div class="auth-field">
        <label class="auth-label" for="login-password">密码</label>
        <div class="password">
          <input
            id="login-password"
            v-model="form.password"
            class="auth-input"
            :type="showPassword ? 'text' : 'password'"
            name="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            :disabled="busy"
            :aria-invalid="Boolean(error)"
          />
          <button
            class="password__toggle"
            type="button"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            {{ showPassword ? '隐藏' : '显示' }}
          </button>
        </div>
      </div>

      <p v-if="error" class="auth-error" role="alert">{{ error }}</p>

      <button class="btn btn--primary auth-submit" type="submit" :disabled="!canSubmit">
        <span v-if="busy" class="spinner" aria-hidden="true" />
        {{ busy ? '正在登录…' : '登录' }}
      </button>
    </form>

    <p class="auth-switch">
      还没有账号？
      <RouterLink to="/register">立即注册</RouterLink>
    </p>
  </AuthShell>
</template>

<style scoped>
.auth-switch {
  display: none;
}

.reset-notice {
  margin-bottom: 14px;
}

.form {
  display: grid;
  gap: 14px;
}

.password {
  position: relative;
}

.password .auth-input {
  padding-right: 58px;
}

.password__toggle {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  padding: 3px 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
}

.password__toggle:hover {
  background: var(--surface-muted);
  color: var(--primary);
}

.auth-submit {
  margin-top: 4px;
}
</style>
