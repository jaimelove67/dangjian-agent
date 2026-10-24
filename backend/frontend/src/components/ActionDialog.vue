<script setup lang="ts">
import { onBeforeUnmount, ref, useId, watch } from 'vue'

const props = withDefaults(
  defineProps<{ open: boolean; title: string; busy?: boolean; wide?: boolean }>(),
  { busy: false, wide: false },
)
const emit = defineEmits<{ close: [] }>()
const element = ref<HTMLDialogElement | null>(null)
const titleId = useId()
watch(
  () => props.open,
  (open) => {
    if (open && !element.value?.open) element.value?.showModal()
    if (!open && element.value?.open) element.value.close()
  },
  { flush: 'post' },
)
onBeforeUnmount(() => element.value?.close())

function cancel(event: Event): void {
  event.preventDefault()
  if (!props.busy) emit('close')
}
</script>

<template>
  <dialog
    ref="element"
    class="wb-dialog"
    :class="{ 'wb-dialog--wide': wide }"
    :aria-labelledby="titleId"
    @cancel="cancel"
  >
    <header class="wb-toolbar">
      <h2 :id="titleId" class="u-title-sub">{{ title }}</h2>
      <button type="button" class="btn btn--quiet" :disabled="busy" @click="emit('close')">
        关闭
      </button>
    </header>
    <div class="wb-dialog__body"><slot /></div>
  </dialog>
</template>
