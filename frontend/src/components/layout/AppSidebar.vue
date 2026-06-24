<script setup lang="ts">
import { h, type Component } from 'vue'
import { NLayoutSider, NMenu, NIcon } from 'naive-ui'

const props = defineProps<{
  collapsed: boolean
  menuItems: any[]
  activeKey: string
}>()

const emit = defineEmits<{
  'update:active': [key: string]
  'update:collapsed': [val: boolean]
}>()
</script>

<template>
  <n-layout-sider
    bordered
    collapse-mode="width"
    :collapsed-width="64"
    :width="220"
    :collapsed="collapsed"
    show-trigger="bar"
    @collapse="emit('update:collapsed', true)"
    @expand="emit('update:collapsed', false)"
  >
    <div class="brand">
      <span class="brand-icon">🎬</span>
      <span v-if="!collapsed" class="brand-text">TG视频发布助手</span>
    </div>
    <n-menu
      :collapsed="collapsed"
      :collapsed-width="64"
      :collapsed-icon-size="22"
      :options="menuItems"
      :value="activeKey"
      @update:value="emit('update:active', $event)"
    />
  </n-layout-sider>
</template>

<style scoped>
.brand {
  display: flex;
  align-items: center;
  padding: 16px 20px;
  gap: 10px;
  margin-bottom: 8px;
}
.brand-icon {
  font-size: 24px;
}
.brand-text {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-brand);
  white-space: nowrap;
}
</style>
