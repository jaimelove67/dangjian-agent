import { http } from './http'
import type { MemberRosterItem } from './types'

export interface PersonalArchive {
  profile: MemberRosterItem | null
  max_upload_size: number
}

export const MATERIAL_CATEGORIES = {
  thought_report: '思想汇报',
  study_note: '学习心得',
  certificate: '证明材料',
  other: '其他材料',
} as const

export type MaterialCategory = keyof typeof MATERIAL_CATEGORIES
export interface PersonalMaterial {
  id: string
  title: string
  category: MaterialCategory
  description: string
  file_name: string
  file_size: number
  created_at: string
  status: 'submitted'
}

export interface MaterialList {
  items: PersonalMaterial[]
  total: number
  page: number
  page_size: number
}

export function getOwnArchive(): Promise<PersonalArchive> {
  return http.get('/member/self/archive')
}

export function listOwnMaterials(page = 1): Promise<MaterialList> {
  return http.get('/member/self/materials', { params: { page, page_size: 20 } })
}

export function submitOwnMaterial(form: { title: string; category: MaterialCategory; description: string; file: File; submission_key: string }): Promise<PersonalMaterial> {
  const data = new FormData()
  data.append('title', form.title)
  data.append('category', form.category)
  data.append('description', form.description)
  data.append('file', form.file)
  data.append('submission_key', form.submission_key)
  return http.post('/member/self/materials', data, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export function linkMemberAccount(profileId: string, username: string): Promise<MemberRosterItem> {
  return http.put(`/member/roster/${encodeURIComponent(profileId)}/account`, { username })
}

export function listSubmittedMaterials(profileId: string, page = 1): Promise<MaterialList> {
  return http.get(`/member/roster/${encodeURIComponent(profileId)}/materials`, { params: { page, page_size: 20 } })
}

export async function downloadMaterial(material: PersonalMaterial, profileId?: string): Promise<void> {
  const base = profileId ? `/member/roster/${encodeURIComponent(profileId)}/materials` : '/member/self/materials'
  const blob: Blob = await http.get(`${base}/${encodeURIComponent(material.id)}/file`, { responseType: 'blob' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = material.file_name
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function formatFileSize(size: number): string {
  return size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.ceil(size / 1024))} KB`
}
