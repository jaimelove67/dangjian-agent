<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { createAccount, listAccountOrganizations } from '@/api/admin'
import { ROLE_LABELS, type AccountCreated, type AccountOrgOption, type UserRole } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'

const organizations = ref<AccountOrgOption[]>([])
const loading = ref(true)
const loadError = ref<unknown>(null)
const creating = ref(false)
const createError = ref<unknown>(null)
const created = ref<AccountCreated | null>(null)
const form = reactive({
  username: '', name: '', role: 'member' as UserRole, org_unit_id: '',
  password: '', confirm_password: '',
})
const roles = Object.keys(ROLE_LABELS) as UserRole[]
const ORG_LABELS = { school: '学校', department: '院系', branch: '支部' }
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
const valid = computed(() =>
  !!form.username.trim() && !/\s/u.test(form.username.trim()) && !!form.name.trim() &&
  availableOrganizations.value.some((org) => org.id === form.org_unit_id) &&
  passwordValid.value && form.password === form.confirm_password,
)

watch(availableOrganizations, (options) => {
  if (options.some((org) => org.id === form.org_unit_id)) return
  form.org_unit_id = options.find((org) => org.id === session.state.user?.org_unit_id)?.id ?? ''
})

async function loadOrganizations(): Promise<void> {
  loading.value = true
  loadError.value = null
  try { organizations.value = await listAccountOrganizations() }
  catch (error) { loadError.value = error }
  finally { loading.value = false }
}

onMounted(() => { void loadOrganizations() })

async function submit(): Promise<void> {
  if (!valid.value || creating.value) return
  creating.value = true
  createError.value = null
  created.value = null
  try {
    created.value = await createAccount({
      username: form.username.trim(), name: form.name.trim(), role: form.role,
      org_unit_id: form.org_unit_id, password: form.password,
    })
    Object.assign(form, { username: '', name: '', password: '', confirm_password: '' })
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
      <p v-if="created.role === 'member' || created.role === 'applicant'">
        党员与申请人都需在名册中关联本人档案后，才能查看档案与提交个人材料。
        <RouterLink to="/members">前往党员发展关联档案</RouterLink>
      </p>
    </section>

    <section class="u-card account-card">
      <header class="u-panel-head"><h2 class="card-title">账号信息</h2><span class="badge">仅系统管理员</span></header>
      <LoadingBlock v-if="loading" variant="list" :rows="3" />
      <ErrorState v-else-if="loadError" :error="loadError">
        <button class="btn btn--ghost" type="button" @click="loadOrganizations">重新加载组织</button>
      </ErrorState>
      <EmptyState v-else-if="!organizations.length" title="尚未配置组织" body="请先由维护人员登记本单位的学校、院系或支部，再创建账号。" icon="people" />
      <form v-else class="account-form" @submit.prevent="submit">
        <p class="account-form__intro">账号归属当前单位。请按人员职责选择角色，所属组织决定其业务范围。</p>
        <fieldset class="form-grid" :disabled="creating">
          <legend class="u-sr">新账号信息</legend>
          <div class="field">
            <label for="account-username" class="field__label">用户名</label>
            <input id="account-username" v-model="form.username" class="input" maxlength="50" autocomplete="off" required aria-describedby="username-hint" />
            <p id="username-hint" class="field__hint">最多 50 个字符，不能包含空白；用于登录。</p>
          </div>
          <div class="field">
            <label for="account-name" class="field__label">姓名</label>
            <input id="account-name" v-model="form.name" class="input" maxlength="50" autocomplete="off" required />
          </div>
          <div class="field">
            <label for="account-role" class="field__label">角色</label>
            <select id="account-role" v-model="form.role" class="select" required>
              <option v-for="role in roles" :key="role" :value="role">{{ ROLE_LABELS[role] }}</option>
            </select>
          </div>
          <div class="field">
            <label for="account-org" class="field__label">所属组织</label>
            <select id="account-org" v-model="form.org_unit_id" class="select" :disabled="!availableOrganizations.length" required aria-describedby="org-hint">
              <option value="">请选择组织</option>
              <option v-for="org in availableOrganizations" :key="org.id" :value="org.id">{{ org.name }} · {{ ORG_LABELS[org.org_type] }}</option>
            </select>
            <p id="org-hint" class="field__hint">{{ organizationHint }}</p>
            <p v-if="!availableOrganizations.length" class="field__error" role="status">当前没有此角色可用的组织，请先登记组织或选择其他角色。</p>
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
