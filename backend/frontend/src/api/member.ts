import { http } from './http'
import type {
  QualificationCheckRequest,
  QualificationResult,
  TodoSuggestionsResponse,
  TransitionSuggestion,
  MemberCreateRequest,
  MemberOrgOption,
  MemberRosterItem,
  MemberRosterResponse,
  RosterImportReport,
} from './types'

/**
 * app/api/v1/member.py
 *
 * 三项规则接口只返回校验/建议结果；名册查询和人工登记另行提供。
 * 阶段流转本身必须由具备权限的组织人员经人工途径操作，接口不下结论
 * （见 app/schemas/member.py::DECISION_BOUNDARY_NOTE）。
 *
 */

export function listMembers(params: { page?: number; page_size?: number; year?: number; batch_no?: string; org_unit_id?: string; include_transferred?: boolean } = {}): Promise<MemberRosterResponse> {
  return http.get('/member/roster', { params })
}

export function listMemberOrganizations(): Promise<MemberOrgOption[]> {
  return http.get('/member/org-units')
}

export function createMember(payload: MemberCreateRequest): Promise<MemberRosterItem> {
  return http.post('/member/roster', payload)
}

export function checkQualification(
  payload: QualificationCheckRequest,
): Promise<QualificationResult> {
  return http.post('/member/qualification-check', payload)
}

export function getTransitionSuggestion(payload: QualificationCheckRequest): Promise<TransitionSuggestion> {
  return http.post('/member/transition-suggestion', payload)
}

export function getTodoSuggestions(payload: {
  current_stage: QualificationCheckRequest['current_stage']
  materials?: string[]
  days_in_stage?: number
}): Promise<TodoSuggestionsResponse> {
  return http.post('/member/todo-suggestions', payload)
}

/**
 * 名册模板 / 导出 / 导入（T-DATA-06）：
 * 模板与导出按当前账号的组织权限生成；导入先 dry_run=true 预检，
 * 由使用者确认报告后再 dry_run=false 落库，避免"点一下就批量写台账"。
 */
export function downloadRosterTemplate(): Promise<Blob> {
  return http.get('/member/roster/template', { responseType: 'blob' })
}

export function downloadRoster(params: { year?: number; batch_no?: string; org_unit_id?: string; include_transferred?: boolean } = {}): Promise<Blob> {
  return http.get('/member/roster/export', { params, responseType: 'blob' })
}

export function importRoster(
  file: File,
  sourceNote: string,
  dryRun: boolean,
): Promise<RosterImportReport> {
  const data = new FormData()
  data.append('file', file)
  data.append('source_note', sourceNote)
  data.append('dry_run', dryRun ? 'true' : 'false')
  return http.post('/member/roster/import', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
