import { http } from './http'
import type {
  QualificationCheckRequest,
  QualificationResult,
  TodoSuggestionsResponse,
  TransitionSuggestion,
} from './types'

/**
 * app/api/v1/member.py
 *
 * 三项均为**纯计算**接口：只返回校验/建议结果，不落库、不改状态。
 * 阶段流转本身必须由具备权限的组织人员经人工途径操作，接口不下结论
 * （见 app/schemas/member.py::DECISION_BOUNDARY_NOTE）。
 *
 * ⚠️ 后端没有成员名册接口，名册页使用 mock 数据并显式标注。
 */

export function checkQualification(
  payload: QualificationCheckRequest,
): Promise<QualificationResult> {
  return http.post('/member/qualification-check', payload)
}

export function getTransitionSuggestion(payload: {
  current_stage: QualificationCheckRequest['current_stage']
  materials: string[]
  days_in_stage: number
}): Promise<TransitionSuggestion> {
  return http.post('/member/transition-suggestion', payload)
}

export function getTodoSuggestions(payload: {
  current_stage: QualificationCheckRequest['current_stage']
}): Promise<TodoSuggestionsResponse> {
  return http.post('/member/todo-suggestions', payload)
}
