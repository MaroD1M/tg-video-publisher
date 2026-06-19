import { createRouter, createWebHistory } from 'vue-router'
import { getSetupStatus } from '@/api/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
      meta: { title: '仪表盘', icon: 'grid-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/videos',
      name: 'videos',
      component: () => import('@/views/VideoBrowser.vue'),
      meta: { title: '视频管理', icon: 'film-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/compress',
      name: 'compress',
      component: () => import('@/views/CompressJobs.vue'),
      meta: { title: '压缩任务', icon: 'hardware-chip-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/publish-tasks',
      name: 'publish-tasks',
      component: () => import('@/views/PublishJobs.vue'),
      meta: { title: '发布任务', icon: 'send-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/disk-cleanup',
      name: 'disk-cleanup',
      component: () => import('@/views/DiskCleanup.vue'),
      meta: { title: '磁盘管理', icon: 'trash-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/thumbnails',
      name: 'thumbnails',
      component: () => import('@/views/ThumbnailPreview.vue'),
      meta: { title: '缩略图', icon: 'grid-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/schedules',
      name: 'schedules',
      component: () => import('@/views/Schedules.vue'),
      meta: { title: '发布计划', icon: 'calendar-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/PublishHistory.vue'),
      meta: { title: '发布记录', icon: 'document-text-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/Settings.vue'),
      meta: { title: '系统设置', icon: 'settings-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/bot-status',
      name: 'bot-status',
      component: () => import('@/views/BotStatus.vue'),
      meta: { title: 'Bot 状态', icon: 'git-network-outline', requiresSetup: true, requiresAuth: true },
    },
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/views/SetupWizard.vue'),
      meta: { title: '首次设置' },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/Login.vue'),
      meta: { title: '登录' },
    },
  ],
})

let setupChecked = false

router.beforeEach(async (to) => {
  // Public paths
  if (to.name === 'setup' || to.name === 'login') return true

  // Check authentication first — synchronous, no API call
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    return '/login'
  }

  // Check system configuration (async, only once)
  if (!setupChecked) {
    try {
      const { configured } = await getSetupStatus()
      if (!configured) return '/setup'
      setupChecked = true
    } catch {
      return '/setup'
    }
  }

  return true
})

export default router
