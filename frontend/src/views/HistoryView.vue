<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import AnswerCard from '@/components/AnswerCard.vue'
import { deleteSession, fetchHistory, fetchSessionTurns, fetchTurnDetail } from '@/api'
import { pushToast } from '@/composables/useToast'
import { forgetSession, resumeFromHistory, turnToMessage } from '@/stores/session'
import { formatDateTime, formatNumber } from '@/utils/format'

const PAGE_SIZE = 20

const router = useRouter()

const sessions = ref([])
const total = ref(0)
const listLoading = ref(false)
const listError = ref('')

const activeId = ref('')
const turns = ref([])
const turnsLoading = ref(false)
const turnsError = ref('')

/** turn_id -> 已转成 AnswerCard 可渲染结构的 message */
const details = reactive({})
const activeTurnId = ref(null)
const detailLoadingId = ref(null)

const resumingId = ref('')
/** 是否处于「确认删除」状态（删除会连原始文件一起删，必须二次确认） */
const confirmingDelete = ref(false)
const deleting = ref(false)

const hasMore = computed(() => sessions.value.length < total.value)
const activeSession = computed(
  () => sessions.value.find((item) => item.session_id === activeId.value) ?? null,
)

async function loadSessions({ append = false } = {}) {
  if (listLoading.value) return

  listLoading.value = true
  listError.value = ''

  try {
    const offset = append ? sessions.value.length : 0
    const data = await fetchHistory({ limit: PAGE_SIZE, offset })
    const items = data.items ?? []

    sessions.value = append ? [...sessions.value, ...items] : items
    total.value = data.total ?? sessions.value.length

    if (!append) {
      activeId.value = ''
      turns.value = []
      if (sessions.value.length > 0) selectSession(sessions.value[0])
    }
  } catch (error) {
    listError.value = error?.message ?? '加载历史记录失败'
  } finally {
    listLoading.value = false
  }
}

async function selectSession(item) {
  if (!item) return

  activeId.value = item.session_id
  activeTurnId.value = null
  confirmingDelete.value = false
  turns.value = []
  turnsError.value = ''
  turnsLoading.value = true

  try {
    const data = await fetchSessionTurns(item.session_id)
    turns.value = data.turns ?? []
  } catch (error) {
    turnsError.value = error?.message ?? '加载会话失败'
  } finally {
    turnsLoading.value = false
  }
}

async function toggleTurn(turn) {
  if (activeTurnId.value === turn.turn_id) {
    activeTurnId.value = null
    return
  }

  activeTurnId.value = turn.turn_id
  if (details[turn.turn_id]) return

  detailLoadingId.value = turn.turn_id
  try {
    const data = await fetchTurnDetail(turn.turn_id)
    details[turn.turn_id] = turnToMessage(data)
  } catch (error) {
    details[turn.turn_id] = null
    pushToast(error?.message ?? '加载这条记录失败', 'error')
  } finally {
    detailLoadingId.value = null
  }
}

async function resume(item) {
  if (!item || resumingId.value) return

  resumingId.value = item.session_id
  try {
    const result = await resumeFromHistory(item.session_id)

    if (!result.ok) {
      if (!result.error) return
      const message =
        result.error.status === 404
          ? '原始文件已不存在，只能查看历史，无法继续提问'
          : result.error.message ?? '恢复会话失败'
      pushToast(message, 'error')
      return
    }

    pushToast(
      result.turns > 0 ? `会话已恢复，载入 ${result.turns} 轮历史问答` : '会话已恢复',
      'success',
    )
    await router.push({ name: 'home' })
  } finally {
    resumingId.value = ''
  }
}

onMounted(() => loadSessions())

/* ---------------- 删除会话 ---------------- */

function requestDelete() {
  if (!activeSession.value || deleting.value) return
  confirmingDelete.value = true
}

function cancelDelete() {
  confirmingDelete.value = false
}

async function confirmDelete() {
  const item = activeSession.value
  if (!item || deleting.value) return

  deleting.value = true
  try {
    const result = await deleteSession(item.session_id)

    // 工作台如果正开着这个会话，一起清掉，避免继续对着已删除的 session 提问
    forgetSession(item.session_id)

    sessions.value = sessions.value.filter((entry) => entry.session_id !== item.session_id)
    total.value = Math.max(0, total.value - 1)
    activeId.value = ''
    activeTurnId.value = null
    turns.value = []
    confirmingDelete.value = false

    const turnsDeleted = Number(result?.deleted_turns) || 0
    pushToast(
      turnsDeleted > 0
        ? `已删除 ${turnsDeleted} 轮对话及原始文件`
        : '已删除该会话的记录',
      'success',
    )

    if (sessions.value.length > 0) {
      selectSession(sessions.value[0])
    } else if (hasMore.value) {
      await loadSessions()
    }
  } catch (error) {
    if (error?.status === 404) {
      pushToast('记录不存在或已被删除', 'error')
      await loadSessions()
    } else {
      pushToast(error?.message ?? '删除失败，请重试', 'error')
    }
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="history">
    <header class="page-head">
      <h1 class="page-head__title">历史记录</h1>
      <p class="page-head__desc">
        共 {{ formatNumber(total) }} 个会话。记录是当时的快照，打开不消耗模型额度；点「继续问」可恢复上下文接着聊。
      </p>
    </header>

    <div class="history__grid">
      <aside class="card history__list">
        <p v-if="listLoading && sessions.length === 0" class="history__placeholder">加载中…</p>

        <div v-else-if="listError" class="history__placeholder">
          <p>{{ listError }}</p>
          <button class="btn btn--sm" type="button" @click="loadSessions()">重试</button>
        </div>

        <p v-else-if="sessions.length === 0" class="history__placeholder">
          还没有历史记录。去
          <RouterLink class="link" :to="{ name: 'home' }">工作台</RouterLink>
          上传一份体检表开始吧。
        </p>

        <ul v-else class="session-list">
          <li v-for="item in sessions" :key="item.session_id">
            <button
              class="session-item"
              :class="{ 'session-item--active': item.session_id === activeId }"
              type="button"
              @click="selectSession(item)"
            >
              <span class="session-item__name">{{ item.filename }}</span>
              <span class="session-item__meta">
                <span class="badge">{{ formatNumber(item.turn_count) }} 轮</span>
                <span class="badge">
                  {{ formatNumber(item.rows) }} 行 × {{ formatNumber(item.columns) }} 列
                </span>
              </span>
              <span v-if="item.last_question" class="session-item__question">
                {{ item.last_question }}
              </span>
              <span class="session-item__time">{{ formatDateTime(item.updated_at) }}</span>
            </button>
          </li>
        </ul>

        <button
          v-if="hasMore"
          class="btn btn--sm history__more"
          type="button"
          :disabled="listLoading"
          @click="loadSessions({ append: true })"
        >
          {{ listLoading ? '加载中…' : `加载更多（还有 ${formatNumber(total - sessions.length)} 个）` }}
        </button>
      </aside>

      <section class="history__detail">
        <p v-if="!activeSession" class="card history__empty">从左侧选择一个会话查看详情</p>

        <template v-else>
          <header class="card detail-head">
            <div class="detail-head__main">
              <h2 class="detail-head__name">{{ activeSession.filename }}</h2>
              <p class="detail-head__meta">
                {{ formatNumber(activeSession.rows) }} 行 ×
                {{ formatNumber(activeSession.columns) }} 列 ·
                {{ formatNumber(activeSession.turn_count) }} 轮问答 · 最近更新
                {{ formatDateTime(activeSession.updated_at) }}
              </p>
            </div>
            <div class="detail-head__actions">
              <template v-if="confirmingDelete">
                <span class="detail-head__warn">会连同原始文件一起删除</span>
                <button class="btn btn--sm" type="button" :disabled="deleting" @click="cancelDelete">
                  取消
                </button>
                <button
                  class="btn btn--danger btn--sm"
                  type="button"
                  :disabled="deleting"
                  @click="confirmDelete"
                >
                  <span v-if="deleting" class="spinner" aria-hidden="true" />
                  {{ deleting ? '删除中…' : '确认删除' }}
                </button>
              </template>

              <template v-else>
                <button
                  class="btn btn--primary btn--sm"
                  type="button"
                  :disabled="Boolean(resumingId) || deleting"
                  @click="resume(activeSession)"
                >
                  <span
                    v-if="resumingId === activeSession.session_id"
                    class="spinner"
                    aria-hidden="true"
                  />
                  {{ resumingId === activeSession.session_id ? '正在恢复…' : '继续问' }}
                </button>
                <button
                  class="btn btn--danger-ghost btn--sm"
                  type="button"
                  :disabled="deleting"
                  @click="requestDelete"
                >
                  删除
                </button>
              </template>
            </div>
          </header>

          <p v-if="turnsLoading" class="card history__empty">加载中…</p>
          <p v-else-if="turnsError" class="card history__empty">{{ turnsError }}</p>
          <p v-else-if="turns.length === 0" class="card history__empty">这个会话还没有问答记录。</p>

          <ul v-else class="turn-list">
            <li v-for="(turn, index) in turns" :key="turn.turn_id" class="turn">
              <button
                class="turn__head"
                :class="{ 'turn__head--open': activeTurnId === turn.turn_id }"
                type="button"
                :aria-expanded="activeTurnId === turn.turn_id"
                @click="toggleTurn(turn)"
              >
                <span class="turn__index">{{ index + 1 }}</span>
                <span class="turn__main">
                  <span class="turn__question">{{ turn.question }}</span>
                  <span class="turn__preview">{{ turn.answer_preview }}</span>
                </span>
                <span v-if="turn.degraded" class="badge badge--warn">未执行</span>
                <span class="turn__time">{{ formatDateTime(turn.created_at) }}</span>
                <span
                  class="turn__chevron"
                  :class="{ 'turn__chevron--open': activeTurnId === turn.turn_id }"
                  aria-hidden="true"
                >
                  ▾
                </span>
              </button>

              <div v-if="activeTurnId === turn.turn_id" class="turn__detail">
                <p v-if="detailLoadingId === turn.turn_id" class="turn__hint">加载中…</p>
                <AnswerCard
                  v-else-if="details[turn.turn_id]"
                  :message="details[turn.turn_id]"
                  :index="index + 1"
                />
                <p v-else class="turn__hint">这条记录加载失败</p>
              </div>
            </li>
          </ul>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.history__grid {
  display: grid;
  gap: 16px;
  margin-top: 16px;
}

@media (min-width: 900px) {
  .history__grid {
    grid-template-columns: 320px minmax(0, 1fr);
    align-items: start;
  }
}

/* ---------- 左侧会话列表 ---------- */
.history__list {
  display: flex;
  flex-direction: column;
  padding: 8px;
  max-height: 70vh;
}

.session-list {
  display: grid;
  gap: 6px;
  overflow: auto;
}

.session-item {
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.session-item:hover {
  background: var(--surface-muted);
}

.session-item--active {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.session-item__name {
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}

.session-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.session-item__question {
  display: -webkit-box;
  overflow: hidden;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.session-item__time {
  color: var(--muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.history__more {
  margin: 8px 4px 4px;
}

.history__placeholder,
.history__empty {
  padding: 22px 18px;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}

.history__placeholder {
  display: grid;
  gap: 10px;
  place-items: center;
}

/* ---------- 右侧详情 ---------- */
.history__detail {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
}

.detail-head__main {
  min-width: 0;
}

.detail-head__actions {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.detail-head__warn {
  color: var(--danger);
  font-size: 12px;
}

.detail-head__name {
  font-size: 15px;
  word-break: break-all;
}

.detail-head__meta {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.turn-list {
  display: grid;
  gap: 8px;
}

.turn {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: hidden;
}

.turn__head {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 14px;
  border: 0;
  background: transparent;
  text-align: left;
}

.turn__head:hover {
  background: var(--surface-muted);
}

.turn__head--open {
  background: var(--surface-muted);
  border-bottom: 1px solid var(--border);
}

.turn__index {
  display: grid;
  flex: none;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11px;
  font-weight: 700;
}

.turn__main {
  display: grid;
  flex: 1;
  gap: 2px;
  min-width: 0;
}

.turn__question {
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.turn__preview {
  overflow: hidden;
  color: var(--muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.turn__time {
  flex: none;
  color: var(--muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.turn__chevron {
  flex: none;
  color: var(--muted);
  font-size: 11px;
  transition: transform 0.15s ease;
}

.turn__chevron--open {
  transform: rotate(180deg);
}

.turn__detail {
  padding: 12px;
  background: var(--surface-muted);
}

.turn__hint {
  padding: 8px;
  color: var(--muted);
  font-size: 12px;
  text-align: center;
}

.link {
  color: var(--primary);
  font-weight: 600;
}

.link:hover {
  text-decoration: underline;
}

@media (max-width: 560px) {
  .detail-head {
    flex-direction: column;
    align-items: stretch;
  }

  .detail-head__actions {
    justify-content: flex-start;
  }
}
</style>
