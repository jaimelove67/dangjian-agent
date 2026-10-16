import { http } from './http'
import type { MemberStage, RelationStatus } from './types'

/**
 * 组织关系接转（T-MEM-14）。
 *
 * 接转是"组织关系移动"这件独立的事，不是发展阶段流转：正式党员转出后仍然是正式党员。
 * 因此这里没有"阶段推进"的接口，只有登记、回执与作废——而且转出**开了介绍信不等于转出
 * 完成**，必须等回执（settle）；到期未回执只是提示，系统不自动判定失败。
 */

export interface TransferRevision {
  revision: number
  action: string
  actor_id: string
  reason: string
  created_at: string
}

export interface MemberTransferRecord {
  id: string
  direction: 'in' | 'out'
  direction_label: string
  status: 'pending' | 'settled' | 'revoked'
  status_label: string
  profile_id: string
  member_name: string
  stage: MemberStage
  stage_label: string
  org_unit_id: string
  org_name: string
  counterpart_org: string
  letter_no: string
  issued_on: string
  valid_until: string
  days_left: number
  overdue: boolean
  overdue_notice: string
  settled_on: string | null
  receipt_no: string
  note: string
  revoked_on: string | null
  revoke_reason: string
  created_at: string
  revision: number
  /** 该档案当前的组织关系状态（由接转台账推导） */
  state: RelationStatus
  state_label: string
  notice?: string
  created_profile?: boolean
  /** 转入时按阶段算出的档案清单与缺项（缺项只提示，不阻断登记） */
  archive?: { check_id: string; required: string[]; missing: string[] }
  history?: TransferRevision[]
  boundary?: string
}

export interface TransferSummary {
  pending_out: number
  pending_in: number
  overdue: number
  settled_out: number
  settled_in: number
  revoked: number
  this_year_out: number
  this_year_in: number
  pending_total: number
}

export interface TransferLedger {
  items: MemberTransferRecord[]
  total: number
  page: number
  page_size: number
  summary: TransferSummary
  notice: string
  boundary?: string
}

export interface TransferCreateBody {
  direction: 'in' | 'out'
  profile_id?: string
  name?: string
  org_unit_id?: string
  current_stage?: 'probationary' | 'member'
  stage_joined_on?: string
  counterpart_org: string
  letter_no: string
  issued_on: string
  valid_until?: string
  note?: string
  reason: string
}

export const memberTransferApi = {
  list(params: {
    direction?: 'in' | 'out'
    status?: 'pending' | 'settled' | 'revoked'
    org_unit_id?: string
    profile_id?: string
    overdue?: boolean
    page?: number
    page_size?: number
  }): Promise<TransferLedger> {
    return http.get('/member-full/transfers', { params })
  },
  create(body: TransferCreateBody): Promise<MemberTransferRecord> {
    return http.post('/member-full/transfers', body)
  },
  detail(id: string): Promise<MemberTransferRecord> {
    return http.get(`/member-full/transfers/${encodeURIComponent(id)}`)
  },
  settle(
    id: string,
    body: { settled_on?: string; receipt_no?: string; note?: string; reason: string },
  ): Promise<MemberTransferRecord> {
    return http.post(`/member-full/transfers/${encodeURIComponent(id)}/settle`, body)
  },
  revoke(id: string, body: { reason: string }): Promise<MemberTransferRecord> {
    return http.post(`/member-full/transfers/${encodeURIComponent(id)}/revoke`, body)
  },
}
