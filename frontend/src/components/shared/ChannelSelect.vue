<script setup lang="ts">
import { NSelect } from 'naive-ui'
import { useChannels } from '@/composables/useChannels'

const props = withDefaults(defineProps<{
  modelValue?: number | null
  placeholder?: string
  size?: 'tiny' | 'small' | 'medium'
  width?: string
}>(), {
  placeholder: '选择频道',
  size: 'small',
  width: '200px',
})

const emit = defineEmits<{
  'update:modelValue': [value: number | null]
}>()

const { channelOptions } = useChannels()
</script>

<template>
  <n-select
    :value="modelValue"
    :options="channelOptions()"
    :size="size"
    :style="{ width: width }"
    :placeholder="placeholder"
    clearable
    @update:value="(v: number) => emit('update:modelValue', v)"
  />
</template>
