<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { healthy } from '@/api'
import { generateReportPdf } from '@/api/report'
import AnswerCard from '@/components/AnswerCard.vue'
import AskPanel from '@/components/AskPanel.vue'
import ColumnTable from '@/components/ColumnTable.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import SheetPicker from '@/components/SheetPicker.vue'
import UploadDropzone from '@/components/UploadDropzone.vue'
import { pushToast } from '@/composables/useToast'
import { auth } from '@/stores/auth'
import {
  askQuestion,
  confirmSheets,
  resetSession,
  retryMessage,
  session,
  stopGeneration,
  uploadReport,
} from '@/stores/session'
import { saveBlob } from '@/utils/download'
import { formatNumber } from '@/utils/format'
import { getReportCover, saveReportCover } from '@/utils/reportPrefs'

const question = ref('')
const payload = computed(() => session.payload)

const messagesRef = ref(null)
const showColumns = ref(false)
/** 用户是否停在底部；往上翻看历史时不强行拽回来。 */
const pinnedToBottom = ref(true)

/* ---------- 后端连通性 ---------- */
const backend = ref({ state: 'checking', message: '正在检查后端…' })

async function checkBackend() {
  backend.value = { state: 'checking', message: '正在检查后端…' }
  try {
    const data = await healthy()
    backend.value = data?.app_ready
      ? { state: 'ready', message: '后端已连接，模型可用' }
      : { state: 'degraded', message: '后端已连接，但 Dify 密钥未配全，提问会返回 502' }
  } catch (error) {
    backend.value = { state: 'error', message: error?.message ?? '后端不可达' }
  }
}

onMounted(checkBackend)

// 从历史恢复进来时，直接停在最新一条
onMounted(() => {
  if (session.messages.length > 0) scrollToBottom()
})

/* ---------- 流程动作 ---------- */
function onFileSelected(file) {
  uploadReport(file)
}

function onConfirmSheets(options) {
  confirmSheets(options)
}

function onAsk(text) {
  question.value = ''
  askQuestion(text)
}

function onRetry(message) {
  retryMessage(message)
}

function onStop() {
  stopGeneration()
}

function startOver() {
  const hasWork = Boolean(session.payload) || session.messages.length > 0
  if (hasWork && !window.confirm('重新上传会清空当前会话与全部对话，确定吗？')) return
  resetSession()
  question.value = ''
  showColumns.value = false
}

/* ---------- 生成分析报告 PDF ---------- */
const reportOpen = ref(false)
const reportBusy = ref(false)
const reportForm = ref({ unitName: '', preparedBy: '', reviewedBy: '', reportDate: '' })

/** 报告按 file_id 生成；历史会话 resume 现在也会返回 file_id。 */
const canGenerateReport = computed(() => Boolean(session.payload?.fileId))

const reportReady = computed(
  () =>
    reportForm.value.unitName.trim().length > 0 &&
    reportForm.value.preparedBy.trim().length > 0 &&
    reportForm.value.reviewedBy.trim().length > 0,
)

/** 同一份文件的封面参数记在浏览器里，下次自动带出。 */
const reportCoverKey = computed(() => {
  const file = session.payload?.filename || session.payload?.fileId || ''
  if (!file) return ''
  return `${auth.user?.username ?? 'anon'}::${file}`
})

const reportButtonHint = computed(() => {
  if (reportBusy.value) return '正在生成报告，完成后会自动下载'
  if (!canGenerateReport.value) return '当前会话没有文件信息，重新上传后可生成报告'
  return '按当前文件生成团体体检分析报告 PDF'
})

function todayISO() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function openReportDialog() {
  if (!canGenerateReport.value || reportBusy.value) return

  const remembered = getReportCover(reportCoverKey.value)
  reportForm.value = {
    unitName: remembered?.unitName ?? '',
    preparedBy: remembered?.preparedBy || auth.user?.username || '',
    reviewedBy: remembered?.reviewedBy ?? '',
    reportDate: remembered?.reportDate || todayISO(),
  }
  reportOpen.value = true
}

async function submitReport() {
  if (!reportReady.value || reportBusy.value || !canGenerateReport.value) return

  // 记住这次填的内容，下次打开同一文件直接带出
  saveReportCover(reportCoverKey.value, reportForm.value)

  // 立刻关弹窗：生成期间用户可以去干别的，只靠按钮状态提示
  reportOpen.value = false
  reportBusy.value = true

  try {
    const result = await generateReportPdf({
      fileId: session.payload.fileId,
      unitName: reportForm.value.unitName,
      preparedBy: reportForm.value.preparedBy,
      reviewedBy: reportForm.value.reviewedBy,
      reportDate: reportForm.value.reportDate,
    })

    saveBlob(result.blob, result.filename)

    if (result.narrative === 'fallback') {
      pushToast('报告已生成；叙述部分由模板兜底（模型输出未通过校验）', 'info', 6000)
    } else if (result.cached) {
      pushToast('报告已生成（命中缓存）', 'success')
    } else {
      pushToast('报告已生成，开始下载', 'success')
    }
  } catch (error) {
    pushToast(error?.message ?? '生成报告失败，请重试', 'error', 6000)
  } finally {
    reportBusy.value = false
  }
}

/* ---------- 聊天区滚动 ---------- */
function onScroll() {
  const el = messagesRef.value
  if (!el) return
  pinnedToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 90
}

async function scrollToBottom() {
  await nextTick()
  const el = messagesRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

// 新提问：强制滚到底部
watch(
  () => session.messages.length,
  () => {
    pinnedToBottom.value = true
    scrollToBottom()
  },
)

// 流式增量 / 结果表出现：只在用户仍贴着底部时跟随
watch(
  () => {
    const last = session.messages[session.messages.length - 1]
    if (!last) return ''
    return `${last.status}|${last.answer?.length ?? 0}|${last.result ? 1 : 0}|${last.stage ?? ''}`
  },
  () => {
    if (pinnedToBottom.value) scrollToBottom()
  },
)

const emptyDesc = computed(() => {
  const rows = formatNumber(payload.value?.rows ?? 0)
  const cols = payload.value?.columns?.length ?? 0
  const base = `已载入 ${rows} 行 × ${cols} 列`
  return payload.value?.message ? `${base}，${payload.value.message}` : `${base}，开始提问吧`
})

const FLOW = [
  { title: '上传', desc: '选择 .xlsx / .csv 体检表格' },
  { title: '选表', desc: '多工作表时合并或指定若干张' },
  { title: '提问', desc: '用中文描述要统计的口径' },
  { title: '追问', desc: '同一会话继续问，保留上下文' },
]
</script>

<template>
  <div class="workbench" :class="{ 'workbench--chat': session.stage === 'ready' }">
    <!-- ---------- 空态：上传 ---------- -->
    <template v-if="session.stage === 'empty'">
      <section class="hero">
        <p class="hero__eyebrow">Medical Checkup Report Analysis</p>
        <h1 class="hero__title">用一句话，读懂你的体检报告</h1>
        <p class="hero__desc">
          上传体检表格，用中文提问年龄分布、指标异常、复查建议等问题。
          后端会把自然语言解析成查询条件、在本地表格上执行，再返回结论与明细。
        </p>
      </section>

      <div class="backend" :class="`backend--${backend.state}`">
        <span class="backend__dot" aria-hidden="true" />
        <span class="backend__text">{{ backend.message }}</span>
        <button
          v-if="backend.state === 'error' || backend.state === 'degraded'"
          class="btn btn--ghost btn--sm"
          type="button"
          @click="checkBackend"
        >
          重新检查
        </button>
      </div>

      <UploadDropzone
        :uploading="session.uploading"
        :progress="session.uploadProgress"
        @select="onFileSelected"
      />

      <ol class="flow">
        <li v-for="(step, index) in FLOW" :key="step.title" class="flow__item">
          <span class="flow__index">{{ index + 1 }}</span>
          <div>
            <h3 class="flow__heading">{{ step.title }}</h3>
            <p class="flow__desc">{{ step.desc }}</p>
          </div>
        </li>
      </ol>
    </template>

    <!-- ---------- 待选工作表 / 阻断错误 ---------- -->
    <template v-else-if="session.stage === 'needSheets'">
      <header class="filebar card">
        <div class="filebar__main">
          <h1 class="filebar__name">{{ payload?.filename }}</h1>
          <div class="filebar__meta">
            <span v-if="payload?.type" class="badge badge--primary">
              {{ payload.type.toUpperCase() }}
            </span>
            <span class="badge">{{ formatNumber(payload?.rows ?? 0) }} 行</span>
            <span class="badge">{{ payload?.sheets?.length ?? 0 }} 个工作表</span>
          </div>
        </div>
        <button class="btn btn--sm" type="button" @click="startOver">重新上传</button>
      </header>

      <section v-if="session.blockingError" class="notice notice--error blocking">
        <div class="blocking__text">
          <strong>无法合并所选工作表</strong>
          <p>{{ session.blockingError }}（这是文件本身的问题，改选工作表无法解决）</p>
        </div>
        <button class="btn btn--sm" type="button" @click="startOver">重新上传</button>
      </section>

      <SheetPicker
        v-else
        :sheets="payload?.sheets ?? []"
        :busy="session.selectionBusy"
        @confirm="onConfirmSheets"
      />
    </template>

    <!-- ---------- 就绪：聊天布局 ---------- -->
    <div v-else class="chat">
      <header class="chat__head">
        <div class="chat__file">
          <span class="chat__filename">{{ payload?.filename }}</span>
          <span class="chat__meta">
            <span v-if="payload?.fromHistory" class="badge badge--ok">历史会话</span>
            <span class="badge">{{ formatNumber(payload?.rows ?? 0) }} 行</span>
            <span class="badge">{{ payload?.columns?.length ?? 0 }} 列</span>
            <span v-if="payload?.merged" class="badge badge--ok">已合并</span>
          </span>
        </div>
        <div class="chat__actions">
          <button
            class="btn btn--sm"
            type="button"
            :disabled="!canGenerateReport || reportBusy"
            :title="reportButtonHint"
            @click="openReportDialog"
          >
            <span v-if="reportBusy" class="spinner" aria-hidden="true" />
            {{ reportBusy ? 'PDF 生成中…' : '生成分析报告 PDF' }}
          </button>
          <button
            class="btn btn--ghost btn--sm"
            type="button"
            :aria-expanded="showColumns"
            @click="showColumns = !showColumns"
          >
            字段
          </button>
          <button class="btn btn--sm" type="button" @click="startOver">重新上传</button>
        </div>
      </header>

      <ColumnTable v-if="showColumns" :columns="payload?.columns ?? []" class="chat__columns" />

      <div ref="messagesRef" class="chat__scroll" @scroll="onScroll">
        <div v-if="!session.messages.length" class="chat__empty">
          <p class="chat__empty-title">开始提问</p>
          <p class="chat__empty-desc">{{ emptyDesc }}</p>
        </div>

        <AnswerCard
          v-for="(message, index) in session.messages"
          :key="message.id"
          :message="message"
          :index="index + 1"
          class="chat__msg"
          @retry="onRetry"
          @stop="onStop"
        />
      </div>

      <footer class="chat__composer">
        <AskPanel
          v-model="question"
          :busy="session.asking"
          :disabled="!payload"
          :show-examples="!session.messages.length"
          @submit="onAsk"
        />
      </footer>
    </div>

    <ConfirmDialog
      :open="reportOpen"
      title="生成分析报告 PDF"
      confirm-text="生成并下载"
      cancel-text="取消"
      :confirm-disabled="!reportReady"
      @cancel="reportOpen = false"
      @confirm="submitReport"
    >
      <form class="report-form" @submit.prevent="submitReport">
        <label class="report-field">
          <span class="report-label">受检单位 <i>*</i></span>
          <input
            v-model="reportForm.unitName"
            class="auth-input"
            type="text"
            maxlength="100"
            placeholder="例如：XX 医院体检中心"
            :disabled="reportBusy"
          />
        </label>

        <label class="report-field">
          <span class="report-label">编制人 <i>*</i></span>
          <input
            v-model="reportForm.preparedBy"
            class="auth-input"
            type="text"
            maxlength="50"
            placeholder="填写编制人姓名"
            :disabled="reportBusy"
          />
        </label>

        <label class="report-field">
          <span class="report-label">医学审核 <i>*</i></span>
          <input
            v-model="reportForm.reviewedBy"
            class="auth-input"
            type="text"
            maxlength="50"
            placeholder="填写审核人姓名"
            :disabled="reportBusy"
          />
        </label>

        <label class="report-field">
          <span class="report-label">报告日期</span>
          <input
            v-model="reportForm.reportDate"
            class="auth-input"
            type="date"
            :disabled="reportBusy"
          />
        </label>
      </form>

      <p class="report-note">
        生成时弹窗会自动关闭，可继续做别的事，完成后自动下载；封面信息会记住，同一文件下次自动带出。
      </p>
    </ConfirmDialog>
  </div>
</template>

<style scoped>
.workbench {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  /* 上传/选表阶段内容可能比屏幕高，允许整块滚动 */
  overflow-y: auto;
}

/* 聊天阶段由内部对话区滚动，外层不能再滚 */
.workbench--chat {
  overflow: hidden;
}

/* 非聊天阶段：子块保持自身高度，不要被 flex 压缩 */
.workbench:not(.workbench--chat) > * {
  flex: none;
}

/* ---------- 空态 ---------- */
.hero {
  margin-bottom: 16px;
}

.hero__eyebrow {
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.hero__title {
  margin-top: 8px;
  font-size: 28px;
  line-height: 1.3;
  letter-spacing: -0.01em;
}

.hero__desc {
  max-width: 46em;
  margin-top: 10px;
  color: var(--muted);
}

.backend {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 4px 10px 4px 8px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--muted);
}

.backend__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--muted);
}

.backend--ready .backend__dot {
  background: var(--ok);
}

.backend--degraded .backend__dot {
  background: var(--warn);
}

.backend--error .backend__dot {
  background: var(--danger);
}

.backend--error .backend__text {
  color: var(--danger);
}

.backend--degraded .backend__text {
  color: var(--warn);
}

.backend .btn {
  padding: 1px 6px;
}

.flow {
  display: grid;
  gap: 8px;
  margin-top: 18px;
}

@media (min-width: 720px) {
  .flow {
    grid-template-columns: repeat(4, 1fr);
  }
}

.flow__item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.flow__index {
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

.flow__heading {
  font-size: 13px;
}

.flow__desc {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

/* ---------- 文件信息条 ---------- */
.filebar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
}

.filebar__main {
  min-width: 0;
}

.filebar__name {
  font-size: 15px;
  line-height: 1.4;
  word-break: break-all;
}

.filebar__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.blocking {
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
}

.blocking__text strong {
  font-size: 13px;
}

.blocking__text p {
  margin-top: 2px;
  font-size: 12.5px;
}

/* ---------- 聊天布局 ---------- */
.chat {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  gap: 10px;
}

.chat__head {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.chat__file {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.chat__filename {
  overflow: hidden;
  max-width: 22em;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chat__actions {
  display: flex;
  flex: none;
  gap: 6px;
}

.chat__columns {
  flex: none;
}

.chat__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 2px 4px;
}

.chat__empty {
  display: grid;
  place-content: center;
  gap: 6px;
  height: 100%;
  min-height: 200px;
  text-align: center;
}

.chat__empty-title {
  font-size: 16px;
  font-weight: 600;
}

.chat__empty-desc {
  max-width: 30em;
  color: var(--muted);
  font-size: 13px;
}

.chat__msg {
  flex: none;
}

.chat__composer {
  flex: none;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  background: var(--bg);
}

/* ---------- 生成报告弹窗 ---------- */
.report-form {
  display: grid;
  gap: 10px;
}

.report-field {
  display: grid;
  gap: 4px;
}

.report-label {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 600;
}

.report-label i {
  color: var(--danger);
  font-style: normal;
}

.report-note {
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 640px) {
  .hero__title {
    font-size: 23px;
  }

  .filebar {
    flex-direction: column;
  }

  .blocking {
    flex-direction: column;
  }

  .chat__head {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }

  .chat__actions {
    justify-content: flex-end;
  }
}
</style>
