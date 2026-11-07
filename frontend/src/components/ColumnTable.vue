<script setup>
import { computed, ref } from 'vue'

import { formatNumber } from '@/utils/format'

const props = defineProps({
  columns: { type: Array, default: () => [] },
})

const open = ref(false)
const keyword = ref('')

const filtered = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  if (!query) return props.columns
  return props.columns.filter((column) => String(column.name).toLowerCase().includes(query))
})

function dtypeTone(dtype) {
  switch (dtype) {
    case '整数':
    case '小数':
      return 'badge--primary'
    case '日期':
      return 'badge--ok'
    case '布尔':
      return 'badge--warn'
    default:
      return ''
  }
}
</script>

<template>
  <section class="columns card">
    <button class="columns__toggle" type="button" :aria-expanded="open" @click="open = !open">
      <span class="columns__chevron" :class="{ 'columns__chevron--open': open }" aria-hidden="true">
        ▸
      </span>
      <span class="columns__label">字段预览</span>
      <span class="badge">{{ columns.length }} 列</span>
      <span class="muted columns__hint">{{ open ? '收起' : '展开查看列名与样例' }}</span>
    </button>

    <div v-if="open" class="columns__body">
      <input
        v-model="keyword"
        class="columns__search"
        type="search"
        placeholder="搜索列名"
        aria-label="搜索列名"
      />

      <div class="columns__scroll">
        <table class="column-table">
          <thead>
            <tr>
              <th scope="col">字段</th>
              <th scope="col">类型</th>
              <th scope="col" class="num">非空</th>
              <th scope="col" class="num">缺失</th>
              <th scope="col">样例</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="column in filtered" :key="column.name">
              <td class="column-table__name">{{ column.name }}</td>
              <td>
                <span class="badge" :class="dtypeTone(column.dtype)">{{ column.dtype }}</span>
              </td>
              <td class="num">{{ formatNumber(column.non_null) }}</td>
              <td class="num">
                <span :class="{ 'column-table__missing': column.missing > 0 }">
                  {{ formatNumber(column.missing) }}
                </span>
              </td>
              <td class="column-table__sample">
                <template v-if="column.sample && column.sample.length">
                  {{ column.sample.join(' / ') }}
                </template>
                <span v-else class="muted">—</span>
              </td>
            </tr>
            <tr v-if="filtered.length === 0">
              <td class="column-table__empty" colspan="5">没有匹配的列</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.columns {
  margin-top: 16px;
  overflow: hidden;
}

.columns__toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 12px 16px;
  border: 0;
  background: transparent;
  text-align: left;
}

.columns__toggle:hover {
  background: var(--surface-muted);
}

.columns__chevron {
  color: var(--muted);
  font-size: 11px;
  transition: transform 0.15s ease;
}

.columns__chevron--open {
  transform: rotate(90deg);
}

.columns__label {
  font-size: 13px;
  font-weight: 600;
}

.columns__hint {
  margin-left: auto;
  font-size: 12px;
}

.columns__body {
  padding: 0 16px 16px;
}

.columns__search {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  font-size: 13px;
}

.columns__search:focus {
  border-color: var(--primary);
  outline: none;
}

.columns__scroll {
  max-height: 320px;
  margin-top: 10px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.column-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.column-table th,
.column-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}

.column-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface-muted);
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.column-table tbody tr:last-child td {
  border-bottom: 0;
}

.column-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.column-table__name {
  font-weight: 600;
  word-break: break-all;
}

.column-table__sample {
  max-width: 320px;
  color: var(--muted);
  word-break: break-all;
}

.column-table__missing {
  color: var(--warn);
  font-weight: 600;
}

.column-table__empty {
  color: var(--muted);
  text-align: center;
}
</style>
