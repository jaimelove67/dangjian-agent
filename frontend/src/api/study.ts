import { http } from './http'

export interface StudySource {
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
  current_status?: string
  current_revision?: number
}

export type ReviewStatus = 'draft' | 'pending' | 'approved' | 'rejected'
export interface StudyItem {
  id: string
  plan_id: string
  topic: string
  scheduled_on: string
  responsible: string
  source_doc_ids: string[]
  sources: StudySource[]
  agenda: string
  outline: string
  template_version: string | null
  meeting_record_id: string | null
  execution_status: string
  missing: string[]
}

export interface ReviewedContent {
  id: string
  org_unit_id: string
  revision: number
  review_status: ReviewStatus
  submitted_by: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_comment: string
  source_doc_ids: string[]
  sources: StudySource[]
  notice: string
  missing: string[]
  restricted: boolean
}

export interface StudyPlan extends ReviewedContent {
  year: number
  title: string
  priorities: string[]
  responsible: string
  items: StudyItem[]
}

export interface Participant {
  participant_id: string
  name: string
  attended: boolean
}
export interface EvidenceNote { text: string; quote: string; start: number; end: number }
export type Minutes = Record<'learning_points' | 'consensus' | 'requirements', EvidenceNote[]>

export interface StudyActivity extends ReviewedContent {
  title: string
  scheduled_on: string
  held_on: string | null
  host: string
  transcript: string
  participants: Participant[]
  minutes: Partial<Minutes>
  context: { plan_id: string; item_id: string; plan_revision: number; agenda?: string; outline?: string }
  archived_at: string | null
  archive_policy_version: number | null
  execution_status: string
}

export interface StudyOrganization { id: string; name: string; org_type: string }
export interface StudyPage<T> { items: T[]; total: number; page: number; page_size: number }
export interface ArchivePolicy { enabled: boolean; revision: number; confirmed_by?: string; confirmed_at?: string; evidence?: string }
export interface StudyRevision {
  revision: number; action: string; actor_id: string; created_at: string; reason: string
  restricted: boolean; snapshot: (Partial<StudyPlan & StudyActivity>) | null
}
export interface StudyRatio { value: number | null; numerator: number; denominator: number; status: string }
export interface StudyMetrics {
  year: number
  learning_count: { value: number | null; status: string }
  plan_completion_rate: StudyRatio
  attendance_rate: StudyRatio
  minutes_completeness: StudyRatio
  evidence: { activity_id: string; revision: number; held_on: string; reviewed_by: string; participants: (Participant & { source_id: string })[]; sources: StudySource[] }[]
  plan_evidence: { plan_id: string; plan_revision: number; item_id: string; activity_id: string | null; completed: boolean }[]
  missing: string[]
  calculation_rule: string
}
export interface StudyExport {
  notice: string; record: StudyActivity; plan_version: StudyPlan
  revisions: StudyRevision[]; archive_confirmation: ArchivePolicy; exported_at: string
}
export interface RevisionPayload { expected_revision: number; reason: string }

export const studyApi = {
  organizations(): Promise<{ items: StudyOrganization[] }> { return http.get('/study/org-units') },
  policy(): Promise<ArchivePolicy> { return http.get('/admin/electronic-archive') },
  confirmPolicy(body: { enabled: boolean; expected_revision: number; evidence: string }): Promise<ArchivePolicy> { return http.patch('/admin/electronic-archive', body) },
  plans(params: object): Promise<StudyPage<StudyPlan>> { return http.get('/study/plans', { params }) },
  plan(id: string): Promise<StudyPlan> { return http.get(`/study/plans/${encodeURIComponent(id)}`) },
  createPlan(body: object): Promise<StudyPlan> { return http.post('/study/plans', body) },
  updatePlan(id: string, body: object): Promise<StudyPlan> { return http.patch(`/study/plans/${encodeURIComponent(id)}`, body) },
  addItem(id: string, body: object): Promise<StudyPlan> { return http.post(`/study/plans/${encodeURIComponent(id)}/items`, body) },
  updateItem(id: string, itemId: string, body: object): Promise<StudyPlan> { return http.patch(`/study/plans/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}`, body) },
  recommend(id: string, itemId: string, q?: string): Promise<{ sources: StudySource[]; missing: string[] }> { return http.get(`/study/plans/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}/recommendations`, { params: { q: q || undefined } }) },
  drafts(id: string, itemId: string, body: RevisionPayload): Promise<StudyPlan> { return http.post(`/study/plans/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}/generate-drafts`, body) },
  planAction(id: string, action: 'submit' | 'review', body: RevisionPayload & { decision?: string }): Promise<StudyPlan> { return http.post(`/study/plans/${encodeURIComponent(id)}/${action}`, body) },
  start(id: string, itemId: string, body: RevisionPayload): Promise<StudyActivity> { return http.post(`/study/plans/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}/activity`, body) },
  activity(id: string): Promise<StudyActivity> { return http.get(`/study/activities/${encodeURIComponent(id)}`) },
  updateActivity(id: string, body: object): Promise<StudyActivity> { return http.patch(`/study/activities/${encodeURIComponent(id)}`, body) },
  activityAction(id: string, action: 'generate-minutes' | 'submit' | 'review' | 'archive', body: RevisionPayload & { decision?: string }): Promise<StudyActivity> { return http.post(`/study/activities/${encodeURIComponent(id)}/${action}`, body) },
  revisions(kind: 'plans' | 'activities', id: string): Promise<{ items: StudyRevision[] }> { return http.get(`/study/${kind}/${encodeURIComponent(id)}/revisions`) },
  history(params: object): Promise<StudyPage<StudyActivity>> { return http.get('/study/history', { params }) },
  metrics(params: object): Promise<StudyMetrics> { return http.get('/study/metrics', { params }) },
  export(id: string): Promise<StudyExport> { return http.get(`/study/activities/${encodeURIComponent(id)}/export`) },
}

export const REVIEW_LABELS: Record<ReviewStatus, string> = { draft: '草案', pending: '待审核', approved: '已通过人工审核', rejected: '已退回' }
export const EXECUTION_LABELS: Record<string, string> = { planned: '已安排', held: '已召开，纪要待补', pending: '纪要待审核', completed: '已完成', archived: '已归档', draft: '草案', rejected: '已退回' }
