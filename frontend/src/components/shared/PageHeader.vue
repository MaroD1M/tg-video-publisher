<script setup lang="ts">
defineProps<{
  title: string
  icon?: string
}>()
</script>

<template>
  <div class="page-header">
    <h1 class="page-title">{{ icon ? icon + ' ' : '' }}{{ title }}</h1>
    <div v-if="$slots.default" class="page-actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-shrink: 0;
}
.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
