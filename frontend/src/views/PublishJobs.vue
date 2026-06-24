<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, h } from 'vue'
import { useRoute } from 'vue-router'
import {
  NCard, NProgress, NTag, NText, NEmpty, NSpace, NButton, NImage,
  NGrid, NGi, NStatistic, NPopconfirm, NSelect, useMessage,
} from 'naive-ui'
import { fetchPublishTasks, cancelPublishTask, retryPublishTask, getThumbnailImage, regenerateThumbnail, pausePublishTask, resumePublishTask, reorderPublishTask, deletePublishTask, batchPublish, fetchChats } from '@/api/client'
import api from '@/api/client'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'

const message = useMessage()
const route = useRoute()
const pendingVideos = ref<any[]>([])
const pendingChannelId = ref<number | null>(null)
const channelOpts = ref<{ label: string; value: number; label_full: string }[]>([])
const recentToasts = new Map<string, number>()  // video_name -> timestamp, for dedup

function dedupedToast(type: 'success'|'error', videoName: string, msg: string) {
  const now = Date.now()
  const last = recentToasts.get(videoName) || 0
  if (now - last < 5000) return  // same file within 5s → skip
  recentToasts.set(videoName, now)
  if (recentToasts.size > 100) {
    // Clean old entries
    for (const [k, v] of recentToasts) { if (now - v > 10000) recentToasts.delete(k) }
  }
  if (type === 'success') message.success(msg)
  else message.error(msg)
}

async function initPending() {
  const ids = route.query.ids as string
  if (!ids) return
  try {
    const { data } = await api.get('/videos', { params: { page_size: 100 } })
    const idSet = new Set(ids.split(',').map(Number))
    pendingVideos.value = (data.items || []).filter((v: any) => idSet.has(v.id))
  } catch {}
  try {
    const d = await fetchChats()
    channelOpts.value = (d.items || []).map((c: any) => ({
      label: (c.alias || c.chat_name || String(c.chat_id)).slice(0, 16) + ((c.alias || c.chat_name || '').length > 16 ? '…' : ''),
      value: c.chat_id,
      label_full: c.alias || c.chat_name || String(c.chat_id),
    }))
  } catch {}
}

async function batchPublishVids() {
  if (!pendingChannelId.value || !pendingVideos.value.length) { message.warning('请选择频道'); return }
  message.loading('创建发布任务...')
  try {
    await batchPublish(pendingVideos.value.map(v => v.id), pendingChannelId.value)
    message.success(`已创建 ${pendingVideos.value.length} 个发布任务`)
    pendingVideos.value = []
    load()
  } catch { message.error('创建失败') }
}

interface PublishTask {
  id: number; video_id: number | null; video_name: string; channel_name: string
  status: string; progress: number; elapsed_sec: number; eta_sec: number
  compression_ratio: number | null; error_log: string; thumbnail_id: number | null
  created_at: string; is_paused: boolean;   step_log: { step: string; elapsed: number; result: string; error?: string; speed_kbs?: number }[]
}

const tasks = ref<PublishTask[]>([])
const ws = ref<WebSocket | null>(null)
let reconnectTimer: number | undefined
let reconnectAttempts = 0
const showCompleted = ref(false)
const expandedTaskId = ref<number | null>(null)

function toggleExpand(id: number) {
  expandedTaskId.value = expandedTaskId.value === id ? null : id
}

const stats = computed(() => {
  const total = tasks.value.length
  const done = tasks.value.filter(t => t.status === 'done').length
  const running = tasks.value.filter(t => t.status === 'running' || t.status === 'uploading').length
  const queued = tasks.value.filter(t => t.status === 'queued').length
  const failed = tasks.value.filter(t => t.status === 'failed').length
  return { total, done, running, queued, failed }
})

function connectWS() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('access_token')
  ws.value = new WebSocket(`${protocol}//${location.host}/ws/compress?token=${token || ''}`)
  ws.value.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.type === 'publish_progress') {
      const t = tasks.value.find(j => j.id === msg.task_id)
      if (t) {
        t.status = msg.step === 'uploading' ? 'uploading' : 'running'
        t.progress = msg.progress || t.progress
        t.elapsed_sec = msg.elapsed_sec || 0
        t.eta_sec = msg.eta_sec || 0
        t.thumbnail_id = msg.thumbnail_id || t.thumbnail_id
      }
    } else if (msg.type === 'publish_done') {
      const t = tasks.value.find(j => j.id === msg.task_id)
      if (t) { t.status = 'done'; t.progress = 100 }
      dedupedToast('success', msg.video_name, `发布成功: ${msg.video_name}`)
      load()
    } else if (msg.type === 'publish_error') {
      const t = tasks.value.find(j => j.id === msg.task_id)
      if (t) { t.status = 'failed'; t.error_log = msg.error || '' }
      dedupedToast('error', msg.video_name, `发布失败: ${msg.video_name}`)
      load()
    } else if (msg.type === 'publish_cancelled') {
      const t = tasks.value.find(j => j.id === msg.task_id)
      if (t) t.status = 'cancelled'
      load()
    }
  }
  ws.value.onclose = () => {
    const delay = Math.min((reconnectAttempts || 1) * 5000, 60000)
    reconnectAttempts = (reconnectAttempts || 1) + 1
    reconnectTimer = window.setTimeout(connectWS, delay)
  }
  ws.value.onerror = () => { ws.value?.close() }
  ws.value.onopen = () => { reconnectAttempts = 0 }
}

async function load() {
  try {
    const data = await fetchPublishTasks({ page_size: 100 })
    tasks.value = data.items || []
  } catch { message.error('加载发布任务失败') }
}

async function doCancel(taskId: number) {
  try { await cancelPublishTask(taskId); message.success('已取消'); load() }
  catch { message.error('取消失败') }
}

async function doRetry(taskId: number) {
  try { await retryPublishTask(taskId); message.success('已重新加入队列'); load() }
  catch { message.error('重试失败') }
}

async function doRegenerateThumb(taskId: number) {
  const t = tasks.value.find(j => j.id === taskId)
  if (!t || !t.thumbnail_id) { message.warning('没有缩略图'); return }
  try {
    await regenerateThumbnail(t.thumbnail_id)
    message.success('缩略图已重新生成')
  } catch { message.error('重新生成失败') }
}

function thumbUrl(id: number | null) {
  return id ? getThumbnailImage(id) : ''
}

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1_000_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB'
  return (bytes / 1_000_000_000).toFixed(2) + ' GB'
}

function formatElapsed(sec: number): string {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
}

function statusColor(status: string): string {
  return {
    running: 'var(--color-purple)', uploading: 'var(--color-purple)',
    done: 'var(--color-green)', failed: 'var(--color-red)',
    cancelled: '#aaa', queued: '#5e9eff',
  }[status] || '#888'
}

function statusLabel(status: string): string {
  return {
    running: '处理中', uploading: '上传中', done: '已完成',
    failed: '失败', cancelled: '已取消', queued: '排队中',
  }[status] || status
}

async function doDelete(id: number) {
  try { await deletePublishTask(id); message.success('已删除'); load() }
  catch (e: any) { message.error('删除失败: ' + (e?.response?.data?.detail || e?.message || '')); console.error(e) }
}

async function doPause(id: number) {
  try { await pausePublishTask(id); message.success('已暂停'); load() }
  catch { message.error('暂停失败') }
}

async function doResume(id: number) {
  try { await resumePublishTask(id); message.success('已恢复'); load() }
  catch { message.error('恢复失败') }
}

async function doReorder(id: number, dir: string) {
  try { await reorderPublishTask(id, dir); load() }
  catch { message.error('排序失败') }
}

async function doRetryAllFailed() {
  const failed = tasks.value.filter(t => t.status === 'failed')
  for (const t of failed) {
    try { await retryPublishTask(t.id) } catch {}
  }
  message.success(`已重试 ${failed.length} 个任务`)
  load()
}

async function doDeleteAllCompleted() {
  const comp = tasks.value.filter(t => t.status === 'done' || t.status === 'cancelled')
  for (const t of comp) {
    try { await deletePublishTask(t.id) } catch {}
  }
  message.success(`已删除 ${comp.length} 个任务`)
  load()
}

async function doDeleteAllFailed() {
  const failed = tasks.value.filter(t => t.status === 'failed')
  for (const t of failed) {
    try { await deletePublishTask(t.id) } catch {}
  }
  message.success(`已删除 ${failed.length} 个任务`)
  load()
}

const activeTasks = computed(() => tasks.value.filter(t => t.status === 'queued' || t.status === 'running' || t.status === 'uploading'))
const completedTasks = computed(() => tasks.value.filter(t => t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'))

// Group by date
const grouped = computed(() => {
  const now = new Date()
  const today = now.toDateString()
  const yesterday = new Date(now.getTime() - 86400000).toDateString()
  const groups: Record<string, PublishTask[]> = {}
  
  for (const t of tasks.value) {
    const d = t.created_at ? new Date(t.created_at).toDateString() : 'Unknown'
    const label = d === today ? '今天' : d === yesterday ? '昨天' : d
    if (!groups[label]) groups[label] = []
    groups[label].push(t)
  }
  return Object.entries(groups)
})

onMounted(() => {
  load()
  connectWS()
  initPending()
})

onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws.value?.close()
})
</script>

<template>
  <PageContainer>
    <PageHeader title="发布任务" icon="📤" />

    <n-grid v-if="tasks.length" :cols="4" :x-gap="12" style="margin-bottom: 20px">
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align: center">
          <n-statistic label="总任务" :value="stats.total" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align: center; background: var(--bg-green)">
          <n-statistic label="已完成" :value="stats.done" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align: center; background: var(--bg-purple)">
          <n-statistic label="进行中" :value="stats.running + stats.queued" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align: center; background: rgba(230,78,78,0.06)">
          <n-statistic label="失败" :value="stats.failed" />
        </n-card>
      </n-gi>
    </n-grid>

    <n-empty v-if="!tasks.length && !pendingVideos.length" description="暂无发布任务" style="margin-top: 80px" />

    <!-- Pending batch-publish from VideoBrowser -->
    <div v-if="pendingVideos.length" style="margin-bottom: 20px; padding: 12px; background: var(--bg-subtle); border-radius: 8px;">
      <n-text strong style="font-size: 13px; display: block; margin-bottom: 8px;">待发布 ({{ pendingVideos.length }})</n-text>
      <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px;">
        <n-text v-for="v in pendingVideos" :key="v.id" depth="3" style="font-size: 12px;">🎬 {{ v.filename }}</n-text>
      </div>
      <n-space :size="8">
        <n-select v-model:value="pendingChannelId" size="small" style="width: 200px" :options="channelOpts" placeholder="选择频道"
          :render-option="({node, option}: any) => h('span', { title: option.label_full }, option.label)" />
        <n-button size="small" type="primary" @click="batchPublishVids">全部发布</n-button>
      </n-space>
    </div>

    <!-- Active tasks -->
    <n-space vertical :size="12" v-if="activeTasks.length">
      <n-text depth="3" style="font-size: 12px;">进行中 · 排队中 ({{ activeTasks.length }})</n-text>
      <n-card v-for="task in activeTasks" :key="task.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(task.status)}`, background: 'var(--bg-subtle)', cursor: 'pointer' }"
        @click="toggleExpand(task.id)"><div style="display: flex; gap: 14px">
          <div v-if="task.thumbnail_id" class="thumb-blur" style="flex-shrink: 0; width: 120px; height: 68px; border-radius: 6px; overflow: hidden; background: rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(task.thumbnail_id)" :width="120" :height="68" object-fit="cover" :show-toolbar="false" />
          </div>
          <div v-else style="flex-shrink: 0; width: 120px; height: 68px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.3)"><span style="font-size: 24px; opacity: 0.3">📤</span></div>
          <div style="flex: 1; min-width: 0">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px">
              <div style="min-width: 0">
                <n-text strong style="font-size: 14px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ task.video_name }}</n-text>
                <n-text v-if="task.channel_name" depth="3" style="font-size: 11px;">→ {{ task.channel_name }}</n-text>
              </div>
              <n-tag :type="task.status === 'running' || task.status === 'uploading' ? 'warning' : 'default'" size="small" :bordered="false" round>{{ statusLabel(task.status) }}</n-tag>
            </div>
            <n-progress type="line" :percentage="task.progress || 0" :height="16" :border-radius="8" :color="statusColor(task.status)" :indicator-placement="'inside'" :processing="task.status === 'running' || task.status === 'uploading'" />
            <div style="margin-top: 8px; display: flex; align-items: center; gap: 10px; font-size: 12px; flex-wrap: wrap;">
              <n-text depth="3">⏱ {{ formatElapsed(task.elapsed_sec) }}<template v-if="task.eta_sec"> · 剩余 {{ formatElapsed(task.eta_sec) }}</template></n-text>
              <n-space :size="6" style="margin-left: auto">
                <n-button v-if="task.status === 'queued' && !task.is_paused" size="tiny" @click.stop="doPause(task.id)">暂停</n-button>
                <n-button v-if="task.status === 'queued' && task.is_paused" size="tiny" type="primary" @click.stop="doResume(task.id)">恢复</n-button>
                <n-button v-if="task.status === 'queued'" size="tiny" @click.stop="doReorder(task.id, 'up')">↑</n-button>
                <n-button v-if="task.status === 'queued'" size="tiny" @click.stop="doReorder(task.id, 'down')">↓</n-button>
                <n-button size="tiny" @click.stop="doCancel(task.id)">取消</n-button>
              </n-space>
            </div>
            <div v-if="expandedTaskId === task.id" style="margin-top: 8px; padding-top: 6px; border-top: 1px solid var(--border-subtle)">
              <n-text v-if="task.error_log" depth="3" style="font-size: 11px; white-space: pre-wrap; font-family: monospace; word-break: break-all; display: block;">{{ task.error_log }}</n-text>
              <n-text v-else depth="3">暂无详情</n-text>
            </div>
          </div></div>
      </n-card>
    </n-space>

    <!-- Completed tasks -->
    <div v-if="completedTasks.length" style="margin-top: 20px">
      <n-space :size="6" style="margin-bottom: 8px;">
        <n-button size="tiny" @click="showCompleted = !showCompleted">{{ showCompleted ? '收起历史' : `展开历史 (${completedTasks.length})` }}</n-button>
        <n-popconfirm @positive-click="doRetryAllFailed" positive-text="确定" negative-text="取消">
          <template #trigger><n-button size="tiny" type="primary">重试全部失败</n-button></template>
          确定重试所有失败任务？
        </n-popconfirm>
        <n-popconfirm @positive-click="doDeleteAllCompleted" positive-text="确定" negative-text="取消">
          <template #trigger><n-button size="tiny" type="error">删除已完成</n-button></template>
          确定删除所有已完成任务？
        </n-popconfirm>
        <n-popconfirm @positive-click="doDeleteAllFailed" positive-text="确定" negative-text="取消">
          <template #trigger><n-button size="tiny" type="warning">删除所有失败</n-button></template>
          确定删除所有失败任务？
        </n-popconfirm>
      </n-space>
    </div>
    <n-space v-if="showCompleted && completedTasks.length" vertical :size="12" style="margin-top: 12px">
      <n-card v-for="task in completedTasks" :key="task.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(task.status)}`, background: 'var(--bg-subtle)', opacity: 0.7, cursor: 'pointer' }"
        @click="toggleExpand(task.id)"><div style="display: flex; gap: 14px">
          <div v-if="task.thumbnail_id" class="thumb-blur" style="flex-shrink: 0; width: 80px; height: 45px; border-radius: 4px; overflow: hidden; background: rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(task.thumbnail_id)" :width="80" :height="45" object-fit="cover" :show-toolbar="false" />
          </div>
          <div style="flex: 1; min-width: 0">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
              <div style="min-width: 0">
                <n-text strong style="font-size: 13px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ task.video_name }}</n-text>
                <n-text v-if="task.channel_name" depth="3" style="font-size: 11px;">→ {{ task.channel_name }}</n-text>
              </div>
              <n-tag :type="task.status === 'done' ? 'success' : task.status === 'failed' ? 'error' : 'default'" size="small" :bordered="false" round>{{ statusLabel(task.status) }}</n-tag>
            </div>
            <div style="font-size: 12px;">
              <n-text v-if="task.status === 'done'">⏱ {{ formatElapsed(task.elapsed_sec) }}</n-text>
              <n-text v-else-if="task.status === 'failed' && task.error_log" depth="3" style="color: var(--color-red); font-size: 11px; display: block;">{{ task.error_log.slice(0, 100) }}</n-text>
            </div>
            <div style="margin-top: 4px; display: flex; gap: 6px; flex-wrap: wrap;">
              <n-button size="tiny" @click.stop="toggleExpand(task.id)">{{ expandedTaskId === task.id ? '收起' : '详情' }}</n-button>
              <n-button v-if="task.status === 'failed' || task.status === 'cancelled'" size="tiny" type="primary" @click.stop="doRetry(task.id)">重新发布</n-button>
              <n-button v-if="task.status === 'done'" size="tiny" @click.stop="doRetry(task.id)">重新发布</n-button>
              <n-button v-if="task.thumbnail_id" size="tiny" @click.stop="doRegenerateThumb(task.id)">重生成缩略图</n-button>
              <span @click.stop>
                <n-popconfirm @positive-click="() => doDelete(task.id)" positive-text="确定" negative-text="取消">
                  <template #trigger><n-button size="tiny" type="error">删除</n-button></template>
                  确定删除此记录？
                </n-popconfirm>
              </span>
            </div>
            <div v-if="expandedTaskId === task.id" style="margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border-subtle)">
              <div v-if="task.step_log && task.step_log.length" style="margin-bottom: 6px">
                <n-text depth="3" style="font-size: 11px; display: block; margin-bottom: 2px;">步骤日志：</n-text>
                <n-text v-for="(s,i) in task.step_log" :key="i" depth="3" style="font-size: 11px; display: block;">
                  {{ i+1 }}. {{ s.step }} — {{ s.elapsed }}s {{ s.result }}{{ s.speed_kbs ? ' · '+s.speed_kbs+'KB/s' : '' }}{{ s.error ? ': '+s.error.slice(0,60) : '' }}
                </n-text>
              </div>
              <n-text v-if="task.error_log" depth="3" style="font-size: 11px; white-space: pre-wrap; font-family: monospace; word-break: break-all; max-height: 200px; overflow-y: auto; display: block;">{{ task.error_log }}</n-text>
              <n-text v-else depth="3">暂无详情</n-text>
            </div>
          </div></div>
      </n-card>
    </n-space>
  </PageContainer>
</template>
