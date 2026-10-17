import { http } from './http'

/**
 * 组织生活（三会一课）接口层。
 *
 * 后端契约：app/api/v1/meeting.py + app/services/activity_service.py。
 * 权限码：meeting.query / meeting.manage / meeting.review / meeting.archive。
 */

export type ActivityType =
  | 'branch_member_meeting'
  | 'branch_committee_meeting'
  | 'party_group_meeting'
  | 'party_lecture'
  | 'organizational_life_meeting'
  | 'other'

export const ACTIVITY_TYPE_LABELS: Record<ActivityType, string> = {
  branch_member_meeting: '支部大会',
  branch_committee_meeting: '支委会',
  party_group_meeting: '党小组会',
  party_lecture: '党课',
  organizational_life_meeting: '组织生活会',
  other: '其他组织生活',
}

/** 组织生活会的纪要栏目与三会一课不同：查摆问题 / 批评与自我批评 / 整改方向。 */
export type MinutesKey =
  | 'learning_points'
  | 'consensus'
  | 'requirements'
  | 'problems'
  | 'criticisms'
  | 'rectifications'

/** 三会一课与中心组学习的纪要栏目。 */
export const MINUTES_SECTIONS: { key: MinutesKey; label: string }[] = [
  { key: 'learning_points', label: '学习要点' },
  { key: 'consensus', label: '讨论共识' },
  { key: 'requirements', label: '工作要求' },
]

/** 组织生活会的纪要栏目与三会一课不同：查摆问题 / 批评与自我批评 / 整改方向。 */
export const ORG_LIFE_MINUTES_SECTIONS: { key: MinutesKey; label: string }[] = [
  { key: 'problems', label: '查摆问题' },
  { key: 'criticisms', label: '批评意见' },
  { key: 'rectifications', label: '整改方向' },
]

/** 按活动类型给出纪要栏目，避免把"批评意见"塞进"讨论共识"。 */
export function minutesSectionsFor(type: ActivityType | undefined) {
  return type === 'organizational_life_meeting' ? ORG_LIFE_MINUTES_SECTIONS : MINUTES_SECTIONS
}

export interface Organization { id: string; name: string; org_type: string }
export type ReviewStatus = 'draft' | 'pending' | 'approved' | 'rejected'

export interface Participant { participant_id: string; name: string; attended: boolean }
export interface EvidenceNote { text: string; quote: string; start: number; end: number }
export type Minutes = Partial<Record<MinutesKey, EvidenceNote[]>>

export interface MeetingTask {
  id: string
  record_id: string
  org_unit_id: string
  task_text: string
  source_start: number
  source_end: number
  owner_name: string
  due_on: string | null
  status: 'pending' | 'active' | 'done' | 'cancelled'
  confirmed_by: string | null
  confirmed_at: string | null
  handled_at: string | null
  handle_note: string
}

export interface MeetingSource {
  doc_id: string
  title: string
  issuer: string
  file_name: string
  effective_date: string
  expiration_date: string | null
  visibility: string
  level: string
  status: string
  content_revision: number
  summary: string
  excerpt: string
  chunk_id: string | null
  article: string | null
}

export interface MeetingRecord {
  id: string
  org_unit_id: string
  activity_type: ActivityType
  activity_type_label: string
  title: string
  scheduled_on: string
  held_on: string | null
  host: string
  participants: Participant[]
  source_doc_ids: string[]
  sources: MeetingSource[]
  context: { agenda?: string; notice?: string; agenda_template_version?: string }
  transcript: string
  minutes: Minutes
  revision: number
  review_status: ReviewStatus
  submitted_by: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_comment: string
  archived_at: string | null
  archive_policy_version: number | null
  tasks: MeetingTask[]
  missing: string[]
  restricted: boolean
  notice: string
  execution_status: 'planned' | 'held' | 'pending' | 'completed' | 'archived' | 'rejected'
}

export interface MeetingPage<T> { items: T[]; total: number; page: number; page_size: number }
export interface TypeOption { value: ActivityType; label: string }
export interface MeetingRatio { value: number | null; numerator: number; denominator: number; status: string }
export interface MeetingStats {
  year: number
  counts: Record<string, number>
  by_type: Record<
    string,
    {
      label: string
      required: number
      performed: number
      total_registered: number
      period: 'month' | 'quarter' | 'year' | 'none'
      period_text: string
      basis: string
    }
  >
  attendance_rate: MeetingRatio
  minutes_completeness: MeetingRatio
  evidence: { activity_id: string; activity_type: string; revision: number; held_on: string; participants: (Participant & { source_id: string })[]; sources: MeetingSource[] }[]
  missing: string[]
  calculation_rule: string
}

/** 本周期状态：已达标 / 已召开但纪要未过审 / 期内还差次数 */
export type FrequencyState = 'met' | 'awaiting_review' | 'open'

export interface MeetingFrequencyRow {
  org_unit_id: string
  org_unit_name: string
  activity_type: ActivityType
  activity_type_label: string
  period: 'month' | 'quarter' | 'year' | 'none'
  period_label: string
  period_start: string
  period_end: string
  required: number
  performed: number
  awaiting_review: number
  scheduled: number
  missing: number
  days_left: number
  annual_required: number
  period_text: string
  basis: string
  state: FrequencyState
  reminder: string
}

export interface MeetingFrequencyGap {
  org_unit_id: string
  org_unit_name: string
  activity_type: ActivityType
  activity_type_label: string
  period: 'month' | 'quarter' | 'year' | 'none'
  required: number
  missed_periods: string[]
  missing_total: number
  awaiting_total: number
  text: string
}

export interface MeetingFrequency {
  as_of: string
  year: number
  org_unit_id: string | null
  branch_count: number
  rows: MeetingFrequencyRow[]
  reminders: MeetingFrequencyRow[]
  gaps: MeetingFrequencyGap[]
  missing: string[]
  truncated: boolean
  notice: string
  calculation_rule: string
}
export interface MeetingRevision {
  revision: number
  action: string
  actor_id: string
  created_at: string
  reason: string
  restricted: boolean
  snapshot: Record<string, unknown> | null
}
export interface RevisionPayload { expected_revision: number; reason: string }

export const meetingApi = {
  organizations(): Promise<{ items: Organization[] }> { return http.get('/meeting/org-units') },
  typeOptions(): Promise<{ types: TypeOption[]; requirements: null }> { return http.get('/meeting/type-options') },
  records(params: object): Promise<MeetingPage<MeetingRecord>> { return http.get('/meeting/records', { params }) },
  record(id: string): Promise<MeetingRecord> { return http.get(`/meeting/records/${encodeURIComponent(id)}`) },
  create(body: object): Promise<MeetingRecord> { return http.post('/meeting/records', body) },
  update(id: string, body: object): Promise<MeetingRecord> { return http.patch(`/meeting/records/${encodeURIComponent(id)}`, body) },
  recommend(id: string, q?: string): Promise<{ topic: string; sources: MeetingSource[]; missing: string[] }> {
    return http.get(`/meeting/records/${encodeURIComponent(id)}/recommendations`, { params: { q: q || undefined } })
  },
  action(id: string, action: 'generate-agenda' | 'generate-minutes' | 'submit' | 'review' | 'archive', body: RevisionPayload & { decision?: string }): Promise<MeetingRecord> {
    return http.post(`/meeting/records/${encodeURIComponent(id)}/${action}`, body)
  },
  revisions(id: string): Promise<{ items: MeetingRevision[] }> { return http.get(`/meeting/records/${encodeURIComponent(id)}/revisions`) },
  history(params: object): Promise<MeetingPage<MeetingRecord>> { return http.get('/meeting/history', { params }) },
  stats(params: object): Promise<MeetingStats> { return http.get('/meeting/stats', { params }) },
  frequency(params: object): Promise<MeetingFrequency> { return http.get('/meeting/frequency', { params }) },
  export(id: string): Promise<{ record: MeetingRecord; revisions: MeetingRevision[] }> {
    return http.get(`/meeting/records/${encodeURIComponent(id)}/export`)
  },
  createTask(id: string, body: object): Promise<{ task: MeetingTask; notice: string }> {
    return http.post(`/meeting/records/${encodeURIComponent(id)}/tasks`, body)
  },
  confirmTask(taskId: string, body: object): Promise<{ task: MeetingTask; notice: string }> {
    return http.patch(`/meeting/tasks/${encodeURIComponent(taskId)}`, body)
  },
  handleTask(taskId: string, body: object): Promise<{ task: MeetingTask; notice: string }> {
    return http.post(`/meeting/tasks/${encodeURIComponent(taskId)}/handle`, body)
  },
  tasks(params: object): Promise<MeetingPage<MeetingTask>> { return http.get('/meeting/tasks', { params }) },
}

/** 民主评议党员（模块3 / T-ORG-11）：一条 = 一个年度 × 一名党员。 */
export type ReviewGrade = 'outstanding' | 'qualified' | 'basic' | 'unqualified'

export const GRADE_LABELS: Record<ReviewGrade, string> = {
  outstanding: '优秀',
  qualified: '合格',
  basic: '基本合格',
  unqualified: '不合格',
}

export interface ReviewTest {
  eligible: number
  attended: number
  outstanding: number
  qualified: number
  basic: number
  unqualified: number
}

export interface ReviewProcedure {
  self_assessment: string
  peer_review: string
  test: ReviewTest | null
  branch_opinion: string
}

export interface MemberReviewTarget {
  profile_id: string
  member_name: string
  stage: string
  stage_label: string
  org_unit_id: string
  org_name: string
  in_roster: boolean
  review_id: string | null
  revision: number
  review_status: ReviewStatus | 'not_started'
  submitted_by: string | null
  can_review: boolean
  grade: string
  grade_label: string
  missing: string[]
  advisories: string[]
}

export interface MemberReviewProgress {
  target_total: number
  launched: number
  not_started: number
  draft: number
  pending: number
  approved: number
  rejected: number
}

export interface MemberReviewAttention {
  review_id: string
  member_name: string
  org_name: string
  grade: string
  grade_label: string
  rectification: string
}

export interface MemberReviewWorkspace {
  year: number
  org_unit_id: string | null
  org_name: string
  targets: MemberReviewTarget[]
  target_total: number
  progress: MemberReviewProgress
  grades: Record<string, number>
  grade_options: { key: ReviewGrade; label: string }[]
  outstanding: number
  outstanding_ratio: number
  attention: MemberReviewAttention[]
  advisory_count: number
  truncated: boolean
  missing: string[]
  notices: {
    outstanding_notice: string
    unqualified_notice: string
    feedback_notice: string
  }
  notice: string
  boundary: string
}

export interface MemberReviewDetail {
  id: string
  year: number
  profile_id: string
  org_unit_id: string
  org_name: string
  member_name: string
  stage: string
  procedure: Partial<ReviewProcedure>
  grade: string
  grade_label: string
  basis: string
  rectification: string
  revision: number
  review_status: ReviewStatus
  submitted_by: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_comment: string
  missing: string[]
  advisories: string[]
  revisions: MeetingRevision[]
  // 字段级敏感分级（T-MEM-12）：密级、可否出网 / 向量化、本次被脱敏的第三人字段
  data_level?: string
  data_level_label?: string
  cloud_allowed?: boolean
  embedding_allowed?: boolean
  redacted_fields?: string[]
  notice: string
  boundary: string
}

export const memberReviewApi = {
  workspace(params: { year: number; org_unit_id?: string }): Promise<MemberReviewWorkspace> {
    return http.get('/meeting/member-reviews/workspace', { params })
  },
  launch(body: {
    year: number
    org_unit_id: string
    reason: string
  }): Promise<{ created: number; skipped: number; target_total: number; org_name: string; notice: string }> {
    return http.post('/meeting/member-reviews/launch', body)
  },
  create(body: object): Promise<{ id: string; year: number; revision: number }> {
    return http.post('/meeting/member-reviews', body)
  },
  detail(id: string): Promise<MemberReviewDetail> {
    return http.get(`/meeting/member-reviews/${encodeURIComponent(id)}`)
  },
  update(id: string, body: object): Promise<{ id: string; revision: number; review_status: ReviewStatus }> {
    return http.patch(`/meeting/member-reviews/${encodeURIComponent(id)}`, body)
  },
  submit(id: string, body: RevisionPayload): Promise<{ id: string; revision: number; review_status: ReviewStatus }> {
    return http.post(`/meeting/member-reviews/${encodeURIComponent(id)}/submit`, body)
  },
  review(
    id: string,
    body: RevisionPayload & { decision: 'approved' | 'rejected' },
  ): Promise<{ id: string; revision: number; review_status: ReviewStatus }> {
    return http.post(`/meeting/member-reviews/${encodeURIComponent(id)}/review`, body)
  },
}

export const REVIEW_LABELS: Record<ReviewStatus, string> = {
  draft: '计划/草稿',
  pending: '纪要待审核',
  approved: '已通过人工审核',
  rejected: '已退回',
}

export const EXECUTION_LABELS: Record<string, string> = {
  planned: '已安排（待召开）',
  held: '已召开，纪要待补',
  pending: '纪要待审核',
  completed: '已完成（审核通过）',
  archived: '已归档',
  rejected: '已退回',
}