<script setup lang="ts">
import { RouterView } from 'vue-router'

import ErrorState from '@/components/ErrorState.vue'
import { session } from '@/stores/session'

function retrySession(): void {
  window.location.reload()
}
</script>

<template>
  <main v-if="session.state.restoreError" class="session-recovery">
    <ErrorState :error="session.state.restoreError">
      <button class="btn" type="button" @click="retrySession">重试恢复会话</button>
    </ErrorState>
  </main>
  <RouterView v-else />
</template>

<style scoped>
.session-recovery {
  max-width: 42rem;
  margin: var(--space-8) auto;
  padding: var(--space-4);
}
</style>
