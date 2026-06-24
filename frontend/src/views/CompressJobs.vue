<script setup lang="ts">
import { ref, onMounted, h, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NProgress, NTag, NText, NEmpty, NSpace, NButton, NInputNumber,
  NPopconfirm, NImage, NGrid, NGi, NStatistic, NSelect, NIcon, useMessage
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
import ChannelSelect from '@/components/shared/ChannelSelect.vue'
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
    if ((r.jobs || []).length === 0) {
      message.warning('该视频已在压缩中或已压缩，无法重复添加')
      return
    }
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
            compression_ratio: null, created_at: null, schedule_id: 0, publish_after: false,
          } as CompressJobData)
        }
      } else if (msg.type === 'progress') {
        const job = jobs.value.find(j => j.id === msg.job_id)
        if (job) {
          job.progress = msg.percent; job.eta_sec = msg.eta_sec || 0
          job.elapsed_sec = msg.elapsed_sec || 0; job.speed = msg.speed || 0; job.fps = msg.fps || 0
          job.status = 'running'
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
  const total = jobs.value.length
  const done = jobs.value.filter(j => j.status === 'done').length
  const running = jobs.value.filter(j => j.status === 'running').length
  const failed = jobs.value.filter(j => j.status === 'failed').length
  const skipped = jobs.value.filter(j => j.status === 'skipped').length
  return { total, done, running, failed, skipped }
})

const activeJobs = computed(() => jobs.value.filter(j => j.status === 'running' || j.status === 'queued' || j.status === 'paused'))
const completedJobs = computed(() => jobs.value.filter(j => j.status === 'done' || j.status === 'skipped' || j.status === 'failed' || j.status === 'cancelled'))

let wsMounted = false

async function load() {
  try { jobs.value = ((await fetchCompressJobs()).list || []) as CompressJobData[] } catch {}
}

async function doCancel(jobId: number) { try { await cancelCompressJob(jobId); message.success('已取消'); load() } catch { message.error('取消失败') } }
async function doPause(jobId: number) { try { await pauseJob(jobId); message.success('已暂停'); load() } catch { message.error('暂停失败') } }
async function doResume(jobId: number) { try { await resumeJob(jobId); message.success('已恢复'); load() } catch { message.error('恢复失败') } }
async function doRetry(jobId: number) { try { await retryCompressJob(jobId); message.success('已重试'); load() } catch { message.error('重试失败') } }
async function doDeleteJob(jobId: number) { try { await deleteCompressJob(jobId); message.success('已删除'); load() } catch { message.error('删除失败') } }
async function doBatchDelete(status: string) { try { await batchDeleteCompress(status); message.success('已删除'); load() } catch { message.error('删除失败') } }

async function doPublish(jobId: number) {
  if (!channels.value.length) { message.warning('未发现频道'); return }
  try {
    const job = jobs.value.find(j => j.id === jobId)
    if (!job) return
    await publishNow(job.video_id, channels.value[0].chat_id)
    message.success('已加入发布队列')
  } catch { message.error('发布失败') }
}

async function doCreateThumb(jobId: number) {
  try {
    const job = jobs.value.find(j => j.id === jobId)
    if (!job) return
    await generateThumbnail(job.video_id, '3x3')
    message.success('缩略图已生成')
  } catch { message.error('生成失败') }
}

async function doSettingsChange(jobId: number, updates: any) {
  try { await updateCompressSettings(jobId, updates); message.success('已更新'); load() }
  catch { message.error('更新失败') }
}

onMounted(async () => {
  wsMounted = true
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

const channelOptions = computed(() =>
  channels.value.map(c => {
    const label = c.alias || c.chat_name || String(c.chat_id)
    return   { label: label.length > 16 ? label.slice(0, 14) + '…' : label, value: c.chat_id }
  })
)

function getPendingPreset(vid: number) {
  if (!pendingConfig.value[vid]) updatePendingConfig(vid, 'preset', compressPreset)
  return pendingConfig.value[vid]?.preset || compressPreset
}
function setPendingPreset(vid: number, val: string) {
  updatePendingConfig(vid, 'preset', val)
}
function getPendingSize(vid: number) {
  if (!pendingConfig.value[vid]) updatePendingConfig(vid, 'target_size_mb', 500)
  return pendingConfig.value[vid]?.target_size_mb || 500
}
function setPendingSize(vid: number, val: number) {
  updatePendingConfig(vid, 'target_size_mb', val)
}
</script>

<template>
  <PageContainer>
    <PageHeader title="压缩任务" icon="⚡">
      <template v-if="completedJobs.length" #actions>
        <n-space :size="8">
          <n-button size="small" @click="showCompleted = !showCompleted">
            {{ showCompleted ? '收起历史' : '展开历史' }} ({{ completedJobs.length }})
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

    <!-- Pending batch config -->
    <n-card v-if="pendingVideos.length" size="small" title="📋 待提交的视频" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:12px;display:block;margin-bottom:8px">从视频管理页面导航，配置压缩参数后提交</n-text>
      <n-grid :cols="1" :x-gap="8">
        <n-gi v-for="v in pendingVideos" :key="v.id">
          <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border-subtle)">
            <n-text style="flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ v.filename }}</n-text>
            <n-select :value="getPendingPreset(v.id)" @update:value="(val: string) => setPendingPreset(v.id, val)" size="tiny" style="width:120px" :options="[{label:'极速 H.264',value:'fast'},{label:'均衡 H.265',value:'balanced'},{label:'高画质 2-pass',value:'high_quality'}]" />
            <n-input-number :value="getPendingSize(v.id)" @update:value="(val: number) => setPendingSize(v.id, val)" size="tiny" :min="10" :max="2000" style="width:80px" /> <n-text depth="3" style="font-size:11px">MB</n-text>
            <n-button size="tiny" type="primary" @click="confirmPending(v.id)">提交</n-button>
          </div>
        </n-gi>
      </n-grid>
      <n-button size="small" type="primary" style="margin-top:12px" @click="confirmAll">全部提交</n-button>
      <n-space :size="6" style="margin-top:8px">
        <n-button size="tiny" @click="batchSetAll('preset','fast')">全部: 极速</n-button>
        <n-button size="tiny" @click="batchSetAll('preset','balanced')">全部: 均衡</n-button>
        <n-button size="tiny" @click="batchSetAll('preset','high_quality')">全部: 高画质</n-button>
        <n-button size="tiny" @click="pendingVideos=[]">清除</n-button>
      </n-space>
    </n-card>

    <StatsGrid v-if="jobs.length" :cols="5" :items="[
      { label:'总任务', value: stats.total },
      { label:'已完成', value: stats.done },
      { label:'进行中', value: stats.running },
      { label:'失败', value: stats.failed },
      { label:'已跳过', value: stats.skipped },
    ]" />

    <n-empty v-if="!jobs.length && !pendingVideos.length" description="暂无压缩任务，去视频管理页面选中视频后压缩" style="margin-top: 80px" />

    <!-- Active jobs -->
    <div v-if="activeJobs.length">
      <n-grid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
        <n-gi v-for="job in activeJobs" :key="job.id">
          <n-card size="small" :bordered="true" style="height:100%">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
              <n-text style="flex:1;font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ job.video_name }}</n-text>
              <StatusTag :status="job.status" />
            </div>
            <n-progress type="line" :percentage="job.progress || 0" :height="10" :color="job.status==='running'?'var(--color-purple)':'var(--color-green)'" :indicator-placement="'inside'" :processing="job.status==='running'" style="margin-bottom:8px" />
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
              <n-text depth="3" style="font-size:11px">{{ formatSize(job.original_size || 0) }} · 目标 {{ job.target_size_mb || '-' }}MB</n-text>
              <n-text v-if="job.status==='running'" depth="3" style="font-size:11px">
                {{ job.elapsed_sec ? Math.floor((job.elapsed_sec||0)/60)+'m'+Math.floor((job.elapsed_sec||0)%60)+'s' : '' }}
                <template v-if="job.eta_sec"> · 剩余 {{ Math.floor((job.eta_sec||0)/60) }}m</template>
              </n-text>
              <div style="margin-left:auto;display:flex;gap:4px">
                <n-popconfirm @positive-click="() => doCancel(job.id)" v-if="job.status==='running'"><template #trigger><n-button size="tiny" type="error">取消</n-button></template>确定取消？</n-popconfirm>
                <n-popconfirm @positive-click="() => doCancel(job.id)" v-if="job.status==='queued'||job.status==='paused'"><template #trigger><n-button size="tiny" type="error">取消</n-button></template>确定取消？</n-popconfirm>
                <n-popconfirm @positive-click="() => doDeleteJob(job.id)"><template #trigger><n-button size="tiny" type="error">删除</n-button></template>确定删除？</n-popconfirm>
              </div>
            </div>
          </n-card>
        </n-gi>
      </n-grid>
    </div>

    <!-- Completed jobs -->
    <template v-if="showCompleted && completedJobs.length">
      <n-divider style="margin:16px 0" />
      <n-text depth="2" style="font-weight:600;margin-bottom:12px;display:block">已完成 ({{ completedJobs.length }})</n-text>
      <div v-for="job in completedJobs" :key="job.id" style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border-subtle);font-size:13px;opacity:0.75">
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ job.video_name }}</n-text>
        <StatusTag :status="job.status" />
        <n-text depth="3" style="font-size:11px" v-if="job.output_size">{{ formatSize(job.output_size) }}</n-text>
        <n-popconfirm @positive-click="() => doRetry(job.id)"><template #trigger><n-button size="tiny" type="primary">重试</n-button></template>确定重试？</n-popconfirm>
        <n-popconfirm @positive-click="() => doDeleteJob(job.id)"><template #trigger><n-button size="tiny" type="error">删除</n-button></template>确定删除？</n-popconfirm>
      </div>
    </template>
  </PageContainer>
</template>
