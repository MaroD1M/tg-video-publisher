<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, h } from 'vue'
import { useRoute } from 'vue-router'
import {
  NCard, NProgress, NTag, NText, NEmpty, NSpace, NButton, NImage,
  NPopconfirm, useMessage,
} from 'naive-ui'
import {
  fetchPublishTasks, cancelPublishTask, retryPublishTask, getThumbnailImage,
  regenerateThumbnail, pausePublishTask, resumePublishTask, reorderPublishTask,
  deletePublishTask, batchPublish, fetchVideos,
} from '@/api/client'
import { useWebSocket } from '@/composables/useWebSocket'
import { useChannels } from '@/composables/useChannels'
import { formatSize, formatChannelLabel } from '@/utils/format'
import type { PublishTaskData, Video } from '@/types'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import StatusTag from '@/components/shared/StatusTag.vue'
import ChannelSelect from '@/components/shared/ChannelSelect.vue'
import StatsGrid from '@/components/shared/StatsGrid.vue'

const message = useMessage()
const route = useRoute()
const pendingVideos = ref<Video[]>([])
const pendingChannelId = ref<number | null>(null)
const { channels, load: loadChannels } = useChannels()
const recentToasts = new Map<string, number>()

function dedupedToast(type: 'success'|'error', videoName: string, msg: string) {
  const now = Date.now()
  const last = recentToasts.get(videoName) || 0
  if (now - last < 5000) return
  recentToasts.set(videoName, now)
  if (recentToasts.size > 100) {
    for (const [k, v] of recentToasts) {
      if (now - v > 10000) recentToasts.delete(k)
    }
  }
  if (type === 'success') message.success(msg)
  else message.error(msg)
}

async function initPending() {
  const ids = route.query.ids as string
  if (!ids) return
  const cid = route.query.channel_id as string
  if (cid) pendingChannelId.value = Number(cid)
  try {
    const data = await fetchVideos({ page_size: 100 })
    const idSet = new Set(ids.split(',').map(Number))
    pendingVideos.value = (data.items || []).filter((v: any) => idSet.has(v.id))
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

const tasks = ref<PublishTaskData[]>([])
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

const activeTasks = computed(() => tasks.value.filter(t => t.status === 'queued' || t.status === 'running' || t.status === 'uploading'))
const completedTasks = computed(() => tasks.value.filter(t => t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'))

let wsMounted = false
let elapsedTimer: number | undefined

function startElapsedTimer() {
  if (elapsedTimer) return
  elapsedTimer = window.setInterval(() => {
    for (const t of tasks.value) {
      if (t.status === 'running' || t.status === 'uploading') {
        t.elapsed_sec = (t.elapsed_sec || 0) + 1
        if (t.eta_sec && t.eta_sec > 0) {
          t.progress = Math.min(95, Math.round(10 + (t.elapsed_sec / (t.elapsed_sec + t.eta_sec)) * 90))
        }
      }
    }
  }, 1000)
}

const { connect: connectWS } = useWebSocket(
  '/ws/compress',
  (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'publish_progress') {
        let t = tasks.value.find(p => p.id === msg.task_id)
        if (!t) {
          const newTask: PublishTaskData = {
            id: msg.task_id, video_id: msg.video_id, video_name: msg.video_name,
            channel_name: msg.channel_name || '', status: 'running', progress: msg.progress || 5,
            elapsed_sec: msg.elapsed_sec || 0, eta_sec: msg.eta_sec || 0,
            compression_ratio: null, error: null, thumbnail_id: msg.thumbnail_id || null,
            created_at: null, step_log: [], schedule_id: 0, channel_id: null,
          }
          tasks.value.unshift(newTask)
          startElapsedTimer()
        } else {
          t.progress = msg.progress || t.progress
          t.elapsed_sec = msg.elapsed_sec || 0
          t.eta_sec = msg.eta_sec || 0
          t.thumbnail_id = msg.thumbnail_id || t.thumbnail_id
          t.status = msg.step === 'uploading' ? 'uploading' : 'running'
        }
      } else if (msg.type === 'publish_done') {
        const t = tasks.value.find(p => p.id === msg.task_id)
        if (t) { t.status = 'done'; t.progress = 100; dedupedToast('success', t.video_name, `✅ 发布完成: ${t.video_name}`) }
      } else if (msg.type === 'publish_error') {
        const t = tasks.value.find(p => p.id === msg.task_id)
        if (t) { t.status = 'failed'; t.error = msg.error || ''; dedupedToast('error', t.video_name, `❌ 发布失败: ${t.video_name}`) }
      } else if (msg.type === 'publish_cancelled') {
        const t = tasks.value.find(p => p.id === msg.task_id)
        if (t) t.status = 'cancelled'
      }
    } catch {}
  }
)

async function load() { try { tasks.value = ((await fetchPublishTasks({ page_size: 100 })).items || []) as PublishTaskData[] } catch {} }
async function doCancel(taskId: number) { try { await cancelPublishTask(taskId); load() } catch { message.error('取消失败') } }
async function doRetry(taskId: number) { try { await retryPublishTask(taskId); load() } catch { message.error('重试失败') } }
async function doPause(taskId: number) { try { await pausePublishTask(taskId); load() } catch { message.error('暂停失败') } }
async function doResume(taskId: number) { try { await resumePublishTask(taskId); load() } catch { message.error('恢复失败') } }
async function doReorder(taskId: number, dir: 'up' | 'down') { try { await reorderPublishTask(taskId, dir); load() } catch { message.error('排序失败') } }
async function doDelete(taskId: number) { try { await deletePublishTask(taskId); load() } catch { message.error('删除失败') } }
async function doThumb(thumbId: number) { try { await regenerateThumbnail(thumbId); message.success('已重新生成') } catch { message.error('重新生成失败') } }

async function doRetryAllFailed() {
  const failed = tasks.value.filter(t => t.status === 'failed')
  for (const t of failed) { try { await retryPublishTask(t.id) } catch {} }
  message.success(`已重试 ${failed.length} 个失败任务`)
  load()
}

async function doDeleteAllCompleted() {
  try { for (const t of completedTasks.value) { if (t.status === 'done') await deletePublishTask(t.id) } }
  catch {}
  message.success('已删除已完成')
  load()
}

async function doDeleteAllFailed() {
  try { for (const t of completedTasks.value) { if (t.status === 'failed') await deletePublishTask(t.id) } }
  catch {}
  message.success('已删除失败')
  load()
}

onMounted(() => {
  wsMounted = true
  load()
  connectWS()
  initPending()
  loadChannels()
})

onUnmounted(() => {
  wsMounted = false
  if (elapsedTimer) clearInterval(elapsedTimer)
})
</script>

<template>
  <PageContainer>
    <PageHeader title="发布任务" icon="📤">
      <template v-if="completedTasks.length" #actions>
        <n-space :size="8">
          <n-button size="small" @click="showCompleted = !showCompleted">
            {{ showCompleted ? '收起历史' : '展开历史' }} ({{ completedTasks.length }})
          </n-button>
          <n-popconfirm @positive-click="doRetryAllFailed"><template #trigger><n-button size="small" type="primary">重试全部失败</n-button></template>确定重试所有失败任务？</n-popconfirm>
          <n-popconfirm @positive-click="doDeleteAllCompleted"><template #trigger><n-button size="small" type="warning">清空已完成</n-button></template>确定删除所有已完成任务？</n-popconfirm>
          <n-popconfirm @positive-click="doDeleteAllFailed"><template #trigger><n-button size="small" type="error">清空失败</n-button></template>确定删除所有失败任务？</n-popconfirm>
        </n-space>
      </template>
    </PageHeader>

    <!-- Pending batch -->
    <n-card v-if="pendingVideos.length" size="small" title="📋 待发布的视频" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:12px;display:block;margin-bottom:8px">从视频管理页面导航</n-text>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
        <n-text style="font-size:12px;white-space:nowrap">发布到：</n-text>
        <ChannelSelect v-model="pendingChannelId" size="small" width="200px" />
        <n-button type="primary" size="small" @click="batchPublishVids" :disabled="!pendingVideos.length">全部发布 ({{ pendingVideos.length }})</n-button>
      </div>
      <div v-for="v in pendingVideos" :key="v.id" style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--border-subtle);font-size:12px">
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ v.filename }}</n-text>
      </div>
    </n-card>

    <StatsGrid v-if="tasks.length" :cols="5" :items="[
      { label:'总任务', value: stats.total },
      { label:'已完成', value: stats.done },
      { label:'进行中', value: stats.running },
      { label:'排队中', value: stats.queued },
      { label:'失败', value: stats.failed },
    ]" />

    <n-empty v-if="!tasks.length && !pendingVideos.length" description="暂无发布任务" style="margin-top: 80px" />

    <!-- Active tasks -->
    <div v-if="activeTasks.length">
      <n-grid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
        <n-gi v-for="task in activeTasks" :key="task.id">
          <n-card size="small" :bordered="true" style="height:100%">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <div v-if="task.thumbnail_id" class="thumb-blur" style="width:40px;height:23px;overflow:hidden;border-radius:3px;flex-shrink:0">
                <n-image :src="getThumbnailImage(task.thumbnail_id)" width="100%" :preview-disabled="false" object-fit="cover" />
              </div>
              <div v-else style="width:40px;height:23px;border-radius:3px;background:var(--border-subtle);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:14px">🎬</div>
              <n-text style="flex:1;font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ task.video_name }}</n-text>
              <StatusTag :status="task.status" />
            </div>
            <n-progress type="line" :percentage="task.progress || 0" :height="10" :color="task.status==='failed'?'var(--color-red)':'var(--color-purple)'" :indicator-placement="'inside'" :processing="task.status==='running'||task.status==='uploading'" style="margin-bottom:6px" />
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
              <n-text depth="3" style="font-size:11px">{{ task.channel_name }}</n-text>
              <n-text v-if="task.status==='running'||task.status==='uploading'" depth="3" style="font-size:11px">
                {{ task.elapsed_sec ? Math.floor((task.elapsed_sec||0)/60)+'m'+Math.floor((task.elapsed_sec||0)%60)+'s' : '' }}
                <template v-if="task.eta_sec"> · 剩余 {{ Math.floor((task.eta_sec||0)/60) }}m</template>
              </n-text>
              <div style="margin-left:auto;display:flex;gap:4px">
                <n-popconfirm @positive-click="() => doCancel(task.id)"><template #trigger><n-button size="tiny" type="error">取消</n-button></template>确定取消？</n-popconfirm>
                <n-popconfirm @positive-click="() => doDelete(task.id)"><template #trigger><n-button size="tiny" type="error">删除</n-button></template>确定删除？</n-popconfirm>
              </div>
            </div>
          </n-card>
        </n-gi>
      </n-grid>
    </div>

    <!-- Completed tasks -->
    <template v-if="showCompleted && completedTasks.length">
      <n-divider style="margin: 16px 0" />
      <n-text depth="2" style="font-weight:600;margin-bottom:12px;display:block">已完成 ({{ completedTasks.length }})</n-text>
      <div v-for="(task, i) in completedTasks" :key="task.id || i" style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid var(--border-subtle);font-size:13px;opacity:0.75">
        <div v-if="task.thumbnail_id" class="thumb-blur" style="width:40px;height:23px;overflow:hidden;border-radius:3px;flex-shrink:0">
          <n-image :src="getThumbnailImage(task.thumbnail_id)" width="100%" :preview-disabled="false" object-fit="cover" />
        </div>
        <div v-else style="width:40px;height:23px;border-radius:3px;background:var(--border-subtle);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:14px">🎬</div>
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ task.video_name }}</n-text>
        <StatusTag :status="task.status" />
        <n-text v-if="task.error" depth="3" style="font-size:11px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ task.error.slice(0, 40) }}</n-text>
        <n-popconfirm @positive-click="() => doRetry(task.id)"><template #trigger><n-button size="tiny" type="primary">重试</n-button></template>确定重试？</n-popconfirm>
        <n-popconfirm @positive-click="() => doDelete(task.id)"><template #trigger><n-button size="tiny" type="error">删除</n-button></template>确定删除？</n-popconfirm>
      </div>
    </template>
  </PageContainer>
</template>
