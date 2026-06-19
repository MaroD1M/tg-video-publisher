<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NGrid, NGi, NStatistic, NProgress, NTag, NText, NSpin, NTooltip, useMessage } from 'naive-ui'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import StatusDot from '@/components/shared/StatusDot.vue'
import { fetchStats, fetchDiskUsage, fetchLogs } from '@/api/client'

const message = useMessage()
const stats = ref<Record<string, any>>({ total_videos: 0, compressed: 0, queued: 0, today_published: 0, compress_running: 0, compress_queued: 0 })
const disk = ref({ used_gb: 0, total_gb: 100, percent: 0 })
const recentLogs = ref<any[]>([])
const loading = ref(true)

onMounted(async () => {
  try { stats.value = await fetchStats() } catch { message.warning('部分统计数据加载失败') }
  try {
    const d = await fetchDiskUsage()
    disk.value = { used_gb: d.used_gb || 0, total_gb: d.total_gb || 100, percent: d.percent || 0 }
  } catch { message.warning('磁盘信息加载失败') }
  try {
    const l = await fetchLogs({ page_size: 5 })
    recentLogs.value = l.items || []
  } catch { message.warning('发布记录加载失败') }
  loading.value = false
})

function botStatus(): 'ok' | 'error' | 'unknown' {
  if (stats.value.bot) return 'ok'
  if (stats.value.bot === false) return 'error'
  return 'unknown'
}
</script>

<template>
  <PageContainer>
    <PageHeader title="仪表盘" icon="📊" />

    <n-spin :show="loading">
      <n-grid :cols="6" :x-gap="16" :y-gap="16" responsive="screen" style="margin-bottom: 24px">
        <n-gi>
          <n-card size="small" :bordered="true">
            <n-statistic label="原视频" :value="stats.total_videos || 0" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small" :bordered="true">
            <n-statistic label="已压缩" :value="stats.compressed || 0" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small" :bordered="true" :style="{ background: stats.compress_running ? 'var(--bg-purple)' : '' }">
            <n-statistic label="压缩中" :value="stats.compress_running || 0" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small" :bordered="true">
            <n-statistic label="待发布" :value="stats.queued || 0" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small" :bordered="true">
            <n-statistic label="今日发布" :value="stats.today_published || 0" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card size="small" :bordered="true">
            <n-statistic label="Bot 状态">
              <template #suffix>
                <n-tooltip trigger="hover">
                  <template #trigger>
                    <n-text :style="{ fontSize: '14px', fontWeight: '600', cursor: stats.bot_error ? 'help' : 'default' }">
                      <StatusDot :status="botStatus()" :size="9" style="vertical-align: middle; margin-right: 4px" />
                      {{ stats.bot ? '正常' : '离线' }}
                    </n-text>
                  </template>
                  {{ stats.bot_error || (stats.bot ? '连接正常' : '连接异常') }}
                </n-tooltip>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
      </n-grid>

      <n-card title="磁盘用量" size="small" style="margin-bottom: 24px">
        <n-progress
          type="line"
          :percentage="disk.percent"
          :indicator-placement="'inside'"
          :height="24"
          :border-radius="4"
          :color="disk.percent > 90 ? '#e64e4e' : disk.percent > 70 ? '#faad14' : '#63e2b7'"
        />
        <n-text depth="3" style="margin-top: 8px; display: block;">
          {{ disk.used_gb.toFixed(1) }} GB / {{ disk.total_gb.toFixed(1) }} GB
        </n-text>
      </n-card>

      <n-card title="最近发布" size="small">
        <div v-if="recentLogs.length" style="display:flex;flex-direction:column;gap:6px">
          <div v-for="log in recentLogs" :key="log.id" style="display:flex;align-items:center;gap:8px">
            <n-tag :type="log.success ? 'success' : 'error'" size="small" :bordered="false" round>
              {{ log.success ? '成功' : '失败' }}
            </n-tag>
            <n-text style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px">{{ log.filename || 'Unknown' }}</n-text>
            <n-text depth="3" style="font-size:11px;flex-shrink:0;white-space:nowrap">
              {{ log.published_at ? new Date(log.published_at).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '' }}
            </n-text>
          </div>
        </div>
        <n-text v-else depth="3">暂无发布记录</n-text>
      </n-card>
    </n-spin>
  </PageContainer>
</template>
