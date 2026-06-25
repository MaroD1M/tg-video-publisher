<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  NCard, NProgress, NTag, NText, NEmpty, NSpace, NButton, NImage,
  NPopconfirm, NDivider, NGrid, NGi, useMessage,
} from 'naive-ui'
import {
  fetchPublishTasks, cancelPublishTask, retryPublishTask, getThumbnailImage,
  regenerateThumbnail, pausePublishTask, resumePublishTask, reorderPublishTask,
  deletePublishTask, batchPublish, fetchVideos,
} from '@/api/client'
import { useWebSocket } from '@/composables/useWebSocket'
import { useChannels } from '@/composables/useChannels'
import { formatChannelLabel, formatElapsed } from '@/utils/format'
import type { Video } from '@/types'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import StatusTag from '@/components/shared/StatusTag.vue'
import ChannelSelect from '@/components/shared/ChannelSelect.vue'
import StatsGrid from '@/components/shared/StatsGrid.vue'

const message = useMessage()
const route = useRoute()
const pendingVideos = ref<Video[]>([])
const pendingChannelId = ref<number | null>(null)
const { load: loadChannels } = useChannels()
const recentToasts = new Map<string, number>()

function dedupedToast(type: 'success'|'error', videoName: string, msg: string) {
  const now = Date.now()
  const last = recentToasts.get(videoName) || 0
  if (now - last < 5000) return
  recentToasts.set(videoName, now)
  if (recentToasts.size > 100) {
    for (const [k, v] of recentToasts) { if (now - v > 10000) recentToasts.delete(k) }
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

interface PublishTask {
  id: number; video_id: number | null; video_name: string; channel_name: string
  status: string; progress: number; elapsed_sec: number; eta_sec: number
  compression_ratio: number | null; error_log: string; thumbnail_id: number | null
  created_at: string; is_paused: boolean; step_log: { step: string; elapsed: number; result: string; error?: string; speed_kbs?: number }[]
}

const tasks = ref<PublishTask[]>([])
const showCompleted = ref(false)
const expandedTaskId = ref<number | null>(null)

function toggleExpand(id: number) {
  expandedTaskId.value = expandedTaskId.value === id ? null : id
}

const stats = computed(() => {
  const total = tasks.value.length; const done = tasks.value.filter(t => t.status === 'done').length
  const running = tasks.value.filter(t => t.status === 'running' || t.status === 'uploading').length
  const queued = tasks.value.filter(t => t.status === 'queued').length
  const failed = tasks.value.filter(t => t.status === 'failed').length
  return { total, done, running, queued, failed }
})

const activeTasks = computed(() => tasks.value.filter(t => t.status === 'queued' || t.status === 'running' || t.status === 'uploading'))
const completedTasks = computed(() => tasks.value.filter(t => t.status === 'done' || t.status === 'failed' || t.status === 'cancelled'))

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

function stopElapsedTimer() {
  const active = tasks.value.some(t => t.status === 'running' || t.status === 'uploading')
  if (!active && elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = undefined }
}

const { connect: connectWS } = useWebSocket(
  '/ws/compress',
  (e) => {
    try {
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
        startElapsedTimer()
      } else if (msg.type === 'publish_done') {
        const t = tasks.value.find(j => j.id === msg.task_id)
        if (t) { t.status = 'done'; t.progress = 100 }
        stopElapsedTimer()
        dedupedToast('success', msg.video_name, `发布成功: ${msg.video_name}`)
        load()
      } else if (msg.type === 'publish_error') {
        const t = tasks.value.find(j => j.id === msg.task_id)
        if (t) { t.status = 'failed'; t.error_log = msg.error || '' }
        stopElapsedTimer()
        dedupedToast('error', msg.video_name, `发布失败: ${msg.video_name}`)
        load()
      } else if (msg.type === 'publish_cancelled') {
        const t = tasks.value.find(j => j.id === msg.task_id)
        if (t) t.status = 'cancelled'
        stopElapsedTimer()
        load()
      }
    } catch {}
  }
)

async function load() { try { tasks.value = ((await fetchPublishTasks({ page_size: 100 })).items || []) as PublishTask[] } catch { message.error('加载发布任务失败') } }
async function doCancel(taskId: number) { try { await cancelPublishTask(taskId); message.success('已取消'); load() } catch { message.error('取消失败') } }
async function doRetry(taskId: number) { try { await retryPublishTask(taskId); message.success('已重新加入队列'); load() } catch { message.error('重试失败') } }
async function doRegenerateThumb(taskId: number) {
  const t = tasks.value.find(j => j.id === taskId)
  if (!t || !t.thumbnail_id) { message.warning('没有缩略图'); return }
  try { await regenerateThumbnail(t.thumbnail_id); message.success('缩略图已重新生成') } catch { message.error('重新生成失败') }
}
async function doPause(taskId: number) { try { await pausePublishTask(taskId); load() } catch { message.error('暂停失败') } }
async function doResume(taskId: number) { try { await resumePublishTask(taskId); load() } catch { message.error('恢复失败') } }
async function doReorder(taskId: number, dir: 'up' | 'down') { try { await reorderPublishTask(taskId, dir); load() } catch { message.error('排序失败') } }
async function doDelete(taskId: number) { try { await deletePublishTask(taskId); load() } catch { message.error('删除失败') } }

async function doRetryAllFailed() {
  const failed = tasks.value.filter(t => t.status === 'failed')
  for (const t of failed) { try { await retryPublishTask(t.id) } catch {} }
  message.success(`已重试 ${failed.length} 个失败任务`)
  load()
}
async function doDeleteAllCompleted() {
  try { for (const t of completedTasks.value) { if (t.status === 'done') await deletePublishTask(t.id) } } catch {}
  message.success('已删除已完成')
  load()
}
async function doDeleteAllFailed() {
  try { for (const t of completedTasks.value) { if (t.status === 'failed') await deletePublishTask(t.id) } } catch {}
  message.success('已删除失败')
  load()
}

function thumbUrl(id: number | null) { return id ? getThumbnailImage(id) : '' }
function statusColor(s: string): string { return { running:'var(--color-purple)',uploading:'var(--color-purple)',done:'var(--color-green)',failed:'var(--color-red)',cancelled:'#aaa',queued:'#5e9eff' }[s]||'#888' }
function statusLabel(s: string): string { return { running:'处理中',uploading:'上传中',done:'已完成',failed:'失败',cancelled:'已取消',queued:'排队中' }[s]||s }

onMounted(() => { load(); connectWS(); initPending(); loadChannels() })
onUnmounted(() => { if (elapsedTimer) clearInterval(elapsedTimer) })
</script>

<template>
  <PageContainer>
    <PageHeader title="发布任务" icon="📤">
      <template v-if="completedTasks.length">
        <n-space :size="6" style="margin-bottom: 8px">
          <n-button size="small" @click="showCompleted = !showCompleted">{{ showCompleted ? '收起历史' : `展开历史 (${completedTasks.length})` }}</n-button>
          <n-popconfirm @positive-click="doRetryAllFailed"><template #trigger><n-button size="small" type="primary">重试全部失败</n-button></template>确定重试所有失败任务？</n-popconfirm>
          <n-popconfirm @positive-click="doDeleteAllCompleted"><template #trigger><n-button size="small" type="warning">清空已完成</n-button></template>确定删除所有已完成任务？</n-popconfirm>
          <n-popconfirm @positive-click="doDeleteAllFailed"><template #trigger><n-button size="small" type="error">清空失败</n-button></template>确定删除所有失败任务？</n-popconfirm>
        </n-space>
      </template>
    </PageHeader>

    <StatsGrid v-if="tasks.length" :cols="5" :items="[
      { label:'总任务', value: stats.total }, { label:'已完成', value: stats.done },
      { label:'进行中', value: stats.running }, { label:'排队中', value: stats.queued }, { label:'失败', value: stats.failed },
    ]" />

    <n-empty v-if="!tasks.length && !pendingVideos.length" description="暂无发布任务" style="margin-top: 80px" />

    <!-- Pending batch -->
    <div v-if="pendingVideos.length" style="margin-bottom:20px;padding:12px;background:var(--bg-subtle);border-radius:8px">
      <n-text strong style="font-size:13px;display:block;margin-bottom:8px">待发布 ({{ pendingVideos.length }})</n-text>
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">
        <n-text v-for="v in pendingVideos" :key="v.id" depth="3" style="font-size:12px">🎬 {{ v.filename }}</n-text>
      </div>
      <n-space :size="8">
        <ChannelSelect v-model="pendingChannelId" size="small" width="200px" />
        <n-button size="small" type="primary" @click="batchPublishVids">全部发布</n-button>
      </n-space>
    </div>

    <!-- Active tasks -->
    <n-space vertical :size="12" v-if="activeTasks.length">
      <n-text depth="3" style="font-size:12px">进行中 · 排队中 ({{ activeTasks.length }})</n-text>
      <n-card v-for="task in activeTasks" :key="task.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(task.status)}`, cursor: 'pointer' }"
        @click="toggleExpand(task.id)">
        <div style="display:flex;gap:14px">
          <div v-if="task.thumbnail_id" class="thumb-blur" style="flex-shrink:0;width:120px;height:68px;border-radius:6px;overflow:hidden;background:rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(task.thumbnail_id)" :width="120" :height="68" object-fit="cover" :show-toolbar="false" />
          </div>
          <div v-else style="flex-shrink:0;width:120px;height:68px;border-radius:6px;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.3)"><span style="font-size:24px;opacity:0.3">📤</span></div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
              <div style="min-width:0">
                <n-text strong style="font-size:14px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ task.video_name }}</n-text>
                <n-text v-if="task.channel_name" depth="3" style="font-size:11px">→ {{ task.channel_name }}</n-text>
              </div>
              <StatusTag :status="task.status" />
            </div>
            <n-progress type="line" :percentage="task.progress||0" :height="16" :border-radius="8" :color="statusColor(task.status)" :indicator-placement="'inside'" :processing="task.status==='running'||task.status==='uploading'" />
            <div style="margin-top:8px;display:flex;align-items:center;gap:10px;font-size:12px;flex-wrap:wrap">
              <n-text depth="3">⏱ {{ formatElapsed(task.elapsed_sec) }}<template v-if="task.eta_sec"> · 剩余 {{ formatElapsed(task.eta_sec) }}</template></n-text>
              <n-space :size="6" style="margin-left:auto">
                <n-button v-if="task.status==='queued' && !task.is_paused" size="tiny" @click.stop="doPause(task.id)">暂停</n-button>
                <n-button v-if="task.status==='queued' && task.is_paused" size="tiny" type="primary" @click.stop="doResume(task.id)">恢复</n-button>
                <n-button v-if="task.status==='queued'" size="tiny" @click.stop="doReorder(task.id, 'up')">↑</n-button>
                <n-button v-if="task.status==='queued'" size="tiny" @click.stop="doReorder(task.id, 'down')">↓</n-button>
                <n-popconfirm @positive-click="() => doCancel(task.id)"><template #trigger><n-button size="tiny">取消</n-button></template>确定取消此任务？</n-popconfirm>
              </n-space>
            </div>
            <div v-if="expandedTaskId===task.id" style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border-subtle)">
              <n-text v-if="task.error_log" depth="3" style="font-size:11px;white-space:pre-wrap;font-family:monospace;word-break:break-all;display:block">{{ task.error_log }}</n-text>
              <n-text v-else depth="3">暂无详情</n-text>
            </div>
          </div>
        </div>
      </n-card>
    </n-space>

    <!-- Completed toggle -->
    <div v-if="!showCompleted && completedTasks.length" style="margin-top:20px">
      <n-button size="tiny" @click="showCompleted = true">展开历史 ({{ completedTasks.length }})</n-button>
    </div>

    <!-- Completed tasks -->
    <n-space v-if="showCompleted && completedTasks.length" vertical :size="12" style="margin-top:12px">
      <n-card v-for="task in completedTasks" :key="task.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(task.status)}`, opacity: 0.7, cursor: 'pointer' }"
        @click="toggleExpand(task.id)">
        <div style="display:flex;gap:14px">
          <div v-if="task.thumbnail_id" class="thumb-blur" style="flex-shrink:0;width:80px;height:45px;border-radius:4px;overflow:hidden;background:rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(task.thumbnail_id)" :width="80" :height="45" object-fit="cover" :show-toolbar="false" />
          </div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;align-items:flex-start">
              <div style="min-width:0">
                <n-text strong style="font-size:13px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ task.video_name }}</n-text>
                <n-text v-if="task.channel_name" depth="3" style="font-size:11px">→ {{ task.channel_name }}</n-text>
              </div>
              <StatusTag :status="task.status" />
            </div>
            <div style="font-size:12px">
              <n-text v-if="task.status==='done'">⏱ {{ formatElapsed(task.elapsed_sec) }}</n-text>
              <n-text v-else-if="task.status==='failed' && task.error_log" depth="3" style="color:var(--color-red);font-size:11px;display:block">{{ task.error_log.slice(0,100) }}</n-text>
            </div>
            <div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap">
              <n-button size="tiny" @click.stop="toggleExpand(task.id)">{{ expandedTaskId===task.id?'收起':'详情' }}</n-button>
              <n-button v-if="task.status==='failed'||task.status==='cancelled'" size="tiny" type="primary" @click.stop="doRetry(task.id)">重新发布</n-button>
              <n-button v-if="task.status==='done'" size="tiny" @click.stop="doRetry(task.id)">重新发布</n-button>
              <n-button v-if="task.thumbnail_id" size="tiny" @click.stop="doRegenerateThumb(task.id)">重生成缩略图</n-button>
              <span @click.stop><n-popconfirm @positive-click="() => doDelete(task.id)"><template #trigger><n-button size="tiny" type="error">删除</n-button></template>确定删除此记录？</n-popconfirm></span>
            </div>
            <div v-if="expandedTaskId===task.id" style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border-subtle)">
              <div v-if="task.step_log && task.step_log.length" style="margin-bottom:6px">
                <n-text depth="3" style="font-size:11px;display:block;margin-bottom:2px">步骤日志：</n-text>
                <n-text v-for="(s,i) in task.step_log" :key="i" depth="3" style="font-size:11px;display:block">
                  {{ i+1 }}. {{ s.step }} — {{ s.elapsed }}s {{ s.result }}{{ s.speed_kbs ? ' · '+s.speed_kbs+'KB/s' : '' }}{{ s.error ? ': '+s.error.slice(0,60) : '' }}
                </n-text>
              </div>
              <n-text v-if="task.error_log" depth="3" style="font-size:11px;white-space:pre-wrap;font-family:monospace;word-break:break-all;max-height:200px;overflow-y:auto;display:block">{{ task.error_log }}</n-text>
              <n-text v-else depth="3">暂无详情</n-text>
            </div>
          </div>
        </div>
      </n-card>
    </n-space>
  </PageContainer>
</template>
