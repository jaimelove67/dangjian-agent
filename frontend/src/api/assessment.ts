import { http } from './http'

export type AssessmentSource = 'organizations' | 'members' | 'member_materials' | 'meetings' | 'studies' | 'documents' | 'manual'
export type AssessmentReview = 'pending' | 'approved' | 'returned'
export interface AssessmentOrg { id: string; name: string; org_type: string }
export interface SourceOptions {
  measure: 'count' | 'attendance_rate' | 'material_rate' | 'sum'
  stages: string[]; org_types: string[]; required_materials: string[]; document_ids: string[]
}
export interface IndicatorInput {
  org_unit_id: string; year: number; code: string; name: string; requirement: string
  source: AssessmentSource; formula: 'count' | 'percentage' | 'sum'; source_options: SourceOptions
  target: number; comparison: 'gte' | 'lte' | 'eq'; unit: string; period_start: string; period_end: string
  required_evidence: string[]; confirmed: boolean; confirmation_note: string
  expected_version: number; effective_from?: string
}
export interface AssessmentIndicator extends Omit<IndicatorInput, 'expected_version'> {
  id: string; version: number; active: boolean; school_org_id: string; created_by: string
}
export interface SourceReference {
  source: AssessmentSource; record_id: string; version: string; org_unit_id: string
  occurred_on: string; facts: Record<string, string>
}
export interface AssessmentEvidence {
  id: string; org_unit_id: string; indicator_code: string; requirement_key: string
  revision: number; review_status: AssessmentReview; status: string; doc_id?: string; title?: string
  source_version?: string; content_revision?: number; reviewed_by?: string; review_opinion?: string
  created_by?: string
}
export interface AssessmentResult {
  code: string; name: string; rule_id: string; rule_version: number; requirement: string; source: AssessmentSource
  formula: string; actual: number | null; target: number; satisfied: boolean | null; unit: string
  period_start: string; period_end: string; sources: SourceReference[]; evidence: AssessmentEvidence[]; missing: string[]
}
export interface TaskInput {
  org_unit_id: string; year: number; indicator_code: string; title: string; owner_id: string
  due_date: string; declared_progress: number; manual_value: number | null; completed_on: string | null; basis: string
}
export interface AssessmentTask extends TaskInput {
  id: string; revision: number; progress: number; complete: boolean; overdue: boolean; due_soon: boolean
  missing: string[]; review_status: AssessmentReview; created_by: string; review_opinion: string
}
export interface AssessmentRun {
  id: string; fingerprint: string; engine_version: string; created_at: string; created_by: string
  review_status: AssessmentReview; revision: number; review_opinion: string
  stale?: boolean
}
export interface AssessmentRunDetail extends AssessmentRun {
  results: AssessmentResult[]; stale: boolean; notice: string
}
export interface AssessmentPlan {
  id: string; run_id: string; content: string | null; year: number; version: number; revision: number
  review_status: AssessmentReview; created_by: string; review_opinion: string; stale: boolean
}
export interface AssessmentPolicy {
  version: number; archive_version: number; archive_enabled: boolean; reminder_advance_days: number; confirmation_note: string
}
export interface AssessmentReminder {
  id: string; task_id: string; kind: string; status: 'open' | 'handled' | 'resolved'; handling_note: string
}
export interface AssessmentWorkspace {
  org_unit_id: string; org_name: string; school_org_id: string; year: number; as_of: string
  fingerprint: string; engine_version: string; indicators: AssessmentIndicator[]; results: AssessmentResult[]
  tasks: AssessmentTask[]; evidence: AssessmentEvidence[]; owners: { id: string; name: string }[]
  runs: AssessmentRun[]; plan: AssessmentPlan | null; policy: AssessmentPolicy; reminders: AssessmentReminder[]
  needs_recalculation: boolean; notices: string[]
}

export const assessmentApi = {
  organizations: () => http.get<never, AssessmentOrg[]>('/assessment/org-units'),
  workspace: (org_unit_id: string, year: number) => http.get<never, AssessmentWorkspace>('/assessment/workspace', { params: { org_unit_id, year } }),
  indicator: (body: IndicatorInput) => http.post<never, AssessmentIndicator>('/assessment/indicators', body),
  task: (body: TaskInput, id?: string, expected_revision?: number) => id
    ? http.put<never, AssessmentTask>(`/assessment/tasks/${encodeURIComponent(id)}`, { ...body, expected_revision })
    : http.post<never, AssessmentTask>('/assessment/tasks', body),
  evidence: (body: { org_unit_id: string; year: number; indicator_code: string; requirement_key: string; doc_id: string }) => http.post('/assessment/evidence', body),
  recalculate: (org_unit_id: string, year: number) => http.post<never, AssessmentRun>('/assessment/recalculate', { org_unit_id, year }),
  run: (id: string) => http.get<never, AssessmentRunDetail>(`/assessment/runs/${encodeURIComponent(id)}`),
  review: (kind: string, id: string, revision: number, status: 'approved' | 'returned', opinion: string) => http.post(`/assessment/${kind}/${encodeURIComponent(id)}/review`, { expected_revision: revision, status, opinion }),
  plan: (run_id: string, expected_version: number, content?: string) => http.post('/assessment/plans', { run_id, expected_version, ...(content ? { content } : {}) }),
  policy: (body: AssessmentPolicy & { org_unit_id: string }) => http.put('/assessment/policy', {
    org_unit_id: body.org_unit_id, archive_enabled: body.archive_enabled, reminder_advance_days: body.reminder_advance_days,
    confirmation_note: body.confirmation_note, expected_version: body.version, expected_archive_version: body.archive_version,
  }),
  sync: (org_unit_id: string, year: number) => http.post('/assessment/reminders/sync', { org_unit_id, year }),
  handle: (id: string, note: string) => http.post(`/assessment/reminders/${encodeURIComponent(id)}/handle`, { note }),
  archive: (id: string) => http.post(`/assessment/runs/${encodeURIComponent(id)}/archive`),
  export: (id: string) => http.post<never, Blob>(`/assessment/runs/${encodeURIComponent(id)}/export`, null, { responseType: 'blob' }),
  source: (reference: SourceReference, org_unit_id: string, year: number) => http.get<never, SourceReference>(`/assessment/sources/${reference.source}/${encodeURIComponent(reference.record_id)}`, { params: { org_unit_id, year } }),
}
