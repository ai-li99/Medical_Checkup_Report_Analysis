<script setup>
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import AuthShell from '@/components/AuthShell.vue'
import { pushToast } from '@/composables/useToast'
import { register } from '@/stores/auth'

const USERNAME_RE = /^[A-Za-z0-9_]{3,32}$/
const PASSWORD_MIN = 8
const PASSWORD_MAX = 64

const router = useRouter()

const form = ref({ username: '', password: '', confirm: '' })
const error = ref('')
const busy = ref(false)
const showPassword = ref(false)

const canSubmit = computed(
  () =>
    !busy.value &&
    form.value.username.trim().length > 0 &&
    form.value.password.length > 0 &&
    form.value.confirm.length > 0,
)

const passwordHint = computed(() => {
  const length = form.value.password.length
  if (length === 0) return `${PASSWORD_MIN}-${PASSWORD_MAX} 位，建议字母与数字混用`
  if (length < PASSWORD_MIN) return `还差 ${PASSWORD_MIN - length} 位`
  if (length > PASSWORD_MAX) return `超出 ${length - PASSWORD_MAX} 位`
  return '长度符合要求'
})

function validate() {
  const username = form.value.username.trim()
  if (!USERNAME_RE.test(username)) {
    return '用户名需为 3-32 位字母、数字或下划线'
  }
  if (form.value.password.length < PASSWORD_MIN) {
    return `密码至少 ${PASSWORD_MIN} 位`
  }
  if (form.value.password.length > PASSWORD_MAX) {
    return `密码最多 ${PASSWORD_MAX} 位`
  }
  if (form.value.password !== form.value.confirm) {
    return '两次输入的密码不一致'
  }
  return ''
}

async function submit() {
  if (busy.value) return

  error.value = validate()
  if (error.value) return

  busy.value = true
  try {
    // 后端「注册即登录」，直接拿到 token，无需再调一次 login。
    await register({
      username: form.value.username.trim(),
      password: form.value.password,
    })
    pushToast('注册成功，已自动登录', 'success')
    await router.replace('/home')
  } catch (err) {
    error.value = err?.message ?? '注册失败，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthShell title="注册" subtitle="创建账号后立即进入分析工作台">
    <form class="form" novalidate @submit.prevent="submit">
      <div class="auth-field">
        <label class="auth-label" for="register-username">用户名</label>
        <input
          id="register-username"
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
        <label class="auth-label" for="register-password">密码</label>
        <div class="password">
          <input
            id="register-password"
            v-model="form.password"
            class="auth-input"
            :type="showPassword ? 'text' : 'password'"
            name="new-password"
            autocomplete="new-password"
            placeholder="至少 8 位"
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
        <p class="auth-hint">{{ passwordHint }}</p>
      </div>

      <div class="auth-field">
        <label class="auth-label" for="register-confirm">确认密码</label>
        <input
          id="register-confirm"
          v-model="form.confirm"
          class="auth-input"
          :type="showPassword ? 'text' : 'password'"
          name="confirm-password"
          autocomplete="new-password"
          placeholder="再输入一次密码"
          :disabled="busy"
          :aria-invalid="Boolean(error)"
        />
      </div>

      <p v-if="error" class="auth-error" role="alert">{{ error }}</p>

      <button class="btn btn--primary auth-submit" type="submit" :disabled="!canSubmit">
        <span v-if="busy" class="spinner" aria-hidden="true" />
        {{ busy ? '正在注册…' : '注册并登录' }}
      </button>
    </form>

    <p class="auth-switch">
      已有账号？
      <RouterLink to="/login">返回登录</RouterLink>
    </p>
  </AuthShell>
</template>

<style scoped>
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
