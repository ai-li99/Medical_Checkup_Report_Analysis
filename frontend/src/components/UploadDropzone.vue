<script setup>
import { ref } from 'vue'

import { ACCEPT_ATTR } from '@/utils/file'

const props = defineProps({
  uploading: { type: Boolean, default: false },
  progress: { type: Number, default: 0 },
  fileHint: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const inputRef = ref(null)
const dragging = ref(false)
/** dragenter/dragleave 会在子元素间反复触发，用计数避免闪烁。 */
let dragDepth = 0

function openPicker() {
  if (props.uploading) return
  inputRef.value?.click()
}

function onChange(event) {
  const file = event.target.files?.[0]
  // 清空 value，保证再次选择同一个文件也能触发 change。
  event.target.value = ''
  if (file) emit('select', file)
}

function onDragEnter(event) {
  event.preventDefault()
  dragDepth += 1
  if (!props.uploading) dragging.value = true
}

function onDragOver(event) {
  event.preventDefault()
}

function onDragLeave(event) {
  event.preventDefault()
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragging.value = false
}

function onDrop(event) {
  event.preventDefault()
  dragDepth = 0
  dragging.value = false
  if (props.uploading) return
  const file = event.dataTransfer?.files?.[0]
  if (file) emit('select', file)
}

function onKeydown(event) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    openPicker()
  }
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ 'dropzone--active': dragging, 'dropzone--busy': uploading }"
    role="button"
    tabindex="0"
    :aria-disabled="uploading ? 'true' : 'false'"
    @click="openPicker"
    @keydown="onKeydown"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="inputRef"
      class="sr-only"
      type="file"
      :accept="ACCEPT_ATTR"
      @change="onChange"
    />

    <template v-if="uploading">
      <span class="spinner dropzone__spinner" aria-hidden="true" />
      <p class="dropzone__title">正在上传并解析…</p>
      <div class="progress" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100">
        <div class="progress__bar" :style="{ width: `${progress}%` }" />
      </div>
      <p class="dropzone__hint">已传输 {{ progress }}%，解析大文件可能需要几秒</p>
    </template>

    <template v-else>
      <svg class="dropzone__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
      <p class="dropzone__title">把体检表格拖到这里，或点击选择文件</p>
      <p class="dropzone__hint">
        支持 .xlsx / .csv，单个文件不超过 50 MB、20 万行
      </p>
      <p v-if="fileHint" class="dropzone__hint muted">{{ fileHint }}</p>
    </template>
  </div>
</template>

<style scoped>
.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 44px 24px;
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface);
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.dropzone:hover,
.dropzone:focus-visible {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.dropzone--active {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.dropzone--busy {
  cursor: progress;
  border-style: solid;
}

.dropzone__icon {
  width: 30px;
  height: 30px;
  color: var(--primary);
}

.dropzone__spinner {
  color: var(--primary);
  width: 18px;
  height: 18px;
}

.dropzone__title {
  font-size: 14px;
  font-weight: 600;
}

.dropzone__hint {
  font-size: 12px;
}

.progress {
  width: min(320px, 100%);
  height: 6px;
  margin-top: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--border);
}

.progress__bar {
  height: 100%;
  border-radius: inherit;
  background: var(--primary);
  transition: width 0.2s ease;
}
</style>
