<script setup lang="ts">
import { ref, onMounted, onUnmounted, h, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NProgress, NTag, NText, NEmpty, NSpace, NButton, NInputNumber,
  NPopconfirm, NImage, NGrid, NGi, NStatistic, NSelect, NSlider, NIcon, useMessage
} from 'naive-ui'
import { TimeOutline } from '@vicons/ionicons5'
import { fetchCompressJobs, cancelCompressJob, pauseJob, resumeJob, retryCompressJob, getThumbnailImage, publishNow, fetchChats, deleteCompressJob, batchDeleteCompress, submitCompress, updateCompressSettings, generateThumbnail } from '@/api/client'
import api from '@/api/client'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'

const message = useMessage()
const route = useRoute()
const router = useRouter()
const showCompleted = ref(false)
const expandedJobId = ref<number | null>(null)

// Pending config from VideoBrowser navigation
const pendingVideos = ref<any[]>([])
const pendingLoading = ref(false)
const pendingConfig = ref<Record<number, { preset: string; target_size_mb: number; width: number; height: number }>>({})
const resCache = ref<Record<number, string>>({})
const defaultPreset = ref('balanced')

async function initPendingVideos() {
  const ids = route.query.ids as string
  if (!ids) return
  pendingLoading.value = true
  try {
    const { data } = await api.get('/videos', { params: { page_size: 100 } })
    const idSet = new Set(ids.split(',').map(Number))
    pendingVideos.value = (data.items || []).filter((v: any) => idSet.has(v.id))
    for (const v of pendingVideos.value) {
      pendingConfig.value[v.id] = { preset: defaultPreset.value, target_size_mb: Math.min(Math.ceil((v.size_bytes || 0) / 1_000_000), 500) || 500, width: 0, height: 0 }
    }
  } catch {}
  pendingLoading.value = false
}

function updatePendingConfig(vid: number, key: string, val: any) {
  if (!pendingConfig.value[vid]) {
    const v = pendingVideos.value.find(p => p.id === vid)
    const mb = v ? Math.min(Math.ceil((v.size_bytes || 0) / 1_000_000), 500) || 500 : 500
    pendingConfig.value[vid] = { preset: defaultPreset.value, target_size_mb: mb, width: 0, height: 0 }
  }
  const cfg: any = pendingConfig.value[vid]
  cfg[key] = val
}

async function confirmPending(vid: number) {
  const cfg = pendingConfig.value[vid]
  if (!cfg) return
  message.loading('创建压缩任务...')
  try {
    const r = await submitCompress([vid], cfg.preset, cfg.target_size_mb, cfg.width, cfg.height)
    if ((r.jobs || []).length === 0) {
      message.warning('该视频已在压缩中或已压缩，无法重复添加')
      return
    }
    pendingVideos.value = pendingVideos.value.filter(v => v.id !== vid)
    message.success(`压缩任务已创建`)
    load()
  } catch { message.error('创建失败') }
}

async function confirmAll() {
  const ids = pendingVideos.value.map(v => v.id)
  message.loading('创建压缩任务...')
  for (const vid of ids) {
    const cfg = pendingConfig.value[vid]
    if (cfg) { await submitCompress([vid], cfg.preset, cfg.target_size_mb, cfg.width, cfg.height) }
  }
  pendingVideos.value = []
  message.success(`已创建 ${ids.length} 个压缩任务`)
  load()
}

async function batchSetAll(key: string, val: any) {
  for (const v of pendingVideos.value) {
    updatePendingConfig(v.id, key, val)
  }
}

function toggleExpand(jobId: number) {
  const next = expandedJobId.value === jobId ? null : jobId
  expandedJobId.value = next
  router.replace({ query: { ...route.query, ...(next ? { expanded: String(next) } : {}) } })
}

interface Job {
  id: number
  video_id: number
  video_name: string
  preset: string
  status: string
  progress: number
  output_size_bytes: number
  original_size_bytes: number
  target_size_mb: number
  eta_sec: number
  elapsed_sec: number
  speed: number
  fps: number
  stderr: string
  error_log: string
  thumbnail_id: number | null
  skip_reason: string
  phase: string
  finished_at: string
  is_published: boolean
  step_log: { step: string; elapsed: number; result: string; error?: string; speed?: number; output_gb?: number; thumb_id?: number }[]
}

const jobs = ref<Job[]>([])
const ws = ref<WebSocket | null>(null)
let reconnectTimer: number | undefined
let reconnectAttempts = 0

const stats = computed(() => {
  const total = jobs.value.length
  const done = jobs.value.filter(j => j.status === 'done').length
  const running = jobs.value.filter(j => j.status === 'running').length
  const failed = jobs.value.filter(j => j.status === 'failed').length
  const skipped = jobs.value.filter(j => j.status === 'skipped').length
  return { total, done, running, failed, skipped }
})

const activeJobs = computed(() => jobs.value.filter(j => j.status === 'running' || j.status === 'queued' || j.status === 'paused'))
const completedJobs = computed(() => jobs.value.filter(j => j.status === 'done' || j.status === 'skipped' || j.status === 'failed' || j.status === 'cancelled'))

function connectWS() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('access_token')
  ws.value = new WebSocket(`${protocol}//${location.host}/ws/compress?token=${token || ''}`)
  ws.value.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.type === 'job_start') {
      const existing = jobs.value.find((j) => j.id === msg.job_id)
      if (!existing) {
        jobs.value.unshift({
        id: msg.job_id, video_id: 0, video_name: msg.video,
        preset: msg.preset || 'balanced', status: 'running', progress: 0,
        output_size_bytes: 0, original_size_bytes: msg.original_size || 0,
        eta_sec: msg.eta_sec || 0, elapsed_sec: 0, speed: 0, fps: 0,
        stderr: '', error_log: '', thumbnail_id: msg.thumbnail_id || null, skip_reason: '',
        phase: msg.phase || 'encoding', step_log: [],
        target_size_mb: 0, finished_at: '', is_published: false,
      })
      }
    } else if (msg.type === 'progress') {
      const job = jobs.value.find((j) => j.id === msg.job_id)
      if (job) {
        job.progress = msg.percent; job.eta_sec = msg.eta_sec || 0
        job.elapsed_sec = msg.elapsed_sec || 0; job.speed = msg.speed || 0; job.fps = msg.fps || 0
        job.status = 'running'
        if (msg.phase) job.phase = msg.phase
        if (msg.step_log) job.step_log = msg.step_log
        if (msg.thumbnail_id) job.thumbnail_id = msg.thumbnail_id
      }
    } else if (msg.type === 'job_done') {
      const job = jobs.value.find((j) => j.id === msg.job_id)
      if (job) { job.status = 'done'; job.progress = 100; job.output_size_bytes = msg.output_size }
    } else if (msg.type === 'job_skip') {
      const job = jobs.value.find((j) => j.id === msg.job_id)
      if (job) { job.status = 'skipped'; job.progress = 100; job.skip_reason = msg.reason || ''; job.thumbnail_id = msg.thumbnail_id || null }
    } else if (msg.type === 'job_error') {
      const job = jobs.value.find((j) => j.id === msg.job_id)
      if (job) { job.status = 'failed'; job.stderr = msg.error || '' }
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

onMounted(async () => {
  try {
    const { data } = await api.get('/settings')
    if (data?.compress_preset) defaultPreset.value = data.compress_preset
  } catch {}
  const ex = route.query.expanded as string
  if (ex) expandedJobId.value = Number(ex)
  load()
  connectWS()
  initPendingVideos()
})

onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws.value?.close()
})

function thumbUrl(thumbnailId: number | null) {
  return thumbnailId ? getThumbnailImage(thumbnailId) : ''
}

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1_000_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB'
  return (bytes / 1_000_000_000).toFixed(2) + ' GB'
}

function formatEta(sec: number): string {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return m > 0 ? `剩余 ${m}m${s}s` : `剩余 ${s}s`
}

function formatElapsed(sec: number): string {
  if (!sec) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  if (h > 0) return `${h}h${m}m${s}s`
  return `${m}m${s}s`
}

function statusColor(status: string): string {
  return { running: 'var(--color-purple)', paused: '#faad14', done: 'var(--color-green)', failed: 'var(--color-red)', cancelled: '#aaa', skipped: '#5e9eff' }[status] || '#888'
}

function statusLabel(status: string): string {
  return { running: '压缩中', paused: '已暂停', done: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过', queued: '等待中' }[status] || status
}

function presetLabel(preset: string): string {
  return { fast: '极速 (H.264)', balanced: '均衡 (H.265)', high_quality: '高画质 (2-pass)' }[preset] || preset
}

async function doCancel(jobId: number) {
  try { await cancelCompressJob(jobId); message.success('已取消') } catch { message.error('取消失败') }
}

async function doPause(jobId: number) {
  try { await pauseJob(jobId); message.success('已暂停') } catch { message.error('暂停失败') }
}

async function doGenerateThumb(videoId: number) {
  try {
    const r = await generateThumbnail(videoId)
    message.success(`缩略图已生成 (${r.width}×${r.height})`)
    load()
  } catch { message.error('生成缩略图失败') }
}

async function doResume(jobId: number) {
  try { await resumeJob(jobId); message.success('已恢复') } catch { message.error('恢复失败') }
}

async function doRetry(jobId: number) {
  try { await retryCompressJob(jobId); message.success('已重试'); load() } catch { message.error('重试失败') }
}

const retryConfig = ref<Record<number, { preset: string; target_size_mb: number }>>({})

function initRetryConfig(job: Job) {
  if (!retryConfig.value[job.id]) {
    retryConfig.value[job.id] = { preset: job.preset || defaultPreset.value, target_size_mb: 500 }
  }
}

async function doRetryWithConfig(job: Job) {
  if (!retryConfig.value[job.id]) {
    retryConfig.value[job.id] = {
      preset: job.preset || defaultPreset.value,
      target_size_mb: job.target_size_mb || 500,
    }
  }
  const cfg = retryConfig.value[job.id]
  if (cfg) {
    await updateCompressSettings(job.id, cfg)
    delete retryConfig.value[job.id]
  }
  await doRetry(job.id)
}

async function doPublish(job: Job) {
  if (!job.video_id) { message.warning('无关联视频'); return }
  try {
    const d = await fetchChats()
    const ch = (d.items || [])[0]
    if (!ch) { message.warning('无可用的频道，请先添加频道'); return }
    await publishNow(job.video_id, ch.chat_id)
    message.success(`发布任务已提交: ${job.video_name}`)
  } catch { message.error('发布失败') }
}

async function doDeleteJob(jobId: number) {
  try { await deleteCompressJob(jobId); message.success('已删除'); load() }
  catch { message.error('删除失败') }
}

async function doBatchDelete(status: string) {
  try {
    const r = await batchDeleteCompress(status)
    message.success(`已删除 ${r.deleted || 0} 条`)
    load()
  } catch { message.error('批量删除失败') }
}

async function load() {
  try {
    const data = await fetchCompressJobs()
    jobs.value = (data.items || []).map((j: any) => ({...j, skip_reason: j.status === 'skipped' ? (j.original_size_bytes ? `${formatSize(j.original_size_bytes)}（未压缩）` : '已跳过') : ''}))
  } catch { message.error('加载压缩任务失败') }
}
</script>

<template>
  <PageContainer>
    <PageHeader title="压缩任务" icon="⚡" />

    <n-grid v-if="jobs.length" :cols="4" :x-gap="12" style="margin-bottom: 20px">
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align:center">
          <n-statistic label="总任务" :value="stats.total" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align:center;background:var(--bg-green)">
          <n-statistic label="已完成" :value="stats.done" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align:center;background:var(--bg-purple)">
          <n-statistic label="进行中" :value="stats.running" />
        </n-card>
      </n-gi>
      <n-gi>
        <n-card size="small" :bordered="true" style="text-align:center;background:rgba(230,78,78,0.06)">
          <n-statistic label="失败" :value="stats.failed" />
        </n-card>
      </n-gi>
    </n-grid>

    <n-empty v-if="!jobs.length && !pendingVideos.length" description="暂无压缩任务，去视频管理页面选中视频后压缩" style="margin-top: 80px" />

    <!-- Pending configuration from VideoBrowser -->
    <div v-if="pendingVideos.length" style="margin-bottom: 20px; padding: 16px; background: var(--bg-subtle); border-radius: 8px;">
      <n-text strong style="font-size: 14px; display: block; margin-bottom: 12px;">待配置 ({{ pendingVideos.length }})</n-text>
      <div v-for="v in pendingVideos" :key="v.id" style="margin-bottom: 10px; padding: 10px; background: var(--bg-card); border-radius: 6px; border: 1px solid var(--border-subtle)">
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12px;">
          <n-text strong style="width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0;">{{ v.filename }}</n-text>
          <n-text depth="3">{{ formatSize(v.size_bytes) }}</n-text>
          <n-text depth="3" v-if="v.width">{{ v.width }}×{{ v.height }}</n-text>
          <n-select v-model:value="pendingConfig[v.id].preset" size="tiny" style="width: 120px" :options="[ { label:'极速 H.264', value:'fast' }, { label:'均衡 H.265', value:'balanced' }, { label:'高画质', value:'high_quality' } ]" />
          <n-input-number v-model:value="pendingConfig[v.id].target_size_mb" size="tiny" :min="10" :max="10000" style="width: 80px" placeholder="MB" /><n-text depth="3" style="font-size: 11px;">MB</n-text>
          <n-select v-model:value="resCache[v.id]" size="tiny" style="width: 90px" @update:value="(val: string) => { const [w,h]=val.split('x').map(Number); updatePendingConfig(v.id,'width',w); updatePendingConfig(v.id,'height',h) }"
            :options="[{label:'原尺寸',value:'0x0'},{label:'4K',value:'3840x2160'},{label:'1080p',value:'1920x1080'},{label:'720p',value:'1280x720'},{label:'480p',value:'854x480'}]" />
          <div style="margin-left: auto; display: flex; gap: 6px;">
            <n-button size="tiny" type="primary" @click="confirmPending(v.id)">确认</n-button>
            <n-button size="tiny" @click="pendingVideos = pendingVideos.filter(p => p.id !== v.id)">移除</n-button>
          </div>
        </div>
      </div>
      <n-space :size="6" style="margin-top: 8px;">
        <n-button size="tiny" @click="batchSetAll('preset', 'balanced')">全部均衡</n-button>
        <n-button size="tiny" @click="batchSetAll('target_size_mb', 500)">全部 500MB</n-button>
        <n-button size="tiny" type="primary" @click="confirmAll">全部确认</n-button>
      </n-space>
    </div>

    <!-- Active jobs -->
    <n-space vertical :size="12" v-if="activeJobs.length">
      <n-text depth="3" style="font-size: 12px;">进行中 · 排队中 ({{ activeJobs.length }})</n-text>
      <n-card v-for="job in activeJobs" :key="job.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(job.status)}`, background: 'var(--bg-subtle)', cursor: 'pointer' }"
        @click="toggleExpand(job.id)">
        <div style="display: flex; gap: 14px">
          <div v-if="job.thumbnail_id" class="thumb-blur" style="flex-shrink: 0; width: 120px; height: 68px; border-radius: 6px; overflow: hidden; background: rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(job.thumbnail_id)" :width="120" :height="68" object-fit="cover" :show-toolbar="false" />
          </div>
          <div v-else style="flex-shrink: 0; width: 120px; height: 68px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.3)">
            <span style="font-size: 24px; opacity: 0.3">🎬</span>
          </div>
          <div style="flex: 1; min-width: 0">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px">
              <div style="min-width: 0">
                <n-text strong style="font-size: 14px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ job.video_name }}</n-text>
                <n-text depth="3" style="font-size: 11px;">{{ presetLabel(job.preset) }}</n-text>
              </div>
              <n-tag :type="job.status === 'running' ? 'warning' : 'default'" size="small" :bordered="false" round>{{ statusLabel(job.status) }}</n-tag>
            </div>
            <n-text v-if="job.phase" depth="3" style="font-size:10px;display:block;margin-bottom:4px">{{ job.phase === 'thumbnail' ? '🖼 正在提取缩略图' : job.phase === 'encoding' ? '🎞 正在编码' : job.phase === 'retry_pass2' ? '🔄 二阶段重试' : job.phase }}</n-text>
            <n-text v-else-if="job.status === 'queued'" depth="3" style="font-size:10px;display:block;margin-bottom:4px">🕐 排队中</n-text>
            <n-progress type="line" :percentage="job.progress || 0" :height="16" :border-radius="8" :color="statusColor(job.status)" :indicator-placement="'inside'" :processing="job.status === 'running'" />
            <div style="margin-top: 8px; display: flex; align-items: center; gap: 10px; font-size: 12px;">
              <n-text depth="3" style="flex: 1; display: flex; align-items: center; gap: 4px;">
                <n-icon :size="14"><TimeOutline /></n-icon>
                {{ formatElapsed(job.elapsed_sec) }}
                <template v-if="job.eta_sec"> · {{ formatEta(job.eta_sec) }}</template>
                <template v-if="job.speed"> · {{ job.speed }}x</template>
                <template v-if="job.fps"> · {{ job.fps }}fps</template>
              </n-text>
              <n-space :size="6">
                <template v-if="job.status === 'running'">
                  <n-button size="tiny" @click.stop="doPause(job.id)">暂停</n-button>
                  <n-popconfirm @positive-click="() => doCancel(job.id)">
                    <template #trigger><n-button size="tiny" @click.stop>取消</n-button></template>
                    <template #action><n-button size="tiny" type="primary" @click="() => doCancel(job.id)">确定</n-button><n-button size="tiny" style="margin-left:8px">取消</n-button></template>
                    确定取消？
                  </n-popconfirm>
                </template>
                <template v-if="job.status === 'paused'">
                  <n-button size="tiny" type="primary" @click.stop="doResume(job.id)">继续</n-button>
                  <n-popconfirm @positive-click="() => doCancel(job.id)">
                    <template #trigger><n-button size="tiny" @click.stop>取消</n-button></template>
                    <template #action><n-button size="tiny" type="primary" @click="() => doCancel(job.id)">确定</n-button><n-button size="tiny" style="margin-left:8px">取消</n-button></template>
                    确定取消？
                  </n-popconfirm>
                  <n-popconfirm @positive-click="() => doDeleteJob(job.id)">
                    <template #trigger><n-button size="tiny" type="error" @click.stop>删除</n-button></template>
                    <template #action><n-button size="tiny" type="error" @click="() => doDeleteJob(job.id)">确定</n-button><n-button size="tiny" style="margin-left:8px">取消</n-button></template>
                    确定删除？
                  </n-popconfirm>
                </template>
                <template v-if="job.status === 'queued'">
                  <n-popconfirm @positive-click="() => doDeleteJob(job.id)">
                    <template #trigger><n-button size="tiny" type="error" @click.stop>删除</n-button></template>
                    <template #action><n-button size="tiny" type="error" @click="() => doDeleteJob(job.id)">确定</n-button><n-button size="tiny" style="margin-left:8px">取消</n-button></template>
                    确定删除？
                  </n-popconfirm>
                </template>
              </n-space>
            </div>
            <div v-if="expandedJobId === job.id" style="margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border-subtle)">
              <div v-if="job.step_log && job.step_log.length" style="margin-bottom: 6px">
                <n-text depth="3" style="font-size: 11px; display: block; margin-bottom: 2px;">步骤日志：</n-text>
                <n-text v-for="(s,i) in job.step_log" :key="i" depth="3" style="font-size: 11px; display: block;">
                  {{ i+1 }}. {{ s.step }} — {{ s.elapsed }}s {{ s.result }}{{ s.speed ? ' · '+s.speed+'x' : '' }}{{ s.output_gb ? ' · '+s.output_gb+'GB' : '' }}{{ s.thumb_id ? ' · #'+s.thumb_id : '' }}{{ s.error ? ': '+s.error.slice(0,60) : '' }}
                </n-text>
              </div>
              <n-text depth="3" style="font-size: 11px; white-space: pre-wrap; font-family: monospace; word-break: break-all; max-height: 200px; overflow-y: auto; display: block;">
                {{ job.stderr || job.error_log || '暂无详情' }}
              </n-text>
            </div>
          </div>
        </div>
      </n-card>
    </n-space>

    <!-- Completed jobs -->
    <div v-if="completedJobs.length" style="margin-top: 20px">
      <n-button size="tiny" @click="showCompleted = !showCompleted">
        {{ showCompleted ? '收起历史' : `展开历史 (${completedJobs.length})` }}
      </n-button>
    </div>
    <n-space v-if="showCompleted && completedJobs.length" vertical :size="12" style="margin-top: 12px">
      <n-card v-for="job in completedJobs" :key="job.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(job.status)}`, background: 'var(--bg-subtle)', opacity: showCompleted ? 0.7 : 0, cursor: 'pointer' }"
        @click="toggleExpand(job.id)">
        <div style="display: flex; gap: 14px">
          <div v-if="job.thumbnail_id" class="thumb-blur" style="flex-shrink: 0; width: 80px; height: 45px; border-radius: 4px; overflow: hidden; background: rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(job.thumbnail_id)" :width="80" :height="45" object-fit="cover" :show-toolbar="false" />
          </div>
          <div style="flex: 1; min-width: 0">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
              <div style="min-width: 0">
                <n-text strong style="font-size: 13px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ job.video_name }}</n-text>
                <n-text depth="3" style="font-size: 11px;">{{ presetLabel(job.preset) }}</n-text>
              </div>
              <div style="display: flex; gap: 6px; align-items: center; flex-shrink: 0">
                <n-tag :type="job.status === 'done' ? 'success' : job.status === 'failed' ? 'error' : job.status === 'skipped' ? 'info' : 'default'" size="small" :bordered="false" round>{{ statusLabel(job.status) }}</n-tag>
                <n-tag v-if="job.is_published" type="success" size="small" :bordered="false" round>📤 已发布</n-tag>
              </div>
            </div>
            <div style="font-size: 12px;">
              <n-text v-if="job.finished_at" depth="3" style="font-size:10px;display:block;margin-bottom:2px">完成的于 {{ new Date(job.finished_at).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}) }}</n-text>
              <n-text v-if="job.status === 'done'" style="color: var(--color-green)">
                {{ formatSize(job.original_size_bytes) }} → {{ formatSize(job.output_size_bytes) }}
              </n-text>
              <n-text v-else-if="job.status === 'skipped'" style="color: #5e9eff">{{ job.skip_reason || '已跳过' }}</n-text>
                <n-text v-else-if="job.status === 'failed' && job.stderr" depth="3" style="display: block; margin-top: 4px; font-size: 11px; font-family: monospace; word-break: break-all; max-height: 60px; overflow: hidden; text-overflow: ellipsis;">{{ job.stderr.slice(0, 200) }}</n-text>
              </div>
              <div style="margin-top: 4px; display: flex; gap: 6px; flex-wrap: wrap;">
                <n-button size="tiny" @click.stop="toggleExpand(job.id)">{{ expandedJobId === job.id ? '收起' : '详情' }}</n-button>
                <n-button v-if="job.status === 'done' || job.status === 'skipped'" size="tiny" @click.stop="doPublish(job)">发布</n-button>
                <n-button v-if="job.status === 'failed' || job.status === 'cancelled'" size="tiny" @click.stop="doPublish(job)">发布</n-button>
                <n-button v-if="job.status === 'failed' || job.status === 'skipped' || job.status === 'cancelled'" size="tiny" type="primary" @click.stop="doRetryWithConfig(job)">重试</n-button>
                <n-button v-if="(job.status === 'done' || job.status === 'skipped') && !job.thumbnail_id" size="tiny" @click.stop="doGenerateThumb(job.video_id)">🖼 生成缩略图</n-button>
                <n-popconfirm @positive-click="() => doDeleteJob(job.id)">
                  <template #trigger><n-button size="tiny" type="error" @click.stop>删除</n-button></template>
                  <template #action><n-button size="tiny" type="error" @click="() => doDeleteJob(job.id)">确定</n-button><n-button size="tiny" style="margin-left:8px">取消</n-button></template>
                  确定删除？
                </n-popconfirm>
              </div>
              <div v-if="expandedJobId === job.id" style="margin-top: 8px; padding-top: 6px; border-top: 1px solid var(--border-subtle)">
                <div v-if="job.step_log && job.step_log.length" style="margin-bottom: 6px">
                  <n-text depth="3" style="font-size: 11px; display: block; margin-bottom: 2px;">步骤日志：</n-text>
                  <n-text v-for="(s,i) in job.step_log" :key="i" depth="3" style="font-size: 11px; display: block;">
                    {{ i+1 }}. {{ s.step }} — {{ s.elapsed }}s {{ s.result }}{{ s.speed ? ' · '+s.speed+'x' : '' }}{{ s.output_gb ? ' · '+s.output_gb+'GB' : '' }}{{ s.thumb_id ? ' · #'+s.thumb_id : '' }}{{ s.error ? ': '+s.error.slice(0,60) : '' }}
                  </n-text>
                </div>
                <n-text depth="3" style="font-size: 11px; white-space: pre-wrap; font-family: monospace; word-break: break-all; max-height: 200px; overflow-y: auto; display: block;">{{ job.stderr || job.error_log || '暂无详情' }}</n-text>
                <template v-if="job.status === 'failed' || job.status === 'skipped' || job.status === 'cancelled'">
                  <n-space :size="6" style="margin-top: 6px">
                    <n-text depth="3" style="font-size:10px">重试参数:</n-text>
                    <n-select v-model:value="retryConfig[job.id].preset" size="tiny" style="width:110px" :options="[{label:'极速 H.264',value:'fast'},{label:'均衡 H.265',value:'balanced'},{label:'高画质',value:'high_quality'}]" @click.stop />
                    <n-input-number v-model:value="retryConfig[job.id].target_size_mb" size="tiny" :min="10" :max="10000" style="width:70px" @click.stop /><n-text depth="3" style="font-size:10px">MB</n-text>
                  </n-space>
                </template>
              </div>
            </div>
          </div>
        </n-card>
      </n-space>

      <n-space v-if="showCompleted" style="margin-top:8px" :size="6">
        <n-popconfirm @positive-click="() => doBatchDelete('done')">
          <template #trigger><n-button size="tiny">删除已完成</n-button></template>
          <template #action><n-button size="tiny" type="primary" @click="() => doBatchDelete('done')">确定</n-button><n-button size="tiny" style="margin-left:8px">取消</n-button></template>
          确定删除所有已完成？
        </n-popconfirm>
        <n-popconfirm @positive-click="() => doBatchDelete('')">
          <template #trigger><n-button size="tiny" type="error">删除全部历史</n-button></template>
          <template #action><n-button size="tiny" type="error" @click="() => doBatchDelete('')">确定</n-button><n-button size="tiny" style="margin-left:8px">取消</n-button></template>
          确定删除所有历史任务？
        </n-popconfirm>
      </n-space>
  </PageContainer>
</template>
