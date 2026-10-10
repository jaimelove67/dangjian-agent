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
  | 'other'

export const ACTIVITY_TYPE_LABELS: Record<ActivityType, string> = {
  branch_member_meeting: '支部大会',
  branch_committee_meeting: '支委会',
  party_group_meeting: '党小组会',
  party_lecture: '党课',
  other: '其他组织生活',
}

export interface Organization { id: string; name: string; org_type: string }
export type ReviewStatus = 'draft' | 'pending' | 'approved' | 'rejected'

export interface Participant { participant_id: string; name: string; attended: boolean }
export interface EvidenceNote { text: string; quote: string; start: number; end: number }
export type Minutes = Partial<Record<'learning_points' | 'consensus' | 'requirements', EvidenceNote[]>>

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
  by_type: Record<string, { label: string; required: number; performed: number; total_registered: number }>
  attendance_rate: MeetingRatio
  minutes_completeness: MeetingRatio
  evidence: { activity_id: string; activity_type: string; revision: number; held_on: string; participants: (Participant & { source_id: string })[]; sources: MeetingSource[] }[]
  missing: string[]
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