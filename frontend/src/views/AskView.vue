<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import { askQuestion, listQASessions } from '@/api/qa'
import type { AskQuestionResponse, DataLevel, QASessionItem } from '@/api/types'
import { DATA_LEVEL_LABELS, DATA_LEVEL_ROUTE } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import CitationCard from '@/components/CitationCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import WarningList from '@/components/WarningList.vue'
import { session } from '@/stores/session'

/**
 * 制度问答主界面。
 *
 * 版面：左栏提问与回答（阅读区，行宽受限），右栏是检索参数与来源清单。
 *   这种"阅读 + 工具"的分栏是编辑式排版的常见结构：正文不被控件打断，
 *   而参数、来源索引这类"旁注"集中在侧栏。
 *
 * 关键设计取舍：
 *   1. 答案中的 [n] 角标做成可点击跳转，直接滚到右侧对应来源卡并高亮。
 *      这是"溯源"这个产品主张在交互上的兑现点，不能只做静态文本。
 *   2. 依据充分性单独出结论条，因为"没找到依据"本身就是一种有效回答，
 *      必须比"答案是空"更明确。
 *   3. 数据分级是提交前必选，且实时显示该级别对应的模型走向，
 *      让"什么内容会被送到哪个模型"这件事在使用前就可见。
 */

const question = ref('')
const useReranker = ref(true)
const topK = ref(10)
const dataLevel = ref<DataLevel>('internal')

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
// 浏览器保留会话编号，内容保存在服务端并按租户及用户隔离。
const sessionKey = `party.qa-session.${session.state.user?.id ?? ''}`
const sessionId = ref(sessionStorage.getItem(sessionKey) ?? crypto.randomUUID())
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
  dataLevel.value = item.data_level
  result.value = item
  error.value = null
  activeCitation.value = null
  viewingHistory.value = true
  resultReranker.value = null
  sessionId.value = item.session_id ?? crypto.randomUUID()
  sessionStorage.setItem(sessionKey, sessionId.value)
}

function historyDate(value: string): string {
  const utc = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  return new Date(utc).toLocaleString('zh-CN')
}

const MAX_LEN = 500 // 后端 QuestionRequest.question 的 max_length

const remaining = computed(() => MAX_LEN - question.value.length)
const canSubmit = computed(() => question.value.trim().length > 0 && !loading.value)

const levelHint = computed(() => DATA_LEVEL_ROUTE[dataLevel.value])
const levelIsRestricted = computed(
  () => dataLevel.value !== 'public',
)

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
        if (p) paras[paras.length - 1].push({ kind: 'text', value: p })
      })
    } else {
      paras[paras.length - 1]!.push(t)
    }
  }
  return paras.filter((p) => p.length > 0)
})

async function onAsk(): Promise<void> {
  if (!canSubmit.value) return

  const q = question.value.trim()
  loading.value = true
  error.value = null
  result.value = null
  activeCitation.value = null
  submittedQuestion.value = q
  viewingHistory.value = false
  resultReranker.value = useReranker.value

  try {
    result.value = await askQuestion({
      question: q,
      data_level: dataLevel.value,
      use_reranker: useReranker.value,
      top_k: topK.value,
      session_id: sessionId.value,
    })
    void loadHistory(1)
  } catch (err) {
    error.value = err
  } finally {
    loading.value = false
  }
}

async function jumpToCitation(index: number): Promise<void> {
  activeCitation.value = index
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
  sessionId.value = crypto.randomUUID()
  sessionStorage.setItem(sessionKey, sessionId.value)
}

const SUGGESTIONS = [
  '入党积极分子培养考察期最短是多长时间',
  '发展对象政治审查需要哪些材料',
  '预备党员转正需要经过哪些程序',
]

function useSuggestion(text: string): void {
  question.value = text
}
</script>

<template>
  <div class="ask">
    <PageHeader
      title="制度问答"
      description="以党内法规与校内制度为依据作答，并逐条标注出处。回答仅作辅助参考，不构成组织认定。"
    >
      <template #actions>
        <button v-if="result" class="btn btn--ghost" type="button" :disabled="loading" @click="onReset">
          <AppIcon name="close" :size="14" />
          <span>清空</span>
        </button>
      </template>
    </PageHeader>

    <div class="ask__grid">
      <!-- ------------------------------ 主栏 ------------------------------ -->
      <div class="ask__main">
        <!-- 提问区 -->
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
              <div class="composer__params">
                <div class="param">
                  <label class="param__label" for="level">数据分级</label>
                  <select id="level" v-model="dataLevel" class="select param__select">
                    <option v-for="(label, key) in DATA_LEVEL_LABELS" :key="key" :value="key">
                      {{ label }}
                    </option>
                  </select>
                </div>

                <div class="param">
                  <label class="param__label" for="topk">检索条数</label>
                  <select id="topk" v-model.number="topK" class="select param__select">
                    <option :value="5">5</option>
                    <option :value="10">10</option>
                    <option :value="20">20</option>
                    <option :value="30">30</option>
                  </select>
                </div>

                <label class="check">
                  <input v-model="useReranker" type="checkbox" class="check__box" />
                  <span>启用重排序</span>
                </label>
              </div>

              <div class="composer__submit">
                <span class="u-meta u-num composer__count" :class="{ 'is-low': remaining < 40 }">
                  {{ remaining }}
                </span>
                <button class="btn btn--primary" type="submit" :disabled="!canSubmit">
                  <AppIcon name="search" :size="15" />
                  <span>{{ loading ? '检索中' : '提问' }}</span>
                </button>
              </div>
            </div>
          </div>

          <!-- 数据分级提示：把"送到哪个模型"在使用前讲清楚 -->
          <p class="level-note" :class="{ 'is-restricted': levelIsRestricted }">
            <AppIcon :name="levelIsRestricted ? 'shield' : 'info'" :size="14" />
            <span>
              当前分级为「{{ DATA_LEVEL_LABELS[dataLevel] }}」，{{ levelHint }}。
              <template v-if="levelIsRestricted">
                发送前请确认内容确属该分级，敏感与涉密材料不得送往外部模型。
              </template>
            </span>
          </p>

          <!-- 首次进入的引导：用例句降低冷启动成本，而非空等 -->
          <div v-if="!result && !loading && !error" class="suggest">
            <span class="u-eyebrow">可以这样问</span>
            <ul class="suggest__list">
              <li v-for="s in SUGGESTIONS" :key="s">
                <button class="suggest__item" type="button" @click="useSuggestion(s)">
                  <span>{{ s }}</span>
                  <AppIcon name="arrow-right" :size="14" />
                </button>
              </li>
            </ul>
          </div>
        </form>

        <!-- 加载态 -->
        <LoadingBlock v-if="loading" variant="answer" />

        <!-- 错误态 -->
        <ErrorState v-else-if="error" :error="error">
          <button class="btn btn--ghost" type="button" @click="onAsk">重新提问</button>
          <button class="btn btn--quiet" type="button" @click="onReset">清空</button>
        </ErrorState>

        <!-- 结果 -->
        <template v-else-if="result">
          <p v-if="viewingHistory" class="aside-hint" role="note">当前展示历史回答，引用的文件可能已经更新或失效。再次提问会重新检索。</p>
          <!-- 依据充分性结论条：先给结论强度，再给内容 -->
          <div v-if="evidence" class="evidence" :class="`is-${evidence.tone}`">
            <AppIcon :name="evidence.tone === 'ok' ? 'check' : 'alert'" :size="16" />
            <div>
              <p class="evidence__label">{{ evidence.label }}</p>
              <p class="evidence__text">{{ evidence.text }}</p>
            </div>
          </div>

          <!-- 提问回显 -->
          <div class="echo">
            <span class="u-eyebrow">问题</span>
            <p class="echo__text">{{ submittedQuestion }}</p>
          </div>

          <!-- 回答正文 -->
          <article class="answer">
            <header class="answer__head">
              <h2 class="u-title-section">回答</h2>
              <button class="btn btn--quiet" type="button" @click="copyAnswer">
                <AppIcon :name="copyState === 'done' ? 'check' : 'copy'" :size="14" />
                <span>{{ copyState === 'done' ? '已复制' : '复制全文' }}</span>
              </button>
            </header>

            <div class="answer__body">
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
            <footer class="answer__foot">
              <p class="disclaimer">
                <AppIcon name="info" :size="14" />
                <span>{{ result.disclaimer }}</span>
              </p>
            </footer>
          </article>
        </template>

        <!-- 初始空态 -->
        <EmptyState
          v-else
          icon="ask"
          title="还没有提问"
          body="在上方输入制度问题开始检索。系统会从知识库中查找依据，并在回答中标注可核验的出处。"
        />
      </div>

      <!-- ------------------------------ 侧栏 ------------------------------ -->
      <aside class="ask__aside">
        <section class="aside-card">
          <header class="u-panel-head aside-card__head">
            <h2 class="aside-card__title">最近提问</h2><span class="badge">{{ historyTotal }}</span>
          </header>
          <div class="aside-card__body">
            <LoadingBlock v-if="historyLoading" variant="list" :rows="3" />
            <ErrorState v-else-if="historyError" :error="historyError"><button class="btn btn--ghost" type="button" @click="loadHistory()">重试历史查询</button></ErrorState>
            <p v-else-if="!recent.length" class="aside-hint">尚无问答记录，提问后会在这里保存。</p>
            <ul v-else class="recent-list">
              <li v-for="item in recent" :key="item.id">
                <button class="recent-item" type="button" :disabled="loading" @click="viewHistory(item)">
                  <span>{{ item.question }}</span><time class="u-meta" :datetime="item.created_at">{{ historyDate(item.created_at) }}</time>
                </button>
              </li>
            </ul>
            <div v-if="!historyLoading && !historyError && historyTotal > historyPageSize" class="recent-pages">
              <button class="btn btn--quiet" :disabled="historyPage <= 1" @click="loadHistory(historyPage - 1)">上一页</button>
              <span class="u-meta">第 {{ historyPage }} 页</span>
              <button class="btn btn--quiet" :disabled="historyPage * historyPageSize >= historyTotal" @click="loadHistory(historyPage + 1)">下一页</button>
            </div>
          </div>
        </section>
        <section class="aside-card">
          <header class="u-panel-head aside-card__head">
            <h2 class="aside-card__title">来源清单</h2>
            <span v-if="result" class="badge">{{ result.citations.length }}</span>
          </header>

          <div v-if="loading" class="aside-card__body">
            <LoadingBlock variant="list" :rows="3" />
          </div>

          <div v-else-if="result && result.citations.length" class="aside-card__body">
            <CitationCard
              v-for="c in result.citations"
              :key="c.index"
              :citation="c"
              :index="c.index"
              class="aside-card__cite"
              :class="{ 'is-active': activeCitation === c.index }"
            />
          </div>

          <div v-else-if="result" class="aside-card__body">
            <EmptyState
              icon="empty"
              title="本次未检索到来源"
              body="问题可能超出了知识库收录范围。可尝试换用制度文件中的表述，或先在知识库中补录相关文件。"
            />
          </div>

          <div v-else class="aside-card__body">
            <p class="aside-hint">提问后，这里会列出本次回答引用的全部来源，可按角标逐一核对。</p>
          </div>
        </section>

        <!-- 检索明细：把"检索了多少、用了多少"如实交代 -->
        <section v-if="result" class="aside-card aside-card--stat">
          <header class="u-panel-head aside-card__head">
            <h2 class="aside-card__title">检索明细</h2>
          </header>
          <dl class="stats">
            <div class="stats__row">
              <dt>命中片段</dt>
              <dd class="u-num">{{ result.retrieved_count }}</dd>
            </div>
            <div class="stats__row">
              <dt>实际引用</dt>
              <dd class="u-num">{{ result.used_count }}</dd>
            </div>
            <div class="stats__row">
              <dt>依据充分</dt>
              <dd>{{ result.has_sufficient_evidence ? '是' : '否' }}</dd>
            </div>
            <div v-if="resultReranker !== null" class="stats__row">
              <dt>重排序</dt>
              <dd>{{ resultReranker ? '已启用' : '未启用' }}</dd>
            </div>
          </dl>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.recent-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3);
  text-align: left;
  border-bottom: var(--border);
}
.recent-item:hover { background: var(--paper-dim); }
.recent-pages { display: flex; align-items: center; justify-content: space-between; }

.ask {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-6) var(--space-6) var(--space-12);
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
}

.ask__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--aside-w);
  gap: var(--space-6);
  align-items: start;
}

.ask__main {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  min-width: 0;
}

/* ---------------------------- 提问区 ------------------------------- */
.composer {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.composer__box {
  background: var(--paper-raised);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
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
  min-height: 104px;
}

.composer__input:focus {
  outline: none;
  box-shadow: none;
}

.composer__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-top: var(--border);
  background: var(--paper-dim);
}

.composer__params {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.param {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.param__label {
  font-size: var(--text-xs);
  color: var(--ink-muted);
  white-space: nowrap;
}

.param__select {
  width: auto;
  height: 28px;
  padding-inline: var(--space-2);
  font-size: var(--text-xs);
}

.check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--ink-muted);
  cursor: pointer;
  white-space: nowrap;
}

.check__box {
  width: 14px;
  height: 14px;
  accent-color: var(--accent);
  cursor: pointer;
}

.composer__submit {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: none;
}

.composer__count {
  font-size: var(--text-xs);
}

.composer__count.is-low {
  color: var(--warn-ink);
}

.level-note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.level-note.is-restricted {
  color: var(--warn-ink);
}

/* ---------------------------- 例句 -------------------------------- */
.suggest {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-2);
}

.suggest__list {
  display: flex;
  flex-direction: column;
  border: var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--paper-raised);
}

.suggest__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
  padding: var(--space-3) var(--space-4);
  border-bottom: var(--border);
  text-align: left;
  font-size: var(--text-base);
  color: var(--ink-soft);
  transition: background-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.suggest__list li:last-child .suggest__item {
  border-bottom: 0;
}

.suggest__item:hover {
  background: var(--paper-dim);
  color: var(--ink);
}

.suggest__item :deep(svg) {
  color: var(--ink-faint);
}

/* ---------------------------- 结论条 ------------------------------ */
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

/* ---------------------------- 回显 -------------------------------- */
.echo {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  border-bottom: var(--border);
}

.echo__text {
  font-size: var(--text-md);
  font-weight: 500;
  line-height: var(--leading-normal);
  color: var(--ink);
}

/* ---------------------------- 回答 -------------------------------- */
.answer {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
}

.answer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.answer__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  max-width: var(--measure);
}

/* 阅读正文：行高放宽到 1.85，字号提到 15px，中文长文的可读性优先 */
.answer__body p {
  font-size: var(--text-md);
  line-height: var(--leading-loose);
  color: var(--ink);
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

.answer__foot {
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

/* ---------------------------- 侧栏 -------------------------------- */
.ask__aside {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  position: sticky;
  top: calc(var(--nav-h) + var(--space-6));
  max-height: calc(100dvh - var(--nav-h) - var(--space-12));
  overflow-y: auto;
  padding-right: 2px;
}

.aside-card {
  background: var(--paper-raised);
  border: var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.aside-card__head {
  background: var(--paper-dim);
}

.aside-card__title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink);
}

.aside-card__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
}

.aside-card__cite {
  scroll-margin-top: calc(var(--nav-h) + var(--space-6));
}

.aside-card__cite.is-active {
  border-color: var(--accent-edge);
  background: var(--accent-wash);
}

.aside-hint {
  padding: var(--space-2);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.stats {
  display: flex;
  flex-direction: column;
}

.stats__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: var(--border);
}

.stats__row:last-child {
  border-bottom: 0;
}

.stats__row dt {
  font-size: var(--text-sm);
  color: var(--ink-muted);
}

.stats__row dd {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink);
}

/* ---------------------------- 响应式 ------------------------------ */
@media (max-width: 1080px) {
  .ask__grid {
    grid-template-columns: 1fr;
  }

  .ask__aside {
    position: static;
    max-height: none;
    overflow: visible;
  }
}

@media (max-width: 720px) {
  .ask {
    padding: var(--space-4) var(--space-4) var(--space-10);
    gap: var(--space-4);
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

  .answer {
    padding: var(--space-4);
  }
}
</style>
