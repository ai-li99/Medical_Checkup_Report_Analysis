<script setup>
import { computed } from 'vue'

const props = defineProps({
  busy: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
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

const trimmed = computed(() => question.value.trim())
const canSubmit = computed(() => !props.busy && !props.disabled && trimmed.value.length > 0)

function submit() {
  if (!canSubmit.value) return
  emit('submit', trimmed.value)
}

function onKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    submit()
  }
}

function useExample(example) {
  if (props.busy) return
  question.value = example
}
</script>

<template>
  <section class="ask card">
    <div class="ask__head">
      <label class="ask__label" for="question-input">提问</label>
      <span class="ask__counter" :class="{ 'ask__counter--over': question.length > MAX_LENGTH }">
        {{ question.length }} / {{ MAX_LENGTH }}
      </span>
    </div>

    <textarea
      id="question-input"
      v-model="question"
      class="ask__input"
      rows="3"
      :maxlength="MAX_LENGTH"
      :disabled="busy || disabled"
      placeholder="用中文描述你想统计的内容，例如：年龄大于 40 岁的人有多少？"
      @keydown="onKeydown"
    />

    <div class="ask__examples">
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

    <footer class="ask__foot">
      <p class="ask__hint muted">
        Ctrl / ⌘ + Enter 发送 · 追问可省略条件，但尽量描述完整
      </p>
      <button class="btn btn--primary" type="button" :disabled="!canSubmit" @click="submit">
        <span v-if="busy" class="spinner" aria-hidden="true" />
        {{ busy ? '正在分析…' : '提交问题' }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.ask {
  margin-top: 16px;
  padding: 18px 20px 16px;
}

.ask__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.ask__label {
  font-size: 13px;
  font-weight: 600;
}

.ask__counter {
  color: var(--muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.ask__counter--over {
  color: var(--danger);
}

.ask__input {
  display: block;
  width: 100%;
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
}

.ask__input:focus {
  border-color: var(--primary);
  outline: none;
}

.ask__input:disabled {
  background: var(--surface-muted);
  color: var(--muted);
}

.ask__examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
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

.ask__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
}

.ask__hint {
  font-size: 12px;
}

@media (max-width: 560px) {
  .ask__foot {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
