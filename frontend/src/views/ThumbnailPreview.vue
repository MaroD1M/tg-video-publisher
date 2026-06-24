<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { NCard, NEmpty, NImage, NGrid, NGi, NText, NTag, NSpin, NButton, NSpace, NPopconfirm, useMessage } from 'naive-ui'
import { fetchThumbnails, getThumbnailImage, regenerateThumbnail, deleteThumbnail } from '@/api/client'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'

const message = useMessage()

interface Thumb {
  id: number; video_id: number; video_name: string; layout: string
  filepath: string; width: number; height: number; size_bytes: number; created_at: string
}

const thumbs = ref<Thumb[]>([])
const loading = ref(true)
const selectedIds = ref<Set<number>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)

async function load() {
  loading.value = true
  try {
    const data = await fetchThumbnails()
    thumbs.value = data.items || []
  } catch { message.error('加载缩略图失败') }
  loading.value = false
}

onMounted(load)

async function doRegenerate(thumbId: number) {
  try {
    await regenerateThumbnail(thumbId)
    message.success('已重新生成')
  } catch { message.error('重新生成失败') }
}

async function doDelete(thumbId: number) {
  try {
    await deleteThumbnail(thumbId)
    message.success('已删除')
    await load()
    selectedIds.value = new Set()
  } catch { message.error('删除失败') }
}

async function doBatchDelete() {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) { message.warning('请先选择缩略图'); return }
  let count = 0
  for (const id of ids) {
    try { await deleteThumbnail(id); count++ } catch {}
  }
  message.success(`已删除 ${count} 个`)
  await load()
  selectedIds.value = new Set()
}

function formatSize(bytes: number) {
  if (!bytes) return '-'
  return bytes < 1_000_000 ? (bytes / 1_000).toFixed(1) + ' KB' : (bytes / 1_000_000).toFixed(1) + ' MB'
}
</script>

<template>
  <PageContainer>
    <PageHeader title="缩略图" icon="🖼️">
      <n-button v-if="selectedCount > 0" size="small" type="error" @click="doBatchDelete">删除已选 ({{ selectedCount }})</n-button>
    </PageHeader>

    <n-spin :show="loading">
      <n-empty v-if="!loading && !thumbs.length" description="暂无缩略图，压缩完成后自动生成" style="margin-top: 80px" />

      <n-grid v-if="thumbs.length" :cols="4" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
        <n-gi v-for="t in thumbs" :key="t.id">
          <n-card size="small" hoverable :content-style="{ padding: '8px' }"
            :style="{ border: selectedIds.has(t.id) ? '2px solid var(--color-green)' : '1px solid var(--border-subtle)', cursor: 'pointer' }"
            @click="selectedIds.has(t.id) ? selectedIds.delete(t.id) : selectedIds.add(t.id); selectedIds = new Set(selectedIds)">
            <n-text depth="3" style="font-size: 11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:block; margin-bottom: 4px; text-align:center">{{ t.video_name }}</n-text>
            <n-tag size="tiny" style="margin-bottom: 6px; display:block; text-align:center">{{ t.layout }}</n-tag>
            <div class="thumb-blur" style="height: 180px; overflow: hidden; border-radius: 6px; background: rgba(0,0,0,0.1)">
              <n-image :src="getThumbnailImage(t.id)" width="100%" :preview-disabled="false" style="width:100%; height:100%; object-fit:cover" />
            </div>
            <n-text depth="3" style="font-size: 11px; display: block; margin-top: 6px; text-align: center;">{{ t.width }}×{{ t.height }} · {{ formatSize(t.size_bytes) }}</n-text>
            <n-space justify="center" style="margin-top: 6px" @click.stop>
              <n-button size="tiny" @click="doRegenerate(t.id)">重新生成</n-button>
              <n-popconfirm @positive-click="() => doDelete(t.id)">
                <template #trigger><n-button size="tiny" type="error">删除</n-button></template>
                确定删除此缩略图？
              </n-popconfirm>
            </n-space>
          </n-card>
        </n-gi>
      </n-grid>
    </n-spin>
  </PageContainer>
</template>
