<script setup>
import { computed, ref } from 'vue'

import { formatNumber } from '@/utils/format'

const props = defineProps({
  sheets: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm'])

/** 'merge_all' 合并全部；'select' 只取勾选的若干个 */
const mode = ref('merge_all')
const selected = ref([])

const totalRows = computed(() =>
  props.sheets.reduce((sum, sheet) => sum + (Number(sheet.rows) || 0), 0),
)

const canConfirm = computed(() => {
  if (props.busy) return false
  return mode.value === 'merge_all' || selected.value.length > 0
})

function isChecked(name) {
  return selected.value.includes(name)
}

function toggle(name) {
  if (mode.value === 'merge_all') return
  selected.value = isChecked(name)
    ? selected.value.filter((item) => item !== name)
    : [...selected.value, name]
}

function selectAll() {
  mode.value = 'select'
  selected.value = props.sheets.map((sheet) => sheet.name)
}

function clearAll() {
  selected.value = []
}

function confirm() {
  if (!canConfirm.value) return
  emit('confirm', {
    mode: mode.value,
    sheets: mode.value === 'merge_all' ? [] : [...selected.value],
  })
}
</script>

<template>
  <section class="picker card">
    <header class="picker__head">
      <div>
        <h2 class="picker__title">选择要分析的工作表</h2>
        <p class="picker__desc">
          该文件含 {{ sheets.length }} 个工作表，共 {{ formatNumber(totalRows) }} 行。
          勾选后按工作表顺序纵向合并，列名必须一致。
        </p>
      </div>
    </header>

    <div class="picker__modes" role="radiogroup" aria-label="工作表选择方式">
      <label class="mode" :class="{ 'mode--active': mode === 'merge_all' }">
        <input v-model="mode" class="sr-only" type="radio" value="merge_all" />
        <span class="mode__title">合并全部工作表</span>
        <span class="mode__desc">自动追加 <code>_sheet</code> 列标记数据来源</span>
      </label>
      <label class="mode" :class="{ 'mode--active': mode === 'select' }">
        <input v-model="mode" class="sr-only" type="radio" value="select" />
        <span class="mode__title">只选其中若干个</span>
        <span class="mode__desc">选 1 个即单表，选多个则纵向合并</span>
      </label>
    </div>

    <div class="picker__toolbar">
      <span class="muted">工作表</span>
      <div class="picker__actions">
        <button
          class="btn btn--ghost btn--sm"
          type="button"
          :disabled="mode === 'merge_all' || busy"
          @click="selectAll"
        >
          全选
        </button>
        <button
          class="btn btn--ghost btn--sm"
          type="button"
          :disabled="mode === 'merge_all' || busy || selected.length === 0"
          @click="clearAll"
        >
          清空
        </button>
      </div>
    </div>

    <ul class="picker__list">
      <li v-for="sheet in sheets" :key="sheet.name">
        <label
          class="sheet"
          :class="{
            'sheet--checked': mode === 'select' && isChecked(sheet.name),
            'sheet--disabled': mode === 'merge_all',
          }"
        >
          <input
            class="sheet__box"
            type="checkbox"
            :checked="mode === 'merge_all' || isChecked(sheet.name)"
            :disabled="mode === 'merge_all' || busy"
            @change="toggle(sheet.name)"
          />
          <span class="sheet__name">{{ sheet.name }}</span>
          <span class="sheet__meta">
            {{ formatNumber(sheet.rows) }} 行 × {{ formatNumber(sheet.columns) }} 列
          </span>
        </label>
      </li>
    </ul>

    <footer class="picker__foot">
      <p v-if="mode === 'select' && selected.length === 0" class="picker__hint">
        请至少勾选一个工作表
      </p>
      <p v-else class="picker__hint muted">
        合并多个表时若列名不一致会失败，此时需要重新上传文件。
      </p>

      <button class="btn btn--primary" type="button" :disabled="!canConfirm" @click="confirm">
        <span v-if="busy" class="spinner" aria-hidden="true" />
        {{ busy ? '正在载入…' : '载入并开始' }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.picker {
  margin-top: 16px;
  padding: 20px;
}

.picker__title {
  font-size: 16px;
}

.picker__desc {
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
}

.picker__modes {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

@media (min-width: 640px) {
  .picker__modes {
    grid-template-columns: 1fr 1fr;
  }
}

.mode {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.mode:hover {
  border-color: var(--border-strong);
}

.mode--active {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.mode__title {
  font-size: 13px;
  font-weight: 600;
}

.mode__desc {
  color: var(--muted);
  font-size: 12px;
}

.mode__desc code {
  padding: 0 3px;
  border-radius: 4px;
  background: rgba(43, 108, 176, 0.12);
  font-size: 11px;
}

.picker__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 18px;
  font-size: 13px;
}

.picker__actions {
  display: flex;
  gap: 4px;
}

.picker__list {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}

.sheet {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.sheet:hover {
  border-color: var(--border-strong);
}

.sheet--checked {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.sheet--disabled {
  cursor: not-allowed;
}

.sheet__box {
  width: 15px;
  height: 15px;
  accent-color: var(--primary);
}

.sheet__name {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}

.sheet__meta {
  color: var(--muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.picker__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.picker__hint {
  font-size: 12px;
}

.picker__hint:not(.muted) {
  color: var(--warn);
}

@media (max-width: 560px) {
  .picker__foot {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
