<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import PageHeader from '@/components/PageHeader.vue'
</script>

<template>
  <div class="forbidden">
    <PageHeader title="无法访问该页面" description="当前账号没有访问该功能的权限。" />
    <section class="u-card forbidden__notice" role="alert">
      <AppIcon name="shield" :size="20" />
      <p>
        如需使用此功能，请联系平台系统管理员核对账号角色与所属组织；
        角色决定可访问的资料范围，所属组织决定业务数据范围。
      </p>
    </section>
    <RouterLink to="/ask" class="btn btn--primary forbidden__back">返回制度问答</RouterLink>
  </div>
</template>

<style scoped>
.forbidden {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-6);
}

.forbidden__notice {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5);
  color: var(--ink-soft);
}

.forbidden__back {
  align-self: flex-start;
}
</style>
