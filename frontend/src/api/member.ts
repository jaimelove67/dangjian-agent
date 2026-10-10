import { http } from './http'
import type {
  MemberCreateRequest,
  MemberRosterItem,
  MemberRosterResponse,
  QualificationCheckRequest,
  QualificationResult,
  TodoSuggestionsResponse,
  TransitionSuggestion,
  TransitionSuggestionRequest,
} from './types'

/**
 * app/api/v1/member.py
 *
 * 名册为真实查询接口；资格校验 / 流转建议 / 待办建议为**纯计算**接口：
 * 只返回校验或建议结果，不落库、不改状态。阶段流转本身必须由具备权限的
 * 组织人员经人工途径操作，接口不下结论（见 app/schemas/member.py::DECISION_BOUNDARY_NOTE）。
 */

/** 培养对象名册（当前租户，在阶段天数由后端按日期实时计算） */
export function listRoster(): Promise<MemberRosterResponse> {
  return http.get('/member/roster')
}

/** 新增培养对象（数据录入，不构成组织认定） */
export function createMember(payload: MemberCreateRequest): Promise<MemberRosterItem> {
  return http.post('/member/roster', payload)
}

export function checkQualification(
  payload: QualificationCheckRequest,
): Promise<QualificationResult> {
  return http.post('/member/qualification-check', payload)
}

export function getTransitionSuggestion(
  payload: TransitionSuggestionRequest,
): Promise<TransitionSuggestion> {
  return http.post('/member/transition-suggestion', payload)
}

export function getTodoSuggestions(payload: {
  current_stage: QualificationCheckRequest['current_stage']
}): Promise<TodoSuggestionsResponse> {
  return http.post('/member/todo-suggestions', payload)
}
