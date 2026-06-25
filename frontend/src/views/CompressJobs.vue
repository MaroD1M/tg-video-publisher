<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NProgress, NTag, NText, NEmpty, NSpace, NButton, NInputNumber,
  NPopconfirm, NImage, NGrid, NGi, NSelect, NIcon, NDivider, useMessage
} from 'naive-ui'
import { TimeOutline } from '@vicons/ionicons5'
import {
  fetchCompressJobs, cancelCompressJob, pauseJob, resumeJob, retryCompressJob,
  getThumbnailImage, publishNow, deleteCompressJob, batchDeleteCompress,
  submitCompress, updateCompressSettings, generateThumbnail, fetchVideos,
} from '@/api/client'
import { useSettingsStore } from '@/stores/settings'
import { useWebSocket } from '@/composables/useWebSocket'
import { useChannels } from '@/composables/useChannels'
import { formatSize } from '@/utils/format'
import type { CompressJobData, Video } from '@/types'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import StatusTag from '@/components/shared/StatusTag.vue'
import StatsGrid from '@/components/shared/StatsGrid.vue'

const message = useMessage()
const route = useRoute()
const router = useRouter()
const showCompleted = ref(false)
const expandedJobId = ref<number | null>(null)
const settingsStore = useSettingsStore()
const { channels, load: loadChannels } = useChannels()

const pendingVideos = ref<Video[]>([])
const pendingLoading = ref(false)
const pendingConfig = ref<Record<number, { preset: string; target_size_mb: number; width: number; height: number }>>({})
const resCache = ref<Record<number, string>>({})
const defaultPreset = ref('balanced')
let compressPreset = 'balanced'

async function initPendingVideos() {
  const ids = route.query.ids as string
  if (!ids) return
  pendingLoading.value = true
  try {
    const data = await fetchVideos({ page_size: 100 })
    const idSet = new Set(ids.split(',').map(Number))
    pendingVideos.value = (data.items || []).filter((v: any) => idSet.has(v.id))
    for (const v of pendingVideos.value) {
      pendingConfig.value[v.id] = { preset: compressPreset, target_size_mb: Math.min(Math.ceil((v.size_bytes || 0) / 1_000_000), 500) || 500, width: 0, height: 0 }
    }
  } catch {}
  pendingLoading.value = false
}

function updatePendingConfig(vid: number, key: string, val: any) {
  if (!pendingConfig.value[vid]) {
    const v = pendingVideos.value.find(p => p.id === vid)
    const mb = v ? Math.min(Math.ceil((v.size_bytes || 0) / 1_000_000), 500) || 500 : 500
    pendingConfig.value[vid] = { preset: compressPreset, target_size_mb: mb, width: 0, height: 0 }
  }
  ;(pendingConfig.value[vid] as any)[key] = val
}

async function confirmPending(vid: number) {
  const cfg = pendingConfig.value[vid]
  if (!cfg) return
  message.loading('创建压缩任务...')
  try {
    const r = await submitCompress([vid], cfg.preset, cfg.target_size_mb, cfg.width, cfg.height)
    if ((r.jobs || []).length === 0) { message.warning('该视频已在压缩中或已压缩，无法重复添加'); return }
    pendingVideos.value = pendingVideos.value.filter(v => v.id !== vid)
    message.success('压缩任务已创建')
    load()
  } catch { message.error('创建失败') }
}

async function confirmAll() {
  const ids = pendingVideos.value.map(v => v.id)
  message.loading('创建压缩任务...')
  for (const vid of ids) {
    const cfg = pendingConfig.value[vid]
    if (cfg) await submitCompress([vid], cfg.preset, cfg.target_size_mb, cfg.width, cfg.height)
  }
  pendingVideos.value = []
  message.success(`已创建 ${ids.length} 个压缩任务`)
  load()
}

async function batchSetAll(key: string, val: any) {
  for (const v of pendingVideos.value) updatePendingConfig(v.id, key, val)
}

function toggleExpand(jobId: number) {
  const next = expandedJobId.value === jobId ? null : jobId
  expandedJobId.value = next
  router.replace({ query: { ...route.query, ...(next ? { expanded: String(next) } : {}) } })
}

const jobs = ref<CompressJobData[]>([])

const { connect: connectWS } = useWebSocket(
  '/ws/compress',
  (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'job_start') {
        if (!jobs.value.find(j => j.id === msg.job_id)) {
          jobs.value.unshift({
            id: msg.job_id, video_id: 0, video_name: msg.video, preset: msg.preset || 'balanced',
            status: 'running', progress: 0, output_size: 0, original_size: msg.original_size || 0,
            eta_sec: msg.eta_sec || 0, elapsed_sec: 0, speed: 0, fps: 0, error: '',
            thumbnail_id: msg.thumbnail_id || null, step_log: [], output_path: null,
            target_size_mb: 0, target_width: 0, target_height: 0, thumbnail_layout: '3x3',
            compression_ratio: null, phase: null, finished_at: null, is_published: false,
            created_at: null, schedule_id: 0, publish_after: false,
          } as CompressJobData)
        }
      } else if (msg.type === 'progress') {
        const job = jobs.value.find(j => j.id === msg.job_id)
        if (job) {
          job.progress = msg.percent; job.eta_sec = msg.eta_sec || 0
          job.elapsed_sec = msg.elapsed_sec || 0; job.speed = msg.speed || 0; job.fps = msg.fps || 0
          job.status = 'running'
          if (msg.phase) job.phase = msg.phase
          if (msg.step_log) job.step_log = msg.step_log
          if (msg.thumbnail_id) job.thumbnail_id = msg.thumbnail_id
        }
      } else if (msg.type === 'job_done') {
        const job = jobs.value.find(j => j.id === msg.job_id)
        if (job) { job.status = 'done'; job.progress = 100; job.output_size = msg.output_size }
      } else if (msg.type === 'job_skip') {
        const job = jobs.value.find(j => j.id === msg.job_id)
        if (job) { job.status = 'skipped'; job.progress = 100; job.thumbnail_id = msg.thumbnail_id || null }
      } else if (msg.type === 'job_error') {
        const job = jobs.value.find(j => j.id === msg.job_id)
        if (job) { job.status = 'failed'; job.error = msg.error || '' }
      }
    } catch {}
  }
)

const stats = computed(() => {
  const total = jobs.value.length; const done = jobs.value.filter(j => j.status === 'done').length
  const running = jobs.value.filter(j => j.status === 'running').length
  const failed = jobs.value.filter(j => j.status === 'failed').length
  const skipped = jobs.value.filter(j => j.status === 'skipped').length
  return { total, done, running, failed, skipped }
})

const activeJobs = computed(() => jobs.value.filter(j => j.status === 'running' || j.status === 'queued' || j.status === 'paused'))
const completedJobs = computed(() => jobs.value.filter(j => j.status === 'done' || j.status === 'skipped' || j.status === 'failed' || j.status === 'cancelled'))

async function load() { try { jobs.value = ((await fetchCompressJobs()).items || []) as CompressJobData[] } catch {} }

function thumbUrl(id: number | null) { return id ? getThumbnailImage(id) : '' }
function formatEta(sec: number) { if (!sec) return ''; const m = Math.floor(sec/60), s = Math.floor(sec%60); return m > 0 ? `剩余 ${m}m${s}s` : `剩余 ${s}s` }
function formatElapsed(sec: number) { if (!sec) return ''; const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = Math.floor(sec%60); if (h>0) return `${h}h${m}m${s}s`; return `${m}m${s}s` }
function statusColor(s: string) { return { running: 'var(--color-purple)', paused: '#faad14', done: 'var(--color-green)', failed: 'var(--color-red)', cancelled: '#aaa', skipped: '#5e9eff' }[s] || '#888' }
function statusLabel(s: string) { return { running: '压缩中', paused: '已暂停', done: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过', queued: '等待中' }[s] || s }
function presetLabel(p: string) { return { fast: '极速 (H.264)', balanced: '均衡 (H.265)', high_quality: '高画质 (2-pass)' }[p] || p }

async function doCancel(jobId: number) { try { await cancelCompressJob(jobId); message.success('已取消') } catch { message.error('取消失败') } }
async function doPause(jobId: number) { try { await pauseJob(jobId); message.success('已暂停') } catch { message.error('暂停失败') } }
async function doResume(jobId: number) { try { await resumeJob(jobId); message.success('已恢复') } catch { message.error('恢复失败') } }
async function doRetry(jobId: number) { try { await retryCompressJob(jobId); message.success('已重试'); load() } catch { message.error('重试失败') } }
async function doDeleteJob(jobId: number) { try { await deleteCompressJob(jobId); message.success('已删除'); load() } catch { message.error('删除失败') } }
async function doBatchDelete(status: string) { try { await batchDeleteCompress(status); message.success('已删除'); load() } catch { message.error('删除失败') } }

const retryConfig = ref<Record<number, { preset: string; target_size_mb: number }>>({})
function initRetryConfig(job: CompressJobData) {
  if (!retryConfig.value[job.id]) {
    retryConfig.value[job.id] = { preset: job.preset || compressPreset, target_size_mb: 500 }
  }
}
async function doRetryWithConfig(job: CompressJobData) {
  if (!retryConfig.value[job.id]) {
    retryConfig.value[job.id] = { preset: job.preset || compressPreset, target_size_mb: job.target_size_mb || 500 }
  }
  const cfg = retryConfig.value[job.id]
  if (cfg) { await updateCompressSettings(job.id, cfg); delete retryConfig.value[job.id] }
  await doRetry(job.id)
}

async function doGenerateThumb(videoId: number) {
  try { const r = await generateThumbnail(videoId); message.success(`缩略图已生成 (${r.width}×${r.height})`); load() }
  catch { message.error('生成缩略图失败') }
}

async function doPublish(jobId: number) {
  if (!channels.value.length) { message.warning('未发现频道'); return }
  const job = jobs.value.find(j => j.id === jobId)
  if (!job?.video_id) { message.warning('无关联视频'); return }
  try {
    await publishNow(job.video_id, channels.value[0].chat_id)
    message.success(`发布任务已提交: ${job.video_name}`)
  } catch { message.error('发布失败') }
}

function getPendingPreset(vid: number) { if (!pendingConfig.value[vid]) updatePendingConfig(vid, 'preset', compressPreset); return pendingConfig.value[vid]?.preset || compressPreset }
function setPendingPreset(vid: number, val: string) { updatePendingConfig(vid, 'preset', val) }
function getPendingSize(vid: number) { if (!pendingConfig.value[vid]) updatePendingConfig(vid, 'target_size_mb', 500); return pendingConfig.value[vid]?.target_size_mb || 500 }
function setPendingSize(vid: number, val: number | null) { updatePendingConfig(vid, 'target_size_mb', val ?? 500) }

onMounted(async () => {
  try {
    const data = await settingsStore.loadSettings()
    compressPreset = data.compress_preset || 'balanced'
    defaultPreset.value = compressPreset
  } catch {}
  const ex = route.query.expanded as string
  if (ex) expandedJobId.value = Number(ex)
  loadChannels()
  load()
  connectWS()
  initPendingVideos()
})
</script>

<template>
  <PageContainer>
    <PageHeader title="压缩任务" icon="⚡">
      <template v-if="completedJobs.length">
        <n-space :size="8">
          <n-button size="small" @click="showCompleted = !showCompleted">
            {{ showCompleted ? '收起历史' : `展开历史 (${completedJobs.length})` }}
          </n-button>
          <n-popconfirm @positive-click="() => doBatchDelete('done')">
            <template #trigger><n-button size="small" type="warning">清空已完成</n-button></template>
            确定删除所有已完成/已跳过的任务？
          </n-popconfirm>
          <n-popconfirm @positive-click="() => doBatchDelete('')">
            <template #trigger><n-button size="small" type="error">清空全部</n-button></template>
            确定删除所有压缩任务？
          </n-popconfirm>
        </n-space>
      </template>
    </PageHeader>

    <StatsGrid v-if="jobs.length" :cols="5" :items="[
      { label:'总任务', value: stats.total }, { label:'已完成', value: stats.done },
      { label:'进行中', value: stats.running }, { label:'失败', value: stats.failed }, { label:'已跳过', value: stats.skipped },
    ]" />

    <n-empty v-if="!jobs.length && !pendingVideos.length" description="暂无压缩任务，去视频管理页面选中视频后压缩" style="margin-top: 80px" />

    <!-- Pending batch config -->
    <div v-if="pendingVideos.length" style="margin-bottom: 20px; padding: 16px; background: var(--bg-subtle); border-radius: 8px;">
      <n-text strong style="font-size:14px;display:block;margin-bottom:10px">待配置 ({{ pendingVideos.length }})</n-text>
      <div v-for="v in pendingVideos" :key="v.id" style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border-subtle);font-size:13px">
        <n-text strong style="width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0">{{ v.filename }}</n-text>
        <n-text depth="3" style="font-size:11px;width:70px;flex-shrink:0">{{ formatSize(v.size_bytes) }}</n-text>
        <n-text v-if="v.width" depth="3" style="font-size:11px;width:90px;flex-shrink:0">{{ v.width }}×{{ v.height }}</n-text>
        <n-select :value="getPendingPreset(v.id)" @update:value="(val: string) => setPendingPreset(v.id, val)" size="tiny" style="width:120px" :options="[{label:'极速 H.264',value:'fast'},{label:'均衡 H.265',value:'balanced'},{label:'高画质 2-pass',value:'high_quality'}]" />
        <n-select v-model:value="resCache[v.id]" size="tiny" style="width:90px" :options="[{label:'原尺寸',value:'0x0'},{label:'4K',value:'3840x2160'},{label:'1080p',value:'1920x1080'},{label:'720p',value:'1280x720'},{label:'480p',value:'640x480'}]" />
        <n-input-number :value="getPendingSize(v.id)" @update:value="(val: number | null) => setPendingSize(v.id, val)" size="tiny" :min="10" :max="10000" style="width:70px" /><n-text depth="3" style="font-size:10px">MB</n-text>
        <n-button size="tiny" type="primary" @click="confirmPending(v.id)">确认</n-button>
        <n-button size="tiny" @click="pendingVideos = pendingVideos.filter(p => p.id !== v.id)">移除</n-button>
      </div>
      <n-space :size="6" style="margin-top:10px">
        <n-button size="tiny" @click="batchSetAll('preset','balanced')">全部均衡</n-button>
        <n-button size="tiny" @click="batchSetAll('target_size_mb', 500)">全部 500MB</n-button>
        <n-button size="small" type="primary" @click="confirmAll">全部确认</n-button>
      </n-space>
    </div>

    <!-- Active jobs -->
    <n-space vertical :size="12" v-if="activeJobs.length">
      <n-text depth="3" style="font-size:12px">进行中 · 排队中 ({{ activeJobs.length }})</n-text>
      <n-card v-for="job in activeJobs" :key="job.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(job.status)}`, cursor: 'pointer' }"
        @click="toggleExpand(job.id)">
        <div style="display:flex;gap:14px">
          <div v-if="job.thumbnail_id" class="thumb-blur" style="flex-shrink:0;width:120px;height:68px;border-radius:6px;overflow:hidden;background:rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(job.thumbnail_id)" :width="120" :height="68" object-fit="cover" :show-toolbar="false" />
          </div>
          <div v-else style="flex-shrink:0;width:120px;height:68px;border-radius:6px;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.3)"><span style="font-size:24px;opacity:0.3">🎬</span></div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
              <div style="min-width:0">
                <n-text strong style="font-size:14px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ job.video_name }}</n-text>
                <n-text depth="3" style="font-size:11px">{{ presetLabel(job.preset) }}</n-text>
              </div>
              <StatusTag :status="job.status" />
            </div>
            <n-text v-if="job.phase" depth="3" style="font-size:10px;display:block;margin-bottom:4px">{{ { thumbnail: '🖼 正在提取缩略图', encoding: '🎞 正在编码', retry_pass2: '🔄 二阶段重试' }[job.phase as string] || job.phase }}</n-text>
            <n-text v-else-if="job.status==='queued'" depth="3" style="font-size:10px;display:block;margin-bottom:4px">🕐 排队中</n-text>
            <n-progress type="line" :percentage="job.progress||0" :height="16" :border-radius="8" :color="statusColor(job.status)" :indicator-placement="'inside'" :processing="job.status==='running'" />
            <div style="margin-top:8px;display:flex;align-items:center;gap:10px;font-size:12px">
              <n-text depth="3" style="flex:1;display:flex;align-items:center;gap:4px">
                <n-icon :size="14"><TimeOutline /></n-icon>
                {{ formatElapsed(job.elapsed_sec||0) }}
                <template v-if="job.eta_sec"> · {{ formatEta(job.eta_sec) }}</template>
                <template v-if="job.speed"> · {{ job.speed }}x</template>
                <template v-if="job.fps"> · {{ job.fps }}fps</template>
              </n-text>
              <n-space :size="6">
                <n-button v-if="job.status==='running'" size="tiny" @click.stop="doPause(job.id)">暂停</n-button>
                <n-button v-if="job.status==='paused'" size="tiny" type="primary" @click.stop="doResume(job.id)">继续</n-button>
                <n-popconfirm v-if="job.status==='running'" @positive-click="() => doCancel(job.id)"><template #trigger><n-button size="tiny">取消</n-button></template>确定取消？</n-popconfirm>
                <n-popconfirm v-if="job.status==='queued'||job.status==='paused'" @positive-click="() => doDeleteJob(job.id)"><template #trigger><n-button size="tiny" type="error">删除</n-button></template>确定删除？</n-popconfirm>
              </n-space>
            </div>
            <div v-if="expandedJobId===job.id" style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border-subtle)">
              <div v-if="job.step_log && job.step_log.length" style="margin-bottom:6px">
                <n-text depth="3" style="font-size:11px;display:block;margin-bottom:2px">步骤日志：</n-text>
                <n-text v-for="(s,i) in job.step_log" :key="i" depth="3" style="font-size:11px;display:block">
                  {{ i+1 }}. {{ s.step }} — {{ s.elapsed }}s {{ s.result }}{{ s.speed ? ' · '+s.speed+'x' : '' }}{{ s.output_gb ? ' · '+s.output_gb+'GB' : '' }}{{ s.thumb_id ? ' · #'+s.thumb_id : '' }}{{ s.error ? ': '+s.error.slice(0,60) : '' }}
                </n-text>
              </div>
              <n-text depth="3" style="font-size:11px;white-space:pre-wrap;font-family:monospace;word-break:break-all;max-height:200px;overflow-y:auto;display:block">{{ (job as any).stderr || job.error || '暂无详情' }}</n-text>
            </div>
          </div>
        </div>
      </n-card>
    </n-space>

    <!-- Completed toggle -->
    <div v-if="!showCompleted && completedJobs.length" style="margin-top: 20px">
      <n-button size="tiny" @click="showCompleted = true">展开历史 ({{ completedJobs.length }})</n-button>
    </div>

    <!-- Completed jobs -->
    <n-space v-if="showCompleted && completedJobs.length" vertical :size="12" style="margin-top:12px">
      <n-card v-for="job in completedJobs" :key="job.id" size="small" :bordered="true"
        :style="{ borderLeft: `3px solid ${statusColor(job.status)}`, opacity: 0.7, cursor: 'pointer' }"
        @click="toggleExpand(job.id)">
        <div style="display:flex;gap:14px">
          <div v-if="job.thumbnail_id" class="thumb-blur" style="flex-shrink:0;width:80px;height:45px;border-radius:4px;overflow:hidden;background:rgba(0,0,0,0.3)">
            <n-image :src="thumbUrl(job.thumbnail_id)" :width="80" :height="45" object-fit="cover" :show-toolbar="false" />
          </div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;align-items:flex-start">
              <div style="min-width:0">
                <n-text strong style="font-size:13px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ job.video_name }}</n-text>
                <n-text depth="3" style="font-size:11px">{{ presetLabel(job.preset) }}</n-text>
              </div>
              <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
                <StatusTag :status="job.status" />
              </div>
            </div>
            <div style="font-size:12px">
              <n-text v-if="(job as any).finished_at" depth="3" style="font-size:10px;display:block;margin-bottom:2px">完成的于 {{ new Date((job as any).finished_at).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}) }}</n-text>
              <n-text v-if="job.status==='done'" style="color:var(--color-green)">{{ formatSize(job.original_size||0) }} → {{ formatSize(job.output_size||0) }}</n-text>
              <n-text v-else-if="job.status==='skipped'" style="color:#5e9eff">{{ (job as any).skip_reason || '已跳过' }}</n-text>
              <n-text v-else-if="job.status==='failed' && job.error" depth="3" style="display:block;margin-top:4px;font-size:11px;font-family:monospace;word-break:break-all;max-height:60px;overflow:hidden;text-overflow:ellipsis">{{ job.error.slice(0,200) }}</n-text>
            </div>
            <div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap">
              <n-button size="tiny" @click.stop="toggleExpand(job.id)">{{ expandedJobId===job.id?'收起':'详情' }}</n-button>
              <n-button v-if="job.status==='done'||job.status==='skipped'||job.status==='failed'||job.status==='cancelled'" size="tiny" @click.stop="doPublish(job.id)">发布</n-button>
              <n-button v-if="job.status==='failed'||job.status==='skipped'||job.status==='cancelled'" size="tiny" type="primary" @click.stop="doRetryWithConfig(job)">重试</n-button>
              <n-button v-if="(job.status==='done'||job.status==='skipped') && !job.thumbnail_id" size="tiny" @click.stop="doGenerateThumb(job.video_id)">🖼 生成缩略图</n-button>
              <n-popconfirm @positive-click="() => doDeleteJob(job.id)"><template #trigger><n-button size="tiny" type="error" @click.stop>删除</n-button></template>确定删除？</n-popconfirm>
            </div>
            <div v-if="expandedJobId===job.id" style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border-subtle)">
              <div v-if="job.step_log && job.step_log.length" style="margin-bottom:6px">
                <n-text depth="3" style="font-size:11px;display:block;margin-bottom:2px">步骤日志：</n-text>
                <n-text v-for="(s,i) in job.step_log" :key="i" depth="3" style="font-size:11px;display:block">
                  {{ i+1 }}. {{ s.step }} — {{ s.elapsed }}s {{ s.result }}{{ s.speed ? ' · '+s.speed+'x' : '' }}{{ s.output_gb ? ' · '+s.output_gb+'GB' : '' }}{{ s.thumb_id ? ' · #'+s.thumb_id : '' }}{{ s.error ? ': '+s.error.slice(0,60) : '' }}
                </n-text>
              </div>
              <n-text depth="3" style="font-size:11px;white-space:pre-wrap;font-family:monospace;word-break:break-all;max-height:200px;overflow-y:auto;display:block">{{ (job as any).stderr || job.error || '暂无详情' }}</n-text>
              <n-space v-if="job.status==='failed'||job.status==='skipped'||job.status==='cancelled'" :size="6" style="margin-top:6px" @click.stop>
                <n-text depth="3" style="font-size:10px">重试参数:</n-text>
                <n-select :value="retryConfig[job.id]?.preset" @update:value="(val: string) => { if (!retryConfig[job.id]) initRetryConfig(job); retryConfig[job.id].preset = val }" size="tiny" style="width:110px" :options="[{label:'极速 H.264',value:'fast'},{label:'均衡 H.265',value:'balanced'},{label:'高画质',value:'high_quality'}]" @click.stop />
                <n-input-number :value="retryConfig[job.id]?.target_size_mb" @update:value="(val: number | null) => { if (!retryConfig[job.id]) initRetryConfig(job); retryConfig[job.id].target_size_mb = val ?? 500 }" size="tiny" :min="10" :max="10000" style="width:70px" @click.stop /><n-text depth="3" style="font-size:10px">MB</n-text>
              </n-space>
            </div>
          </div>
        </div>
      </n-card>
    </n-space>
  </PageContainer>
</template>
