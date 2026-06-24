<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NInput, NButton, NDataTable, NSpace,
  NTag, NText, NEmpty,
  NBreadcrumb, NBreadcrumbItem, NSpin, NProgress, NIcon,
  NPopconfirm, useMessage,
} from 'naive-ui'
import { ScanOutline } from '@vicons/ionicons5'
import { fetchVideos, scanDirectory, deleteVideo, fetchChats, publishNow, cancelPublishTask, retryPublishTask } from '@/api/client'
import api from '@/api/client'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'

const message = useMessage()
const router = useRouter()

function navigateTo(path: string) {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  router.push({ path, query: { ids: ids.join(',') } })
}

const currentPath = ref('/data/videos')
const videos = ref<any[]>([])
const loading = ref(false)
const scanning = ref(false)
const selectedIds = ref<Set<number>>(new Set())
const hasSelected = computed(() => selectedIds.value.size > 0)
const selectedCount = computed(() => selectedIds.value.size)
const filterStatus = ref('')
const searchText = ref('')
const sortKey = ref('')
const sortDir = ref<'asc'|'desc'>('asc')

const filteredVideos = computed(() => {
  let arr = videos.value || []
  if (searchText.value) {
    arr = arr.filter(v => v.filename.toLowerCase().includes(searchText.value.toLowerCase()))
  }
  if (sortKey.value) {
    arr = [...arr].sort((a, b) => {
      const va = a[sortKey.value] ?? ''; const vb = b[sortKey.value] ?? ''
      const n = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb))
      return sortDir.value === 'asc' ? n : -n
    })
  }
  return arr
})


const breadcrumbs = computed(() => {
  const parts: { name: string; path: string }[] = []
  const segs = currentPath.value.split('/').filter(Boolean)
  let cum = ''
  for (const s of segs) {
    cum += '/' + s
    parts.push({ name: s, path: cum })
  }
  return parts
})

async function browseDir(path?: string) {
  if (path !== undefined) currentPath.value = path
  selectedIds.value = new Set()
  await loadVideos()
}

async function loadVideos() {
  loading.value = true
  try {
    const params: Record<string, any> = { path: currentPath.value }
    if (filterStatus.value) params.status = filterStatus.value
    const data = await fetchVideos(params)
    videos.value = data.items || []
  } catch { message.warning('加载视频列表失败') }
  loading.value = false
}

async function doScan() {
  scanning.value = true
  try {
    const data = await scanDirectory(currentPath.value)
    message.success(`扫描完成，新增 ${data.added || data.count || 0} 个视频`)
    await loadVideos()
  } catch { message.error('扫描失败') }
  scanning.value = false
}

function onFilterChange(val: string) {
  filterStatus.value = val
  loadVideos()
}

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1_000_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB'
  return (bytes / 1_000_000_000).toFixed(2) + ' GB'
}

function formatDuration(sec: number): string {
  if (!sec) return '-'
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60)
  return h > 0 ? `${h}h${m}m` : `${m}m${s}s`
}

async function doPublishOne(videoId: number) {
  try {
    const d = await fetchChats()
    const ch = (d.items || [])[0]
    if (!ch) { message.warning('无可用的频道，请先在系统设置中添加频道'); return }
    message.loading('加入发布队列...')
    await publishNow(videoId, ch.chat_id)
    message.success('已加入发布队列')
    loadVideos()
  } catch (e: any) {
    message.error('发布失败: ' + (e?.response?.data?.detail || e?.message || ''))
  }
}

async function doDeleteOne(videoId: number) {
  try { await deleteVideo(videoId); message.success('已删除'); loadVideos() }
  catch { message.error('删除失败') }
}

const columns = [
  { type: 'selection' as const },
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true }, sorter: true },
  { title: '大小', key: 'size_bytes', width: 100, render: (r: any) => formatSize(r.size_bytes), sorter: true },
  { title: '时长', key: 'duration_sec', width: 90, render: (r: any) => formatDuration(r.duration_sec), sorter: true },
  { title: '分辨率', key: 'resolution', width: 110, render: (r: any) => r.width ? `${r.width}x${r.height}` : '-', sorter: true },
  {
    title: '状态', key: 'status', width: 80,
    render: (r: any) => {
      const map: Record<string, { type: any; label: string }> = {
        pending: { type: 'default', label: '待处理' },
        compressed: { type: 'success', label: '已压缩' },
        skipped: { type: 'info', label: '已跳过' },
        compressing: { type: 'warning', label: '压缩中' },
        failed: { type: 'error', label: '失败' },
      }
      const s = map[r.status] || { type: 'default', label: r.status }
      return h(NTag, { type: s.type, size: 'small', bordered: false }, { default: () => s.label })
    },
  },
  {
    title: '操作', key: 'actions', width: 100,
    render: (r: any) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', onClick: () => doPublishOne(r.id) }, { default: () => '发布' }),
        h(NPopconfirm, { onPositiveClick: () => doDeleteOne(r.id) },
          { trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }), default: () => '确定删除？' }
        ),
      ],
    }),
  },
]

const channels = ref<any[]>([])

async function loadChannels() {
  try { const d = await fetchChats(); channels.value = (d.items || []).map((c: any) => ({ ...c, _label: c.chat_name?.length > 16 ? c.chat_name.slice(0,14)+'…' : c.chat_name })) } catch {}
}

const ws = ref<WebSocket | null>(null)
let reconnectTimer: number | undefined
let reconnectAttempts = 0

interface ProgressJob {
  id: number; video_name: string; status: string; progress: number; eta_sec: number
  elapsed_sec: number; speed: number; fps: number; error: string
}
const runningJobs = ref<ProgressJob[]>([])

interface PublishTask {
  id: number; video_id: number | null; video_name: string; channel_name: string
  status: string; progress: number; elapsed_sec: number; eta_sec: number
  thumbnail_id: number | null; error: string
}
const publishTasks = ref<PublishTask[]>([])

function connectWS() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('access_token')
  ws.value = new WebSocket(`${protocol}//${location.host}/ws/compress?token=${token || ''}`)
  ws.value.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    const idx = runningJobs.value.findIndex(j => j.id === msg.job_id)
    if (msg.type === 'job_start') {
      if (idx < 0) runningJobs.value.push({ id: msg.job_id, video_name: msg.video, status: 'running', progress: 0, eta_sec: msg.eta_sec || 0, elapsed_sec: 0, speed: 0, fps: 0, error: '' })
    } else if (msg.type === 'progress') {
      if (idx >= 0) { runningJobs.value[idx].progress = msg.percent; runningJobs.value[idx].eta_sec = msg.eta_sec || 0; runningJobs.value[idx].elapsed_sec = msg.elapsed_sec || 0; runningJobs.value[idx].speed = msg.speed || 0; runningJobs.value[idx].fps = msg.fps || 0 }
    } else if (msg.type === 'job_done') {
      if (idx >= 0) { runningJobs.value[idx].status = 'done'; runningJobs.value[idx].progress = 100 }
    } else if (msg.type === 'job_skip') {
      if (idx >= 0) { runningJobs.value[idx].status = 'skipped'; runningJobs.value[idx].progress = 100 }
    } else if (msg.type === 'job_error') {
      if (idx >= 0) { runningJobs.value[idx].status = 'failed'; runningJobs.value[idx].error = msg.error || '' }
    } else if (msg.type === 'publish_progress') {
      let t = publishTasks.value.find(p => p.id === msg.task_id)
      if (!t) { t = { id: msg.task_id, video_id: msg.video_id, video_name: msg.video_name, channel_name: msg.channel_name || '', status: 'running', progress: msg.progress || 5, elapsed_sec: msg.elapsed_sec || 0, eta_sec: msg.eta_sec || 0, thumbnail_id: msg.thumbnail_id || null, error: '' }; publishTasks.value.unshift(t) }
      else { t.progress = msg.progress || t.progress; t.elapsed_sec = msg.elapsed_sec || 0; t.eta_sec = msg.eta_sec || 0; t.thumbnail_id = msg.thumbnail_id || t.thumbnail_id; t.status = msg.step === 'uploading' ? 'uploading' : 'running' }
    } else if (msg.type === 'publish_done') {
      const t = publishTasks.value.find(p => p.id === msg.task_id); if (t) { t.status = 'done'; t.progress = 100 }
    } else if (msg.type === 'publish_error') {
      const t = publishTasks.value.find(p => p.id === msg.task_id); if (t) { t.status = 'failed'; t.error = msg.error || '' }
    } else if (msg.type === 'publish_cancelled') {
      const t = publishTasks.value.find(p => p.id === msg.task_id); if (t) t.status = 'cancelled'
    }
  }
  ws.value.onclose = () => { const delay = Math.min((reconnectAttempts || 1) * 5000, 60000); reconnectAttempts = (reconnectAttempts || 1) + 1; reconnectTimer = window.setTimeout(connectWS, delay) }
  ws.value.onerror = () => { ws.value?.close() }
  ws.value.onopen = () => { reconnectAttempts = 0 }
}

function clearProgress() {
  runningJobs.value = runningJobs.value.filter(j => j.status === 'running')
  publishTasks.value = publishTasks.value.filter(t => t.status === 'running' || t.status === 'uploading' || t.status === 'queued')
}

async function cancelPublish(taskId: number) {
  try { await cancelPublishTask(taskId) } catch { message.error('取消失败') }
}
async function retryPublish(taskId: number) {
  try { await retryPublishTask(taskId); message.success('已重新加入队列') } catch { message.error('重试失败') }
}

onMounted(async () => {
  loadChannels()
  connectWS()
  try { const { data } = await api.get('/settings'); if (data?.video_source_dir) currentPath.value = data.video_source_dir } catch {}
  browseDir()
})

onUnmounted(() => { if (reconnectTimer) clearTimeout(reconnectTimer); ws.value?.close() })

const hasActiveTasks = computed(() => runningJobs.value.length > 0 || publishTasks.value.length > 0)
</script>

<template>
  <PageContainer>
    <PageHeader title="视频工作台" icon="📹" />

    <n-card size="small" style="margin-bottom: 12px">
      <n-space vertical :size="8">
        <n-breadcrumb>
          <n-breadcrumb-item v-for="(crumb, i) in breadcrumbs" :key="crumb.path" @click="browseDir(crumb.path)">
            {{ i === 0 ? '📁' : '' }} {{ crumb.name }}
          </n-breadcrumb-item>
        </n-breadcrumb>
        <n-space :size="8">
          <n-input v-model:value="currentPath" size="small" placeholder="/data/videos" style="flex: 1" clearable />
          <n-button size="small" @click="browseDir()">浏览</n-button>
          <n-button size="small" :loading="scanning" @click="doScan">
            <template #icon><n-icon><ScanOutline /></n-icon></template>扫描
          </n-button>
          <n-input v-model:value="searchText" size="small" placeholder="搜索文件名..." clearable style="width: 200px" />
        </n-space>
      </n-space>
    </n-card>

    <!-- Status filter chips -->
    <n-space :size="6" style="margin-bottom: 10px">
      <n-button :type="filterStatus === '' ? 'primary' : 'default'" size="tiny" round @click="onFilterChange('')">全部</n-button>
      <n-button :type="filterStatus === 'pending' ? 'primary' : 'default'" size="tiny" round @click="onFilterChange('pending')">待处理</n-button>
      <n-button :type="filterStatus === 'compressed' ? 'primary' : 'default'" size="tiny" round @click="onFilterChange('compressed')">已压缩</n-button>
      <n-button :type="filterStatus === 'failed' ? 'primary' : 'default'" size="tiny" round @click="onFilterChange('failed')">失败</n-button>
      <n-text depth="3" style="font-size: 11px; margin-left: auto" v-if="videos.length">共 {{ videos.length }} 个</n-text>
    </n-space>

    <n-spin :show="loading || scanning">
      <n-empty v-if="!videos.length && !loading" description="此目录无视频，请点击扫描按钮" style="margin: 60px 0" />
      <n-dataTable
        v-else
        :columns="columns"
        :data="filteredVideos"
        :pagination="{ pageSize: 20 }"
        :row-key="(r: any) => r.id"
        :checked-row-keys="Array.from(selectedIds)"
        @update:checked-row-keys="(keys: number[]) => selectedIds = new Set(keys)"
        size="small"
        :max-height="hasSelected ? 'calc(100vh - 480px)' : 'calc(100vh - 260px)'"
        virtual-scroll
        style="margin-bottom: 8px"
        @update:sorter="(s: any) => { if(s){sortKey=s.key;sortDir=s.order==='ascend'?'asc':'desc'} else {sortKey='';sortDir='asc'} }"
      />
    </n-spin>

    <!-- Sticky action bar -->
    <div v-if="hasSelected" class="action-bar">
      <n-card size="small" :bordered="true">
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
          <n-text>已选择 <strong>{{ selectedCount }}</strong> 个</n-text>
          <n-button size="tiny" @click="selectedIds = new Set()">清空</n-button>

          <div style="margin-left: auto; display: flex; gap: 8px; align-items: center;">
            <n-button type="default" size="small" @click="navigateTo('/schedules')">📅 加入计划</n-button>
            <n-button type="info" size="small" @click="navigateTo('/publish-tasks')">📤 立即发布</n-button>
            <n-button type="primary" size="small" @click="navigateTo('/compress')">⚡ 加入压缩任务</n-button>
          </div>
        </div>
      </n-card>
    </div>

    <!-- Unified task bar -->
    <div v-if="hasActiveTasks" class="progress-bar">
      <template v-for="job in runningJobs" :key="'c-'+job.id">
        <div class="progress-item">
          <div class="progress-header">
            <n-tag type="warning" size="tiny" round :bordered="false">⚡ 压缩</n-tag>
            <n-text style="font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ job.video_name }}</n-text>
            <n-text depth="3" style="font-size: 10px; flex-shrink: 0; white-space: nowrap;">
              <template v-if="job.status === 'running'">{{ job.elapsed_sec ? Math.floor(job.elapsed_sec/60)+'m'+Math.floor(job.elapsed_sec%60)+'s' : '' }}<template v-if="job.eta_sec"> · 剩余 {{ Math.floor(job.eta_sec/60) }}m{{ Math.floor(job.eta_sec%60) }}s</template></template>
              <template v-else-if="job.status === 'done'">完成</template>
              <template v-else-if="job.status === 'skipped'">已跳过</template>
              <template v-else-if="job.status === 'failed'">失败<template v-if="job.error">: {{ job.error.slice(0,40) }}</template></template>
            </n-text>
          </div>
          <n-progress type="line" :percentage="job.progress || 0" :height="12" :border-radius="6"
            :color="job.status === 'done' ? 'var(--color-green)' : job.status === 'failed' ? 'var(--color-red)' : 'var(--color-purple)'"
            :indicator-placement="'inside'" :processing="job.status === 'running'" />
        </div>
      </template>
      <template v-for="t in publishTasks" :key="'p-'+t.id">
        <div class="progress-item">
          <div class="progress-header">
            <n-tag type="default" size="tiny" round :bordered="false">📤 发布</n-tag>
            <n-text style="font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ t.video_name }}</n-text>
            <n-text depth="3" style="font-size: 10px; flex-shrink: 0; white-space: nowrap;">
              <template v-if="t.status === 'running' || t.status === 'uploading'">{{ t.elapsed_sec ? Math.floor(t.elapsed_sec/60)+'m'+Math.floor(t.elapsed_sec%60)+'s' : '' }}<template v-if="t.eta_sec"> · 剩余 {{ Math.floor(t.eta_sec/60) }}m{{ Math.floor(t.eta_sec%60) }}s</template></template>
              <template v-else-if="t.status === 'done'">完成</template>
              <template v-else-if="t.status === 'failed'">失败</template>
              <template v-else-if="t.status === 'cancelled'">已取消</template>
            </n-text>
          </div>
          <n-progress type="line" :percentage="t.progress || 0" :height="12" :border-radius="6"
            :color="t.status === 'done' ? 'var(--color-green)' : t.status === 'failed' ? 'var(--color-red)' : t.status === 'uploading' ? 'var(--color-purple)' : 'var(--color-purple)'"
            :indicator-placement="'inside'" :processing="t.status === 'running' || t.status === 'uploading'" />
          <n-button v-if="t.status === 'running' || t.status === 'uploading' || t.status === 'queued'" size="tiny" style="margin-top:4px" @click="cancelPublish(t.id)">取消</n-button>
              <n-text v-if="t.status === 'failed' || t.status === 'cancelled'" size="tiny" type="error" style="margin-top:4px;display:block">{{ t.error ? t.error.slice(0,60) : '任务失败' }}</n-text>
        </div>
      </template>
      <n-button size="tiny" style="margin-top: 6px" @click="clearProgress">清除已完成</n-button>
    </div>
  </PageContainer>
</template>

<style scoped>
.action-bar {
  position: sticky;
  bottom: 0;
  z-index: 10;
  padding-top: 8px;
  background: var(--body-bg);
}
.progress-bar { border-top: 1px solid var(--border-subtle); margin-top: 12px; padding: 10px 0 4px; display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
.progress-item { flex: 1; min-width: 200px; max-width: 350px; }
.progress-header { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; }
</style>
