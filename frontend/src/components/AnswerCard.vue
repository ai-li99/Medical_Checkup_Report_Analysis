<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

import ResultTable from '@/components/ResultTable.vue'
import { formatClock, formatDuration, formatNumber } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps({
  message: { type: Object, required: true },
  index: { type: Number, default: 1 },
})

defineEmits(['retry'])

const KIND_LABEL = {
  count: '计数',
  list: '明细',
  aggregate: '分组统计',
  distinct: '去重取值',
  unsupported: '无法查询',
}

const isPending = computed(() => props.message.status === 'pending')
const isError = computed(() => props.message.status === 'error')
const result = computed(() => props.message.result)
const specText = computed(() =>
  props.message.querySpec ? JSON.stringify(props.message.querySpec, null, 2) : '',
)
const answerHtml = computed(() => renderMarkdown(props.message.answer))

const kindLabel = computed(() => KIND_LABEL[result.value?.kind] ?? result.value?.kind ?? '')

/** count 且无分组时，直接用标量展示，比一行表格直观。 */
const scalarValue = computed(() => {
  const data = result.value
  if (!data || data.kind !== 'count') return null
  if (data.group_by?.length) return null
  return data.value ?? null
})

const truncatedLabel = computed(() => {
  const data = result.value
  if (!data?.truncated) return ''
  return `仅展示前 ${formatNumber(data.row_count)} 行，共命中 ${formatNumber(data.matched_rows)} 行`
})

const matchedLabel = computed(() => {
  const data = result.value
  if (!data) return ''
  return `命中 ${formatNumber(data.matched_rows)} 行`
})

const returnedLabel = computed(() => {
  const data = result.value
  if (!data || data.kind === 'count') return ''
  return `返回 ${formatNumber(data.row_count)} 行`
})

/* ---------- 等待期间的时间计数 ---------- */
const tick = ref(Date.now())
let timer = null

const elapsed = computed(() =>
  isPending.value ? Math.max(0, tick.value - props.message.startedAt) : props.message.elapsedMs,
)

function stopTicker() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

watch(
  isPending,
  (pending) => {
    if (!pending) {
      stopTicker()
      return
    }
    stopTicker()
    tick.value = Date.now()
    timer = setInterval(() => {
      tick.value = Date.now()
    }, 500)
  },
  { immediate: true },
)

onUnmounted(stopTicker)
</script>

<template>
  <article class="answer card" :class="{ 'answer--error': isError }">
    <header class="answer__head">
      <span class="answer__index">第 {{ index }} 问</span>
      <span class="answer__time">{{ formatClock(message.startedAt) }}</span>
      <span v-if="message.attempts > 1" class="badge">第 {{ message.attempts }} 次</span>
      <span v-if="elapsed" class="answer__elapsed">{{ formatDuration(elapsed) }}</span>
    </header>

    <p class="answer__question">{{ message.question }}</p>

    <div v-if="isPending" class="answer__pending">
      <span class="spinner" aria-hidden="true" />
      <span>正在解析问题并执行查询，最长约 3 分钟…</span>
      <span class="muted">{{ formatDuration(elapsed) }}</span>
    </div>

    <template v-else-if="isError">
      <div class="notice notice--error">{{ message.error }}</div>
      <div class="answer__actions">
        <button class="btn btn--sm" type="button" @click="$emit('retry', message)">
          重试这个问题
        </button>
      </div>
    </template>

    <template v-else>
      <div v-if="message.degraded" class="notice notice--warn">
        <strong>查询未执行成功。</strong>
        <span>{{ message.error || '模型未能给出可执行的查询条件。' }}</span>
      </div>

      <div v-if="message.answer" class="answer-body" v-html="answerHtml" />
      <p v-else class="muted">（模型没有返回文字回答）</p>

      <section v-if="result" class="answer__result">
        <header class="answer__result-head">
          <span class="answer__result-title">查询结果</span>
          <span class="badge badge--primary">{{ kindLabel }}</span>
          <span v-if="matchedLabel" class="badge">{{ matchedLabel }}</span>
          <span v-if="returnedLabel" class="badge">{{ returnedLabel }}</span>
          <span v-if="truncatedLabel" class="badge badge--warn">{{ truncatedLabel }}</span>
        </header>

        <div v-if="result.kind === 'unsupported'" class="notice notice--warn answer__unsupported">
          {{ result.reason || '表里没有这个问题需要的字段，可以换个问法。' }}
        </div>

        <div v-else-if="scalarValue !== null" class="answer__scalar">
          <strong>{{ formatNumber(Number(scalarValue)) }}</strong>
          <span class="muted">{{ result.note || '条记录' }}</span>
        </div>

        <ResultTable
          v-else
          :columns="result.columns || []"
          :rows="result.rows || []"
        />

        <p v-if="result.note && scalarValue === null" class="answer__note muted">
          {{ result.note }}
        </p>
      </section>

      <details v-if="specText" class="answer__details">
        <summary>查询规格（调优用）</summary>
        <pre class="answer__pre">{{ specText }}</pre>
      </details>

      <details v-if="message.rawOutput" class="answer__details">
        <summary>模型原始输出（调试）</summary>
        <pre class="answer__pre">{{ message.rawOutput }}</pre>
      </details>
    </template>
  </article>
</template>

<style scoped>
.answer {
  padding: 16px 18px;
}

.answer--error {
  border-color: #f1c9c9;
}

.answer__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.answer__index {
  color: var(--primary);
  font-weight: 700;
}

.answer__time {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.answer__elapsed {
  margin-left: auto;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.answer__question {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.55;
  word-break: break-word;
}

.answer__pending {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 13px;
}

.answer__pending .spinner {
  color: var(--primary);
}

.answer__actions {
  margin-top: 10px;
}

.answer-body {
  margin-top: 10px;
}

.answer__result {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.answer__result-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.answer__result-title {
  font-size: 13px;
  font-weight: 600;
}

.answer__unsupported {
  margin-bottom: 4px;
}

.answer__scalar {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.answer__scalar strong {
  font-size: 30px;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.answer__scalar span {
  font-size: 12px;
}

.answer__note {
  margin-top: 8px;
  font-size: 12px;
}

.answer__details {
  margin-top: 12px;
  font-size: 12.5px;
}

.answer__details summary {
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}

.answer__details summary:hover {
  color: var(--primary);
}

.answer__pre {
  max-height: 280px;
  margin: 8px 0 0;
  padding: 10px 12px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  color: #374151;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
