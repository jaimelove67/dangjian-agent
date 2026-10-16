import { http } from './http'
import type { MemberStage } from './types'

/**
 * 上级党组织审批 / 备案报送（T-MEM-11）。
 *
 * 这里没有"审批通过"这种接口：系统没有上级党组织的登录身份，做不出也不该做出"由系统批准
 * 入党"的结论。接口只有三个动作——**登记报送**（把材料报出去这一事实）、**回填批复**
 * （上级的结论，含批复文号）、**作废**（报错事项）。回填批复不改动党员阶段：阶段仍由授权
 * 人员在人工流转里按程序办理。
 */

export type UpperItemKey =
  | 'activist_record'
  | 'candidate_record'
  | 'probationary_approval'
  | 'member_approval'

export type UpperResult = 'agreed' | 'rejected' | 'supplement'

export interface UpperReportRevision {
  revision: number
  action: string
  actor_id: string
  reason: string
  created_at: string
}

export interface UpperReportRecord {
  id: string
  item: UpperItemKey
  item_label: string
  kind: 'record' | 'approval'
  kind_label: string
  /** 依据条文由后端单源给出：界面不自己写一套 */
  basis: string
  report_to: string
  status: 'submitted' | 'settled' | 'revoked'
  status_label: string
  profile_id: string
  member_name: string
  stage: MemberStage
  stage_label: string
  org_unit_id: string
  org_name: string
  upper_org: string
  letter_no: string
  submitted_on: string
  /** 随报材料**清单**（与阶段材料要求同一来源），不是材料原件 */
  materials: string[]
  material_count: number
  result: UpperResult | ''
  result_label: string
  decided_on: string | null
  reply_no: string
  decide_note: string
  /** 审批类事项才有批复时限；备案类为 null（细则未统一规定，不编数字） */
  deadline: string | null
  days_left: number | null
  overdue: boolean
  /** 临近审批时限（配置的提前提示天数内）：提前提醒，而不是到期才发现 */
  due_soon: boolean
  overdue_notice: string
  no_deadline_note: string
  note: string
  revoked_on: string | null
  revoke_reason: string
  created_at: string
  notice?: string
  boundary?: string
  history?: UpperReportRevision[]
}

export interface UpperItemCatalog {
  item: UpperItemKey
  label: string
  kind: 'record' | 'approval'
  kind_label: string
  stage: MemberStage
  stage_label: string
  basis: string
  report_to: string
  materials: string[]
}

export interface UpperReportSummary {
  pending: number
  pending_approval: number
  overdue: number
  supplement: number
  settled: number
  revoked: number
  this_year: number
}

export interface UpperReportLedger {
  items: UpperReportRecord[]
  total: number
  page: number
  page_size: number
  summary: UpperReportSummary
  items_catalog: UpperItemCatalog[]
  notice: string
  boundary?: string
}

export interface UpperReportCreateBody {
  profile_id: string
  item: UpperItemKey
  upper_org: string
  letter_no?: string
  submitted_on: string
  note?: string
  reason: string
}

export interface UpperReportSettleBody {
  result: UpperResult
  decided_on?: string
  reply_no?: string
  decide_note?: string
  reason: string
}

export const upperReportApi = {
  list(params: {
    item?: UpperItemKey
    kind?: 'record' | 'approval'
    status?: 'submitted' | 'settled' | 'revoked'
    org_unit_id?: string
    profile_id?: string
    overdue?: boolean
    page?: number
    page_size?: number
  }): Promise<UpperReportLedger> {
    return http.get('/member-full/upper-reports', { params })
  },
  create(body: UpperReportCreateBody): Promise<UpperReportRecord> {
    return http.post('/member-full/upper-reports', body)
  },
  detail(id: string): Promise<UpperReportRecord> {
    return http.get(`/member-full/upper-reports/${encodeURIComponent(id)}`)
  },
  settle(id: string, body: UpperReportSettleBody): Promise<UpperReportRecord> {
    return http.post(`/member-full/upper-reports/${encodeURIComponent(id)}/settle`, body)
  },
  revoke(id: string, body: { reason: string }): Promise<UpperReportRecord> {
    return http.post(`/member-full/upper-reports/${encodeURIComponent(id)}/revoke`, body)
  },
  /** 导出台账（Excel）：不含材料原件、也不含政治审查材料内容 */
  downloadLedger(): Promise<Blob> {
    return http.get('/member-full/upper-reports/export', { responseType: 'blob' })
  },
}
