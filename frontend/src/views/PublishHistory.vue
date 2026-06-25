<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { NEmpty, NCard, NDataTable, NTag, NText, NSpin, NInput, NSelect, NSpace, NButton, NDatePicker, NImage, NPopconfirm, useMessage } from 'naive-ui'
import { fetchLogsWithFilters, fetchChats, retryPublishTask, getThumbnailImage, deletePublishLog } from '@/api/client'
import { formatSize } from '@/utils/format'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'

const logs = ref<any[]>([])
const loading = ref(true)
const message = useMessage()
const total = ref(0)

const searchText = ref('')
const filterSuccess = ref<string | null>(null)
const filterChatId = ref<number | null>(null)
const filterDateFrom = ref<number | null>(null)
const filterDateTo = ref<number | null>(null)
const channels = ref<any[]>([])
const currentPage = ref(1)
const pageSize = 20

const columns = [
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true }, render: (r: any) => {
    if (r.thumbnail_id) {
      return         h('span', { class: 'thumb-blur', style: 'display:inline-flex;align-items:center;gap:6px' }, [
        h(NImage, { src: getThumbnailImage(r.thumbnail_id), width: 40, height: 23, objectFit: 'cover', style: 'border-radius:3px;cursor:pointer;vertical-align:middle', previewDisabled: false, showToolbar: false }),
        h('span', r.filename),
      ])
    }
    return r.filename
  }},
  { title: '目标', key: 'target_chat_name', width: 130, ellipsis: { tooltip: true }, render: (r: any) => r.target_chat_name || String(r.target_chat_id || '-') },
  {
    title: '大小', key: 'size_info', width: 140, render: (r: any) => {
      if (r.compression_ratio) return `原 ${formatSize(r.original_size || 0)} → ${formatSize(r.size || 0)} (${r.compression_ratio}%)`
      return r.size ? formatSize(r.size) : '—'
    }
  },
  {
    title: '状态', key: 'success', width: 60,
    render: (r: any) => h(NTag, { type: r.success ? 'success' : 'error', size: 'small' },
      { default: () => r.success ? '成功' : '失败' }
    ),
  },
  { title: '时间', key: 'published_at', width: 140 },
  { title: '错误', key: 'error_msg', ellipsis: { tooltip: true }, width: 160, render: (r: any) => r.error_msg || '—' },
  {
    title: '操作', key: 'actions', width: 100,
    render: (r: any) => {
      const btns: any[] = []
      if (!r.success && r.video_id) {
        btns.push(h(NButton, { size: 'tiny', type: 'primary', onClick: () => doRetryFromHistory(r) }, { default: () => '重试' }))
      }
      btns.push(
        h(NPopconfirm, { onPositiveClick: () => doDeleteLog(r.id) }, {
          trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }),
          default: () => '确定删除？',
        })
      )
      return h('div', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, btns)
    }
  },
]

async function loadChannels() {
  try { const d = await fetchChats(); channels.value = d.items || [] } catch {}
}

async function load() {
  loading.value = true
  try {
    const params: any = { page: currentPage.value, page_size: pageSize }
    if (searchText.value) params.search = searchText.value
    if (filterSuccess.value !== null) params.success = filterSuccess.value === 'success' ? true : false
    if (filterChatId.value) params.chat_id = filterChatId.value
    if (filterDateFrom.value) params.date_from = new Date(filterDateFrom.value).toISOString()
    if (filterDateTo.value) params.date_to = new Date(filterDateTo.value).toISOString()
    const data = await fetchLogsWithFilters(params)
    logs.value = data.items || []
    total.value = data.total || 0
  } catch { message.error('加载发布记录失败') }
  loading.value = false
}

function handlePageChange(page: number) {
  currentPage.value = page
  load()
}

function onSearch() {
  currentPage.value = 1
  load()
}

function clearFilters() {
  searchText.value = ''
  filterSuccess.value = null
  filterChatId.value = null
  filterDateFrom.value = null
  filterDateTo.value = null
  currentPage.value = 1
  load()
}

async function doRetryFromHistory(row: any) {
  if (!row.video_id) return
  try {
    await retryPublishTask(row.id)
    message.success('已重新加入发布队列')
  } catch { message.error('重试失败') }
}

async function doDeleteLog(logId: number) {
  try { await deletePublishLog(logId); message.success('已删除'); load() }
  catch { message.error('删除失败') }
}

onMounted(() => {
  loadChannels()
  load()
})
</script>

<template>
  <PageContainer>
    <PageHeader title="发布记录" icon="📋" />

    <n-card size="small" style="margin-bottom: 12px">
      <n-space align="center" :size="8" wrap>
        <n-input v-model:value="searchText" placeholder="搜索文件名..." size="small" style="width: 180px" clearable @keyup.enter="onSearch" @clear="onSearch" />
        <n-select
          v-model:value="filterSuccess" :options="[
            { label: '全部状态', value: null as any },
            { label: '成功', value: 'success' },
            { label: '失败', value: 'failed' },
          ]" size="small" style="width: 100px" @update:value="onSearch" />
        <n-select
          v-model:value="filterChatId" :options="[
            { label: '全部频道', value: null as any },
            ...channels.map((c: any) => ({ label: (c.alias || c.chat_name || String(c.chat_id)).length > 18 ? (c.alias || c.chat_name || String(c.chat_id)).slice(0, 16) + '…' : (c.alias || c.chat_name || String(c.chat_id)), value: c.chat_id })),
          ]" size="small" style="width: 150px" @update:value="onSearch" filterable />
        <n-date-picker v-model:value="filterDateFrom" type="date" size="small" placeholder="开始" style="width: 120px" clearable @update:value="onSearch" />
        <n-date-picker v-model:value="filterDateTo" type="date" size="small" placeholder="结束" style="width: 120px" clearable @update:value="onSearch" />
        <n-button size="small" @click="clearFilters">清除</n-button>
        <n-text v-if="total" depth="3" style="font-size: 12px; margin-left: auto">共 {{ total }} 条</n-text>
      </n-space>
    </n-card>

    <n-card size="small">
      <n-spin :show="loading">
        <n-empty v-if="!loading && !logs.length" description="暂无发布记录" style="margin: 40px 0" />
        <n-dataTable
          v-else
          :columns="columns"
          :data="logs"
          :loading="loading"
          :pagination="{ page: currentPage, pageSize: pageSize, itemCount: total, onChange: handlePageChange }"
          size="small"
        />
      </n-spin>
    </n-card>
  </PageContainer>
</template>
