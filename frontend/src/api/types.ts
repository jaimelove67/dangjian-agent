/**
 * 后端响应与领域类型定义。
 *
 * 权威来源（逐字段核对，勿凭记忆改写）：
 *   - app/schemas/common.py        → APIResponse / ErrorCode
 *   - app/api/v1/auth.py           → TokenResponse
 *   - app/schemas/auth.py          → UserInfo
 *   - app/api/v1/qa.py             → QuestionRequest / QuestionResponse / CitationSchema
 *   - app/api/v1/knowledge.py      → DocumentCreateResponse / DocumentStatusUpdate
 *   - app/schemas/knowledge.py     → DocumentResponse
 *   - app/api/v1/member.py + app/schemas/member.py → 三项计算型接口
 *   - app/rules/member_stages.py   → MemberStage / STAGE_LABELS
 *   - app/core/security.py         → Permission 权限码
 *   - app/llm/base.py              → DataLevel 数据分级
 *
 * ⚠️ 已知后端分歧（前端按下方注释择一，不擅自统一后端）：
 *   app/api/v1/qa.py 内联定义了 QuestionRequest / QuestionResponse / CitationSchema，
 *   与 app/schemas/qa.py 的 AskRequest / QAResponse / Citation **字段名不同**。
 *   挂在路由上的真实契约是前者，故前端一律采用前者。
 */

/** 统一响应包裹体：与 app/schemas/common.py 的 APIResponse 一一对应 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
  trace_id: string
}

/** 与 app/schemas/common.py::ErrorCode 对齐，仅列前端需要分支处理的 */
export const ErrorCode = {
  SUCCESS: 0,
  PARAM_ERROR: 40001,
  UNAUTHORIZED: 40101,
  FORBIDDEN: 40301,
  TENANT_ISOLATION: 40302,
  NOT_FOUND: 40401,
  CONFLICT: 40901,
  BUSINESS_ERROR: 42201,
  RATE_LIMITED: 42901,
  SERVER_ERROR: 50001,
  SERVICE_UNAVAILABLE: 50301,
} as const

/* ============================ 认证 ===================================== */

/** app/api/v1/auth.py::TokenResponse */
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

/** app/schemas/auth.py::LoginRequest */
export interface LoginRequest {
  username: string
  password: string
}

/** app/schemas/auth.py::UserInfo —— email / phone 已被服务端脱敏 */
export interface UserInfo {
  id: string
  username: string
  name: string
  role: UserRole
  tenant_id: string
  org_unit_id?: string | null
  email?: string | null
  phone?: string | null
}

/** app/models/user.py::UserRole */
export type UserRole =
  | 'system_admin'
  | 'school_admin'
  | 'department_admin'
  | 'branch_secretary'
  | 'organizer'
  | 'member'
  | 'applicant'

export const ROLE_LABELS: Record<UserRole, string> = {
  system_admin: '系统管理员',
  school_admin: '校级管理员',
  department_admin: '院系管理员',
  branch_secretary: '支部书记',
  organizer: '组织员',
  member: '党员',
  applicant: '申请人',
}

/** app/core/security.py::Permission —— 前端仅用于按权限显隐，不代替服务端校验 */
export type PermissionCode =
  | 'qa.ask'
  | 'knowledge.query'
  | 'knowledge.manage'
  | 'member.query'
  | 'member.stage_transition'
  | 'member.scoring'
  | 'meeting.archive'
  | 'admin.config'
  | 'admin.audit'

export const PERM = {
  QA_ASK: 'qa.ask',
  KNOWLEDGE_QUERY: 'knowledge.query',
  KNOWLEDGE_MANAGE: 'knowledge.manage',
  MEMBER_QUERY: 'member.query',
  STAGE_TRANSITION: 'member.stage_transition',
  SCORING: 'member.scoring',
  MEETING_ARCHIVE: 'meeting.archive',
  CONFIG_MANAGE: 'admin.config',
  AUDIT_QUERY: 'admin.audit',
} as const satisfies Record<string, PermissionCode>

/* ============================ 问答 ===================================== */

/** app/llm/base.py::DataLevel —— 数据分级，决定模型出网闸门走向 */
export type DataLevel = 'public' | 'internal' | 'sensitive' | 'classified'

export const DATA_LEVEL_LABELS: Record<DataLevel, string> = {
  public: '公开',
  internal: '内部',
  sensitive: '敏感',
  classified: '涉密',
}

/**
 * 项目使用云端模型；最终分级和出网边界由后端校验。
 */
export const DATA_LEVEL_ROUTE: Record<DataLevel, string> = {
  public: '外部模型可处理',
  internal: '仅获准的云端服务可处理',
  sensitive: '当前云端模式禁止处理',
  classified: '禁止 AI 处理',
}

/** app/api/v1/qa.py::QuestionRequest */
export interface AskQuestionRequest {
  question: string
  data_level: DataLevel
  use_reranker: boolean
  top_k: number
  session_id?: string
  include_expired?: boolean
}

/** app/api/v1/qa.py::CitationSchema */
export interface Citation {
  title: string
  issuer: string
  doc_number?: string | null
  article?: string | null
  content: string
  score: number
  index: number
  doc_id: string
  file_name?: string | null
  effective_date?: string | null
  expiration_date?: string | null
  visibility?: string | null
  chunk_id?: string | null
}

/** app/api/v1/qa.py::QuestionResponse */
export interface AskQuestionResponse {
  answer: string
  citations: Citation[]
  retrieved_count: number
  used_count: number
  has_sufficient_evidence: boolean
  warnings: string[]
  disclaimer: string
  refused: boolean
  session_id?: string | null
}

export interface QASessionItem extends AskQuestionResponse {
  id: string
  question: string
  data_level: DataLevel
  created_at: string
}

export interface QASessionListResponse {
  items: QASessionItem[]
  total: number
  page: number
  page_size: number
}

/* ============================ 知识库 =================================== */

export type DocLevel = 'central' | 'provincial' | 'school' | 'department'
export type DocVisibility = 'public' | 'school' | 'department' | 'branch'
export type DocStatus = 'effective' | 'expired' | 'abolished'

export const DOC_LEVEL_LABELS: Record<DocLevel, string> = {
  central: '中央',
  provincial: '省级',
  school: '校级',
  department: '院系',
}

export const DOC_VISIBILITY_LABELS: Record<DocVisibility, string> = {
  public: '公开',
  school: '校内',
  department: '院系内',
  branch: '支部内',
}

export const DOC_STATUS_LABELS: Record<DocStatus, string> = {
  effective: '有效',
  expired: '已失效',
  abolished: '已废止',
}

/** 状态对应的徽标语义，供 UI 统一着色 */
export const DOC_STATUS_TONE: Record<DocStatus, 'ok' | 'warn' | 'bad'> = {
  effective: 'ok',
  expired: 'warn',
  abolished: 'bad',
}

/** app/schemas/knowledge.py::DocumentResponse */
export interface DocumentResponse {
  content_revision?: number
  id: string
  doc_id: string
  file_name: string
  title: string
  issuer: string
  doc_number?: string | null
  level: DocLevel
  visibility: DocVisibility
  security_level: DataLevel
  status: DocStatus
  effective_date?: string | null
  expiration_date?: string | null
  tags: string[]
  summary?: string | null
  page_count?: number | null
}

/** app/api/v1/knowledge.py::create_knowledge_doc 的返回 */
export interface DocumentCreateResponse {
  document: DocumentResponse
  chunk_count: number
}

export interface DocumentListResponse {
  items: DocumentResponse[]
  total: number
  page: number
  page_size: number
  counts: Record<string, number>
}

/** app/schemas/knowledge.py::DocumentStatusUpdate */
export interface DocumentStatusUpdate {
  status: DocStatus
}

/** 上传表单：对应 POST /knowledge-docs 的 multipart 字段 */
export interface DocumentUploadForm {
  file: File
  doc_id: string
  file_name: string
  title: string
  issuer: string
  level: DocLevel
  visibility: DocVisibility
  effective_date: string
  security_level: DataLevel
  tags: string
  doc_number?: string
  summary?: string
  expiration_date?: string
  status?: DocStatus
}

/* ============================ 党员发展 ================================= */

/** app/rules/member_stages.py::MemberStage */
export type MemberStage =
  | 'applicant'
  | 'activist'
  | 'candidate'
  | 'probationary'
  | 'member'
  | 'rejected'

export const STAGE_LABELS: Record<MemberStage, string> = {
  applicant: '入党申请人',
  activist: '入党积极分子',
  candidate: '发展对象',
  probationary: '预备党员',
  member: '正式党员',
  rejected: '退回',
}

/** 发展流程主干（不含退回分支），用于步骤条渲染 */
export const STAGE_ORDER: MemberStage[] = [
  'applicant',
  'activist',
  'candidate',
  'probationary',
  'member',
]

export interface MemberRosterItem {
  id: string
  name: string
  org_name: string
  org_unit_id?: string | null
  stage: MemberStage
  stage_joined_on: string
  days_in_stage: number
  materials: string[]
  pending: number
}

export interface MemberRosterResponse {
  items: MemberRosterItem[]
  total: number
  page: number
  page_size: number
}

export interface MemberCreateRequest {
  name: string
  org_unit_id?: string
  current_stage: MemberStage
  stage_joined_on?: string
  materials: string[]
  pending: number
}

export interface MemberOrgOption {
  id: string
  name: string
  org_type: string
}

/** app/schemas/member.py::QualificationCheckRequest */
export interface QualificationCheckRequest {
  current_stage: MemberStage
  target_stage: MemberStage
  materials: string[]
  days_in_stage: number
}

/** app/schemas/member.py::QualificationResult */
export interface QualificationResult {
  eligible: boolean
  blockers: string[]
  missing_materials: string[]
  present_materials: string[]
  min_days: number
  days_in_stage: number
}

/** app/schemas/member.py::TransitionSuggestion */
export interface TransitionSuggestion {
  current_stage: MemberStage
  suggested_target?: MemberStage | null
  eligible: boolean
  procedures: string[]
  blockers: string[]
  note: string
}

/** app/schemas/member.py::TodoItem */
export interface TodoItem {
  category: 'material' | 'meeting' | 'reminder'
  content: string
}

/** app/schemas/member.py::TodoSuggestionsResponse */
export interface TodoSuggestionsResponse {
  todos: TodoItem[]
  note: string
}

export const TODO_CATEGORY_LABELS: Record<TodoItem['category'], string> = {
  material: '材料',
  meeting: '会议',
  reminder: '提醒',
}

/* ============================ 健康检查 ================================= */

/** app/api/v1/health.py::GET /health */
export interface HealthResponse {
  status: string
  service: string
  version: string
  environment: string
}

export interface ReadyResponse {
  status: 'ready' | 'not_ready'
  checks: Record<string, string>
  model_capabilities: Record<string, string>
}
