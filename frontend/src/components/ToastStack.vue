<script setup>
import { dismissToast, toasts } from '@/composables/useToast'
</script>

<template>
  <div class="toast-stack" aria-live="polite" aria-atomic="false">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast"
        :class="`toast--${toast.tone}`"
        role="status"
      >
        <span class="toast__text">{{ toast.message }}</span>
        <button
          class="toast__close"
          type="button"
          aria-label="关闭提示"
          @click="dismissToast(toast.id)"
        >
          ×
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(360px, calc(100vw - 40px));
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 12px;
  border-radius: var(--radius-sm);
  background: #1f2937;
  color: #fff;
  font-size: 13px;
  line-height: 1.5;
  box-shadow: 0 10px 30px rgba(16, 24, 40, 0.24);
  pointer-events: auto;
}

.toast--success {
  background: #166534;
}

.toast--error {
  background: #991b1b;
}

.toast__text {
  flex: 1;
  word-break: break-word;
}

.toast__close {
  flex: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.16);
  color: inherit;
  font-size: 13px;
  line-height: 1;
}

.toast__close:hover {
  background: rgba(255, 255, 255, 0.28);
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@media (max-width: 640px) {
  .toast-stack {
    right: 12px;
    bottom: 12px;
    width: calc(100vw - 24px);
  }
}
</style>
