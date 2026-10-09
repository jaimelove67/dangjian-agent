/**
 * 党建工作智能助手 —— 知识问答接口
 *
 * 后端真实接口：POST /api/v1/qa/ask（依赖 PR #16 的六阶段问答链）
 * 接口未合并前走 Mock，切换只改 mock.ts 里的 PARTY_USE_MOCK。
 */

import { requestClient } from '#/api/request';

import { PARTY_USE_MOCK, pickMockAnswer } from './mock';
import type { QaAnswer } from './types';

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 提问
 *
 * 后端返回结构（APIResponse 解包后）：
 * { sessionId, answerType, content, citations[], refusedReason?, suggestions? }
 */
export async function askQuestionApi(
  question: string,
  sessionId?: string,
): Promise<QaAnswer> {
  if (PARTY_USE_MOCK) {
    // 模拟检索与生成耗时，便于观察加载态
    await delay(650);
    return pickMockAnswer(question);
  }

  return await requestClient.post<QaAnswer>('/v1/qa/ask', {
    question,
    session_id: sessionId,
  });
}
