<script setup lang="ts">
import { zhCN, dateZhCN, NConfigProvider, NMessageProvider } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import AppLayout from './components/layout/AppLayout.vue'
import { useTheme } from './composables/useTheme'

const { theme } = useTheme()

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#8b5cf6',
    primaryColorHover: '#a78bfa',
    primaryColorPressed: '#7c3aed',
    primaryColorSuppl: '#8b5cf6',
    successColor: '#63e2b7',
    successColorHover: '#86efac',
    errorColor: '#e64e4e',
    errorColorHover: '#f87171',
    warningColor: '#faad14',
    borderRadius: '8px',
    fontSize: '14px',
  },
  Card: {
    borderRadius: '10px',
    paddingMedium: '16px 20px',
    paddingSmall: '12px 16px',
    titleFontSizeMedium: '15px',
  },
  Button: {
    borderRadiusMedium: '8px',
    borderRadiusSmall: '6px',
  },
  Tag: { borderRadius: '4px' },
  DataTable: { thFontWeight: '600' },
}
</script>

<template>
  <n-config-provider :theme="theme" :theme-overrides="themeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <AppLayout>
        <router-view v-slot="{ Component }">
          <template v-if="Component">
            <Transition name="page" mode="out-in">
              <component :is="Component" />
            </Transition>
          </template>
        </router-view>
      </AppLayout>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
body {
  margin: 0;
  padding: 0;
  background: var(--body-bg);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans SC', sans-serif;
}
#app {
  min-height: 100vh;
}
.page-enter-active,
.page-leave-active {
  transition: opacity 0.15s ease;
}
.page-enter-from,
.page-leave-to {
  opacity: 0;
}

.thumb-blur .n-image img,
.thumb-blur img {
  filter: blur(14px);
  transition: filter 0.25s ease;
}
.thumb-blur:hover .n-image img,
.thumb-blur:hover img {
  filter: blur(4px);
}
.thumb-blur .n-image-preview img {
  filter: none !important;
}
</style>
