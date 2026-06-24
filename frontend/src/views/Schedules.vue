<script setup lang="ts">
import { ref, onMounted, h, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import {
  NCard, NButton, NModal, NForm, NFormItem, NInput, NSelect,
  NDataTable, NSpace, NTag, NPopconfirm, NText, NAlert, NIcon, NTooltip, useMessage
} from 'naive-ui'
import { AddOutline, InformationCircleOutline } from '@vicons/ionicons5'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import {
  fetchSchedules, createSchedule, updateSchedule, deleteSchedule, triggerSchedule, fetchChats, batchAddToSchedule
} from '@/api/client'
import api from '@/api/client'

const message = useMessage()
const route = useRoute()
const pendingVideos = ref<any[]>([])
const pendingScheduleId = ref<number | null>(null)

async function initPending() {
  const ids = route.query.ids as string
  if (!ids) return
  try {
    const { data } = await api.get('/videos', { params: { page_size: 100 } })
    const idSet = new Set(ids.split(',').map(Number))
    pendingVideos.value = (data.items || []).filter((v: any) => idSet.has(v.id))
  } catch {}
}

async function batchAdd() {
  if (!pendingScheduleId.value || !pendingVideos.value.length) { message.warning('请选择计划'); return }
  message.loading('加入计划...')
  try {
    await batchAddToSchedule(pendingScheduleId.value, pendingVideos.value.map(v => v.id))
    message.success(`已添加 ${pendingVideos.value.length} 个视频到计划`)
    pendingVideos.value = []
  } catch { message.error('添加失败') }
}
const schedules = ref<any[]>([])
const showModal = ref(false)
const editing = ref<any>(null)
const form = ref({ name: '', cron_expr: '0 20 * * *', target_chat_id: '', queue_strategy: 'sequential', thumb_caption_template: '', video_caption_template: '' })
const selectedChannelId = ref<number | null>(null)
const channelOptions = ref<{ label: string; value: number }[]>([])
const cronPreview = ref<string[]>([])
const previewLoading = ref(false)

async function loadCronPreview() {
  if (!form.value.cron_expr || !form.value.cron_expr.trim()) return
  previewLoading.value = true
  try {
    const { data } = await api.get('/cron/preview', { params: { expr: form.value.cron_expr } })
    cronPreview.value = data.times || []
  } catch { cronPreview.value = [] }
  previewLoading.value = false
}

const cronPreset = ref('')
const saving = ref(false)
const cronPresets = [
  { label: '每天 08:00', value: '0 8 * * *' },
  { label: '每天 12:00', value: '0 12 * * *' },
  { label: '每天 20:00', value: '0 20 * * *' },
  { label: '每周一 20:00', value: '0 20 * * 1' },
  { label: '每周五 19:30', value: '30 19 * * 5' },
  { label: '每周六日 12:00', value: '0 12 * * 6,0' },
  { label: '每月 1 号 10:00', value: '0 10 1 * *' },
  { label: '每 6 小时', value: '0 */6 * * *' },
  { label: '每 30 分钟', value: '*/30 * * * *' },
]

function onCronPreset(val: string) {
  if (val) {
    form.value.cron_expr = val
    loadCronPreview()
    nextTick(() => { cronPreset.value = '' })
  }
}

const columns = [
  { title: '名称', key: 'name', width: 150 },
  { title: 'Cron 表达式', key: 'cron_expr', width: 110 },
  { title: '目标频道', key: 'target_chat_name', ellipsis: { tooltip: true }, render: (r: any) => r.target_chat_name || r.target_chat_id || '-' },
  { title: '队列', key: 'item_count', width: 55, render: (r: any) => r.item_count || 0 },
  { title: '策略', key: 'queue_strategy', width: 65, render: (r: any) => {
    const labels: Record<string, string> = { sequential: '顺序', random: '随机', rotate: '循环' }
    return labels[r.queue_strategy] || r.queue_strategy
  } },
  { title: '下次执行', key: 'next_run_at', width: 90, ellipsis: { tooltip: true }, render: (r: any) => r.next_run_at ? new Date(r.next_run_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—' },
  {
    title: '状态', key: 'enabled', width: 65,
    render: (r: any) => h(NTag, { type: r.enabled ? 'success' : 'default', size: 'small' },
      { default: () => r.enabled ? '启用' : '停用' }
    ),
  },
  {
    title: '操作', key: 'actions', width: 220,
    render: (r: any) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', onClick: () => openQueue(r) }, { default: () => '队列' }),
        h(NButton, { size: 'tiny', onClick: () => edit(r) }, { default: () => '编辑' }),
        h(NButton, { size: 'tiny', onClick: () => doTrigger(r.id) }, { default: () => '执行' }),
        h(NPopconfirm, { onPositiveClick: () => doDelete(r.id) },
          { trigger: () => h(NButton, { size: 'tiny', type: 'error' }, { default: () => '删除' }), default: () => '确定删除？' }
        ),
      ],
    }),
  },
]

async function load() {
  try {
    const data = await fetchSchedules()
    schedules.value = data.items || []
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '未知错误'
    message.error('加载计划失败: ' + msg)
  }
}

function edit(row: any) {
  editing.value = row
  form.value = { name: row.name, cron_expr: row.cron_expr, target_chat_id: row.target_chat_id ? String(row.target_chat_id) : '', queue_strategy: row.queue_strategy, thumb_caption_template: row.thumb_caption_template || '', video_caption_template: row.video_caption_template || '' }
  selectedChannelId.value = row.target_chat_id ? Number(row.target_chat_id) : null
  cronPreset.value = ''
  showModal.value = true
  setTimeout(loadCronPreview, 200)
}

function openCreate() {
  editing.value = null
  form.value = { name: '', cron_expr: '0 20 * * *', target_chat_id: '', queue_strategy: 'sequential', thumb_caption_template: '', video_caption_template: '' }
  selectedChannelId.value = null
  cronPreset.value = ''
  showModal.value = true
  setTimeout(loadCronPreview, 200)
}

async function loadChannels() {
  try {
    const d = await fetchChats()
    channelOptions.value = (d.items || []).map((c: any) => ({
      label: c.chat_name?.length > 20 ? c.chat_name.slice(0, 18) + '…' : (c.chat_name || String(c.chat_id)),
      value: c.chat_id,
    }))
  } catch {}
}

async function save() {
  if (!form.value.target_chat_id || parseInt(form.value.target_chat_id) === 0) {
    message.error('请填写有效的目标频道 ID')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateSchedule(editing.value.id, { ...form.value, target_chat_id: parseInt(form.value.target_chat_id) })
    } else {
      await createSchedule({ ...form.value, target_chat_id: parseInt(form.value.target_chat_id) || 0 })
    }
    message.success('保存成功')
    showModal.value = false
    await load()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '未知错误'
    message.error('保存失败: ' + msg)
  }
  saving.value = false
}

async function doDelete(id: number) {
  try {
    await deleteSchedule(id)
    message.success('已删除')
    await load()
  } catch (e: any) { message.error('删除失败: ' + (e?.response?.data?.detail || e?.message || '')) }
}

async function doTrigger(id: number) {
  try {
    await triggerSchedule(id)
    message.success('已触发发布')
  } catch (e: any) { message.error('触发失败: ' + (e?.response?.data?.detail || e?.message || '')) }
}

// ── Queue management ──
const showQueueModal = ref(false)
const queueScheduleId = ref(0)
const queueScheduleName = ref('')
const queueItems = ref<any[]>([])
const queueLoading = ref(false)

async function openQueue(schedule: any) {
  queueScheduleId.value = schedule.id
  queueScheduleName.value = schedule.name
  queueLoading.value = true
  try {
    const { data } = await api.get(`/schedules/${schedule.id}/items`)
    queueItems.value = data.items || []
  } catch { message.error('加载队列失败') }
  queueLoading.value = false
  showQueueModal.value = true
}

async function removeQueueItem(itemId: number) {
  try {
    await api.put(`/schedules/${queueScheduleId.value}/items?action=remove`, [itemId])
    message.success('已移除')
    queueItems.value = queueItems.value.filter((i: any) => i.id !== itemId)
  } catch { message.error('移除失败') }
}

const queueColumns = [
  { title: '#', key: 'sort_order', width: 40 },
  { title: '视频', key: 'video_name', ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'status', width: 120,
    render: (r: any) => {
      const labels: Record<string, string> = { queued: '排队中', publishing_thumb: '发送缩略图', publishing_video: '发送视频', published: '已发布', failed: '失败', skipped: '已跳过' }
      const tag = h(NTag, { type: r.status === 'published' ? 'success' : r.status === 'failed' ? 'error' : 'default', size: 'small' }, { default: () => labels[r.status] || r.status })
      if (r.status === 'failed' && r.error_msg) {
        return h('div', { style: 'display:flex;flex-direction:column;gap:2px' }, [
          tag,
          h(NText, { depth: '3', style: 'font-size:10px;word-break:break-all' }, { default: () => r.error_msg }),
        ])
      }
      return tag
    },
  },
  {
    title: '操作', key: 'actions', width: 70,
    render: (r: any) => r.status === 'queued' ? h(NButton, { size: 'tiny', type: 'error', onClick: () => removeQueueItem(r.id) }, { default: () => '移除' }) : null,
  },
]

onMounted(() => {
  load()
  loadChannels()
  initPending()
})
</script>

<template>
  <PageContainer>
    <PageHeader title="发布计划" icon="📅">
      <n-button type="primary" @click="openCreate">
        <template #icon><n-icon><AddOutline /></n-icon></template>
        新增计划
      </n-button>
    </PageHeader>

    <n-card size="small">
      <!-- Pending batch-add from VideoBrowser -->
      <div v-if="pendingVideos.length" style="margin-bottom: 16px; padding: 12px; background: var(--bg-subtle); border-radius: 8px;">
        <n-text strong style="font-size: 13px; display: block; margin-bottom: 8px;">待加入计划 ({{ pendingVideos.length }})</n-text>
        <n-text v-for="v in pendingVideos" :key="v.id" depth="3" style="font-size: 12px; display: inline-block; margin-right: 12px;">🎬 {{ v.filename }}</n-text>
        <n-space :size="8" style="margin-top: 8px;">
          <n-select v-model:value="pendingScheduleId" size="small" style="width: 200px" :options="schedules.filter(s => s.enabled).map((s: any) => ({ label: s.name, value: s.id }))" placeholder="选择计划" />
          <n-button size="small" type="primary" @click="batchAdd">全部加入</n-button>
        </n-space>
      </div>
      <n-empty v-if="!schedules.length" description="暂无发布计划，点击右上角新增" style="margin: 40px 0" />
      <n-dataTable v-else :columns="columns" :data="schedules" :pagination="false" size="small" />
    </n-card>

    <n-modal v-model:show="showModal" :title="editing ? '编辑计划' : '新增计划'">
      <n-card style="width: 520px">
        <n-form label-placement="top" size="small">
          <n-form-item label="计划名称">
            <n-input v-model:value="form.name" placeholder="如：每周五晚 8 点发布" />
          </n-form-item>

          <n-form-item label="Cron 表达式">
            <n-space :size="8" align="center" style="width: 100%">
              <n-select
                v-model:value="cronPreset"
                placeholder="快速选择..."
                :options="cronPresets"
                clearable
                @update:value="onCronPreset"
                style="width: 160px; flex-shrink: 0"
              />
              <n-input v-model:value="form.cron_expr" placeholder="分 时 日 月 周" @blur="loadCronPreview" style="flex: 1" />
              <n-tooltip v-if="cronPreview.length" trigger="hover" placement="top" :style="{ maxWidth: '260px' }">
                <template #trigger>
                  <n-icon size="18" :depth="3" style="cursor: help; flex-shrink: 0">
                    <InformationCircleOutline />
                  </n-icon>
                </template>
                <div>
                  <n-text depth="3" style="font-size: 11px; display: block; margin-bottom: 4px;">下次执行时间：</n-text>
                  <n-text v-for="(t, i) in cronPreview.slice(0, 5)" :key="i" depth="2" style="font-size: 12px; display: block; padding: 1px 0;">
                    {{ t }}
                  </n-text>
                  <n-text v-if="cronPreview.length > 5" depth="3" style="font-size: 11px;">...等 {{ cronPreview.length }} 次</n-text>
                </div>
              </n-tooltip>
              <n-spin v-else-if="previewLoading" :size="14" />
            </n-space>
          </n-form-item>

          <n-form-item label="目标频道">
            <n-select
              v-model:value="selectedChannelId"
              :options="channelOptions"
              placeholder="选择频道..."
              filterable
              :consistent-menu-width="false"
              :render-label="(opt: any) => opt.label?.length > 20 ? opt.label.slice(0, 18) + '…' : opt.label"
              @update:value="form.target_chat_id = String($event)"
            />
          </n-form-item>

          <n-form-item label="队列策略">
            <n-select v-model:value="form.queue_strategy"
              :options="[
                { label: '顺序发布', value: 'sequential' },
                { label: '随机发布', value: 'random' },
              ]"
            />
          </n-form-item>

          <n-divider style="margin: 8px 0" />
          <n-text strong style="font-size: 13px; display: block; margin-bottom: 4px;">发布文案模板</n-text>
          <n-text depth="3" style="font-size: 11px; margin-bottom: 6px; display: block;">
             可用变量：<code class="var-tag">&#123;&#123;title&#125;&#125;</code> 标题 · <code class="var-tag">&#123;&#123;duration&#125;&#125;</code> 时长 · <code class="var-tag">&#123;&#123;resolution&#125;&#125;</code> 分辨率 · <code class="var-tag">&#123;&#123;size&#125;&#125;</code> 大小 · <code class="var-tag">&#123;&#123;nl&#125;&#125;</code> 换行
          </n-text>
          <n-space :size="6" style="margin-bottom: 12px">
            <n-button size="tiny" @click="form.thumb_caption_template='🎬 {{title}} | ⏱ {{duration}}{{nl}}评论区 👇'; form.video_caption_template='{{title}}{{nl}}💾 {{size}} {{resolution}}'">默认模板</n-button>
            <n-button size="tiny" @click="form.thumb_caption_template='{{title}} | {{resolution}}{{nl}}评论区见 👇'; form.video_caption_template='{{title}}{{nl}}{{size}}'">简洁模板</n-button>
            <n-button size="tiny" @click="form.thumb_caption_template=''; form.video_caption_template=''">清空</n-button>
          </n-space>

          <n-form-item label="缩略图文案（发在频道主时间线）">
            <n-input v-model:value="form.thumb_caption_template" type="textarea" :rows="2" placeholder="留空使用全局默认" />
          </n-form-item>
          <n-form-item label="视频文案（发在评论区/讨论组）">
            <n-input v-model:value="form.video_caption_template" type="textarea" :rows="2" placeholder="留空使用全局默认" />
          </n-form-item>
        </n-form>
        <n-space justify="end" style="margin-top: 16px">
          <n-button @click="showModal = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </n-space>
      </n-card>
    </n-modal>

    <!-- Queue management modal -->
    <n-modal v-model:show="showQueueModal" :title="'计划队列 - ' + queueScheduleName" style="width: 600px">
      <n-card>
        <n-spin :show="queueLoading">
          <n-empty v-if="!queueLoading && !queueItems.length" description="队列为空，从视频管理页选择视频加入计划" style="margin: 30px 0" />
          <n-dataTable
            v-else
            :columns="queueColumns"
            :data="queueItems"
            :pagination="false"
            size="small"
          />
        </n-spin>
      </n-card>
    </n-modal>
  </PageContainer>
</template>

<style scoped>
.var-tag {
  color: var(--color-green);
  background: rgba(99,226,183,0.1);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: monospace;
}
</style>
