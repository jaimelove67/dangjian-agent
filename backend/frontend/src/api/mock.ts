import type { TodoItem } from './types'

/**
 * 演示数据源。
 *
 * 仅剩「待办建议」的离线示例（MOCK_TODOS），供党员发展页「查看示例」按钮使用，
 * 界面上明确标注"离线示例，未取自后端计算"。
 *
 * 其余页面均已切换到真实接口，对应 mock 已移除：
 *   - 知识库列表 / 删除    → GET/POST/PATCH/DELETE /knowledge-docs（api/knowledge.ts）
 *   - 问答历史             → GET /qa/sessions（api/qa.ts）
 *   - 培养对象名册         → GET /member/roster（api/member.ts）
 */

export const MOCK_TODOS: TodoItem[] = [
  { category: 'material', content: '张一鸣 的培养考察记录距下次支委会审议不足 30 天' },
  { category: 'material', content: '李思远 尚缺群众评议材料，请补齐后提交' },
  { category: 'meeting', content: '研究生第二党支部本季度支部大会尚未归档' },
  { category: 'reminder', content: '王砚书 的公示情况报告公示期已满，可提交上级审批' },
]