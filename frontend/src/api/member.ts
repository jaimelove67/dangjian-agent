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
} from './types'

/**
 * app/api/v1/member.py
 *
 * 三项规则接口只返回校验/建议结果；名册查询和人工登记另行提供。
 * 阶段流转本身必须由具备权限的组织人员经人工途径操作，接口不下结论
 * （见 app/schemas/member.py::DECISION_BOUNDARY_NOTE）。
 *
 */

export function listMembers(params: { page?: number; page_size?: number } = {}): Promise<MemberRosterResponse> {
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
