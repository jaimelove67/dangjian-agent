<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { createAccount, listAccountOrganizations, listMemberCandidates } from '@/api/admin'
import { listTenants, type TenantRecord } from '@/api/governance'
import { ApiError } from '@/api/http'
import { memberDevelopmentApi } from '@/api/member-development'
import { ROLE_LABELS, type AccountCreated, type AccountMemberOption, type AccountOrgOption, type UserRole } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'

const organizations = ref<AccountOrgOption[]>([])
// 平台管理员的登录租户（平台租户）本身没有组织树，必须显式选一个学校租户才能开户；
// 学校管理员只看到自己租户，下拉隐藏。
const isPlatformAdmin = computed(() => session.state.user?.role === 'system_admin')
const tenants = ref<TenantRecord[]>([])
// 平台管理员不预选租户：同名/测试租户并存时，默认值选错等于白填一张表单。
const selectedTenant = ref(isPlatformAdmin.value ? '' : (session.state.user?.tenant_id ?? ''))
const tenantMissing = computed(() => isPlatformAdmin.value && !selectedTenant.value)
const loading = ref(true)
const loadError = ref<unknown>(null)
const creating = ref(false)
const createError = ref<unknown>(null)
const created = ref<AccountCreated | null>(null)
// 建号时是否已顺手关联名册档案：关联过就不再提示"去关联"。
const createdLinked = ref(false)
const form = reactive({
  username: '', name: '', role: 'member' as UserRole, org_unit_id: '',
  password: '', confirm_password: '',
})
const roles = Object.keys(ROLE_LABELS) as UserRole[]
// 本页按学校租户开户，系统管理员不属于任何学校组织；平台级账号在治理页维护。
const assignableRoles = computed(() => roles.filter(role => role !== 'system_admin'))
const ORG_LABELS = { school: '学校', department: '院系', branch: '支部' }
// 名册里尚未开户的人：选中即带出姓名与组织，建号时一并完成档案关联。
const members = ref<AccountMemberOption[]>([])
const selectedMemberId = ref('')
const selectedMember = computed(() => members.value.find((m) => m.id === selectedMemberId.value) ?? null)
const memberLocked = computed(() => Boolean(selectedMember.value?.org_unit_id))
const STAGE_LABELS: Record<string, string> = {
  applicant: '入党申请人', activist: '入党积极分子', candidate: '发展对象',
  probationary: '预备党员', member: '正式党员',
}
// 未转为预备党员之前（申请人 / 积极分子 / 发展对象）按申请人授权：只能读公开制度；
// 预备党员与正式党员同等授权——系统没有表决类权限点，二者能力差异只存在于流程。
// 反过来把积极分子当党员会放宽知识库可见范围，属于提权，不能默认。
const APPLICANT_STAGES = ['applicant', 'activist', 'candidate']
// 档案已有身份证号时，登录账号就用它：学校习惯这么登录，也免去手敲 18 位。
const ID_CARD_PATTERN = /^\d{17}[\dXx]$/
const usernameLocked = computed(() => Boolean(selectedMember.value?.id_card_masked))
// 登录账号统一用身份证号：档案缺号时先补录，别在这里编一个用户名。
const memberMissingIdCard = computed(() =>
  Boolean(selectedMember.value) && !usernameLocked.value,
)
// 开户时才发现档案缺身份证：就地补录，别让人在两个页面之间来回找人。
// 补录走的是档案接口，权限与「党员发展」里补录完全一致，不额外开后门。
const idCardDraft = reactive({
  value: '', saving: false, error: null as unknown, message: '',
})
const idCardDraftValid = computed(() => ID_CARD_PATTERN.test(idCardDraft.value.trim()))
watch(selectedMemberId, () => {
  idCardDraft.value = ''
  idCardDraft.error = null
  idCardDraft.message = ''
})

async function saveIdCard(): Promise<void> {
  const member = selectedMember.value
  const value = idCardDraft.value.trim().toUpperCase()
  if (!member || !ID_CARD_PATTERN.test(value) || idCardDraft.saving) return
  idCardDraft.saving = true
  idCardDraft.error = null
  idCardDraft.message = ''
  try {
    await memberDevelopmentApi.updateProfile(member.id, {
      id_card_no: value,
      reason: '开户前在创建账号页补录身份证号',
    })
    // 补录后重取候选：脱敏值和"能否开户"都由后端算，前端不自己拼。
    await loadMembers()
    selectedMemberId.value = member.id
    await nextTick()
    idCardDraft.message = '身份证号已补录，登录账号将使用该号码。'
  } catch (error) {
    idCardDraft.error = error
  } finally {
    idCardDraft.saving = false
  }
}
// 按任职职务预选角色：支部书记→支部管理员，党总支/院系书记→院系管理员，党委书记→学校管理员。
// 否则名册里的书记会被默认开成普通党员，登录后连审批入口都看不到。
function roleFromLeaderTitle(title: string | null | undefined): UserRole | null {
  const text = (title ?? '').trim()
  if (!text) return null
  if (text.includes('支部')) return 'branch_secretary'
  if (text.includes('总支') || text.includes('院系')) return 'department_admin'
  if (text.includes('党委')) return 'school_admin'
  return null
}
watch(selectedMember, (member) => {
  form.username = ''
  if (!member) return
  form.name = member.name
  if (member.org_unit_id) form.org_unit_id = member.org_unit_id
  const byTitle = roleFromLeaderTitle(member.leader_title)
  form.role = byTitle ?? (APPLICANT_STAGES.includes(member.current_stage) ? 'applicant' : 'member')
})
const ROLE_ORG_TYPES: Partial<Record<UserRole, AccountOrgOption['org_type']>> = {
  school_admin: 'school', department_admin: 'department', branch_secretary: 'branch',
  organizer: 'branch', member: 'branch', applicant: 'branch',
}
const availableOrganizations = computed(() => {
  const type = ROLE_ORG_TYPES[form.role]
  return organizations.value.filter((org) => !type || org.org_type === type)
})
const organizationHint = computed(() => {
  const type = ROLE_ORG_TYPES[form.role]
  return type ? `此角色需关联${ORG_LABELS[type]}。` : '可选择本单位的学校、院系或支部。'
})
const passwordValid = computed(() =>
  Array.from(form.password).length >= 8 && !!form.password.trim() &&
  new TextEncoder().encode(form.password).length <= 72,
)
const passwordsMismatch = computed(() => !!form.confirm_password && form.password !== form.confirm_password)
const usernameOk = computed(() => usernameLocked.value || ID_CARD_PATTERN.test(form.username.trim()))
const valid = computed(() =>
  usernameOk.value && !memberMissingIdCard.value && !!form.name.trim() &&
  availableOrganizations.value.some((org) => org.id === form.org_unit_id) &&
  passwordValid.value && form.password === form.confirm_password,
)

watch(availableOrganizations, (options) => {
  if (options.some((org) => org.id === form.org_unit_id)) return
  form.org_unit_id = options.find((org) => org.id === session.state.user?.org_unit_id)?.id ?? ''
})

/** 只有平台管理员会把租户显式带给接口；其他角色始终落在自己的租户。 */
const activeTenant = computed(() => (isPlatformAdmin.value ? selectedTenant.value : ''))

async function loadTenants(): Promise<void> {
  if (!isPlatformAdmin.value) return
  try {
    // 只有学校租户有组织树，院系/支部租户开户另走治理页，这里不列。
    const rows = (await listTenants()).items.filter(row => row.is_active && row.tenant_type === 'school')
    tenants.value = rows
    if (selectedTenant.value && !rows.some(row => row.id === selectedTenant.value)) selectedTenant.value = ''
    // 只有一个可选租户时替他选上；多个租户必须由人确认，避免落进同名测试租户。
    if (rows.length === 1) selectedTenant.value = rows[0].id
  } catch (error) { loadError.value = error }
}

async function loadOrganizations(): Promise<void> {
  if (tenantMissing.value) { organizations.value = []; loading.value = false; loadError.value = null; return }
  loading.value = true
  loadError.value = null
  try { organizations.value = await listAccountOrganizations(activeTenant.value || undefined) }
  catch (error) { loadError.value = error }
  finally { loading.value = false }
}

async function loadMembers(): Promise<void> {
  selectedMemberId.value = ''
  if (tenantMissing.value) { members.value = []; return }
  try { members.value = await listMemberCandidates(activeTenant.value || undefined) }
  catch { members.value = [] }
}

watch(selectedTenant, () => { void loadOrganizations(); void loadMembers() })

onMounted(async () => {
  await loadTenants()
  await Promise.all([loadOrganizations(), loadMembers()])
})

async function submit(): Promise<void> {
  if (!valid.value || creating.value) return
  creating.value = true
  createError.value = null
  created.value = null
  try {
    createdLinked.value = Boolean(selectedMemberId.value)
    created.value = await createAccount({
      ...(usernameLocked.value ? {} : { username: form.username.trim() }),
      name: form.name.trim(), role: form.role,
      org_unit_id: form.org_unit_id, password: form.password,
      ...(selectedMemberId.value ? { member_id: selectedMemberId.value } : {}),
    }, activeTenant.value || undefined)
    Object.assign(form, { username: '', name: '', password: '', confirm_password: '' })
    // 已开户的人不再出现在候选里，重新拉一次名册。
    await loadMembers()
  } catch (error) {
    createError.value = error
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div class="accounts">
    <PageHeader title="创建账号" description="为本单位人员开通登录账号，设置角色与所属组织。" />

    <section v-if="created" class="u-card success" role="status">
      <h2 class="success__title"><AppIcon name="check" :size="17" />账号创建成功</h2>
      <p>{{ created.name }}（{{ created.username }}） · {{ ROLE_LABELS[created.role] }} · {{ created.org_name }}</p>
      <p>该账号现在可使用设置的密码登录。</p>
      <p v-if="createdLinked">已同步关联党员档案，本人登录后即可查看自己的档案与提交材料。</p>
      <p v-else-if="created.role === 'member' || created.role === 'applicant'">
        党员与申请人都需在名册中关联本人档案后，才能查看档案与提交个人材料。
        <RouterLink to="/members">前往党员发展关联档案</RouterLink>
      </p>
    </section>

    <section class="u-card account-card">
      <header class="u-panel-head"><h2 class="card-title">账号信息</h2><span class="badge">仅系统管理员</span></header>
      <div v-if="isPlatformAdmin" class="field">
        <label for="account-tenant" class="field__label">开户租户</label>
        <select id="account-tenant" v-model="selectedTenant" class="select">
          <option value="">请选择开户租户</option>
          <option v-for="row in tenants" :key="row.id" :value="row.id">{{ row.name }}</option>
        </select>
        <p class="field__hint">平台管理员须先选择学校租户；组织与账号都归属该租户，切换后组织列表随之刷新。</p>
      </div>
      <LoadingBlock v-if="loading" variant="list" :rows="3" />
      <ErrorState v-else-if="loadError" :error="loadError">
        <button class="btn btn--ghost" type="button" @click="loadOrganizations">重新加载组织</button>
      </ErrorState>
      <EmptyState v-else-if="tenantMissing" title="请先选择开户租户" body="平台管理员要先选定学校租户，组织与账号都会归属该租户；切换租户后组织列表会自动刷新。" icon="people" />
      <EmptyState v-else-if="!organizations.length" title="尚未配置组织" :body="isPlatformAdmin ? '所选租户还没有登记组织。切换开户租户，或先到「管理与审核 → 组织与账号」登记组织。' : '请先由维护人员登记本单位的学校、院系或支部，再创建账号。'" icon="people" />
      <form v-else class="account-form" @submit.prevent="submit">
        <p class="account-form__intro">账号归属{{ isPlatformAdmin ? '所选租户' : '当前单位' }}。请按人员职责选择角色，所属组织决定其业务范围。</p>
        <div v-if="members.length" class="field">
          <label for="account-member" class="field__label">从党员名册选人（可选）</label>
          <select id="account-member" v-model="selectedMemberId" class="select">
            <option value="">手动填写新人员</option>
            <option v-for="m in members" :key="m.id" :value="m.id">
              {{ m.name }} · {{ m.org_name }} · {{ m.leader_title || (STAGE_LABELS[m.current_stage] ?? m.current_stage) }}{{ m.id_card_masked ? '' : '（缺身份证，暂不可开户）' }}
            </option>
          </select>
          <p class="field__hint">
            选中后姓名与所属组织以档案为准，账号创建时一并完成档案关联。
            <template v-if="selectedMember">
              已按{{ selectedMember.leader_title ? `任职职务「${selectedMember.leader_title}」` : `「${STAGE_LABELS[selectedMember.current_stage] ?? selectedMember.current_stage}」` }}推断角色为「{{ ROLE_LABELS[form.role] }}」，可按需调整。
            </template>
          </p>
        </div>
        <fieldset class="form-grid" :disabled="creating">
          <legend class="u-sr">新账号信息</legend>
          <div class="field">
            <label for="account-username" class="field__label">登录账号（身份证号）</label>
            <input id="account-username" v-model="form.username" class="input" maxlength="18" autocomplete="off" :required="!usernameLocked" :disabled="usernameLocked" :placeholder="usernameLocked ? (selectedMember?.id_card_masked ?? '') : '18 位身份证号'" :aria-invalid="!usernameLocked && !!form.username && !usernameOk" aria-describedby="username-hint" />
            <p v-if="usernameLocked" id="username-hint" class="field__hint">
              使用档案身份证号登录（{{ selectedMember?.id_card_masked }}），完整号码不出网，登录时输入完整 18 位即可。
            </p>
            <div v-else-if="memberMissingIdCard" id="username-hint" role="alert">
              <p class="field__error">
                该人员档案没有身份证号，无法开户。可在此补录，或到<RouterLink to="/members">党员发展</RouterLink>处理。
              </p>
              <div class="inline-idcard">
                <input
                  id="account-id-card"
                  v-model="idCardDraft.value"
                  class="input"
                  maxlength="18"
                  autocomplete="off"
                  placeholder="18 位身份证号"
                  aria-label="补录身份证号"
                />
                <button
                  type="button"
                  class="btn btn--quiet"
                  :disabled="!idCardDraftValid || idCardDraft.saving"
                  @click="saveIdCard"
                >
                  {{ idCardDraft.saving ? '保存中' : '补录并用于开户' }}
                </button>
              </div>
              <p v-if="idCardDraft.error" class="field__error">
                {{ idCardDraft.error instanceof ApiError ? idCardDraft.error.message : '补录失败，请重试' }}
              </p>
              <p v-if="idCardDraft.message" class="field__hint">{{ idCardDraft.message }}</p>
            </div>
            <p v-else-if="form.username && !usernameOk" id="username-hint" class="field__error" role="alert">请填写完整的 18 位身份证号，末位可为 X。</p>
            <p v-else id="username-hint" class="field__hint">18 位，末位可为 X；这就是登录账号。</p>
          </div>
          <div class="field">
            <label for="account-name" class="field__label">姓名</label>
            <input id="account-name" v-model="form.name" class="input" maxlength="50" autocomplete="off" required :readonly="Boolean(selectedMember)" aria-describedby="name-hint" />
            <p v-if="selectedMember" id="name-hint" class="field__hint">来自党员名册，如需修改请先在「党员发展」更正档案。</p>
          </div>
          <div class="field">
            <label for="account-role" class="field__label">角色</label>
            <select id="account-role" v-model="form.role" class="select" required>
              <option v-for="role in assignableRoles" :key="role" :value="role">{{ ROLE_LABELS[role] }}</option>
            </select>
          </div>
          <div class="field">
            <label for="account-org" class="field__label">所属组织</label>
            <select id="account-org" v-model="form.org_unit_id" class="select" :disabled="!availableOrganizations.length || memberLocked" required aria-describedby="org-hint">
              <option value="">请选择组织</option>
              <option v-for="org in availableOrganizations" :key="org.id" :value="org.id">{{ org.name }} · {{ ORG_LABELS[org.org_type] }}</option>
            </select>
            <p id="org-hint" class="field__hint">{{ memberLocked ? '来自党员名册，与档案保持一致。' : organizationHint }}</p>
            <p v-if="!availableOrganizations.length" class="field__error" role="status">当前没有此角色可用的组织，请先登记组织或选择其他角色。</p>
            <p v-else-if="memberLocked && !availableOrganizations.some((org) => org.id === form.org_unit_id)" class="field__error" role="status">档案所在组织的层级与所选角色不匹配，请调整角色。</p>
          </div>
          <div class="field">
            <label for="account-password" class="field__label">密码</label>
            <input id="account-password" v-model="form.password" class="input" type="password" minlength="8" maxlength="72" autocomplete="new-password" required aria-describedby="password-hint" :aria-invalid="!!form.password && !passwordValid" />
            <p id="password-hint" class="field__hint">至少 8 个字符，不能全部为空白，最多 72 字节；中文等字符会占多个字节。</p>
            <p v-if="form.password && !passwordValid" class="field__error">密码长度或内容不符合要求。</p>
          </div>
          <div class="field">
            <label for="account-confirm" class="field__label">确认密码</label>
            <input id="account-confirm" v-model="form.confirm_password" class="input" type="password" minlength="8" maxlength="72" autocomplete="new-password" required :aria-invalid="passwordsMismatch" aria-describedby="confirm-error" />
            <p id="confirm-error" class="field__error" :role="passwordsMismatch ? 'alert' : undefined">{{ passwordsMismatch ? '两次输入的密码不一致。' : '' }}</p>
          </div>
        </fieldset>
        <ErrorState v-if="createError" :error="createError" />
        <div class="form-actions">
          <button class="btn btn--primary" type="submit" :disabled="!valid || creating" :aria-busy="creating">
            <AppIcon v-if="!creating" name="plus" :size="15" />
            {{ creating ? '正在创建…' : '创建账号' }}
          </button>
          <span class="field__hint">创建后即可登录。密码不会在创建结果中显示。</span>
        </div>
      </form>
    </section>
  </div>
</template>

<style scoped>
.accounts { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-6) var(--space-6) var(--space-10); width: 100%; }
.account-card, .success { width: 100%; max-width: 960px; }
.card-title { font-size: var(--text-base); font-weight: 600; }
.account-form { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-5); }
.account-form__intro { font-size: var(--text-sm); color: var(--ink-soft); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); border: 0; padding: 0; min-width: 0; }
.field { min-width: 0; }
.form-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
/* 缺身份证时就地补录：输入框与按钮同一行，避免和下方正式表单混淆 */
.inline-idcard { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-top: var(--space-2); }
.inline-idcard .input { max-width: 220px; }
.success { padding: var(--space-4) var(--space-5); border-color: var(--ok-edge); background: var(--ok-wash); overflow-wrap: anywhere; }
.success__title { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); font-size: var(--text-base); color: var(--ok-ink); }
.success p { margin-top: var(--space-2); font-size: var(--text-sm); }
.success a { color: var(--accent); text-decoration: underline; }
@media (max-width: 640px) {
  .accounts { padding: var(--space-4) var(--space-4) var(--space-8); }
  .form-grid { grid-template-columns: minmax(0, 1fr); }
  .account-form { padding: var(--space-4); }
}
</style>
