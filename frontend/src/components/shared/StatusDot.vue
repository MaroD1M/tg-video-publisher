<script setup lang="ts">
defineProps<{
  status: 'ok' | 'error' | 'warn' | 'unknown'
  size?: number
}>()
</script>

<template>
  <span
    class="status-dot"
    :style="{
      width: (size || 7) + 'px',
      height: (size || 7) + 'px',
      background:
        status === 'ok' ? 'var(--color-green)' :
        status === 'error' ? 'var(--color-red)' :
        status === 'warn' ? '#faad14' : 'gray',
    }"
  />
</template>

<style scoped>
.status-dot {
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}
</style>
