<script setup lang="ts">
import { ref, onMounted, computed, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NInput, NButton, NDataTable, NSpace,
  NTag, NText, NEmpty,
  NBreadcrumb, NBreadcrumbItem, NSpin, NProgress, NIcon,
  NPopconfirm, NPopover, NSelect, useMessage,
} from 'naive-ui'
import { ScanOutline } from '@vicons/ionicons5'
import { fetchVideos, scanDirectory, deleteVideo, publishNow, cancelPublishTask, retryPublishTask } from '@/api/client'
import { useSettingsStore } from '@/stores/settings'
import { useTaskStore } from '@/stores/tasks'
import { useWebSocket } from '@/composables/useWebSocket'
import { useChannels } from '@/composables/useChannels'
import { formatSize, formatDuration, formatChannelLabel } from '@/utils/format'
import type { Video } from '@/types'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import StatusTag from '@/components/shared/StatusTag.vue'
import ChannelSelect from '@/components/shared/ChannelSelect.vue'

const message = useMessage()
const router = useRouter()

const settingsStore = useSettingsStore()
const taskStore = useTaskStore()
const { channels, channelOptions, load: loadChannels } = useChannels()

function navigateTo(path: string) {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) { message.warning('请先选择视频'); return }
  const query: Record<string, string> = { ids: ids.join(',') }
  if (path === '/publish-tasks' && publishChannel.value) {
    query.channel_id = String(publishChannel.value)
  }
  router.push({ path, query })
}

function unselectVideo(id: number) {
  const next = new Set(selectedIds.value)
  next.delete(id)
  selectedIds.value = next
}

const currentPath = ref('/data/videos')
const videoSourceDirs = ref<string[]>(['/data/videos'])
const selectedRootDir = ref('/data/videos')
const videos = ref<Video[]>([])
const loading = ref(false)
const scanning = ref(false)
const selectedIds = ref<Set<number>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)
const selectedVideos = computed(() =>
  (videos.value || []).filter(v => selectedIds.value.has(v.id))
)
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
      const va = a[sortKey.value as keyof Video] ?? ''; const vb = b[sortKey.value as keyof Video] ?? ''
      const n = typeof va === 'number' ? (va as number) - (vb as number) : String(va).localeCompare(String(vb))
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

function switchRootDir(dir: string) {
  selectedRootDir.value = dir
  currentPath.value = dir
  selectedIds.value = new Set()
  loadVideos()
}

async function browseDir(path?: string) {
  if (path !== undefined) {
    if (!path.startsWith(selectedRootDir.value)) {
      path = selectedRootDir.value
    }
    currentPath.value = path
  }
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

async function doPublishOne(videoId: number) {
  if (!publishChannel.value) { message.warning('请先在操作栏选择发布频道'); return }
  try {
    message.loading('加入发布队列...')
    await publishNow(videoId, publishChannel.value)
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
  { title: '大小', key: 'size_bytes', width: 100, render: (r: Video) => formatSize(r.size_bytes), sorter: true },
  { title: '时长', key: 'duration_sec', width: 90, render: (r: Video) => formatDuration(r.duration_sec || 0), sorter: true },
  { title: '分辨率', key: 'resolution', width: 110, render: (r: Video) => r.width ? `${r.width}x${r.height}` : '-', sorter: true },
  {
    title: '状态', key: 'status', width: 110,
    render: (r: Video) => {
      const tags = [h(StatusTag, { status: r.status })]
      if (r.is_published) {
        tags.push(h(NTag, { type: 'success', size: 'small', bordered: false, style: 'margin-left:4px' }, { default: () => '📤 已发布' }))
      }
      return h(NSpace, { size: 'small' }, { default: () => tags })
    },
  },
  {
    title: '操作', key: 'actions', width: 100,
    render: (r: Video) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', onClick: () => doPublishOne(r.id) }, { default: () => '发布' }),
        h(NPopconfirm, { onPositiveClick: () => doDeleteOne(r.id) },
          { trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }), default: () => '确定删除？' }
        ),
      ],
    }),
  },
]

const publishChannel = ref<number | null>(null)

const { connect: connectWS } = useWebSocket(
  '/ws/compress',
  (e) => { try { taskStore.handleWSMessage(JSON.parse(e.data)) } catch {} }
)

async function cancelPublish(taskId: number) {
  try { await cancelPublishTask(taskId) } catch { message.error('取消失败') }
}
async function retryPublish(taskId: number) {
  try { await retryPublishTask(taskId); message.success('已重新加入队列') } catch { message.error('重试失败') }
}

onMounted(async () => {
  loadChannels()
  connectWS()
  try {
    const data = await settingsStore.loadSettings()
    const dirs = data.video_source_dirs
    if (dirs && dirs.length) {
      videoSourceDirs.value = dirs
      selectedRootDir.value = dirs[0]
      currentPath.value = dirs[0]
    }
  } catch {}
  browseDir()
})

const hasActiveTasks = computed(() => taskStore.hasActive)
const runningJobs = computed(() => taskStore.runningJobs)
const publishTasks = computed(() => taskStore.publishTasks)
</script>

<template>
  <PageContainer>
    <PageHeader title="视频工作台" icon="📹" />

    <n-card size="small" style="margin-bottom: 12px">
      <n-space vertical :size="8">
        <n-space :size="8" align="center" v-if="videoSourceDirs.length > 1">
          <n-text depth="3" style="font-size: 12px; white-space: nowrap;">视频源：</n-text>
          <n-select
            v-model:value="selectedRootDir"
            :options="videoSourceDirs.map((d: string) => ({ label: d, value: d }))"
            size="small"
            style="width: 220px"
            @update:value="switchRootDir"
          />
        </n-space>
        <n-breadcrumb>
          <n-breadcrumb-item v-for="(crumb, i) in breadcrumbs" :key="crumb.path" @click="browseDir(crumb.path)">
            {{ i === 0 ? '📁' : '' }} {{ crumb.name }}
          </n-breadcrumb-item>
        </n-breadcrumb>
        <n-space :size="8">
          <n-input v-model:value="currentPath" size="small" :placeholder="selectedRootDir" style="flex: 1" clearable />
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
        :row-key="(r: Video) => r.id"
        :checked-row-keys="Array.from(selectedIds)"
        @update:checked-row-keys="(keys: number[]) => selectedIds = new Set(keys)"
        size="small"
        :max-height="'calc(100vh - 360px)'"
        virtual-scroll
        style="margin-bottom: 8px"
        @update:sorter="(s: any) => { if(s){sortKey=s.key;sortDir=s.order==='ascend'?'asc':'desc'} else {sortKey='';sortDir='asc'} }"
      />
    </n-spin>

    <!-- Sticky action bar — always visible -->
    <div class="action-bar">
      <n-card size="small" :bordered="true">
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
          <n-popover trigger="click" :disabled="selectedCount === 0" :width="260" placement="top-start">
            <template #trigger>
              <n-text :depth="selectedCount === 0 ? 3 : undefined" style="cursor: pointer; user-select: none;">
                已选择 <strong>{{ selectedCount }}</strong> 个 <span style="font-size:10px;opacity:0.5">▾</span>
              </n-text>
            </template>
            <div style="max-height: 240px; overflow-y: auto; margin-bottom: 8px;">
              <div v-for="v in selectedVideos" :key="v.id"
                style="display: flex; align-items: center; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid var(--border-subtle); font-size: 12px;">
                <n-text style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;">{{ v.filename }}</n-text>
                <n-button size="tiny" quaternary type="error" @click="unselectVideo(v.id)" style="margin-left: 6px; flex-shrink: 0;">✕</n-button>
              </div>
              <n-empty v-if="!selectedVideos.length" description="无选中视频" style="margin: 12px 0;" />
            </div>
            <n-button size="tiny" type="error" block @click="selectedIds = new Set()" style="margin-top: 4px;">清空全部</n-button>
          </n-popover>
          <n-button size="tiny" :disabled="selectedCount === 0" @click="selectedIds = new Set()">清空</n-button>

          <ChannelSelect v-model="publishChannel" size="tiny" width="140px" />

          <div style="margin-left: auto; display: flex; gap: 8px; align-items: center;">
            <n-button type="default" size="small" :disabled="selectedCount === 0" @click="navigateTo('/schedules')">📅 加入计划</n-button>
            <n-button type="info" size="small" :disabled="selectedCount === 0" @click="navigateTo('/publish-tasks')">📤 立即发布</n-button>
            <n-button type="primary" size="small" :disabled="selectedCount === 0" @click="navigateTo('/compress')">⚡ 加入压缩任务</n-button>
          </div>
        </div>
      </n-card>
    </div>

    <!-- Unified task bar -->
    <div v-if="hasActiveTasks" class="progress-bar">
      <template v-for="job in runningJobs" :key="'c-'+job.id">
        <div class="progress-item">
          <div class="progress-header">
            <StatusTag status="compressing" />
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
            <StatusTag status="running" />
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
      <n-button size="tiny" style="margin-top: 6px" @click="taskStore.clearDone">清除已完成</n-button>
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
