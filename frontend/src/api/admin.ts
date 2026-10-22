import { http } from './http'
import type { AccountCreated, AccountCreateRequest, AccountOrgOption } from './types'

/** 省略 tenantId 时按登录租户取；平台管理员可显式指定租户（跨租户开户）。 */
export function listAccountOrganizations(tenantId?: string): Promise<AccountOrgOption[]> {
  return http.get('/admin/org-units', { params: tenantId ? { tenant_id: tenantId } : {} })
}

export function createAccount(payload: AccountCreateRequest, tenantId?: string): Promise<AccountCreated> {
  return http.post('/admin/users', payload, { params: tenantId ? { tenant_id: tenantId } : {} })
}
