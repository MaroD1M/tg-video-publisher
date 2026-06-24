<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NText, NButton, NSpace, NGrid, NGi, NStatistic, NPopconfirm, NEmpty, useMessage } from 'naive-ui'
import { fetchDiskCleanup, executeDiskCleanup } from '@/api/client'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'

const message = useMessage()
const data = ref<any>(null)
const loading = ref(true)

async function load() {
  loading.value = true
  try { data.value = await fetchDiskCleanup() } catch { message.error('加载失败') }
  loading.value = false
}

function formatSize(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1e6) return (bytes / 1e3).toFixed(1) + ' KB'
  if (bytes < 1e9) return (bytes / 1e6).toFixed(1) + ' MB'
  return (bytes / 1e9).toFixed(2) + ' GB'
}

async function del(paths: string[]) {
  try { await executeDiskCleanup({ paths }); message.success(`已删除 ${paths.length} 个文件`); load() }
  catch { message.error('删除失败') }
}

async function delPublished(category: string) {
  const files = category === 'output' ? data.value?.output?.published : data.value?.thumbnails?.published
  if (!files || !files.length) { message.warning('没有可清理的文件'); return }
  const paths = files.map((f: any) => f.path)
  await del(paths)
}

async function cleanTmp() {
  try { await executeDiskCleanup({ clean_tmp: true }); message.success('临时文件已清理'); load() }
  catch { message.error('清理失败') }
}

async function cleanBotCache() {
  try { await executeDiskCleanup({ clean_bot_cache: true }); message.success('Bot 缓存已清理'); load() }
  catch { message.error('清理失败') }
}

onMounted(load)
</script>

<template>
  <PageContainer>
    <PageHeader title="磁盘管理" icon="🧹" />

    <n-grid v-if="data" :cols="4" :x-gap="12" style="margin-bottom: 20px">
      <n-gi><n-card size="small" :bordered="true" style="text-align: center"><n-statistic label="输出目录" :value="formatSize(data.output.size)" /></n-card></n-gi>
      <n-gi><n-card size="small" :bordered="true" style="text-align: center"><n-statistic label="缩略图" :value="formatSize(data.thumbnails.size)" /></n-card></n-gi>
      <n-gi><n-card size="small" :bordered="true" style="text-align: center"><n-statistic label="临时文件" :value="formatSize(data.tmp.size)" /></n-card></n-gi>
      <n-gi><n-card size="small" :bordered="true" style="text-align: center"><n-statistic label="Bot缓存" :value="formatSize(data.bot_cache.size)" /></n-card></n-gi>
    </n-grid>

    <n-empty v-if="!loading && !data" description="无法获取磁盘信息" style="margin-top: 80px" />

    <!-- Orphan outputs -->
    <n-card size="small" title="🗑 未被引用的压缩文件" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:11px;display:block;margin-bottom:8px">文件存在于输出目录，但在压缩任务中已无对应记录，可安全删除</n-text>
      <n-empty v-if="!data?.output.orphans.length" description="干净，无冗余文件 👍" style="margin:8px 0" />
      <div v-for="f in data.output.orphans" :key="f.path" style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid var(--border-subtle);font-size:13px">
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ f.name }}</n-text>
        <n-text depth="3">{{ formatSize(f.size) }}</n-text>
        <n-popconfirm :on-positive-click="() => del([f.path])" positive-text="确定" negative-text="取消"><n-button size="tiny" type="error">删除</n-button>确定删除？</n-popconfirm>
      </div>
    </n-card>

    <!-- Published outputs -->
    <n-card v-if="data?.output.published.length" size="small" title="📤 已发布的压缩文件" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:11px;display:block;margin-bottom:8px">这些压缩文件已成功发布到 Telegram，占 {{ formatSize(data.output.published_size) }}，可安全删除以释放磁盘空间</n-text>
      <div v-for="f in data.output.published.slice(0, 10)" :key="f.path" style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid var(--border-subtle);font-size:13px">
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ f.name }}</n-text>
        <n-text depth="3">{{ formatSize(f.size) }}</n-text>
        <n-popconfirm :on-positive-click="() => del([f.path])" positive-text="确定" negative-text="取消"><n-button size="tiny" type="warning">删除</n-button>确定删除？</n-popconfirm>
      </div>
      <n-text v-if="data.output.published.length > 10" depth="3" style="font-size:11px;display:block;margin-top:4px">...还有 {{ data.output.published.length - 10 }} 个文件</n-text>
      <n-button size="tiny" type="error" style="margin-top:8px" @click="delPublished('output')">删除全部已发布 ({{ data.output.published.length }})</n-button>
    </n-card>

    <!-- Orphan thumbnails -->
    <n-card size="small" title="🗑 未被引用的缩略图" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:11px;display:block;margin-bottom:8px">文件存在于缩略图目录，但在缩略图库中已无对应记录，可安全删除</n-text>
      <n-empty v-if="!data?.thumbnails.orphans.length" description="干净，无冗余文件 👍" style="margin:8px 0" />
      <div v-for="f in data.thumbnails.orphans" :key="f.path" style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid var(--border-subtle);font-size:13px">
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ f.name }}</n-text>
        <n-text depth="3">{{ formatSize(f.size) }}</n-text>
        <n-popconfirm :on-positive-click="() => del([f.path])" positive-text="确定" negative-text="取消"><n-button size="tiny" type="error">删除</n-button>确定删除？</n-popconfirm>
      </div>
    </n-card>

    <!-- Published thumbnails -->
    <n-card v-if="data?.thumbnails.published.length" size="small" title="📤 已发布的缩略图" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:11px;display:block;margin-bottom:8px">这些缩略图已发布到 Telegram，占 {{ formatSize(data.thumbnails.published_size) }}，可安全删除</n-text>
      <div v-for="f in data.thumbnails.published.slice(0, 10)" :key="f.path" style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid var(--border-subtle);font-size:13px">
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ f.name }}</n-text>
        <n-text depth="3">{{ formatSize(f.size) }}</n-text>
        <n-popconfirm :on-positive-click="() => del([f.path])" positive-text="确定" negative-text="取消"><n-button size="tiny" type="warning">删除</n-button>确定删除？</n-popconfirm>
      </div>
      <n-text v-if="data.thumbnails.published.length > 10" depth="3" style="font-size:11px;display:block;margin-top:4px">...还有 {{ data.thumbnails.published.length - 10 }} 个文件</n-text>
      <n-button size="tiny" type="error" style="margin-top:8px" @click="delPublished('thumbnails')">删除全部已发布 ({{ data.thumbnails.published.length }})</n-button>
    </n-card>

    <!-- Temp files -->
    <n-card v-if="data?.tmp.count" size="small" title="🗑 临时文件 (compress_workers)" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:12px;display:block;margin-bottom:8px">{{ data.tmp.count }} 个文件，占 {{ formatSize(data.tmp.size) }}</n-text>
      <n-popconfirm :on-positive-click="cleanTmp" positive-text="确定" negative-text="取消"><n-button size="small" type="warning">一键清理</n-button>确定清理所有临时文件？</n-popconfirm>
    </n-card>
    <!-- Bot cache -->
    <n-card v-if="data?.bot_cache.files.length" size="small" title="🗑 Bot API 缓存 (bot-api-data)" style="margin-bottom: 16px">
      <n-text depth="3" style="font-size:11px;display:block;margin-bottom:8px">{{ data.bot_cache.count }} 个文件，占 {{ formatSize(data.bot_cache.size) }}，清理后 Bot API 需重新建立连接</n-text>
      <div v-for="f in data.bot_cache.files.slice(0, 15)" :key="f.path" style="display:flex;align-items:center;gap:12px;padding:3px 0;border-bottom:1px solid var(--border-subtle);font-size:12px;font-family:monospace">
        <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ f.name }}</n-text>
        <n-text depth="3">{{ formatSize(f.size) }}</n-text>
      </div>
      <n-text v-if="data.bot_cache.files.length > 15" depth="3" style="font-size:11px;display:block;margin-top:4px">...还有 {{ data.bot_cache.files.length - 15 }} 个文件</n-text>
      <n-popconfirm :on-positive-click="cleanBotCache" positive-text="确定" negative-text="取消" style="margin-top:8px"><n-button size="small" type="error">清理全部缓存</n-button>确定清理 Bot API 缓存？此操作可能导致 Bot API 重新登录</n-popconfirm>
    </n-card>
  </PageContainer>
</template>
