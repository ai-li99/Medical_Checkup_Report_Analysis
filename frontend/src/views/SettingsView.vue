<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { pushToast } from '@/composables/useToast'
import { auth, resetPassword } from '@/stores/auth'

const PASSWORD_MIN = 8
const PASSWORD_MAX = 64

const router = useRouter()

const form = ref({ oldPassword: '', newPassword: '', confirm: '' })
const error = ref('')
const busy = ref(false)
const showPassword = ref(false)

const canSubmit = computed(
  () => !busy.value && form.value.newPassword.length > 0 && form.value.confirm.length > 0,
)

const newPasswordHint = computed(() => {
  const length = form.value.newPassword.length
  if (length === 0) return `${PASSWORD_MIN}-${PASSWORD_MAX} 位，建议字母与数字混用`
  if (length < PASSWORD_MIN) return `还差 ${PASSWORD_MIN - length} 位`
  if (length > PASSWORD_MAX) return `超出 ${length - PASSWORD_MAX} 位`
  return '长度符合要求'
})

function validate() {
  const { oldPassword, newPassword, confirm } = form.value
  if (newPassword.length < PASSWORD_MIN) return `密码至少 ${PASSWORD_MIN} 位`
  if (newPassword.length > PASSWORD_MAX) return `密码最多 ${PASSWORD_MAX} 位`
  if (oldPassword && oldPassword === newPassword) return '新密码不能与原密码相同'
  if (newPassword !== confirm) return '两次输入的新密码不一致'
  return ''
}

async function submit() {
  if (busy.value) return

  error.value = validate()
  if (error.value) return

  busy.value = true
  try {
    await resetPassword({
      newPassword: form.value.newPassword,
      oldPassword: form.value.oldPassword || undefined,
    })
    // 后端已作废所有令牌，store 里也清空了登录态。
    pushToast('密码已重置，请用新密码重新登录', 'success')
    await router.replace({ name: 'login', query: { reset: '1' } })
  } catch (err) {
    if (err?.code === 'old_password_mismatch') {
      error.value = '原密码不正确'
    } else if (err?.code === 'reset_requires_login') {
      error.value = '登录状态已失效，请重新登录后再修改密码'
    } else {
      error.value = err?.message ?? '修改密码失败，请重试'
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="settings">
    <header class="page-head">
      <h1 class="page-head__title">账号设置</h1>
      <p class="page-head__desc">修改登录密码。修改成功后所有设备都需要用新密码重新登录。</p>
    </header>

    <section class="card account">
      <div class="account__row">
        <span class="account__label">用户名</span>
        <span class="account__value">{{ auth.user?.username || '—' }}</span>
      </div>
      <div class="account__row">
        <span class="account__label">注册时间</span>
        <span class="account__value">{{ auth.user?.createdAt || '—' }}</span>
      </div>
    </section>

    <section class="card password-card">
      <h2 class="password-card__title">修改密码</h2>

      <form class="form" novalidate @submit.prevent="submit">
        <div class="auth-field">
          <label class="auth-label" for="old-password">原密码</label>
          <div class="password">
            <input
              id="old-password"
              v-model="form.oldPassword"
              class="auth-input"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="可不填；填写则会校验"
              :disabled="busy"
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

        <div class="auth-field">
          <label class="auth-label" for="new-password">新密码</label>
          <input
            id="new-password"
            v-model="form.newPassword"
            class="auth-input"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="new-password"
            placeholder="至少 8 位"
            :disabled="busy"
            :aria-invalid="Boolean(error)"
          />
          <p class="auth-hint">{{ newPasswordHint }}</p>
        </div>

        <div class="auth-field">
          <label class="auth-label" for="confirm-password">确认新密码</label>
          <input
            id="confirm-password"
            v-model="form.confirm"
            class="auth-input"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="new-password"
            placeholder="再输入一次新密码"
            :disabled="busy"
            :aria-invalid="Boolean(error)"
          />
        </div>

        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>

        <div class="form__foot">
          <p class="auth-hint">修改成功后会被强制退出登录。</p>
          <button class="btn btn--primary" type="submit" :disabled="!canSubmit">
            <span v-if="busy" class="spinner" aria-hidden="true" />
            {{ busy ? '正在提交…' : '确认修改' }}
          </button>
        </div>
      </form>
    </section>
  </div>
</template>

<style scoped>
.settings {
  max-width: 560px;
}

.account {
  display: grid;
  gap: 10px;
  margin-top: 16px;
  padding: 16px 18px;
}

.account__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  font-size: 13px;
}

.account__label {
  color: var(--muted);
}

.account__value {
  font-weight: 600;
  word-break: break-all;
}

.password-card {
  margin-top: 16px;
  padding: 20px;
}

.password-card__title {
  font-size: 15px;
}

.form {
  display: grid;
  gap: 14px;
  margin-top: 14px;
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

.form__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 4px;
}

@media (max-width: 560px) {
  .form__foot {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
