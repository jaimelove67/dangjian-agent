import { http } from './http'
import type { MemberStage } from './types'

export interface MemberPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
export interface MemberBatch {
  id: string
  year: number
  batch_no: string
  label: string
  org_unit_id: string
  org_name: string
  member_count: number
  is_active: boolean
}
export interface MaterialRevision {
  revision: number
  action: string
  actor_id: string
  created_at: string
  reason: string
  snapshot: { review_status?: string; note?: string }
}
export interface MemberMaterial {
  id?: string
  legacy_material?: boolean
  material_type: string
  file_version?: string
  stage?: MemberStage
  submit_date?: string | null
  review_status: 'pending' | 'approved' | 'rejected'
  note: string
  review_history?: MaterialRevision[]
}
export interface StageHistory {
  id: string
  from_stage: MemberStage
  to_stage: MemberStage
  decision_date: string
  basis: string
  opinion: string
  decided_by: string
}
export type CultivationCategory =
  'theory_test' | 'volunteer_service' | 'academic' | 'public_review' | 'party_review' | 'other'
export const CULTIVATION_LABELS: Record<CultivationCategory, string> = {
  theory_test: '理论学习',
  volunteer_service: '志愿服务',
  academic: '学业表现',
  public_review: '群众评议',
  party_review: '党员评议',
  other: '其他培养记录',
}
export interface CultivationRecord {
  id: string
  category: CultivationCategory
  score: number | string | null
  period: string
  source_note: string
  verified_by: string | null
  verified_at: string | null
  is_risk: boolean
  risk_note: string
}
export interface MemberProfile {
  id: string
  name: string
  org_name: string
  org_unit_id: string | null
  current_stage: MemberStage
  stage_joined_on: string
  year: number | null
  batch_no: string | null
  is_active: boolean
  pending: number
  materials: MemberMaterial[]
  cultivation: CultivationRecord[]
  stage_history: StageHistory[]
  boundary: string
}
export interface MemberReminder {
  id: string
  profile_id: string
  kind: string
  due_on: string
  status: 'open' | 'closed' | 'skipped'
  note: string
  processed_at: string | null
}
export const REMINDER_LABELS: Record<string, string> = {
  training_period: '培养期到期',
  training_period_advance: '培养期提前提醒',
  material_submission: '材料提交',
  material_submission_advance: '材料提交提前提醒',
  meeting_discussion: '会议讨论',
  meeting_discussion_advance: '会议讨论提前提醒',
  probationary_expiration: '预备期到期',
  probationary_expiration_advance: '预备期提前提醒',
}
export interface MemberScoring {
  year: number | null
  weighted_score: number | null
  rule_version: string
  disclaimer: string
  missing: string[]
  dimensions: Record<
    string,
    {
      value: number | null
      status: string
      weight: number
      evidence: { source_id: string; period: string; note: string }[]
    }
  >
  risks: { source_id: string; risk_note: string }[]
}
export interface ArchiveCheckResult {
  check_id: string
  checked_at: string
  rule_version: string
  note: string
  result: { required_for: string; missing: string[]; irregular: string[]; risks: string[] }
}
export interface VoteSummary {
  batch_no: string
  round_no: number
  voter_count: number
  note: string
  tally: Record<string, { agree: number; disagree: number; abstain: number; voters: string[] }>
}
const profileURL = (id: string) => `/member-full/profiles/${encodeURIComponent(id)}`

export const memberDevelopmentApi = {
  batches(params: {
    year?: number
    page?: number
    page_size?: number
  }): Promise<MemberPage<MemberBatch>> {
    return http.get('/member-full/batches', { params })
  },
  createBatch(body: {
    year: number
    batch_no: string
    label: string
    org_unit_id: string
    reason: string
  }): Promise<MemberBatch> {
    return http.post('/member-full/batches', body)
  },
  profile(id: string): Promise<MemberProfile> {
    return http.get(profileURL(id))
  },
  updateProfile(
    id: string,
    body: { year: number; batch_no: string; reason: string },
  ): Promise<MemberProfile> {
    return http.patch(profileURL(id), body)
  },
  addMaterial(
    id: string,
    body: {
      material_type: string
      file_version: string
      submit_date: string | null
      reason: string
    },
  ): Promise<MemberMaterial> {
    return http.post(`${profileURL(id)}/materials`, body)
  },
  reviewMaterial(
    id: string,
    body: { review_status: 'approved' | 'rejected'; note: string; reason: string },
  ): Promise<MemberMaterial> {
    return http.post(`/member-full/materials/${encodeURIComponent(id)}/review`, body)
  },
  transition(
    id: string,
    body: { target_stage: MemberStage; decision_date: string; basis: string; opinion: string },
  ): Promise<MemberProfile> {
    return http.post(`${profileURL(id)}/transition`, body)
  },
  cultivation(
    id: string,
    body: {
      profile_id: string
      category: CultivationCategory
      score: number | null
      period: string
      source_note: string
      is_risk: boolean
      risk_note: string
    },
  ): Promise<CultivationRecord> {
    return http.post(`${profileURL(id)}/cultivation`, body)
  },
  syncReminders(id: string): Promise<{ created: number; notice: string }> {
    return http.post(`${profileURL(id)}/sync-reminders`)
  },
  reminders(params: {
    status?: string
    page: number
    page_size: number
  }): Promise<MemberPage<MemberReminder>> {
    return http.get('/member-full/reminders', { params })
  },
  resolveReminder(
    id: string,
    body: { status: 'closed' | 'skipped'; note: string },
  ): Promise<MemberReminder> {
    return http.post(`/member-full/reminders/${encodeURIComponent(id)}/resolve`, body)
  },
  scoring(profile_id: string, year: number): Promise<MemberScoring> {
    return http.post('/member-full/scoring', { profile_id, year })
  },
  archiveCheck(
    profile_id: string,
    materials_note: Record<string, string>,
  ): Promise<ArchiveCheckResult> {
    return http.post('/member-full/archive-check', { profile_id, materials_note })
  },
  submitVotes(body: {
    batch_no: string
    round_no: number
    votes: { profile_id: string; vote: 'agree' | 'disagree' | 'abstain'; comment: string }[]
  }): Promise<{ recorded: number }> {
    return http.post('/member-full/votes', body)
  },
  voteSummary(batch_no: string, round_no: number): Promise<VoteSummary> {
    return http.get('/member-full/votes/summary', { params: { batch_no, round_no } })
  },
}
