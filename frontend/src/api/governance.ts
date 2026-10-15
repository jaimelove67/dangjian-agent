import { http } from './http'
import type { UserRole } from './types'

export interface TenantRecord {
  id: string; name: string; tenant_type: string; parent_id: string | null
  is_active: boolean; config_version: number
}
export interface OrgRecord {
  id: string; name: string; org_type: 'school' | 'department' | 'branch'
  parent_id: string | null; is_active: boolean; path: string
}
export interface UserRecord {
  id: string; username: string; name: string; role: UserRole
  org_unit_id: string | null; is_active: boolean
}
export interface Approval { status: 'pending' | 'confirmed' | 'revoked'; evidence: string }
export interface GovernanceValues {
  registration: Approval; organization_approval: Approval; it_approval: Approval; secrecy_approval: Approval
  pilot_scope: string
  model_policy: {
    external_enabled: boolean; internal_approved: boolean; local_sensitive_enabled: boolean
    allowed_hosts: string[]; local_hosts: string[]; evidence: string
  }
  model_routes: Record<string, string>; scoring_weights: Record<string, number>
  prompt_versions: Record<string, 'v1' | 'v2'>
  retention: { file_days: number; audit_days: number; physical_purge: string; evidence: string }
}
export interface GovernanceConfig {
  version: number; values: GovernanceValues
  admission: { status: string; pending: string[]; electronic_archive: string; notice: string }
  archive_policy?: { enabled?: boolean; revision?: number; evidence?: string }
  model_catalog: { id: string; type: string; deployment: string; provider: string }[]
}
export interface ReviewRecord {
  id: string; source_kind: string; source_id: string; source_version: string
  status: string; effective_status: string; stale: boolean; submitted_by: string
  reviewed_by: string | null; reviewed_at: string | null; opinion: string | null
  created_at: string; snapshot?: Record<string, unknown>
}
export interface JobRecord {
  id: string; kind: string; status: string; attempts: number; max_attempts: number
  created_at: string; error_code: string | null; result: { processed?: number } | null
}
export interface AuditRecord {
  id: string; user_id: string; action: string; resource_type: string; resource_id: string | null
  data_level: string; result: string; request_id: string; created_at: string; ip_address: string | null
}
export interface Operations {
  jobs: Record<string, number>; reviews: Record<string, number>
  model_usage: { type: string; result: string; calls: number; mean_seconds: number }[]
  alerts: { action: string; result: string; count: number; window_hours: number }[]
  audit_spool_pending: number
}
export interface NotificationChannel {
  name: string; description: string; configured: boolean
}
export interface NotificationChannels {
  items: NotificationChannel[]; events: string[]; routes: Record<string, string[]>
  max_attempts: number
}
export interface NotificationDelivery {
  id: string; event: string; channel: string; recipient_id: string | null; subject: string
  status: string; attempts: number; last_error: string | null
  delivered_at: string | null; created_at: string | null
}
export interface NotificationDispatch {
  results: { channel: string; status: string; attempts: number; skipped: boolean; error: string | null }[]
}
const target = (tenant_id?: string) => tenant_id ? { tenant_id } : {}
export const listTenants = () => http.get<never, {items: TenantRecord[]}>('/admin/tenants')
export const listOrgs = (tenant_id?: string) =>
  http.get<never, {items: OrgRecord[]}>('/admin/organizations', { params: target(tenant_id) })
export const listUsers = (tenant_id?: string) =>
  http.get<never, {items: UserRecord[]}>('/admin/users', { params: target(tenant_id) })
export const createTenant = (body: {name: string; tenant_type: string; parent_id: string}) =>
  http.post<never, TenantRecord>('/admin/tenants', body)
export const updateTenant = (id: string, body: {name?: string; is_active?: boolean}) =>
  http.patch<never, TenantRecord>('/admin/tenants/' + encodeURIComponent(id), body)
export const saveOrg = (id: string | null, body: object, tenant_id?: string) =>
  id ? http.patch('/admin/organizations/' + encodeURIComponent(id), body, {params: target(tenant_id)})
    : http.post('/admin/organizations', body, {params: target(tenant_id)})
export const saveUser = (id: string | null, body: object, tenant_id?: string) =>
  id ? http.patch('/admin/users/' + encodeURIComponent(id), body, {params: target(tenant_id)})
    : http.post('/admin/users', body, {params: target(tenant_id)})
export const getGovernance = () => http.get<never, GovernanceConfig>('/admin/governance')
export const saveGovernance = (body: {expected_version: number; reason: string; values: GovernanceValues}) =>
  http.patch<never, GovernanceConfig>('/admin/governance', body)
export const listReviews = (page = 1) =>
  http.get<never, {items: ReviewRecord[]; has_more: boolean; total: number}>('/admin/reviews', {params: {page}})
export const getReview = (id: string) =>
  http.get<never, ReviewRecord>('/admin/reviews/' + encodeURIComponent(id))
export const submitReview = (body: {source_kind: string; source_id: string; year: number; round: number}) =>
  http.post<never, ReviewRecord>('/admin/reviews', body)
export const decideReview = (id: string, body: {decision: string; source_version: string; opinion: string}) =>
  http.post<never, ReviewRecord>('/admin/reviews/' + encodeURIComponent(id) + '/decision', body)
export const getOperations = () => http.get<never, Operations>('/admin/operations')
export const listJobs = () => http.get<never, {items: JobRecord[]}>('/admin/jobs')
export const queueJob = (body: {kind: string; dedup_key: string; document_ids: string[]}) =>
  http.post<never, JobRecord>('/admin/jobs', body)
export const listAudit = (params: Record<string, string | number>) =>
  http.get<never, {items: AuditRecord[]; total: number}>('/admin/audit-logs', {params})
export const saveArchivePolicy = (body: {enabled: boolean; expected_revision: number; evidence: string}) =>
  http.patch('/admin/electronic-archive', body)
export const listNotificationChannels = () =>
  http.get<never, NotificationChannels>('/admin/notification-channels')
export const listNotificationDeliveries = (params: Record<string, string | number> = {}) =>
  http.get<never, {items: NotificationDelivery[]; statuses: string[]}>('/admin/notification-deliveries', {params})
export const dispatchNotification = (body: {
  event: string; subject: string; body: string; dedup_key?: string; channels?: string[]
}) => http.post<never, NotificationDispatch>('/admin/notifications/dispatch', body)
