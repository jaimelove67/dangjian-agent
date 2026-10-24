<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getOwnArchive, type PersonalArchive } from '@/api/member-self'
import { STAGE_LABELS } from '@/api/types'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PageHeader from '@/components/PageHeader.vue'
import { session } from '@/stores/session'

const archive = ref<PersonalArchive | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
/** 账号姓名与名册登记姓名不一致时，界面上必须解释清楚，不能并排放两个名字不说明 */
const nameMismatch = computed(
  () => Boolean(session.state.user?.name) && Boolean(archive.value?.profile?.name) &&
    session.state.user?.name !== archive.value?.profile?.name,
)
async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try { archive.value = await getOwnArchive() }
  catch (err) { error.value = err }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="personal">
    <PageHeader title="本人档案" description="查看组织登记的本人信息。档案信息由组织核实维护。">
      <template #actions><button class="btn btn--ghost" :disabled="loading" @click="load">刷新档案</button></template>
    </PageHeader>
    <LoadingBlock v-if="loading" variant="list" :rows="4" />
    <ErrorState v-else-if="error" :error="error"><button class="btn btn--ghost" @click="load">重试</button></ErrorState>
    <template v-else>
      <section class="u-card personal__card">
        <h2>账号信息</h2>
        <dl class="personal__fields">
          <div><dt>登录账号姓名</dt><dd>{{ session.state.user?.name }}</dd></div>
          <div><dt>登录账号</dt><dd>{{ session.state.user?.username }}</dd></div>
          <div><dt>邮箱</dt><dd>{{ session.state.user?.email || '未登记' }}</dd></div>
          <div><dt>手机号</dt><dd>{{ session.state.user?.phone || '未登记' }}</dd></div>
        </dl>
        <p class="u-meta">
          账号信息用于登录与通知；组织档案中的姓名、组织与阶段以党组织名册登记为准。
        </p>
      </section>
      <EmptyState v-if="!archive?.profile" icon="people" title="尚未关联本人档案" body="请联系组织管理员，在党员名册中将本人档案关联到你的登录账号。系统不会按姓名自动匹配。" />
      <section v-else class="u-card personal__card">
        <h2>组织档案</h2>
        <p v-if="nameMismatch" class="personal__notice" role="note">
          <AppIcon name="alert" :size="14" />
          <span>
            登录账号姓名（{{ session.state.user?.name }}）与名册登记姓名（{{ archive.profile.name }}）不一致。
            如组织档案有误，请联系组织管理员核实；系统不会自动按姓名匹配。
          </span>
        </p>
        <dl class="personal__fields">
          <div><dt>登记姓名</dt><dd>{{ archive.profile.name }}</dd></div>
          <div><dt>所属组织</dt><dd>{{ archive.profile.org_name }}</dd></div>
          <div><dt>当前阶段</dt><dd>{{ STAGE_LABELS[archive.profile.stage] }}</dd></div>
          <div><dt>进入当前阶段日期</dt><dd>{{ archive.profile.stage_joined_on }}</dd></div>
        </dl>
        <h3>组织登记的已具备材料</h3>
        <ul v-if="archive.profile.materials.length" class="personal__materials"><li v-for="material in archive.profile.materials" :key="material">{{ material }}</li></ul>
        <p v-else class="u-meta">暂未登记已具备材料。</p>
        <p class="u-meta">个人提交材料不会自动计为组织已核验材料。如有信息不一致，请联系组织管理员核实。</p>
        <RouterLink to="/my-materials" class="btn btn--primary">提交个人材料</RouterLink>
      </section>
    </template>
  </div>
</template>

<style scoped>
.personal { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-6); }
.personal__card { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.personal__fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr)); gap: var(--space-4); }
.personal__fields dt { color: var(--ink-muted); font-size: var(--text-sm); }
.personal__fields dd { margin-top: var(--space-1); overflow-wrap: anywhere; }
.personal__materials { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.personal__notice {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--warn-wash);
  border: 1px solid var(--warn-edge);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--warn-ink);
}
.personal__card .btn { align-self: flex-start; }
</style>
