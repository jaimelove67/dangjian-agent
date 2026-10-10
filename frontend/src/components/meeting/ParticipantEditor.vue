<script setup lang="ts">
import type { Participant } from '@/api/meeting'

const props = withDefaults(defineProps<{ modelValue: Participant[]; readonly?: boolean }>(), {
  readonly: false,
})
const emit = defineEmits<{ 'update:modelValue': [participants: Participant[]] }>()
function change(index: number, changes: Partial<Participant>): void {
  emit(
    'update:modelValue',
    props.modelValue.map((person, position) =>
      position === index ? { ...person, ...changes } : person,
    ),
  )
}
</script>

<template>
  <div class="wb-stack">
    <div class="wb-toolbar">
      <h3>参会与出勤</h3>
      <button
        v-if="!readonly"
        class="btn btn--ghost btn--sm"
        type="button"
        :disabled="modelValue.length >= 500"
        @click="
          emit('update:modelValue', [
            ...modelValue,
            { participant_id: '', name: '', attended: true },
          ])
        "
      >
        添加参会人员
      </button>
    </div>
    <div v-if="modelValue.length" class="wb-table-wrap">
      <table class="wb-table">
        <thead>
          <tr>
            <th>人员编号</th>
            <th>姓名</th>
            <th>出勤</th>
            <th v-if="!readonly">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(person, index) in modelValue" :key="index">
            <td>
              <span v-if="readonly">{{ person.participant_id }}</span
              ><input
                v-else
                class="input"
                :value="person.participant_id"
                :aria-label="`第${index + 1}位参会人员编号`"
                placeholder="工号 / 学号"
                maxlength="100"
                required
                @input="
                  change(index, { participant_id: ($event.target as HTMLInputElement).value })
                "
              />
            </td>
            <td>
              <span v-if="readonly">{{ person.name }}</span
              ><input
                v-else
                class="input"
                :value="person.name"
                :aria-label="`第${index + 1}位参会人员姓名`"
                maxlength="100"
                required
                @input="change(index, { name: ($event.target as HTMLInputElement).value })"
              />
            </td>
            <td>
              <span v-if="readonly">{{ person.attended ? '已参会' : '未参会' }}</span
              ><label v-else class="wb-check"
                ><input
                  type="checkbox"
                  :checked="person.attended"
                  @change="change(index, { attended: ($event.target as HTMLInputElement).checked })"
                />已参会</label
              >
            </td>
            <td v-if="!readonly">
              <button
                type="button"
                class="btn btn--quiet btn--sm"
                @click="
                  emit(
                    'update:modelValue',
                    modelValue.filter((_, position) => position !== index),
                  )
                "
              >
                移除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="u-meta">尚未登记参会人员。实际参会情况是纪要审核和归档的必要依据。</p>
  </div>
</template>
