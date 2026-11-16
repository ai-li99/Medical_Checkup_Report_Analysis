<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '确认操作' },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  /** 危险操作：确认按钮用红色 */
  danger: { type: Boolean, default: false },
  /** 处理中：按钮禁用、禁止关闭 */
  busy: { type: Boolean, default: false },
  /** 表单未填完时单独禁用确认按钮（不影响取消） */
  confirmDisabled: { type: Boolean, default: false },
  /** 内容居中（用于删除这类需要强调警示的弹窗） */
  center: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm', 'cancel'])

const cardRef = ref(null)
const cancelRef = ref(null)

function close() {
  if (props.busy) return
  emit('cancel')
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

/** 打开时把焦点放到「取消」上：破坏性操作默认不聚焦红色按钮。 */
watch(
  () => props.open,
  async (open) => {
    if (open) {
      await nextTick()
      cancelRef.value?.focus()
    }
  },
)

let previousOverflow = ''

watch(
  () => props.open,
  (open) => {
    if (open) {
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = previousOverflow
    }
  },
)

onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = previousOverflow
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal" @mousedown.self="close">
        <div
          ref="cardRef"
          class="modal__card"
          :class="{ 'modal__card--center': center }"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
        >
          <h2 class="modal__title">{{ title }}</h2>

          <div class="modal__body">
            <slot />
          </div>

          <footer class="modal__actions">
            <button
              ref="cancelRef"
              class="btn modal__cancel"
              type="button"
              :disabled="busy"
              @click="emit('cancel')"
            >
              {{ cancelText }}
            </button>
            <button
              class="btn"
              :class="danger ? 'btn--danger' : 'btn--primary'"
              type="button"
              :disabled="busy || confirmDisabled"
              @click="emit('confirm')"
            >
              <span v-if="busy" class="spinner" aria-hidden="true" />
              {{ busy ? '处理中…' : confirmText }}
            </button>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.48);
  backdrop-filter: blur(2px);
}

.modal__card {
  width: min(420px, 100%);
  padding: 22px;
  border-radius: 16px;
  background: var(--surface);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.28);
}

.modal__title {
  font-size: 17px;
  line-height: 1.4;
}

.modal__body {
  margin-top: 10px;
  color: var(--muted);
  font-size: 13.5px;
  line-height: 1.65;
}

.modal__card--center .modal__title,
.modal__card--center .modal__body {
  text-align: center;
}

.modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}

.modal__card--center .modal__actions {
  justify-content: center;
}

/* 取消：白底（默认 .btn 就是白底描边），这里只是显式声明 */
.modal__cancel {
  background: var(--surface);
  color: var(--text);
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.16s ease;
}

.modal-enter-active .modal__card,
.modal-leave-active .modal__card {
  transition: transform 0.16s ease, opacity 0.16s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal__card,
.modal-leave-to .modal__card {
  transform: translateY(8px) scale(0.98);
  opacity: 0;
}

@media (max-width: 480px) {
  .modal__actions {
    flex-direction: column-reverse;
  }

  .modal__actions .btn {
    width: 100%;
  }
}
</style>
