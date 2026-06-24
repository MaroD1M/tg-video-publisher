<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { NLayoutFooter, NTooltip } from 'naive-ui'
import StatusDot from '@/components/shared/StatusDot.vue'
import { fetchStats, fetchVersion, checkVersion, fetchDiskUsage } from '@/api/client'

const router = useRouter()
const status = ref<Record<string, any>>({ api: false, queued: 0, compress_running: 0, compress_queued: 0, last_publish: '' })
const version = ref('')
const updateAvailable = ref(false)
const updateRemote = ref('')
const updateDismissed = ref(localStorage.getItem('update_dismissed') || '')
const diskPercent = ref(0)
let timer: number | undefined

async function poll() {
  try {
    const [stats, disk] = await Promise.all([fetchStats(), fetchDiskUsage()])
    status.value = {
      bot: stats.bot || false,
      bot_error: stats.bot_error || '',
      queued: stats.queued || 0,
      compress_running: stats.compress_running || 0,
      compress_queued: stats.compress_queued || 0,
      last_publish: stats.last_publish || '',
    }
    diskPercent.value = disk.percent || 0
  } catch { /* silent */ }
}

async function loadVersion() {
  try {
    const v = await fetchVersion()
    version.value = v.version || ''
  } catch {}
  try {
    const c = await checkVersion()
    if (c.has_update && c.remote && c.remote !== updateDismissed.value) {
      updateAvailable.value = true
      updateRemote.value = c.remote
    }
  } catch {}
}

function dismissUpdate() {
  updateAvailable.value = false
  localStorage.setItem('update_dismissed', updateRemote.value)
}

function explainQueue() {
  if (status.value.compress_running || status.value.compress_queued)
    return `压缩: ${status.value.compress_running} 进行中, ${status.value.compress_queued} 等待中`
  return '暂无压缩任务'
}

onMounted(() => {
  poll()
  loadVersion()
  timer = window.setInterval(poll, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <n-layout-footer bordered class="app-footer">
    <div class="footer-inner">
      <!-- Status indicators -->
      <n-tooltip trigger="hover">
        <template #trigger>
          <span class="status-item clickable" @click="router.push('/bot-status')" role="button" tabindex="0" aria-label="Bot 状态" @keydown.enter="router.push('/bot-status')">
            <StatusDot :status="status.bot ? 'ok' : status.bot == null ? 'unknown' : 'error'" :size="7" />
            Bot
          </span>
        </template>
        {{ status.bot ? 'Bot 连接正常' : status.bot_error ? 'Bot 连接异常: ' + status.bot_error : 'Bot 连接异常' }}
      </n-tooltip>

      <span class="sep">·</span>

      <n-tooltip trigger="hover">
        <template #trigger>
          <span class="status-item clickable" @click="router.push('/compress')">
            ⚡ 压缩中 {{ status.compress_running }}
            <template v-if="status.compress_queued">+{{ status.compress_queued }}</template>
          </span>
        </template>
        {{ explainQueue() }}
      </n-tooltip>

      <span class="sep">·</span>

      <n-tooltip trigger="hover">
        <template #trigger>
          <span class="status-item clickable" @click="router.push('/schedules')">
            📋 待发布 {{ status.queued }}
          </span>
        </template>
        发布计划中等待定时发布的视频
      </n-tooltip>

      <span v-if="status.last_publish" class="sep">·</span>
      <span v-if="status.last_publish" class="status-item">⏱ {{ status.last_publish }}</span>

      <!-- Right side -->
      <div class="footer-right">
        <n-tooltip v-if="updateAvailable" trigger="hover">
          <template #trigger>
            <span class="update-badge" @click="dismissUpdate">
              🆕 v{{ updateRemote }} <span class="dismiss-x">×</span>
            </span>
          </template>
          有新版本可用，点击 × 关闭提醒
        </n-tooltip>

        <span class="disk-item" :style="{ color: diskPercent > 90 ? 'var(--color-red)' : diskPercent > 70 ? '#faad14' : 'var(--text-secondary)' }">
          💾 {{ diskPercent }}%
        </span>

        <span class="sep" style="margin: 0 8px">·</span>
        <span>TG视频发布助手 v{{ version || '1.0' }}</span>
      </div>
    </div>
  </n-layout-footer>
</template>

<style scoped>
.app-footer {
  padding: 0 24px;
  height: 36px;
  display: flex;
  align-items: center;
  flex-shrink: 0;
  border-top: 1px solid var(--border-subtle);
}
.footer-inner {
  display: flex;
  align-items: center;
  gap: 0;
  width: 100%;
  font-size: 13px;
  color: var(--text-secondary);
}
.status-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.clickable {
  cursor: pointer;
  transition: color 0.15s;
}
.clickable:hover {
  color: var(--text-brand);
}
.sep {
  margin: 0 10px;
  opacity: 0.25;
}
.footer-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0;
}
.update-badge {
  background: rgba(250,173,20,0.15);
  color: #faad14;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  cursor: pointer;
  margin-right: 10px;
  white-space: nowrap;
}
.update-badge:hover {
  background: rgba(250,173,20,0.25);
}
.dismiss-x {
  margin-left: 4px;
  opacity: 0.6;
}
.disk-item {
  margin-right: 0;
  font-size: 11px;
  white-space: nowrap;
}
</style>
