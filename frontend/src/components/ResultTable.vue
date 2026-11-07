<script setup>
import { displayCell, formatNumber } from '@/utils/format'

defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="table-wrap">
    <table class="result-table">
      <thead>
        <tr>
          <th scope="col" class="result-table__index">#</th>
          <th v-for="column in columns" :key="column" scope="col">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, rowIndex) in rows" :key="rowIndex">
          <td class="result-table__index">{{ formatNumber(rowIndex + 1) }}</td>
          <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ displayCell(cell) }}</td>
        </tr>
        <tr v-if="rows.length === 0">
          <td class="result-table__empty" :colspan="columns.length + 1">没有匹配的数据</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.table-wrap {
  max-height: 360px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.result-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.result-table th,
.result-table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
}

.result-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface-muted);
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.result-table tbody tr:last-child td {
  border-bottom: 0;
}

.result-table tbody tr:hover td {
  background: var(--surface-muted);
}

.result-table__index {
  width: 44px;
  color: var(--muted);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.result-table__empty {
  color: var(--muted);
  text-align: center;
}
</style>
