<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import {
  NCard, NTabs, NTabPane, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NSwitch, NButton, NSpace, NModal, NDataTable, NText, NDivider, NTag, NAlert, useMessage
} from 'naive-ui'
import PageHeader from '@/components/shared/PageHeader.vue'
import PageContainer from '@/components/shared/PageContainer.vue'
import StatusDot from '@/components/shared/StatusDot.vue'
import { useTheme } from '@/composables/useTheme'
import {
  fetchSettings, updateSettings, testProxy, applySettings,
  fetchChats, verifyChat, refreshChats, changePassword as changePwdApi,
  fetchVersion, checkVersion, fetchNotificationConfig, updateNotificationConfig,
} from '@/api/client'

const message = useMessage()
const { isDark, toggle: toggleTheme } = useTheme()
const settings = ref<Record<string, string>>({})
const proxyTestResult = ref('')
const showRestartModal = ref(false)
const activeTab = ref('bot')

// ── Password change ──
const pwdForm = ref({ old: '', new: '', confirm: '' })
const pwdLoading = ref(false)

// ── Version / About ──
const versionInfo = ref<{ local: string; remote: string | null; has_update: boolean; build_date: string; error?: string }>({
  local: '', remote: null, has_update: false, build_date: '',
})
const versionLoading = ref(false)

const themeLabel = ref(isDark.value ? '切换亮色' : '切换暗色')
function doToggleTheme() {
  toggleTheme()
  themeLabel.value = isDark.value ? '切换亮色' : '切换暗色'
}

async function loadVersionInfo() {
  versionLoading.value = true
  try {
    const v = await fetchVersion()
    versionInfo.value.local = v.version || ''
    versionInfo.value.build_date = v.build_date || ''
  } catch { versionInfo.value.local = '未知' }
  try {
    const c = await checkVersion()
    versionInfo.value.remote = c.remote
    versionInfo.value.has_update = c.has_update
    if (c.error) versionInfo.value.error = c.error
  } catch { versionInfo.value.error = '检查失败' }
  versionLoading.value = false
}

async function doChangePassword() {
  if (!pwdForm.value.old || !pwdForm.value.new) { message.error('请填写所有密码字段'); return }
  if (pwdForm.value.new.length < 4) { message.error('新密码至少 4 位'); return }
  if (pwdForm.value.new !== pwdForm.value.confirm) { message.error('两次密码不一致'); return }
  pwdLoading.value = true
  try {
    await changePwdApi(pwdForm.value.old, pwdForm.value.new)
    message.success('密码已更改')
    pwdForm.value = { old: '', new: '', confirm: '' }
  } catch { message.error('密码修改失败') }
  pwdLoading.value = false
}

// ── Channels ──
const channels = ref<any[]>([])
const channelsLoading = ref(false)

const channelColumns = [
  { title: '名称', key: 'chat_name', ellipsis: { tooltip: true }, render: (r: any) => r.alias ? `${r.alias} [${r.chat_name || r.chat_id}]` : (r.chat_name || String(r.chat_id)) },
  { title: '类型', key: 'chat_type', width: 80, render: (r: any) => r.chat_type === 'channel' ? '频道' : r.chat_type === 'supergroup' ? '群组' : r.chat_type },
  { title: 'Chat ID', key: 'chat_id', width: 170, render: (r: any) => h(NText, { depth: '3', style: 'font-family:monospace;font-size:12px' }, { default: () => String(r.chat_id) }) },
  { title: '讨论组 ID', key: 'linked_chat_id', width: 150, render: (r: any) => r.linked_chat_id ? h(NText, { depth: '3', style: 'font-family:monospace;font-size:12px' }, { default: () => String(r.linked_chat_id) }) : h(NText, { depth: '3' }, { default: () => '—' }) },
]

async function loadChannels() {
  channelsLoading.value = true
  try { const d = await fetchChats(); channels.value = d.items || [] } catch { message.error('加载频道失败') }
  channelsLoading.value = false
}

async function doRefreshChats() {
  try {
    await refreshChats()
    message.success('已刷新频道列表')
    await loadChannels()
  } catch { message.error('刷新失败，请检查 Bot 连接') }
}

// ── Proxy form ──
const proxyForm = ref({
  proxy_enabled: false, proxy_type: 'http', proxy_host: '127.0.0.1',
  proxy_port: 7890, proxy_user: '', proxy_pass: '',
})

// ── General form ──
const generalForm = ref<Record<string, any>>({
  video_source_dirs: ['/data/videos'], output_dir: '/data/output', thumbnail_dir: '/data/thumbnails',
  compress_preset: 'balanced', thumbnail_layout: '3x3', max_workers: 1,
  thumb_caption_template: '', video_caption_template: '',
})

// ── Bot form ──
const botForm = ref({ bot_token: '', api_id: '', api_hash: '', admin_chat_id: '' })
const botTestResult = ref('')
const testingBot = ref(false)
const manualChatId = ref('')
const verifyResult = ref('')

async function saveBot() {
  try {
    await updateSettings({
      bot_token: botForm.value.bot_token,
      api_id: botForm.value.api_id,
      api_hash: botForm.value.api_hash,
      admin_chat_id: botForm.value.admin_chat_id,
    })
    await applySettings()
    message.success('Bot 配置已保存，Bot API 正在重启')
  } catch { message.error('保存失败') }
}

async function doTestBot() {
  testingBot.value = true
  try {
    const d = await fetchChats()
    botTestResult.value = '✓ Bot 连接正常，发现 ' + (d.items?.length || 0) + ' 个对话'
  } catch { botTestResult.value = '✗ Bot 连接失败，请检查 Token 和网络配置' }
  testingBot.value = false
}

async function doAddChat() {
  if (!manualChatId.value) { message.error('请输入 Chat ID'); return }
  try {
    const d = await verifyChat(parseInt(manualChatId.value))
    if (d.ok) { message.success('已添加: ' + (d.alias || d.chat_name)); manualChatId.value = ''; loadChannels() }
    else message.error(d.error || '验证失败')
  } catch { message.error('验证失败') }
}

// ── Load settings on mount ──
onMounted(async () => {
  loadChannels()
  try {
    const data = await fetchSettings()
    settings.value = data
    if (Array.isArray(data.video_source_dirs) && data.video_source_dirs.length) {
      generalForm.value.video_source_dirs = [...data.video_source_dirs]
    } else if (typeof data.video_source_dirs === 'string') {
      try {
        const parsed = JSON.parse(data.video_source_dirs)
        if (Array.isArray(parsed) && parsed.length) generalForm.value.video_source_dirs = parsed
      } catch {}
    } else if (data.video_source_dir) {
      generalForm.value.video_source_dirs = [data.video_source_dir]
    }
    generalForm.value.output_dir = data.output_dir || '/data/output'
    generalForm.value.thumbnail_dir = data.thumbnail_dir || '/data/thumbnails'
    if (data.compress_preset) generalForm.value.compress_preset = data.compress_preset
    if (data.thumbnail_layout) generalForm.value.thumbnail_layout = data.thumbnail_layout
    if (data.max_workers) generalForm.value.max_workers = parseInt(data.max_workers) || 1
    if (data.thumb_caption_template) generalForm.value.thumb_caption_template = data.thumb_caption_template
    if (data.video_caption_template) generalForm.value.video_caption_template = data.video_caption_template
    botForm.value.bot_token = data.bot_token || ''
    botForm.value.api_id = data.api_id || ''
    botForm.value.api_hash = data.api_hash || ''
    botForm.value.admin_chat_id = data.admin_chat_id || ''
    proxyForm.value.proxy_enabled = data.proxy_enabled === 'true'
    if (data.proxy_type) proxyForm.value.proxy_type = data.proxy_type
    if (data.proxy_host) proxyForm.value.proxy_host = data.proxy_host
    if (data.proxy_port) proxyForm.value.proxy_port = parseInt(data.proxy_port)
    if (data.proxy_user) proxyForm.value.proxy_user = data.proxy_user
  } catch { message.error('加载设置失败') }
  loadVersionInfo()
  loadNotifications()
})

async function saveGeneral() {
  try {
    const body: Record<string, string> = {}
    for (const [k, v] of Object.entries(generalForm.value)) {
      if (k === 'video_source_dirs') {
        const dirs = (v as string[]).filter(d => d.trim())
        if (dirs.length === 0) { message.error('至少需要配置一个视频源目录'); return }
        body[k] = JSON.stringify(dirs)
      } else {
        body[k] = String(v)
      }
    }
    await updateSettings(body)
    message.success('已保存')
  } catch { message.error('保存失败') }
}

async function saveProxy() {
  try {
    await updateSettings({
      proxy_enabled: proxyForm.value.proxy_enabled ? 'true' : 'false',
      proxy_type: proxyForm.value.proxy_type, proxy_host: proxyForm.value.proxy_host,
      proxy_port: String(proxyForm.value.proxy_port),
      proxy_user: proxyForm.value.proxy_user, proxy_pass: proxyForm.value.proxy_pass,
    })
    message.success('代理配置已保存')
  } catch { message.error('保存失败') }
}

async function doTestProxy() {
  proxyTestResult.value = '测试中...'
  try {
    const data = await testProxy()
    proxyTestResult.value = data.success ? `✓ ${data.message}` : `✗ ${data.message}`
  } catch {}
}

async function doApply() {
  showRestartModal.value = false
  try {
    const res = await applySettings()
    if (res.ok) {
      message.success(res.message || 'Bot API 正在重启 (约 3 秒)')
    } else {
      message.error(res.message || '重启失败，请查看 Bot 状态诊断页')
    }
  } catch { message.error('应用失败，请重试') }
}

// ── Notification settings ──
const notificationItems = ref<any[]>([])
const notificationSaving = ref(false)

async function loadNotifications() {
  try {
    const d = await fetchNotificationConfig()
    notificationItems.value = d.items || []
  } catch {}
}

async function saveNotification(item: any) {
  notificationSaving.value = true
  try {
    await updateNotificationConfig(item)
    message.success('已保存')
  } catch { message.error('保存失败') }
  notificationSaving.value = false
}
</script>

<template>
  <PageContainer>
    <PageHeader title="系统设置" icon="⚙️" />

    <n-card size="small">
      <n-tabs v-model:value="activeTab" type="line" animated>
        <!-- ─── Bot 管理 ─── -->
        <n-tab-pane name="bot" tab="🤖 Bot 管理">
          <n-grid :cols="2" :x-gap="24" style="margin-top: 16px">
            <n-gi>
              <n-card size="small" title="Bot 配置" :bordered="true">
                <n-form label-placement="top" size="small">
                  <n-form-item label="Bot Token">
                    <n-input v-model:value="botForm.bot_token" type="textarea" :rows="2" placeholder="123456:ABC-DEF..." />
                    <n-text depth="3" style="font-size: 11px; margin-top: 2px; display:block;">从 @BotFather 创建 Bot 获取 Token</n-text>
                  </n-form-item>
                  <n-form-item label="API ID">
                    <n-input v-model:value="botForm.api_id" placeholder="在 my.telegram.org/apps 获取" />
                  </n-form-item>
                  <n-form-item label="API Hash">
                    <n-input v-model:value="botForm.api_hash" placeholder="在 my.telegram.org/apps 获取" />
                  </n-form-item>
                  <n-divider style="margin: 12px 0" />
                  <n-form-item label="管理员 Chat ID">
                    <n-input v-model:value="botForm.admin_chat_id" placeholder="你的 Telegram 用户 ID" />
                    <n-text depth="3" style="font-size: 11px; margin-top: 2px; display:block;">
                      用于接收压缩/发布通知。先向 Bot 私聊发一条消息，再到下方频道管理页刷新查看你的 Chat ID。
                    </n-text>
                  </n-form-item>
                  <n-space>
                    <n-button @click="saveBot" type="primary">保存并重启 Bot</n-button>
                    <n-button :loading="testingBot" @click="doTestBot">测试连接</n-button>
                  </n-space>
                  <n-text v-if="botTestResult" depth="3" style="font-size:12px; display:block; margin-top: 8px;">{{ botTestResult }}</n-text>
                </n-form>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" title="🔒 修改密码" :bordered="true">
                <n-space vertical :size="12">
                  <n-input v-model:value="pwdForm.old" type="password" placeholder="当前密码" />
                  <n-input v-model:value="pwdForm.new" type="password" placeholder="新密码（至少 4 位）" />
                  <n-input v-model:value="pwdForm.confirm" type="password" placeholder="确认新密码" />
                  <n-button :loading="pwdLoading" @click="doChangePassword">修改密码</n-button>
                </n-space>
              </n-card>
            </n-gi>
          </n-grid>
        </n-tab-pane>

        <!-- ─── 常规 ─── -->
        <n-tab-pane name="general" tab="⚙️ 常规">
          <n-grid :cols="2" :x-gap="24" style="margin-top: 16px">
            <n-gi>
              <n-card size="small" title="📁 目录配置" :bordered="true">
                <n-form label-placement="top" size="small">
                  <n-form-item label="视频源目录">
                    <n-space vertical :size="6">
                      <n-space v-for="(dir, idx) in generalForm.video_source_dirs" :key="idx" :size="6" align="center">
                        <n-input v-model:value="generalForm.video_source_dirs[idx]" style="flex: 1" :placeholder="'/data/videos'" />
                        <n-button size="tiny" type="error" quaternary @click="generalForm.video_source_dirs.splice(idx, 1)"
                          :disabled="generalForm.video_source_dirs.length <= 1">✕</n-button>
                      </n-space>
                      <n-button size="tiny" dashed @click="generalForm.video_source_dirs.push('')">+ 添加目录</n-button>
                    </n-space>
                  </n-form-item>
                  <n-form-item label="压缩输出目录">
                    <n-input v-model:value="generalForm.output_dir" />
                  </n-form-item>
                  <n-form-item label="缩略图目录">
                    <n-input v-model:value="generalForm.thumbnail_dir" />
                  </n-form-item>
                </n-form>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card size="small" title="⚡ 压缩配置" :bordered="true">
                <n-form label-placement="top" size="small">
                  <n-form-item label="默认压缩预设">
                    <n-select v-model:value="generalForm.compress_preset"
                      :options="[
                        { label: '极速 (H.264)', value: 'fast' },
                        { label: '均衡 (H.265)', value: 'balanced' },
                        { label: '高画质 (2-pass)', value: 'high_quality' },
                      ]" />
                  </n-form-item>
                  <n-form-item label="默认缩略图宫格">
                    <n-select v-model:value="generalForm.thumbnail_layout"
                      :options="[
                        { label: '3×3 九宫格', value: '3x3' },
                        { label: '2×3 六宫格', value: '2x3' },
                        { label: '4×4 十六格', value: '4x4' },
                        { label: '2×2 四宫格', value: '2x2' },
                      ]" />
                  </n-form-item>
                  <n-form-item label="最大并发压缩">
                    <n-input-number v-model:value="generalForm.max_workers" :min="1" :max="8" style="width: 100%" />
                  </n-form-item>
                  <n-button @click="saveGeneral" type="primary">保存常规设置</n-button>
                </n-form>
              </n-card>
            </n-gi>
          </n-grid>

          <n-divider style="margin: 16px 0" />
          <n-card size="small" title="📝 默认发布文案" :bordered="true">
            <n-text depth="3" style="font-size: 12px; margin-bottom: 8px; display: block;">
              变量：<code class="var-tag">&#123;&#123;title&#125;&#125;</code> 标题 · <code class="var-tag">&#123;&#123;duration&#125;&#125;</code> 时长 · <code class="var-tag">&#123;&#123;resolution&#125;&#125;</code> 分辨率 · <code class="var-tag">&#123;&#123;size&#125;&#125;</code> 大小 · <code class="var-tag">&#123;&#123;nl&#125;&#125;</code> 换行
            </n-text>
            <n-space :size="8" style="margin-bottom: 12px">
              <n-button size="tiny" @click="generalForm.thumb_caption_template='🎬 {{title}} | ⏱ {{duration}}{{nl}}评论区 👇'; generalForm.video_caption_template='{{title}}{{nl}}💾 {{size}} {{resolution}}'">默认模板</n-button>
              <n-button size="tiny" @click="generalForm.thumb_caption_template='{{title}} | {{resolution}}{{nl}}评论区见 👇'; generalForm.video_caption_template='{{title}}{{nl}}{{size}}'">简洁模板</n-button>
              <n-button size="tiny" @click="generalForm.thumb_caption_template=''; generalForm.video_caption_template=''">清空</n-button>
            </n-space>
            <n-grid :cols="2" :x-gap="16">
              <n-gi>
                <n-form-item label="缩略图文案（频道主时间线）" label-placement="top">
                  <n-input v-model:value="generalForm.thumb_caption_template" type="textarea" :rows="2" placeholder="留空使用默认" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="视频文案（评论区/讨论组）" label-placement="top">
                  <n-input v-model:value="generalForm.video_caption_template" type="textarea" :rows="2" placeholder="留空使用默认" />
                </n-form-item>
              </n-gi>
            </n-grid>
            <n-button @click="saveGeneral" size="small" style="margin-top: 8px">保存文案模板</n-button>
          </n-card>
        </n-tab-pane>

        <!-- ─── 代理 ─── -->
        <n-tab-pane name="proxy" tab="🌐 代理">
          <n-card size="small" title="代理配置" :bordered="true" style="max-width: 560px; margin-top: 16px">
            <n-form label-placement="top" size="small">
              <n-form-item label="启用代理">
                <n-switch v-model:value="proxyForm.proxy_enabled" />
              </n-form-item>
              <n-grid :cols="2" :x-gap="16">
                <n-gi>
                  <n-form-item label="代理类型">
                    <n-select v-model:value="proxyForm.proxy_type"
                      :options="[
                        { label: 'HTTP', value: 'http' },
                        { label: 'MTProto', value: 'mtproto' },
                      ]" />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="代理端口">
                    <n-input-number v-model:value="proxyForm.proxy_port" :min="1" :max="65535" style="width:100%" />
                  </n-form-item>
                </n-gi>
              </n-grid>
              <n-form-item label="代理地址">
                <n-input v-model:value="proxyForm.proxy_host" />
              </n-form-item>
              <template v-if="proxyForm.proxy_type === 'mtproto'">
                <n-form-item label="Secret">
                  <n-input v-model:value="proxyForm.proxy_pass" placeholder="64 位 hex secret" />
                </n-form-item>
              </template>
              <template v-else>
                <n-grid :cols="2" :x-gap="16">
                  <n-gi><n-form-item label="用户名 (可选)"><n-input v-model:value="proxyForm.proxy_user" /></n-form-item></n-gi>
                  <n-gi><n-form-item label="密码 (可选)"><n-input v-model:value="proxyForm.proxy_pass" type="password" /></n-form-item></n-gi>
                </n-grid>
              </template>
              <n-space>
                <n-button @click="saveProxy">保存代理配置</n-button>
                <n-button @click="doTestProxy">测试连接</n-button>
                <n-button type="primary" @click="showRestartModal = true">应用并重启</n-button>
              </n-space>
              <div v-if="proxyTestResult" style="margin-top: 12px">
                <n-text>{{ proxyTestResult }}</n-text>
              </div>
            </n-form>
          </n-card>
        </n-tab-pane>

        <!-- ─── 频道管理 ─── -->
        <n-tab-pane name="channels" tab="📡 频道管理">
          <n-card size="small" :bordered="true" style="margin-top: 16px">
            <n-space style="margin-bottom: 16px" align="center" justify="space-between">
              <n-space align="center" :size="12">
                <n-input v-model:value="manualChatId" placeholder="手动输入 Chat ID" style="width: 220px" size="small" />
                <n-button size="small" @click="doAddChat">添加</n-button>
                <n-divider vertical />
                <n-button size="small" @click="doRefreshChats" :loading="channelsLoading">🔄 自动刷新（从 Bot 已加入的群组/频道中获取）</n-button>
              </n-space>
            </n-space>
            <n-alert type="info" style="margin-bottom: 12px" v-if="!channels.length && !channelsLoading">
              点击"自动刷新"按钮，系统会从 Bot 最近消息中自动获取已加入的群组和频道。也可以手动输入 Chat ID 添加。
            </n-alert>
            <n-dataTable
              :columns="channelColumns"
              :data="channels"
              :pagination="false"
              size="small"
            />
          </n-card>
        </n-tab-pane>

        <!-- ─── 通知 ─── -->
        <n-tab-pane name="notify" tab="📢 通知">
          <n-card size="small" title="通知设置" :bordered="true" style="margin-top: 16px">
            <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 12px;">
              配置各类型事件的通知开关、模板和目标。可用变量：{"{filename}"} {"{size}"} {"{out_size}"} {"{ratio}"} {"{channel}"} {"{error}"} {"{status}"} {"{username}"}
            </n-text>
            <div v-for="item in notificationItems" :key="item.event_type" style="margin-bottom: 16px; padding: 12px; background: var(--bg-subtle); border-radius: 8px;">
              <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
                <n-text strong style="width: 100px; flex-shrink: 0;">
                  {{ item.event_type === 'compress_done' ? '⚡ 压缩完成' : item.event_type === 'compress_fail' ? '⚡ 压缩失败' : item.event_type === 'publish_done' ? '📤 发布完成' : item.event_type === 'publish_fail' ? '📤 发布失败' : '🤖 Bot状态' }}
                </n-text>
                <n-switch v-model:value="item.enabled" size="small" @update:value="saveNotification({event_type:item.event_type,enabled:item.enabled,template:item.template,target_chat_ids:item.target_chat_ids})" />
              </div>
              <n-form-item label="通知模板" label-placement="top" size="small">
                <n-input v-model:value="item.template" type="textarea" :rows="2" @blur="saveNotification({event_type:item.event_type,enabled:item.enabled,template:item.template,target_chat_ids:item.target_chat_ids})" />
              </n-form-item>
              <n-form-item label="通知目标 ChatID（逗号分隔，留空使用管理员ChatID）" label-placement="top" size="small">
                <n-input v-model:value="item.target_chat_ids" placeholder="123456789, -100222333444" @blur="saveNotification({event_type:item.event_type,enabled:item.enabled,template:item.template,target_chat_ids:item.target_chat_ids})" />
              </n-form-item>
            </div>
          </n-card>
        </n-tab-pane>

        <!-- ─── 关于 ─── -->
        <n-tab-pane name="about" tab="ℹ️ 关于">
          <n-card size="small" :bordered="true" style="max-width: 480px; margin-top: 16px">
            <n-space vertical :size="16">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                  <n-text depth="3" style="font-size: 12px; display: block;">应用名称</n-text>
                  <n-text strong style="font-size: 18px;">🎬 TG视频发布助手</n-text>
                </div>
                <n-button size="small" @click="doToggleTheme">{{ themeLabel }}</n-button>
              </div>
              <n-grid :cols="2" :x-gap="16">
                <n-gi>
                  <n-text depth="3" style="font-size: 12px; display: block;">当前版本</n-text>
                  <n-text strong style="font-size: 15px;">v{{ versionInfo.local }}</n-text>
                </n-gi>
                <n-gi>
                  <n-text depth="3" style="font-size: 12px; display: block;">构建时间</n-text>
                  <n-text strong style="font-size: 13px; font-family: monospace;">{{ versionInfo.build_date || '未知' }}</n-text>
                </n-gi>
              </n-grid>

              <div>
                <n-text depth="3" style="font-size: 12px; display: block; margin-bottom: 4px;">远端版本</n-text>
                <n-space align="center" :size="12">
                  <n-text v-if="versionLoading" depth="3" style="font-size: 13px;">检查中...</n-text>
                  <n-text v-else-if="versionInfo.remote" :style="{ color: versionInfo.has_update ? '#faad14' : '#63e2b7', fontSize: '13px' }">
                    {{ versionInfo.has_update ? '🆕 ' + versionInfo.remote + ' (有新版本可用)' : '✓ 已是最新版本 (' + versionInfo.remote + ')' }}
                  </n-text>
                  <n-text v-else depth="3" style="font-size: 13px;">{{ versionInfo.error || '无法获取' }}</n-text>
                  <n-button size="tiny" :loading="versionLoading" @click="loadVersionInfo">重新检查</n-button>
                </n-space>
              </div>

              <n-divider style="margin: 4px 0" />
              <n-space :size="12">
                <n-button size="small" tag="a" href="https://github.com/MaroD1M/tg-video-publisher" target="_blank">
                  访问 GitHub 仓库
                </n-button>
                <n-button size="small" tag="a" href="https://github.com/MaroD1M/tg-video-publisher/releases" target="_blank">
                  查看更新日志
                </n-button>
              </n-space>
            </n-space>
          </n-card>
        </n-tab-pane>
      </n-tabs>
    </n-card>

    <n-modal v-model:show="showRestartModal" title="确认重启" style="width: 360px">
      <n-card>
        <p>Bot API 将使用新的代理配置重启，约需 3 秒。</p>
        <n-space justify="end">
          <n-button @click="showRestartModal = false">取消</n-button>
          <n-button type="primary" @click="doApply">确认</n-button>
        </n-space>
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
