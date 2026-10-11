import { http } from './http'
import type { AccountCreated, AccountCreateRequest, AccountOrgOption } from './types'

/** 仅 system_admin 可调用，组织和新账号均限当前租户。 */
export function listAccountOrganizations(): Promise<AccountOrgOption[]> {
  return http.get('/admin/org-units')
}

export function createAccount(payload: AccountCreateRequest): Promise<AccountCreated> {
  return http.post('/admin/users', payload)
}
