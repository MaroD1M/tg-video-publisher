<script setup lang="ts">
import { computed } from 'vue'
import { NTag } from 'naive-ui'

const props = withDefaults(defineProps<{
  status: string
  size?: 'tiny' | 'small' | 'medium'
}>(), {
  size: 'tiny',
})

const config = computed(() => {
  const s = props.status
  if (s === 'done' || s === 'compressed' || s === 'published' || s === 'success')
    return { type: 'success', text: s === 'done' ? '完成' : s === 'compressed' ? '已压缩' : s === 'published' ? '已发布' : '成功' }
  if (s === 'running' || s === 'uploading')
    return { type: 'warning', text: s === 'uploading' ? '上传中' : '运行中' }
  if (s === 'failed' || s === 'error')
    return { type: 'error', text: '失败' }
  if (s === 'cancelled')
    return { type: 'default', text: '已取消' }
  if (s === 'queued')
    return { type: 'info', text: '排队中' }
  if (s === 'pending')
    return { type: 'default', text: '待处理' }
  if (s === 'skipped' || s === 'skipped')
    return { type: 'default', text: '已跳过' }
  return { type: 'default', text: s }
})
</script>

<template>
  <n-tag :type="config.type as any" :size="size" round :bordered="false">
    {{ config.text }}
  </n-tag>
</template>
