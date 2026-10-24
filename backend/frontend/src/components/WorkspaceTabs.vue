<script setup lang="ts">
import { useId } from 'vue'

const props = defineProps<{
  modelValue: string
  items: { key: string; label: string }[]
  label: string
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const id = useId()

function move(event: KeyboardEvent, index: number): void {
  if (props.disabled) return
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
  if (!keys.includes(event.key)) return
  event.preventDefault()
  const length = props.items.length
  const next =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + length) % length
  const item = props.items[next]
  if (!item) return
  emit('update:modelValue', item.key)
  document.getElementById(`${id}-${item.key}`)?.focus()
}
</script>

<template>
  <div class="wb-tabs">
    <div class="wb-tabs__nav" role="tablist" :aria-label="label">
      <button
        v-for="(item, index) in items"
        :id="`${id}-${item.key}`"
        :key="item.key"
        type="button"
        role="tab"
        :disabled="disabled"
        :aria-selected="modelValue === item.key"
        :aria-controls="`${id}-panel`"
        :tabindex="modelValue === item.key ? 0 : -1"
        :class="{ 'is-active': modelValue === item.key }"
        @click="emit('update:modelValue', item.key)"
        @keydown="move($event, index)"
      >
        {{ item.label }}
      </button>
    </div>
    <div
      :id="`${id}-panel`"
      class="wb-tabs__body"
      role="tabpanel"
      :aria-labelledby="`${id}-${modelValue}`"
    >
      <slot />
    </div>
  </div>
</template>
