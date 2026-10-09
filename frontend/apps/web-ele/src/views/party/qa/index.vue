<script lang="ts" setup>
/**
 * 智能问答页
 *
 * 核心交互：
 * 1. 提问 → 六阶段问答链（当前走 Mock）→ 带引用编号的作答
 * 2. 回答内引用编号可点击，展开该条引用的核验明细（后端五大核验项）
 * 3. 无依据时呈现拒答态，不给出结论
 */
import 'element-plus/es/components/message/style/css';

import { nextTick, ref } from 'vue';

import { ElButton, ElMessage } from 'element-plus';

import { askQuestionApi } from '#/api/party/qa';
import type { ChatMessage, Citation } from '#/api/party/types';

interface Segment {
  /** 引用编号；纯文本段固定为 0 */
  index: number;
  text: string;
  /** 是否为引用标记段 */
  isCitation: boolean;
}

const SAMPLE_QUESTIONS = [
  '发展对象的确定需要经过哪些程序？',
  '入党积极分子的培养联系人如何确定',
  '本次发展对象的群众意见征求期限',
];

let messageSeq = 0;
function nextId(): string {
  messageSeq += 1;
  return `msg-${messageSeq}`;
}

const messages = ref<ChatMessage[]>([]);
const draft = ref('');
const loading = ref(false);
const sessionId = ref<string>();
const listRef = ref<HTMLElement>();
const expandedKey = ref<null | string>(null);

/** 把一行文本按 [n] 引用标记切成文本段与引用段 */
function parseLine(line: string): Segment[] {
  const segments: Segment[] = [];
  const pattern = /\[(\d+)\]/g;
  let lastIndex = 0;
  let matched = pattern.exec(line);
  while (matched !== null) {
    if (matched.index > lastIndex) {
      segments.push({
        index: 0,
        text: line.slice(lastIndex, matched.index),
        isCitation: false,
      });
    }
    segments.push({
      index: Number(matched[1]),
      text: matched[0],
      isCitation: true,
    });
    lastIndex = matched.index + matched[0].length;
    matched = pattern.exec(line);
  }
  if (lastIndex < line.length) {
    segments.push({ index: 0, text: line.slice(lastIndex), isCitation: false });
  }
  return segments;
}

function linesOf(content: string): string[] {
  return content.split('\n');
}

function citationKey(messageId: string, index: number): string {
  return `${messageId}-${index}`;
}

function isExpanded(messageId: string, index: number): boolean {
  return expandedKey.value === citationKey(messageId, index);
}

function toggleCitation(messageId: string, index: number): void {
  const key = citationKey(messageId, index);
  expandedKey.value = expandedKey.value === key ? null : key;
}

/** 汇总核验结果 */
function verifySummary(citations: Citation[]): { passed: number; total: number } {
  const all = citations.flatMap((item) => item.checks);
  return {
    total: all.length,
    passed: all.filter((item) => item.passed).length,
  };
}

function statusText(status: Citation['docStatus']): string {
  const map: Record<Citation['docStatus'], string> = {
    abolished: '已废止',
    effective: '现行有效',
    expired: '已失效',
  };
  return map[status];
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = listRef.value;
  if (el) {
    el.scrollTop = el.scrollHeight;
  }
}

async function handleSend(preset?: string): Promise<void> {
  const question = (preset ?? draft.value).trim();
  if (!question || loading.value) {
    return;
  }

  draft.value = '';
  messages.value.push({ id: nextId(), role: 'user', content: question });

  const assistantId = nextId();
  messages.value.push({
    id: assistantId,
    role: 'assistant',
    content: '',
    pending: true,
  });

  loading.value = true;
  await scrollToBottom();

  try {
    const answer = await askQuestionApi(question, sessionId.value);
    sessionId.value = answer.sessionId;
    const target = messages.value.find((item) => item.id === assistantId);
    if (target) {
      target.pending = false;
      target.content = answer.content;
      target.answer = answer;
    }
    const first = answer.citations[0];
    if (first) {
      expandedKey.value = citationKey(assistantId, first.index);
    }
  } catch {
    const index = messages.value.findIndex((item) => item.id === assistantId);
    if (index !== -1) {
      messages.value.splice(index, 1);
    }
    ElMessage.error('问答服务暂时不可用，请稍后重试');
  } finally {
    loading.value = false;
    await scrollToBottom();
  }
}

function handleReset(): void {
  messages.value = [];
  sessionId.value = undefined;
  expandedKey.value = null;
}
</script>

<template>
  <div class="party-qa">
    <header class="qa-header">
      <div class="qa-title-group">
        <span class="qa-logo"></span>
        <div>
          <div class="qa-title">党建工作智能助手</div>
          <div class="qa-subtitle">
            回答均附引用出处，无依据时系统将直接拒答
          </div>
        </div>
      </div>
      <ElButton size="small" :disabled="messages.length === 0" @click="handleReset">
        新会话
      </ElButton>
    </header>

    <div ref="listRef" class="qa-body">
      <div v-if="messages.length === 0" class="qa-empty">
        <div class="empty-title">可以这样问我</div>
        <div class="empty-chips">
          <button
            v-for="item in SAMPLE_QUESTIONS"
            :key="item"
            class="empty-chip"
            type="button"
            @click="handleSend(item)"
          >
            {{ item }}
          </button>
        </div>
        <div class="empty-hint">
          第 3 个示例用于演示「无依据拒答」状态
        </div>
      </div>

      <template v-for="msg in messages" :key="msg.id">
        <div v-if="msg.role === 'user'" class="msg msg-user">
          <div class="bubble bubble-user">{{ msg.content }}</div>
        </div>

        <div v-else class="msg msg-assistant">
          <span class="assistant-avatar">党</span>
          <div class="assistant-main">
            <div v-if="msg.pending" class="pending">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              正在检索知识库并核验引用…
            </div>

            <div v-else-if="msg.answer?.answerType === 'refuse'" class="refuse">
              <div class="refuse-title">拒答状态 · 未检索到可靠依据</div>
              <div class="refuse-body">{{ msg.answer.refusedReason }}</div>
              <div class="refuse-actions">
                <ElButton
                  v-for="item in msg.answer.suggestions"
                  :key="item"
                  size="small"
                >
                  {{ item }}
                </ElButton>
              </div>
            </div>

            <template v-else-if="msg.answer">
              <div class="answer-body">
                <template v-for="(line, li) in linesOf(msg.answer.content)" :key="li">
                  <p v-if="line.trim()" class="answer-line">
                    <template v-for="(seg, si) in parseLine(line)" :key="si">
                      <span v-if="!seg.isCitation">{{ seg.text }}</span>
                      <button
                        v-else
                        class="cite-ref"
                        type="button"
                        @click="toggleCitation(msg.id, seg.index)"
                      >
                        [{{ seg.index }}]
                      </button>
                    </template>
                  </p>
                </template>
              </div>

              <div v-if="msg.answer.citations.length > 0" class="citations">
                <div class="citations-head">
                  <span class="citations-title">
                    引用溯源 · {{ msg.answer.citations.length }} 条依据
                  </span>
                  <span class="verify-badge">
                    核验 {{ verifySummary(msg.answer.citations).passed }}/{{
                      verifySummary(msg.answer.citations).total
                    }} 通过
                  </span>
                </div>

                <div
                  v-for="cite in msg.answer.citations"
                  :key="cite.index"
                  class="citation"
                >
                  <div
                    class="citation-row"
                    @click="toggleCitation(msg.id, cite.index)"
                  >
                    <span class="citation-index">[{{ cite.index }}]</span>
                    <div class="citation-main">
                      <div class="citation-title">
                        {{ cite.title }} · {{ cite.clause }}
                      </div>
                      <div class="citation-meta">
                        {{ cite.issuer }} · {{ statusText(cite.docStatus) }}
                        <template v-if="cite.effectiveDate">
                          · {{ cite.effectiveDate }} 施行
                        </template>
                      </div>
                    </div>
                    <span class="citation-toggle">
                      {{ isExpanded(msg.id, cite.index) ? '收起' : '核验明细' }}
                    </span>
                  </div>

                  <div
                    v-if="isExpanded(msg.id, cite.index)"
                    class="citation-detail"
                  >
                    <div class="excerpt">{{ cite.excerpt }}</div>
                    <div class="excerpt-meta">{{ cite.hitParagraph }}</div>
                    <div class="checks">
                      <div v-for="chk in cite.checks" :key="chk.name" class="check">
                        <span class="check-name">{{ chk.name }}</span>
                        <span class="check-result" :class="chk.passed ? 'ok' : 'bad'">
                          <span class="check-dot" :class="chk.passed ? 'ok' : 'bad'"></span>
                          {{ chk.passed ? '通过' : '未通过' }}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
      </template>
    </div>

    <footer class="qa-footer">
      <div class="input-shell">
        <textarea
          v-model="draft"
          class="input-area"
          rows="1"
          placeholder="请输入您的问题，例如「入党积极分子的培养联系人如何确定」"
          @keydown.enter.exact.prevent="handleSend()"
        ></textarea>
        <ElButton type="primary" :loading="loading" @click="handleSend()">
          发送
        </ElButton>
      </div>
      <div class="footer-hint">
        <span>回答均附引用出处，可点击核验</span>
        <span>涉密材料不参与检索</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.party-qa {
  --party-red: #a32d2d;
  --party-red-deep: #791f1f;
  --party-red-light: #fcebeb;
  --party-red-border: #f09595;
  --ok-text: #3b6d11;
  --ok-bg: #eaf3de;
  --warn-text: #633806;
  --warn-bg: #faeeda;
  --warn-border: #ef9f27;
  --line: rgba(0, 0, 0, 0.12);
  --surface: #f7f7f5;

  display: flex;
  flex-direction: column;
  height: calc(100vh - 165px);
  min-height: 520px;
  overflow: hidden;
  background: #fff;
  border: 0.5px solid var(--line);
  border-radius: 8px;
}

.qa-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 0.5px solid var(--line);
}

.qa-title-group {
  display: flex;
  gap: 9px;
  align-items: center;
}

.qa-logo {
  width: 15px;
  height: 15px;
  border-radius: 3px;
  background: var(--party-red);
}

.qa-title {
  font-size: 14px;
  font-weight: 500;
}

.qa-subtitle {
  margin-top: 2px;
  font-size: 11px;
  color: #9b9b97;
}

.qa-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  padding: 14px 16px;
  overflow-y: auto;
}

.qa-empty {
  margin: auto;
  text-align: center;
}

.empty-title {
  font-size: 12px;
  color: #9b9b97;
}

.empty-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  max-width: 520px;
  margin: 12px auto 0;
}

.empty-chip {
  padding: 7px 12px;
  font-size: 12px;
  color: #6b6b68;
  cursor: pointer;
  background: var(--surface);
  border: 0.5px solid var(--line);
  border-radius: 999px;
}

.empty-chip:hover {
  color: var(--party-red-deep);
  background: var(--party-red-light);
  border-color: var(--party-red-border);
}

.empty-hint {
  margin-top: 12px;
  font-size: 11px;
  color: #b4b2a9;
}

.msg-user {
  display: flex;
  justify-content: flex-end;
}

.bubble-user {
  max-width: 76%;
  padding: 9px 12px;
  font-size: 13px;
  line-height: 1.6;
  background: var(--surface);
  border-radius: 10px;
}

.msg-assistant {
  display: flex;
  gap: 9px;
}

.assistant-avatar {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  font-size: 11px;
  color: #fff;
  background: var(--party-red);
  border-radius: 50%;
}

.assistant-main {
  min-width: 0;
  flex: 1;
}

.pending {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: #9b9b97;
}

.pending .dot {
  width: 5px;
  height: 5px;
  background: var(--party-red-border);
  border-radius: 50%;
}

.answer-body {
  font-size: 13px;
  line-height: 1.75;
}

.answer-line {
  margin: 0;
}

.cite-ref {
  padding: 0 2px;
  font-size: 11px;
  color: var(--party-red);
  cursor: pointer;
  background: none;
  border: none;
}

.cite-ref:hover {
  text-decoration: underline;
}

.citations {
  margin-top: 10px;
  overflow: hidden;
  border: 0.5px solid var(--line);
  border-left: 2px solid var(--party-red);
  border-radius: 8px;
}

.citations-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 0.5px solid var(--line);
}

.citations-title {
  font-size: 12px;
  font-weight: 500;
}

.verify-badge {
  padding: 2px 7px;
  font-size: 11px;
  color: var(--ok-text);
  background: var(--ok-bg);
  border-radius: 999px;
}

.citation + .citation {
  border-top: 0.5px solid var(--line);
}

.citation-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 9px 12px;
  cursor: pointer;
}

.citation-row:hover {
  background: #fbfbfa;
}

.citation-index {
  flex: none;
  padding: 1px 5px;
  font-size: 11px;
  color: var(--party-red);
  background: var(--party-red-light);
  border-radius: 4px;
}

.citation-main {
  min-width: 0;
  flex: 1;
}

.citation-title {
  font-size: 12px;
  line-height: 1.5;
}

.citation-meta {
  margin-top: 2px;
  font-size: 11px;
  color: #9b9b97;
}

.citation-toggle {
  flex: none;
  font-size: 11px;
  color: #9b9b97;
}

.citation-detail {
  padding: 0 12px 12px 34px;
}

.excerpt {
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.75;
  color: #6b6b68;
  background: var(--surface);
  border-left: 2px solid var(--party-red-border);
  border-radius: 0 6px 6px 0;
}

.excerpt-meta {
  margin-top: 7px;
  font-size: 11px;
  color: #9b9b97;
}

.checks {
  margin-top: 10px;
}

.check {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 0;
  border-bottom: 0.5px solid var(--line);
}

.check:last-child {
  border-bottom: none;
}

.check-name {
  font-size: 12px;
}

.check-result {
  display: flex;
  gap: 5px;
  align-items: center;
  font-size: 11px;
}

.check-result.ok {
  color: var(--ok-text);
}

.check-result.bad {
  color: var(--party-red);
}

.check-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.check-dot.ok {
  background: #639922;
}

.check-dot.bad {
  background: #e24b4a;
}

.refuse {
  padding: 12px 14px;
  background: var(--warn-bg);
  border-left: 2px solid var(--warn-border);
  border-radius: 8px;
}

.refuse-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--warn-text);
}

.refuse-body {
  margin-top: 7px;
  font-size: 12px;
  line-height: 1.7;
  color: #6b6b68;
}

.refuse-actions {
  display: flex;
  gap: 8px;
  margin-top: 9px;
}

.qa-footer {
  padding: 10px 14px;
  border-top: 0.5px solid var(--line);
}

.input-shell {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 8px 10px;
  border: 0.5px solid rgba(0, 0, 0, 0.2);
  border-radius: 10px;
}

.input-area {
  flex: 1;
  min-height: 24px;
  max-height: 96px;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  color: inherit;
  resize: none;
  background: none;
  border: none;
  outline: none;
}

.footer-hint {
  display: flex;
  gap: 14px;
  margin-top: 7px;
  font-size: 11px;
  color: #b4b2a9;
}
</style>
