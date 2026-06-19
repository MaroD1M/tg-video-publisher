<script setup lang="ts">
import { ref, onMounted, onUnmounted, h } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NGrid, NGi, NText, NButton, NDataTable, NTag, NAlert, NSpace, NSpin, NDivider, useMessage } from 'naive-ui'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import StatusDot from '@/components/shared/StatusDot.vue'
import { fetchChats, refreshChats } from '@/api/client'
import api from '@/api/client'

const router = useRouter()
const message = useMessage()
const loading = ref(true)
const channels = ref<any[]>([])
const status = ref<Record<string, any>>({})
const testing = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const channelColumns = [
  { title: '名称', key: 'chat_name', ellipsis: { tooltip: true } },
  { title: '类型', key: 'chat_type', width: 80, render: (r: any) => r.chat_type === 'channel' ? '频道' : r.chat_type === 'supergroup' ? '群组' : r.chat_type },
  { title: 'Chat ID', key: 'chat_id', width: 170, render: (r: any) => h(NText, { depth: '3', style: 'font-family:monospace;font-size:12px' }, { default: () => String(r.chat_id) }) },
]

function diagLevel(type: string): 'success' | 'error' | 'warning' | 'info' {
  const m: Record<string, any> = { success: 'success', error: 'error', warn: 'warning', info: 'info' }
  return m[type] || 'info'
}

function procStateColor(state: string): 'success' | 'error' | 'warning' | 'default' {
  if (state === 'RUNNING') return 'success'
  if (state === 'FATAL' || state === 'EXITED') return 'error'
  if (state === 'BACKOFF' || state === 'STARTING') return 'warning'
  return 'default'
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/bot/status')
    status.value = data
  } catch { message.error('加载 Bot 状态失败') }
  try {
    const d = await fetchChats()
    channels.value = d.items || []
  } catch {}
  loading.value = false
}

async function doTest() {
  testing.value = true
  await load()
  testing.value = false
}

async function doRefreshChats() {
  try {
    await refreshChats()
    message.success('已刷新')
    const d = await fetchChats()
    channels.value = d.items || []
  } catch { message.error('刷新失败') }
}

onMounted(load)
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <PageContainer>
    <PageHeader title="Bot 状态诊断" icon="🤖" />

    <n-spin :show="loading">
      <!-- Diagnosis -->
      <div style="margin-bottom: 16px">
        <div v-for="(d, i) in status.diagnosis" :key="i" style="margin-bottom: 6px">
          <n-alert :type="diagLevel(d.level)" :bordered="false">
            {{ d.msg }}
          </n-alert>
        </div>
      </div>

      <n-grid :cols="2" :x-gap="16" :y-gap="16" style="margin-bottom: 16px">
        <!-- Connection -->
        <n-gi>
          <n-card size="small" title="连接状态" :bordered="true">
            <n-space vertical :size="10">
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <StatusDot :status="status.bot?.ok ? 'ok' : 'error'" :size="10" />
                  <n-text :style="{ fontSize: '15px', fontWeight: '600' }">{{ status.bot?.ok ? '已连接' : '离线' }}</n-text>
                  <n-text v-if="status.bot?.username" style="font-size: 12px; opacity: 0.5">@{{ status.bot.username }}</n-text>
                </div>
                <n-text v-if="status.bot?.error" depth="3" style="font-size: 11px; display: block; margin-top: 2px">{{ status.bot.error }}</n-text>
              </div>
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <StatusDot :status="status.bot_server?.ok ? 'ok' : 'error'" :size="10" />
                  <n-text :style="{ fontSize: '14px' }">API 服务器 (localhost:8081)</n-text>
                  <n-tag :type="status.bot_server?.ok ? 'success' : 'error'" size="tiny">{{ status.bot_server?.ok ? '运行中' : '不可达' }}</n-tag>
                </div>
                <n-text v-if="status.bot_server?.error" depth="3" style="font-size: 11px; display: block; margin-top: 2px">{{ status.bot_server.error }}</n-text>
                <div v-if="status.bot_server?.process" style="display: flex; gap: 12px; margin-top: 4px">
                  <n-tag :type="procStateColor(status.bot_server.process.state)" size="tiny">{{ status.bot_server.process.state }}</n-tag>
                  <n-text v-if="status.bot_server.process.pid" depth="3" style="font-size: 11px">PID {{ status.bot_server.process.pid }}</n-text>
                  <n-text v-if="status.bot_server.process.uptime" depth="3" style="font-size: 11px">{{ status.bot_server.process.uptime }}</n-text>
                </div>
              </div>
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <StatusDot :status="status.dns?.ok ? 'ok' : 'error'" :size="10" />
                  <n-text :style="{ fontSize: '14px' }">DNS 解析</n-text>
                  <n-tag :type="status.dns?.ok ? 'success' : 'error'" size="tiny">{{ status.dns?.ok ? '正常' : '失败' }}</n-tag>
                </div>
                <n-text depth="3" style="font-size: 10px; display: block; margin-top: 1px">{{ status.dns?.target || 'pluto.web.telegram.org' }}</n-text>
                <n-text v-if="status.dns?.ips?.length" depth="3" style="font-size: 11px; display: block; margin-top: 2px">{{ status.dns.ips.join(', ') }}</n-text>
                <n-text v-if="status.dns?.error" depth="3" style="font-size: 11px; display: block; margin-top: 2px">{{ status.dns.error }}</n-text>
              </div>
              <div>
                <n-text depth="3" style="font-size: 12px">已发现频道</n-text>
                <n-text :style="{ fontSize: '20px', fontWeight: '700', display: 'block' }">{{ status.channel_count ?? '-' }}</n-text>
              </div>
            </n-space>
          </n-card>
        </n-gi>

        <!-- Config -->
        <n-gi>
          <n-card size="small" title="配置详情" :bordered="true">
            <n-space vertical :size="6">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <n-text>Bot Token</n-text>
                <n-tag :type="status.config?.bot_token ? 'success' : 'error'" size="small">{{ status.config?.bot_token ? (status.config?.bot_token_preview || '已配置') : '未配置' }}</n-tag>
              </div>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <n-text>API ID</n-text>
                <n-tag :type="status.config?.api_id ? 'success' : 'error'" size="small">{{ status.config?.api_id || '未配置' }}</n-tag>
              </div>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <n-text>API Hash</n-text>
                <n-tag :type="status.config?.api_hash ? 'success' : 'error'" size="small">{{ status.config?.api_hash ? '已配置' : '未配置' }}</n-tag>
              </div>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <n-text>管理员 Chat ID</n-text>
                <n-tag :type="status.config?.admin_chat_id ? 'success' : 'info'" size="small">{{ status.config?.admin_chat_id || '未配置' }}</n-tag>
              </div>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <n-text>代理</n-text>
                <n-tag :type="status.config?.proxy_enabled ? 'success' : 'default'" size="small">{{ status.config?.proxy_enabled ? '已启用' : '未启用' }}</n-tag>
              </div>
              <template v-if="status.proxy?.config">
                <n-divider style="margin: 4px 0" />
                <n-text depth="3" style="font-size: 11px">{{ status.proxy.config.type }}://{{ status.proxy.config.host }}:{{ status.proxy.config.port }}{{ status.proxy.config.has_auth ? ' (有认证)' : '' }}</n-text>
                <div style="display: flex; align-items: center; gap: 6px">
                  <StatusDot :status="status.proxy?.check ? 'ok' : 'error'" :size="8" />
                  <n-text depth="3" style="font-size: 11px">{{ status.proxy?.check ? 'TCP 连通' : status.proxy?.error || '连接失败' }}</n-text>
                </div>
              </template>
            </n-space>
          </n-card>
        </n-gi>
      </n-grid>

      <!-- Env file -->
      <n-card v-if="status.env" size="small" title="📁 Bot API 环境文件" :bordered="true" style="margin-bottom: 16px">
        <n-space :size="12">
          <n-tag :type="status.env.exists ? 'success' : 'error'" size="small">{{ status.env.exists ? '文件存在' : '文件不存在' }}</n-tag>
          <n-tag :type="status.env.has_api_id ? 'success' : 'error'" size="small">{{ status.env.has_api_id ? 'API ID 已写入' : 'API ID 缺失' }}</n-tag>
          <n-tag :type="status.env.has_proxy ? 'success' : (status.config?.proxy_enabled ? 'warning' : 'default')" size="small">{{ status.env.has_proxy ? '代理已写入' : (status.config?.proxy_enabled ? '代理未写入' : '无代理') }}</n-tag>
        </n-space>
      </n-card>

      <!-- Channels -->
      <n-card size="small" title="频道列表" :bordered="true" style="margin-bottom: 16px">
        <n-empty v-if="!channels.length" description="暂无频道" style="margin: 20px 0" />
        <n-dataTable v-else :columns="channelColumns" :data="channels" :pagination="false" size="small" />
      </n-card>

      <!-- Actions -->
      <n-card size="small" :bordered="true">
        <n-space :size="12">
          <n-button type="primary" :loading="testing" @click="doTest">刷新诊断</n-button>
          <n-button @click="doRefreshChats">自动刷新频道</n-button>
          <n-button @click="router.push('/settings')">⚙️ 系统设置</n-button>
        </n-space>
      </n-card>
    </n-spin>
  </PageContainer>
</template>
