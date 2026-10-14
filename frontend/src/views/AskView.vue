<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { askQuestion, deleteQASession, listQASessions } from '@/api/qa'
import type { AskQuestionResponse, QASessionItem } from '@/api/types'
import ActionDialog from '@/components/ActionDialog.vue'
import AppIcon from '@/components/AppIcon.vue'
import CitationCard from '@/components/CitationCard.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import WarningList from '@/components/WarningList.vue'
import { session } from '@/stores/session'
import { uuid } from '@/utils/uuid'

/**
 * 制度问答主界面（DeepSeek 式对话布局，沿用本项目编辑式设计令牌）。
 *
 * 版面：左侧会话栏（新对话 + 最近提问）+ 中间对话流 + 底部吸附输入框。
 *   问答像聊天一样从底部向上生长，引用来源内联在回答下方可折叠。
 *
 * 关键设计取舍：
 *   1. 答案中的 [n] 角标仍做成可点击跳转，事件点击后滚到来源卡并高亮，
 *      这是"溯源"这个产品主张在交互上的兑现点，不因版式变化而丢失。
 *   2. 依据充分性单独出结论条，未找到依据也是一种有效回答，必须明确。
 *   3. 查询区只保留输入框与提问按钮：检索参数采用固定默认值（数据分级
 *      固定 internal、检索 10 条、开启重排序），由后端继续强制执行边界。
 */

const question = ref('')
/** 固定检索参数：不再提供 UI 开关，保持后端订阅的默认链路 */
const DATA_LEVEL_SUBMIT = 'internal'
const TOP_K_SUBMIT = 10
const USE_RERANKER_SUBMIT = true

const loading = ref(false)
const result = ref<AskQuestionResponse | null>(null)
const error = ref<unknown>(null)
const submittedQuestion = ref('')
const activeCitation = ref<number | null>(null)
const copyState = ref<'idle' | 'done'>('idle')
const recent = ref<QASessionItem[]>([])
const historyLoading = ref(false)
const historyError = ref<unknown>(null)
const historyPage = ref(1)
const historyTotal = ref(0)
const historyPageSize = 8
const viewingHistory = ref(false)
const resultReranker = ref<boolean | null>(null)
// 会话栏展开状态：桌面可折叠，移动端作抽屉
const convOpen = ref(false)
const activeItemId = ref<string | null>(null)
const chatScroll = ref<HTMLElement | null>(null)

// 浏览器保留会话编号，内容保存在服务端并按租户及用户隔离。
const sessionKey = `party.qa-session.${session.state.user?.id ?? ''}`
const sessionId = ref(sessionStorage.getItem(sessionKey) ?? uuid())
sessionStorage.setItem(sessionKey, sessionId.value)

let historySequence = 0
async function loadHistory(page = historyPage.value): Promise<void> {
  const sequence = ++historySequence
  historyLoading.value = true
  historyError.value = null
  try {
    const response = await listQASessions({ page, page_size: historyPageSize })
    if (sequence !== historySequence) return
    recent.value = response.items
    historyTotal.value = response.total
    historyPage.value = response.page
  } catch (error) {
    if (sequence === historySequence) historyError.value = error
  } finally {
    if (sequence === historySequence) historyLoading.value = false
  }
}
onMounted(() => { void loadHistory() })

function viewHistory(item: QASessionItem): void {
  if (loading.value) return
  question.value = item.question
  submittedQuestion.value = item.question
  result.value = item
  error.value = null
  activeCitation.value = null
  viewingHistory.value = true
  resultReranker.value = null
  activeItemId.value = item.id
  sessionId.value = item.session_id ?? uuid()
  sessionStorage.setItem(sessionKey, sessionId.value)
  void scrollToBottom()
}

function isActive(item: QASessionItem): boolean {
  return activeItemId.value === item.id
}

/* ------------------------- 删除历史提问 ---------------------------- */

const pendingDelete = ref<QASessionItem | null>(null)
const deletingId = ref<string | null>(null)

function askDelete(item: QASessionItem): void {
  pendingDelete.value = item
}

async function confirmDelete(): Promise<void> {
  const item = pendingDelete.value
  if (!item || deletingId.value) return
  deletingId.value = item.id
  try {
    await deleteQASession(item.id)
    pendingDelete.value = null
    // 删掉的正是当前展示的记录时，清空对话区，避免展示已删除内容
    if (activeItemId.value === item.id) onReset()
    await loadHistory(historyPage.value)
  } catch (err) {
    historyError.value = err
    pendingDelete.value = null
  } finally {
    deletingId.value = null
  }
}

const MAX_LEN = 500 // 后端 QuestionRequest.question 的 max_length

const remaining = computed(() => MAX_LEN - question.value.length)
const canSubmit = computed(() => question.value.trim().length > 0 && !loading.value)

/** 欢迎态：无任何提问或结果时居中显示引导 */
const welcome = computed(
  () => !submittedQuestion.value && !loading.value && !result.value && !error.value,
)

const citationOpen = ref(true)

/** 依据充分性：三种状态需要三种完全不同的措辞与色调 */
const evidence = computed(() => {
  const r = result.value
  if (!r) return null
  if (!r.has_sufficient_evidence) {
    return {
      tone: 'warn' as const,
      label: '依据不充分',
      text: '检索到的片段不足以支撑确定回答。请补充提问条件，或向上一级党组织确认。',
    }
  }
  if (r.used_count === 0) {
    return {
      tone: 'warn' as const,
      label: '未引用依据',
      text: '回答未标注具体来源，请谨慎采信。',
    }
  }
  return {
    tone: 'ok' as const,
    label: '依据充分',
    text: `本次回答引用了 ${r.used_count} 条来源。请逐条核对后再采用。`,
  }
})

/** 把答案里的 [n] 拆成可渲染片段，使角标可点击 */
interface AnswerToken {
  kind: 'text' | 'cite'
  value: string
  index?: number
}

const answerTokens = computed<AnswerToken[]>(() => {
  const text = result.value?.answer ?? ''
  if (!text) return []

  const tokens: AnswerToken[] = []
  const re = /\[(\d+)\]/g
  let last = 0
  let m: RegExpExecArray | null

  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      tokens.push({ kind: 'text', value: text.slice(last, m.index) })
    }
    tokens.push({ kind: 'cite', value: m[0], index: Number(m[1]) })
    last = m.index + m[0].length
  }

  if (last < text.length) {
    tokens.push({ kind: 'text', value: text.slice(last) })
  }

  return tokens
})

const answerParagraphs = computed(() => {
  const tokens = answerTokens.value
  const paras: AnswerToken[][] = [[]]
  for (const t of tokens) {
    if (t.kind === 'text' && t.value.includes('\n')) {
      const parts = t.value.split('\n')
      parts.forEach((p, i) => {
        if (i > 0) paras.push([])
        if (p) paras[paras.length - 1]!.push({ kind: 'text', value: p })
      })
    } else {
      paras[paras.length - 1]!.push(t)
    }
  }
  return paras.filter((p) => p.length > 0)
})

async function scrollToBottom(): Promise<void> {
  await nextTick()
  chatScroll.value?.scrollTo({ top: chatScroll.value.scrollHeight, behavior: 'smooth' })
}

async function onAsk(): Promise<void> {
  if (!canSubmit.value) return

  const q = question.value.trim()
  loading.value = true
  error.value = null
  result.value = null
  activeCitation.value = null
  submittedQuestion.value = q
  viewingHistory.value = false
  activeItemId.value = null
  resultReranker.value = USE_RERANKER_SUBMIT
  citationOpen.value = true
  void scrollToBottom()

  try {
    result.value = await askQuestion({
      question: q,
      data_level: DATA_LEVEL_SUBMIT,
      use_reranker: USE_RERANKER_SUBMIT,
      top_k: TOP_K_SUBMIT,
      session_id: sessionId.value,
    })
    void loadHistory(1)
    void scrollToBottom()
  } catch (err) {
    error.value = err
    void scrollToBottom()
  } finally {
    loading.value = false
  }
}

watch(loading, (isLoading) => {
  if (isLoading) void scrollToBottom()
})

async function jumpToCitation(index: number): Promise<void> {
  activeCitation.value = index
  citationOpen.value = true
  await nextTick()
  const el = document.getElementById(`cite-${index}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function copyAnswer(): Promise<void> {
  const r = result.value
  if (!r) return

  const sources = r.citations
    .map((c) => `[${c.index}] ${c.title}（${c.issuer}${c.doc_number ? `，${c.doc_number}` : ''}）`)
    .join('\n')

  const payload = `${submittedQuestion.value}\n\n${r.answer}\n\n来源：\n${sources}\n\n${r.disclaimer}`

  try {
    await navigator.clipboard.writeText(payload)
    copyState.value = 'done'
    window.setTimeout(() => (copyState.value = 'idle'), 1800)
  } catch {
    // 剪贴板在非安全上下文不可用，静默失败即可，不打断阅读
  }
}

function onReset(): void {
  question.value = ''
  result.value = null
  error.value = null
  submittedQuestion.value = ''
  activeCitation.value = null
  viewingHistory.value = false
  resultReranker.value = null
  activeItemId.value = null
  citationOpen.value = false
  sessionId.value = uuid()
  sessionStorage.setItem(sessionKey, sessionId.value)
}

const SUGGESTIONS = [
  '入党积极分子培养考察期最短是多长时间',
  '发展对象政治审查需要哪些材料',
  '预备党员转正需要经过哪些程序',
]

function useSuggestion(text: string): void {
  question.value = text
  void nextTick(() => document.getElementById('question')?.focus())
}

function historyDateParts(value: string): string {
  const utc = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const d = new Date(utc)
  const today = new Date()
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  if (sameDay) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
</script>

<template>
  <div class="ask">
    <!-- ============================ 会话栏 ============================ -->
    <aside class="conv" :class="{ 'is-open': convOpen }" aria-label="会话列表">
      <div class="conv__top">
        <button class="btn btn--ghost conv__new" type="button" @click="onReset">
          <AppIcon name="plus" :size="15" />
          <span>新对话</span>
        </button>
      </div>

      <section class="conv__section">
        <header class="conv__head">
          <h2 class="conv__title">最近提问</h2>
          <span class="badge">{{ historyTotal }}</span>
        </header>

        <div class="conv__body">
          <LoadingBlock v-if="historyLoading" variant="list" :rows="3" />
          <ErrorState v-else-if="historyError" :error="historyError">
            <button class="btn btn--ghost" type="button" @click="loadHistory()">重试历史查询</button>
          </ErrorState>
          <p v-else-if="!recent.length" class="conv__empty">尚无问答记录，提问后会保存在这里。</p>
          <ul v-else class="recent-list">
            <li v-for="item in recent" :key="item.id" class="recent">
              <button
                class="recent-item"
                :class="{ 'is-active': isActive(item) }"
                type="button"
                :disabled="loading"
                @click="viewHistory(item)"
              >
                <span class="recent-item__text">{{ item.question }}</span>
                <time class="u-meta" :datetime="item.created_at">{{ historyDateParts(item.created_at) }}</time>
              </button>
              <button
                class="recent-remove"
                type="button"
                :disabled="loading || deletingId !== null"
                :aria-label="`删除提问：${item.question}`"
                :title="'删除这条提问记录'"
                @click="askDelete(item)"
              >
                <AppIcon name="close" :size="12" />
              </button>
            </li>
          </ul>
          <div v-if="!historyLoading && !historyError && historyTotal > historyPageSize" class="conv__pages">
            <button class="btn btn--quiet" :disabled="historyPage <= 1" type="button" @click="loadHistory(historyPage - 1)">上一页</button>
            <span class="u-meta">第 {{ historyPage }} 页</span>
            <button class="btn btn--quiet" :disabled="historyPage * historyPageSize >= historyTotal" type="button" @click="loadHistory(historyPage + 1)">下一页</button>
          </div>
        </div>
      </section>
    </aside>

    <button v-if="convOpen" class="scrim conv__scrim" type="button" aria-label="关闭会话列表" @click="convOpen = false"></button>

    <!-- ============================ 对话区 ============================ -->
    <div class="chat">
      <header class="chat__top">
        <button
          class="btn btn--quiet chat__toggle"
          type="button"
          :aria-expanded="convOpen"
          @click="convOpen = !convOpen"
        >
          <AppIcon name="layout" :size="15" />
          <span>会话列表</span>
        </button>
        <button
          v-if="result"
          class="btn btn--ghost chat__clear"
          type="button"
          :disabled="loading"
          @click="onReset"
        >
          <AppIcon name="close" :size="14" />
          <span>清空</span>
        </button>
      </header>

      <div ref="chatScroll" class="chat__scroll">
        <!-- 历史查看提示 -->
        <p v-if="viewingHistory" class="chat-hint" role="note">
          当前展示历史回答，引用的文件可能已经更新或失效。再次提问会重新检索。
        </p>

        <!-- 欢迎态：居中问候 + 建议卡片 -->
        <section v-if="welcome" class="welcome">
          <h1 class="u-title-page welcome__title">有什么制度问题想确认？</h1>
          <p class="welcome__sub">
            以党内法规与校内制度为依据作答，并逐条标注出处。回答仅作辅助参考，不构成组织认定。
          </p>
          <div class="suggest">
            <span class="u-eyebrow">可以这样问</span>
            <div class="suggest__grid">
              <button
                v-for="s in SUGGESTIONS"
                :key="s"
                class="suggest__card"
                type="button"
                @click="useSuggestion(s)"
              >
                <span>{{ s }}</span>
                <AppIcon name="arrow-right" :size="14" />
              </button>
            </div>
          </div>
        </section>

        <!-- 对话流 -->
        <div v-if="submittedQuestion || loading || result || error" class="stream">
          <!-- 用户问题 -->
          <div v-if="submittedQuestion" class="msg msg--user">
            <p class="msg__bubble">{{ submittedQuestion }}</p>
          </div>

          <!-- 加载态：骨架回答 -->
          <div v-if="loading" class="msg msg--bot">
            <LoadingBlock variant="answer" />
          </div>

          <!-- 错误态 -->
          <ErrorState v-else-if="error" :error="error" class="msg msg--error">
            <button class="btn btn--ghost" type="button" @click="onAsk">重新提问</button>
            <button class="btn btn--quiet" type="button" @click="onReset">清空</button>
          </ErrorState>

          <!-- 回答 -->
          <article v-else-if="result" class="msg msg--bot msg--answer">
            <!-- 依据充分性结论条 -->
            <div v-if="evidence" class="evidence" :class="`is-${evidence.tone}`">
              <AppIcon :name="evidence.tone === 'ok' ? 'check' : 'alert'" :size="16" />
              <div>
                <p class="evidence__label">{{ evidence.label }}</p>
                <p class="evidence__text">{{ evidence.text }}</p>
              </div>
            </div>

            <header class="msg__head">
              <span class="u-eyebrow">回答</span>
              <button class="btn btn--quiet" type="button" @click="copyAnswer">
                <AppIcon :name="copyState === 'done' ? 'check' : 'copy'" :size="14" />
                <span>{{ copyState === 'done' ? '已复制' : '复制全文' }}</span>
              </button>
            </header>

            <div class="msg__body">
              <p v-for="(para, pi) in answerParagraphs" :key="pi">
                <template v-for="(tok, ti) in para" :key="ti">
                  <button
                    v-if="tok.kind === 'cite'"
                    class="ref"
                    type="button"
                    :class="{ 'is-active': activeCitation === tok.index }"
                    :title="`查看第 ${tok.index} 条来源`"
                    @click="jumpToCitation(tok.index!)"
                  >
                    {{ tok.index }}
                  </button>
                  <template v-else>{{ tok.value }}</template>
                </template>
              </p>
            </div>

            <WarningList v-if="result.warnings.length" :warnings="result.warnings" />

            <!-- 来源：内联折叠区，点角标会自动展开 -->
            <section v-if="result.citations.length" class="cites">
              <button
                class="cites__trigger"
                type="button"
                :aria-expanded="citationOpen"
                @click="citationOpen = !citationOpen"
              >
                <AppIcon :name="citationOpen ? 'chevron-down' : 'chevron-right'" :size="15" />
                <span>来源</span>
                <span class="badge badge--accent">{{ result.citations.length }}</span>
                <span class="u-meta cites__hint">点角标可定位到对应来源</span>
              </button>
              <div v-if="citationOpen" class="cites__list">
                <CitationCard
                  v-for="c in result.citations"
                  :key="c.index"
                  :citation="c"
                  :index="c.index"
                  :class="{ 'is-active': activeCitation === c.index }"
                />
              </div>
            </section>

            <!-- 检索明细 -->
            <dl class="stats">
              <div class="stats__row"><dt>命中片段</dt><dd class="u-num">{{ result.retrieved_count }}</dd></div>
              <div class="stats__row"><dt>实际引用</dt><dd class="u-num">{{ result.used_count }}</dd></div>
              <div class="stats__row"><dt>依据充分</dt><dd>{{ result.has_sufficient_evidence ? '是' : '否' }}</dd></div>
              <div v-if="resultReranker !== null" class="stats__row">
                <dt>重排序</dt><dd>{{ resultReranker ? '已启用' : '未启用' }}</dd>
              </div>
            </dl>

            <footer class="msg__foot">
              <p class="disclaimer">
                <AppIcon name="info" :size="14" />
                <span>{{ result.disclaimer }}</span>
              </p>
            </footer>
          </article>
        </div>
      </div>

      <!-- ============================ 输入框 ============================ -->
      <form class="composer" @submit.prevent="onAsk">
        <div class="composer__box">
          <label class="u-sr" for="question">提问内容</label>
          <textarea
            id="question"
            v-model="question"
            class="textarea composer__input"
            :maxlength="MAX_LEN"
            placeholder="用一句话描述你要确认的制度问题，例如：发展对象的政治审查需要哪些材料"
            @keydown.meta.enter="onAsk"
            @keydown.ctrl.enter="onAsk"
          ></textarea>

          <div class="composer__bar">
            <div class="composer__submit">
              <span class="u-meta u-num" :class="{ 'is-low': remaining < 40 }">{{ remaining }}</span>
              <button class="btn btn--primary" type="submit" :disabled="!canSubmit">
                <AppIcon name="search" :size="15" />
                <span>{{ loading ? '检索中' : '提问' }}</span>
              </button>
            </div>
          </div>
        </div>
      </form>
    </div>

    <!-- 删除历史提问：站内确认，不弹原生窗口 -->
    <ActionDialog
      :open="Boolean(pendingDelete)"
      title="删除这条提问记录"
      :busy="deletingId !== null"
      @close="pendingDelete = null"
    >
      <p class="del-question">{{ pendingDelete?.question }}</p>
      <p class="del-note">
        仅从"最近提问"中删除，不影响制度库文件与审计记录。删除后无法恢复。
      </p>
      <div class="del-actions">
        <button class="btn btn--quiet" type="button" :disabled="deletingId !== null" @click="pendingDelete = null">
          取消
        </button>
        <button class="btn btn--primary" type="button" :disabled="deletingId !== null" @click="confirmDelete">
          {{ deletingId !== null ? '删除中…' : '确认删除' }}
        </button>
      </div>
    </ActionDialog>
  </div>
</template>

<style scoped>
/* ============================ 骨架 ================================ */
.ask {
  display: flex;
  height: calc(100dvh - var(--nav-h));
  overflow: hidden;
  width: 100%;
}

/* ============================ 会话栏 =============================== */
.conv {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  width: var(--conv-w, 268px);
  flex: none;
  padding: var(--space-4) var(--space-3);
  border-right: var(--border);
  background: var(--paper);
}

.conv__top {
  display: flex;
}

.conv__new {
  width: 100%;
  justify-content: flex-start;
}

.conv__section {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.conv__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--paper-dim);
}

.conv__title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink);
}

.conv__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2);
  overflow-y: auto;
  flex: 1;
}

.conv__empty {
  padding: var(--space-3);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.recent-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  text-align: left;
  border-radius: var(--radius-sm);
  color: var(--ink-soft);
  transition: background-color var(--dur-fast) var(--ease);
}

/* 历史项与删除按钮并列：删除按钮不能嵌在按钮内部（非法嵌套） */
.recent {
  position: relative;
  display: flex;
  align-items: stretch;
}

.recent .recent-item {
  /* 给删除按钮让出固定位置，长问题也不会与按钮重叠 */
  padding-right: 28px;
}

.recent-remove {
  position: absolute;
  top: 6px;
  right: 6px;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  color: var(--ink-faint);
  border-radius: var(--radius-full);
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.recent-remove:hover,
.recent-remove:focus-visible {
  color: var(--bad-ink);
  background: var(--bad-wash);
}

.recent-item:hover {
  background: var(--paper-dim);
}

.recent-item.is-active {
  background: var(--accent-wash);
  color: var(--accent-deep);
}

.recent-item__text {
  font-size: var(--text-base);
  line-height: var(--leading-snug);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.recent-item time {
  font-size: var(--text-2xs);
}

.conv__pages {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2);
}

.conv__scrim {
  display: none;
}

/* ============================ 对话区 =============================== */
.chat {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  background: var(--paper);
  position: relative;
}

.chat__top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
}

.chat__clear {
  margin-left: auto;
  flex: none;
}

.chat__toggle {
  width: 100%;
  justify-content: flex-start;
  color: var(--ink-muted);
}

.chat__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-8) var(--space-6);
}

.chat-hint {
  align-self: center;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  color: var(--warn-ink);
  background: var(--warn-wash);
  border: 1px solid var(--warn-edge);
  border-radius: var(--radius-sm);
}

/* ---- 欢迎态 ---- */
.welcome {
  margin: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  max-width: 640px;
  text-align: center;
  padding: var(--space-6) 0;
}

.welcome__title {
  color: var(--ink);
}

.welcome__sub {
  max-width: 48ch;
  font-size: var(--text-md);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.suggest {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
}

.suggest__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  width: 100%;
}

.suggest__card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  text-align: left;
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
  color: var(--ink-soft);
  transition:
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.suggest__card:hover {
  border-color: var(--accent-edge);
  background: var(--accent-wash);
  color: var(--accent-deep);
}

.suggest__card :deep(svg) {
  color: var(--ink-faint);
  flex: none;
}

/* ---- 消息流 ---- */
.stream {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  margin-top: auto;
  width: 100%;
  max-width: 860px;
  align-self: center;
}

.msg {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-width: 100%;
}

.msg--user {
  align-items: flex-end;
}

.msg__bubble {
  max-width: 34rem;
  padding: var(--space-3) var(--space-4);
  background: var(--accent-wash);
  border: 1px solid var(--accent-edge);
  border-radius: var(--radius-md);
  font-size: var(--text-md);
  line-height: var(--leading-normal);
  color: var(--accent-deep);
}

.msg--error {
  padding: var(--space-3);
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
}

.msg--error :deep(.state) {
  padding: var(--space-4) var(--space-3);
}

.msg__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.msg__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  max-width: var(--measure);
}

.msg__body p {
  font-size: var(--text-md);
  line-height: var(--leading-loose);
  color: var(--ink);
  white-space: pre-wrap;
}

/* 引用角标：与来源卡的角标同形同色，建立视觉对应 */
.ref {
  display: inline-grid;
  place-items: center;
  min-width: 17px;
  height: 17px;
  margin: 0 2px;
  padding: 0 4px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 600;
  line-height: 1;
  vertical-align: 2px;
  color: var(--accent-deep);
  background: var(--accent-wash);
  border: 1px solid var(--accent-edge);
  border-radius: var(--radius-xs);
  transition: background-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.ref:hover,
.ref.is-active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

/* ---- 结论条 ---- */
.evidence {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--ok-edge);
  border-left-width: 3px;
  border-radius: var(--radius-sm);
  background: var(--ok-wash);
  color: var(--ok-ink);
}

.evidence.is-warn {
  border-color: var(--warn-edge);
  background: var(--warn-wash);
  color: var(--warn-ink);
}

.evidence__label {
  font-size: var(--text-base);
  font-weight: 600;
}

.evidence__text {
  margin-top: 2px;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-soft);
}

/* ---- 来源折叠 ---- */
.cites {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  border: var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--paper-raised);
}

.cites__trigger {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  text-align: left;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink);
}

.cites__trigger:hover {
  background: var(--paper-dim);
}

.cites__hint {
  margin-left: auto;
  font-weight: 400;
}

.cites__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: 0 var(--space-3) var(--space-3);
}

.cites__list :deep(.cite.is-active) {
  border-color: var(--accent-edge);
  background: var(--accent-wash);
}

.cites__list :deep(.cite) {
  scroll-margin-top: calc(var(--nav-h) + var(--space-4));
}

/* ---- 检索明细 ---- */
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  border: var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  background: var(--paper-dim);
}

.stats__row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
}

.stats__row dt {
  font-size: var(--text-xs);
  color: var(--ink-muted);
}

.stats__row dd {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink);
}

.msg__foot {
  padding-top: var(--space-3);
  border-top: var(--border);
}

.disclaimer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--ink-muted);
}

/* ============================ 输入框 =============================== */
.composer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-8) var(--space-4);
  border-top: var(--border);
  background: var(--paper);
}

.composer__box {
  background: var(--paper-raised);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  box-shadow: var(--shadow-pop);
}

.composer__box:focus-within {
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}

.composer__input {
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: var(--space-4);
  font-size: var(--text-md);
  line-height: var(--leading-normal);
  min-height: 92px;
  resize: vertical;
}

.composer__input:focus {
  outline: none;
  box-shadow: none;
}

.composer__bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-top: var(--border);
  background: var(--paper-dim);
}

.composer__submit {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: none;
}

.composer__submit .is-low {
  color: var(--warn-ink);
}

/* ============================ 删除确认 ============================= */
.del-question {
  padding: var(--space-3);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink);
  background: var(--paper-dim);
  border: 1px solid var(--rule);
  border-radius: var(--radius-sm);
}

.del-note {
  margin-top: var(--space-3);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.del-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-5);
}

/* ============================ 响应式 =============================== */
@media (max-width: 1180px) {
  .suggest__grid {
    grid-template-columns: 1fr;
    max-width: 520px;
  }
}

@media (max-width: 1079px) {
  .conv {
    position: fixed;
    top: var(--nav-h);
    bottom: 0;
    left: 0;
    z-index: var(--z-pop);
    width: min(320px, 84vw);
    transform: translateX(-100%);
    transition: transform var(--dur) var(--ease);
    box-shadow: var(--shadow-pop);
  }

  .conv.is-open {
    transform: translateX(0);
  }

  .conv__scrim {
    display: block;
    position: fixed;
    inset: var(--nav-h) 0 0 0;
    z-index: calc(var(--z-pop) - 1);
    background: var(--overlay-bg);
    border: 0;
    width: 100%;
  }
}

@media (max-width: 720px) {
  .chat__scroll {
    padding: var(--space-2) var(--space-4) var(--space-5);
  }

  .composer {
    padding: var(--space-3) var(--space-3) var(--space-3);
  }

  .composer__bar {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
  }

  .composer__submit {
    justify-content: space-between;
  }

  .composer__submit .btn {
    flex: 1;
  }

  .msg__body {
    max-width: none;
  }
}
</style>