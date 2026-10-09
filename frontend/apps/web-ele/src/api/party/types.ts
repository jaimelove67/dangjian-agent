/**
 * 党建工作智能助手 —— 业务类型定义
 *
 * 字段命名与后端 schemas 保持一致，便于 Mock 与真实接口无缝切换。
 */

/** 引用核验项（对应后端五大核验项） */
export interface VerifyCheck {
  /** 核验项名称 */
  name: string;
  /** 是否通过 */
  passed: boolean;
  /** 未通过时的说明 */
  detail?: string;
}

/** 单条引用依据 */
export interface Citation {
  /** 引用编号，与正文中的 [n] 对应 */
  index: number;
  /** 文件标题 */
  title: string;
  /** 条款号 */
  clause: string;
  /** 发布机关 */
  issuer: string;
  /** 发文字号 */
  docNumber?: string;
  /** 施行日期 */
  effectiveDate?: string;
  /** 文件状态 */
  docStatus: 'abolished' | 'effective' | 'expired';
  /** 命中原文片段 */
  excerpt: string;
  /** 命中位置说明，如「命中段落 3 / 12」 */
  hitParagraph?: string;
  /** 该条引用的核验明细 */
  checks: VerifyCheck[];
}

/** 回答类型：正常作答 / 无依据拒答 */
export type AnswerType = 'answer' | 'refuse';

/** 问答响应 */
export interface QaAnswer {
  /** 会话 ID */
  sessionId: string;
  /** 回答类型 */
  answerType: AnswerType;
  /** 回答正文，引用编号以 [n] 形式内联 */
  content: string;
  /** 引用依据列表 */
  citations: Citation[];
  /** 拒答原因（answerType 为 refuse 时存在） */
  refusedReason?: string;
  /** 拒答时的建议操作 */
  suggestions?: string[];
}

/** 会话消息 */
export interface ChatMessage {
  id: string;
  role: 'assistant' | 'user';
  content: string;
  /** 助手消息附带的完整回答 */
  answer?: QaAnswer;
  /** 是否正在生成 */
  pending?: boolean;
}

/** 知识文档（对齐后端 DocumentResponse） */
export interface KnowledgeDoc {
  id: string;
  docId: string;
  fileName: string;
  title: string;
  issuer: string;
  docNumber?: string;
  /** 文件层级：中央级 / 省级 / 市级 / 校级 */
  level: string;
  /** 公开属性 */
  visibility: string;
  /** 密级：公开 / 内部 / 秘密 / 机密 */
  securityLevel: string;
  /** 状态：effective 现行有效 / expired 已失效 / abolished 已废止 */
  status: 'abolished' | 'effective' | 'expired';
  effectiveDate?: string;
  expirationDate?: string;
  tags: string[];
  summary?: string;
}

/** 文档入库请求体 */
export interface KnowledgeDocCreatePayload {
  fileName: string;
  title: string;
  issuer: string;
  docNumber?: string;
  level: string;
  visibility: string;
  securityLevel: string;
  effectiveDate?: string;
  expirationDate?: string;
  tags: string[];
  summary?: string;
}

/** 文档入库响应（对齐后端 DocumentCreateResponse） */
export interface KnowledgeDocCreateResult {
  document: KnowledgeDoc;
  chunkCount: number;
}

/** 分页响应 */
export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}
