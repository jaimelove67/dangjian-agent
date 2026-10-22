import { http } from './http'
import type {
  AccountCreated,
  AccountCreateRequest,
  AccountMemberOption,
  AccountOrgOption,
} from './types'

const scoped = (tenantId?: string) => (tenantId ? { params: { tenant_id: tenantId } } : {})

/** 省略 tenantId 时按登录租户取；平台管理员可显式指定租户（跨租户开户）。 */
export function listAccountOrganizations(tenantId?: string): Promise<AccountOrgOption[]> {
  return http.get('/admin/org-units', scoped(tenantId))
}

/** 尚未关联账号的党员档案：开户时选人，姓名与组织由档案带出。 */
export function listMemberCandidates(tenantId?: string): Promise<AccountMemberOption[]> {
  return http.get('/admin/member-candidates', scoped(tenantId))
}

export function createAccount(payload: AccountCreateRequest, tenantId?: string): Promise<AccountCreated> {
  return http.post('/admin/users', payload, scoped(tenantId))
}
