/**
 * 党建工作智能助手 —— Mock 数据
 *
 * 后端 QA 接口（PR #16）与知识库列表接口尚未就绪，先用 Mock 跑通交互与视觉。
 * 接口就绪后把 PARTY_USE_MOCK 置为 false 即可切到真实接口，页面代码无需改动。
 */

import type { Citation, KnowledgeDoc, QaAnswer, VerifyCheck } from './types';

/** Mock 总开关：接口就绪后改为 false */
export const PARTY_USE_MOCK = true;

/** 后端五大核验项名称（顺序固定，与设计稿一致） */
export const VERIFY_CHECK_NAMES = [
  '引用编号有效性',
  '条款真实性',
  '文件时效',
  '引用完整性',
  '无依据长回答检测',
] as const;

/** 构造一组核验结果 */
function buildChecks(passed: boolean, failedName?: string): VerifyCheck[] {
  return VERIFY_CHECK_NAMES.map((name) => ({
    name,
    passed: failedName ? name !== failedName : passed,
    detail: failedName === name ? '该引用已被自动剔除' : undefined,
  }));
}

/** 引用依据：发展党员工作细则 */
const CITATION_RULE: Citation = {
  index: 1,
  title: '中国共产党发展党员工作细则',
  clause: '第十三条',
  issuer: '中共中央组织部',
  docNumber: '中组发〔2014〕6 号',
  effectiveDate: '2014-06-10',
  docStatus: 'effective',
  excerpt:
    '第十三条　党支部应当听取党小组、培养联系人和党员、群众的意见，支部委员会讨论同意并报上级党委备案后，方可确定为发展对象……',
  hitParagraph: '命中段落 3 / 12',
  checks: buildChecks(true),
};

/** 引用依据：发展党员工作手册 */
const CITATION_MANUAL: Citation = {
  index: 2,
  title: '发展党员工作手册',
  clause: '第三章',
  issuer: '校党委组织部',
  effectiveDate: '2023-03-01',
  docStatus: 'effective',
  excerpt:
    '第三章　发展对象的确定，应当在上级党委审查同意后予以确认，并及时将有关材料归入本人档案……',
  hitParagraph: '命中段落 1 / 8',
  checks: buildChecks(true),
};

/** 正常作答 */
export const MOCK_QA_ANSWER: QaAnswer = {
  sessionId: 'mock-session-0001',
  answerType: 'answer',
  content: [
    '根据《中国共产党发展党员工作细则》第十三条[1]，确定发展对象须履行以下程序：',
    '一、党支部听取党小组、培养联系人和党员、群众的意见；',
    '二、支部委员会讨论同意后，报上级党委备案；',
    '三、上级党委审查同意后，确定为发展对象[2]。',
    '上述程序引自现行有效文件，已完成引用核验。',
  ].join('\n'),
  citations: [CITATION_RULE, CITATION_MANUAL],
};

/** 无依据拒答 */
export const MOCK_QA_REFUSE: QaAnswer = {
  sessionId: 'mock-session-0002',
  answerType: 'refuse',
  content: '',
  citations: [],
  refusedReason:
    '知识库中未找到与该问题直接相关的现行条款，为避免给出错误结论，本次不作回答。建议补充问题范围，或联系校党委组织部核实。',
  suggestions: ['换一种问法', '查看检索到的相近条款'],
};

/** 触发拒答的关键词（用于演示拒答态） */
const REFUSE_KEYWORDS = ['期限', '多久', '几天', '什么时候截止', '时限'];

/** 根据问题返回 Mock 回答 */
export function pickMockAnswer(question: string): QaAnswer {
  const hit = REFUSE_KEYWORDS.some((kw) => question.includes(kw));
  return hit
    ? { ...MOCK_QA_REFUSE, sessionId: `mock-${Date.now()}` }
    : { ...MOCK_QA_ANSWER, sessionId: `mock-${Date.now()}` };
}

/** 知识文档列表 Mock */
export const MOCK_DOCS: KnowledgeDoc[] = [
  {
    id: '1',
    docId: 'DOC-2014-0006',
    fileName: '中国共产党发展党员工作细则.pdf',
    title: '中国共产党发展党员工作细则',
    issuer: '中共中央组织部',
    docNumber: '中组发〔2014〕6 号',
    level: '中央级',
    visibility: '主动公开',
    securityLevel: '公开',
    status: 'effective',
    effectiveDate: '2014-06-10',
    tags: ['发展党员', '党员管理'],
    summary: '规范发展党员工作程序，明确入党积极分子、发展对象、预备党员各环节要求。',
  },
  {
    id: '2',
    docId: 'DOC-2023-0011',
    fileName: '发展党员工作手册.docx',
    title: '发展党员工作手册',
    issuer: '校党委组织部',
    level: '校级',
    visibility: '依申请公开',
    securityLevel: '内部',
    status: 'effective',
    effectiveDate: '2023-03-01',
    tags: ['发展党员', '工作手册'],
    summary: '校内发展党员工作的操作指引，含各环节表单与常见问题。',
  },
  {
    id: '3',
    docId: 'DOC-2019-0032',
    fileName: '关于党员组织关系转接的规定.pdf',
    title: '关于党员组织关系转接的规定',
    issuer: '校党委组织部',
    docNumber: '校党组〔2019〕32 号',
    level: '校级',
    visibility: '主动公开',
    securityLevel: '公开',
    status: 'expired',
    effectiveDate: '2019-05-01',
    expirationDate: '2024-04-30',
    tags: ['组织关系'],
    summary: '党员组织关系转接的办理流程与材料要求。',
  },
  {
    id: '4',
    docId: 'DOC-2017-0009',
    fileName: '党支部工作条例（试行）.pdf',
    title: '中国共产党支部工作条例（试行）',
    issuer: '中共中央',
    level: '中央级',
    visibility: '主动公开',
    securityLevel: '公开',
    status: 'effective',
    effectiveDate: '2018-10-28',
    tags: ['支部建设', '组织生活'],
    summary: '规范党支部的设置、职责、组织生活与建设要求。',
  },
];
