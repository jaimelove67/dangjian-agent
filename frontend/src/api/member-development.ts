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
  // 字段级敏感分级（T-MEM-12）：密级、是否可出网 / 可向量化、本次被脱敏的第三人字段
  data_level?: string
  data_level_label?: string
  cloud_allowed?: boolean
  embedding_allowed?: boolean
  redacted_fields?: string[]
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
  data_level: string
  data_level_label: string
  cloud_allowed: boolean
  embedding_allowed: boolean
  tally: Record<
    string,
    { agree: number; disagree: number; abstain: number; voted_by_me: boolean }
  >
}
// 选优结论（拟推荐名单）与团组织推优（T-MEM-13、T-MEM-06）
export interface SelectionCandidate {
  profile_id: string
  member_name: string
  stage: MemberStage
  stage_label: string
}
/** 结论的依据快照：本轮投票的无记名汇总（只有票数与投票人数，没有投票人身份） */
export interface SelectionEvidence {
  batch_no: string
  round_no: number
  voter_count: number
  tally: Record<string, { agree: number; disagree: number; abstain: number }>
  evidence_note?: string
}
export interface SelectionRevision {
  revision: number
  action: string
  actor_id: string
  reason: string
  created_at: string
}
export type ResearchMethod = 'committee' | 'member_meeting'
export const RESEARCH_METHOD_LABELS: Record<ResearchMethod, string> = {
  committee: '支委会',
  member_meeting: '党员大会',
}
export type SelectionStatus = 'draft' | 'pending' | 'approved' | 'rejected'
export interface MemberSelection {
  id: string
  batch_no: string
  round_no: number
  org_unit_id: string
  org_name: string
  target_stage: MemberStage
  target_stage_label: string
  candidates: SelectionCandidate[]
  candidate_count: number
  basis: string
  evidence: SelectionEvidence
  research_on: string
  research_method: ResearchMethod
  research_method_label: string
  review_status: SelectionStatus
  review_status_label: string
  submitted_by: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_comment: string
  revision: number
  /** 只有审核通过的结论才是组织认定依据 */
  effective: boolean
  /** 由后端判定：待审核 + 不是自己提交的 + 有审核权限 */
  can_review: boolean
  next_step_hint: string
  notice: string
  boundary: string
  missing?: string[]
  advisories?: string[]
  revisions?: SelectionRevision[]
  data_level: string
  data_level_label: string
  cloud_allowed: boolean
  embedding_allowed: boolean
  redacted_fields: string[]
}
export interface SelectionList extends MemberPage<MemberSelection> {
  summary: Record<string, number>
  notice: string
  boundary: string
}
export interface LeagueRecommendation {
  id: string
  profile_id: string
  member_name: string
  stage: MemberStage
  stage_label: string
  org_unit_id: string
  org_name: string
  league_org: string
  recommended_on: string
  note: string
  revoked_on: string | null
  revoke_reason: string
  revision: number
  active: boolean
  age_notice: string
  notice: string
  data_level: string
  data_level_label: string
  cloud_allowed: boolean
  embedding_allowed: boolean
  redacted_fields: string[]
}
export interface LeagueRecommendationStatus {
  profile_id: string
  member_name: string
  has_record: boolean
  active_count: number
  latest_on: string | null
  latest_org: string
  age_notice: string
}
export interface LeagueRecommendationList extends MemberPage<LeagueRecommendation> {
  summary: { total: number; active: number; revoked: number }
  status: LeagueRecommendationStatus[]
  age_notice: string
  notice: string
}
export interface RosterStats {
  year: number | null
  batch_no: string | null
  org_unit_id: string | null
  by_stage: Partial<Record<MemberStage, number>>
  total: number
}
const profileURL = (id: string) => `/member-full/profiles/${encodeURIComponent(id)}`

export const memberDevelopmentApi = {
  stats(params: {
    year?: number
    batch_no?: string
    org_unit_id?: string
  }): Promise<RosterStats> {
    return http.get('/member-full/stats', { params })
  },
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
  // 选优结论（拟推荐名单）：系统不自动产生结论，名单与依据都由人填写（T-MEM-13）
  selections(params: {
    batch_no?: string
    round_no?: number
    review_status?: SelectionStatus
    page?: number
    page_size?: number
  }): Promise<SelectionList> {
    return http.get('/member-full/selections', { params })
  },
  selection(id: string): Promise<MemberSelection> {
    return http.get(`/member-full/selections/${encodeURIComponent(id)}`)
  },
  createSelection(body: {
    batch_no: string
    round_no: number
    target_stage: MemberStage
    candidate_ids: string[]
    basis: string
    research_on: string
    research_method: ResearchMethod
    reason: string
  }): Promise<MemberSelection> {
    return http.post('/member-full/selections', body)
  },
  updateSelection(
    id: string,
    body: {
      expected_revision: number
      target_stage?: MemberStage
      candidate_ids?: string[]
      basis?: string
      research_on?: string
      research_method?: ResearchMethod
      reason: string
    },
  ): Promise<MemberSelection> {
    return http.patch(`/member-full/selections/${encodeURIComponent(id)}`, body)
  },
  submitSelection(
    id: string,
    body: { expected_revision: number; reason: string },
  ): Promise<MemberSelection> {
    return http.post(`/member-full/selections/${encodeURIComponent(id)}/submit`, body)
  },
  reviewSelection(
    id: string,
    body: { expected_revision: number; decision: 'approved' | 'rejected'; reason: string },
  ): Promise<MemberSelection> {
    return http.post(`/member-full/selections/${encodeURIComponent(id)}/review`, body)
  },
  // 团组织推优台账：只登记事实，不判断年龄、不阻断选优与阶段流转（T-MEM-06）
  leagueRecommendations(params: {
    profile_id?: string
    profile_ids?: string
    page?: number
    page_size?: number
  }): Promise<LeagueRecommendationList> {
    return http.get('/member-full/league-recommendations', { params })
  },
  createLeagueRecommendation(body: {
    profile_id: string
    league_org: string
    recommended_on: string
    note: string
    reason: string
  }): Promise<LeagueRecommendation> {
    return http.post('/member-full/league-recommendations', body)
  },
  revokeLeagueRecommendation(id: string, body: { reason: string }): Promise<LeagueRecommendation> {
    return http.post(`/member-full/league-recommendations/${encodeURIComponent(id)}/revoke`, body)
  },
}
