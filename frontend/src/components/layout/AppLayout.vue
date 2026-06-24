<script setup lang="ts">
import { ref, computed, h, type Component, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NIcon, NLayout, NLayoutContent, NTag } from 'naive-ui'
import {
  GridOutline, FilmOutline, HardwareChipOutline, SendOutline,
  CalendarOutline, DocumentTextOutline, SettingsOutline, LayersOutline,
  LogOutOutline, GitNetworkOutline, TrashOutline,
} from '@vicons/ionicons5'
import { fetchPublishTasks } from '@/api/client'
import { useSettingsStore } from '@/stores/settings'
import { useTaskStore } from '@/stores/tasks'
import { useWebSocket } from '@/composables/useWebSocket'
import AppSidebar from './AppSidebar.vue'
import AppFooter from './AppFooter.vue'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const showSetup = computed(() => route.name === 'setup' || route.name === 'login')
const settingsStore = useSettingsStore()
const taskStore = useTaskStore()
const stats = ref({ compress_running: 0, compress_queued: 0, queued: 0, publish_active: 0 })
let statsTimer: number | undefined

function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function doLogout() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('username')
  window.location.href = '/login'
}

function renderExtra(count: number) {
  if (!count) return undefined
  return () => h(NTag, { type: 'warning', size: 'small', bordered: false, round: true, style: 'min-width:20px;text-align:center;font-size:10px;padding:0 5px;height:18px;line-height:18px' }, { default: () => String(count) })
}

const menuItems = computed(() => [
  { label: '仪表盘', key: '/', icon: renderIcon(GridOutline) },
  { label: '视频管理', key: '/videos', icon: renderIcon(FilmOutline) },
  {
    label: '压缩任务', key: '/compress', icon: renderIcon(HardwareChipOutline),
    extra: renderExtra(stats.value.compress_running + stats.value.compress_queued),
  },
  { label: '发布任务', key: '/publish-tasks', icon: renderIcon(SendOutline), extra: renderExtra(stats.value.publish_active) },
  { label: '缩略图', key: '/thumbnails', icon: renderIcon(LayersOutline) },
  { type: 'divider' as const, key: 'd1' },
  {
    label: '发布计划', key: '/schedules', icon: renderIcon(CalendarOutline),
    extra: renderExtra(stats.value.queued),
  },
  { label: '发布记录', key: '/history', icon: renderIcon(DocumentTextOutline) },
  { type: 'divider' as const, key: 'd2' },
  { label: '磁盘管理', key: '/disk-cleanup', icon: renderIcon(TrashOutline) },
  { label: '系统设置', key: '/settings', icon: renderIcon(SettingsOutline) },
  { label: 'Bot 状态', key: '/bot-status', icon: renderIcon(GitNetworkOutline) },
  { type: 'divider' as const, key: 'd3' },
  { label: '退出登录', key: 'logout', icon: renderIcon(LogOutOutline) },
])

async function pollStats() {
  try {
    const data = await settingsStore.loadStats(true)
    stats.value.compress_running = data.compress_running || 0
    stats.value.compress_queued = data.compress_queued || 0
    stats.value.queued = data.queued || 0
  } catch {}
  try {
    const d = await fetchPublishTasks({ status: 'queued,running,uploading', page_size: 100 })
    stats.value.publish_active = d.total || 0
  } catch {}
}

const { connect: connectWS, disconnect: disconnectWS } = useWebSocket(
  '/ws/compress',
  () => { pollStats() }
)

onMounted(() => {
  pollStats()
  connectWS()
  statsTimer = window.setInterval(pollStats, 30000)
})

onUnmounted(() => {
  disconnectWS()
  if (statsTimer) clearInterval(statsTimer)
})
</script>

<template>
  <div v-if="showSetup" class="setup-wrapper">
    <slot />
  </div>
  <n-layout v-else has-sider class="app-layout">
    <AppSidebar
      :collapsed="collapsed"
      :menu-items="menuItems"
      :active-key="route.path"
      @update:active="(k: string) => k === 'logout' ? doLogout() : router.push(k)"
      @update:collapsed="collapsed = $event"
    />
    <n-layout class="main-area">
      <n-layout-content class="content-area">
        <slot />
      </n-layout-content>
      <AppFooter />
    </n-layout>
  </n-layout>
</template>

<style scoped>
.app-layout {
  height: 100vh;
  overflow: hidden;
}
.main-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.content-area {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.setup-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
