<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  busy: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  /** 对话为空时展示示例问题 */
  showExamples: { type: Boolean, default: false },
})

const emit = defineEmits(['submit'])

/** 由父组件 v-model 绑定，提交后由父组件清空。 */
const question = defineModel({ type: String, default: '' })

const MAX_LENGTH = 2000
const EXAMPLES = [
  '一共多少条记录？',
  '按性别统计人数',
  '年龄大于 40 岁的人有多少？',
  '列出年龄最大的前 10 条记录',
]

const textareaRef = ref(null)

const trimmed = computed(() => question.value.trim())
const canSubmit = computed(() => !props.busy && !props.disabled && trimmed.value.length > 0)

function submit() {
  if (!canSubmit.value) return
  emit('submit', trimmed.value)
}

/** Enter 发送，Shift+Enter 换行；输入法组词中不拦截。 */
function onKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) return
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submit()
}

/** 输入框随内容长高（最多 160px），避免长问题把对话框顶得过高。 */
function autosize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

watch(question, () => nextTick(autosize))

function useExample(text) {
  if (props.busy) return
  question.value = text
  nextTick(() => {
    autosize()
    textareaRef.value?.focus()
  })
}
</script>

<template>
  <div class="composer">
    <div v-if="showExamples" class="composer__examples">
      <span class="muted">试试：</span>
      <button
        v-for="example in EXAMPLES"
        :key="example"
        class="chip"
        type="button"
        :disabled="busy || disabled"
        @click="useExample(example)"
      >
        {{ example }}
      </button>
    </div>

    <div class="composer__box">
      <textarea
        ref="textareaRef"
        v-model="question"
        class="composer__input"
        rows="1"
        :maxlength="MAX_LENGTH"
        :disabled="busy || disabled"
        placeholder="问点什么，例如：年龄大于 40 岁的人有多少？"
        @input="autosize"
        @keydown="onKeydown"
      />
      <button class="btn btn--primary composer__send" type="button" :disabled="!canSubmit" @click="submit">
        <span v-if="busy" class="spinner" aria-hidden="true" />
        {{ busy ? '生成中' : '发送' }}
      </button>
    </div>

    <div class="composer__meta">
      <span>Enter 发送 · Shift + Enter 换行 · 追问可省略条件</span>
      <span :class="{ 'composer__count--over': question.length > MAX_LENGTH }">
        {{ question.length }} / {{ MAX_LENGTH }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.composer {
  width: 100%;
}

.composer__examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 12px;
}

.chip {
  padding: 3px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--muted);
  font-size: 12px;
  transition: border-color 0.15s ease, color 0.15s ease;
}

.chip:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.chip:disabled {
  opacity: 0.55;
}

.composer__box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 8px 8px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  background: var(--surface);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.composer__box:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(43, 108, 176, 0.12);
}

.composer__input {
  flex: 1;
  min-height: 24px;
  max-height: 160px;
  padding: 6px 0;
  border: 0;
  background: transparent;
  font-size: 14px;
  line-height: 1.6;
  resize: none;
  outline: none;
}

.composer__input:disabled {
  color: var(--muted);
}

.composer__send {
  flex: none;
  padding: 8px 16px;
  border-radius: 10px;
}

.composer__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 6px;
  padding: 0 4px;
  color: var(--muted);
  font-size: 11px;
}

.composer__count--over {
  color: var(--danger);
}

@media (max-width: 560px) {
  .composer__meta span:first-child {
    display: none;
  }

  .composer__meta {
    justify-content: flex-end;
  }
}
</style>
