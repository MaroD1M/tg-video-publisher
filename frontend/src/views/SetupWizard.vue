<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NSteps, NStep, NCard, NForm, NFormItem, NInput, NInputNumber,
  NButton, NSpace, NText, NSelect, NSwitch, NAlert, useMessage,
} from 'naive-ui'
import { completeSetup, hasUsers, login as loginApi } from '@/api/client'

const router = useRouter()
const message = useMessage()

const currentStep = ref(1)
const needAdmin = ref(false)

const adminForm = ref({ username: '', password: '', confirm: '' })
const teleForm = ref({ bot_token: '', api_id: '', api_hash: '' })
const dirForm = ref({ video_source_dir: '/data/videos', output_dir: '/data/output', thumbnail_dir: '/data/thumbnails' })
const proxyForm = ref({ enabled: false, type: 'http', host: '127.0.0.1', port: 7890, user: '', pass: '' })

const submitting = ref(false)

async function checkNeedAdmin() {
  try { needAdmin.value = !(await hasUsers()).has_users } catch { needAdmin.value = true }
}
onMounted(checkNeedAdmin)

function nextStep() {
  if (needAdmin.value && currentStep.value === 1) {
    if (!adminForm.value.username) { message.error('请填写用户名'); return }
    if (adminForm.value.password.length < 4) { message.error('密码至少 4 位'); return }
    if (adminForm.value.password !== adminForm.value.confirm) { message.error('两次密码不一致'); return }
  }
  if ((needAdmin.value && currentStep.value === 2) || (!needAdmin.value && currentStep.value === 1)) {
    if (!teleForm.value.bot_token || !teleForm.value.api_id || !teleForm.value.api_hash) {
      message.error('请填写所有 Telegram 配置项'); return
    }
  }
  currentStep.value++
}

function prevStep() { currentStep.value-- }

async function doSetup() {
  submitting.value = true
  try {
    const body: Record<string, string> = {
      bot_token: teleForm.value.bot_token,
      api_id: teleForm.value.api_id,
      api_hash: teleForm.value.api_hash,
      video_source_dir: dirForm.value.video_source_dir,
      output_dir: dirForm.value.output_dir,
      thumbnail_dir: dirForm.value.thumbnail_dir,
    }
    if (needAdmin.value) {
      body.admin_username = adminForm.value.username
      body.admin_password = adminForm.value.password
    }
    if (proxyForm.value.enabled) {
      body.proxy_enabled = 'true'
      body.proxy_type = proxyForm.value.type
      body.proxy_host = proxyForm.value.host
      body.proxy_port = String(proxyForm.value.port)
      if (proxyForm.value.type === 'mtproto') {
        body.proxy_pass = proxyForm.value.pass
      } else {
        body.proxy_user = proxyForm.value.user
        body.proxy_pass = proxyForm.value.pass
      }
    }
    await completeSetup(body)
    message.success('设置完成！Bot API 正在启动...')

    // Auto-login with the admin account just created
    if (needAdmin.value) {
      try {
        const auth = await loginApi(adminForm.value.username, adminForm.value.password)
        localStorage.setItem('access_token', auth.token)
        localStorage.setItem('username', auth.username)
      } catch (e) {
        console.error('Auto-login failed:', e)
        message.warning('设置完成但自动登录失败，请手动登录')
      }
    }

    setTimeout(() => router.push('/'), 2000)
  } catch { message.error('设置失败，请检查输入内容') }
  submitting.value = false
}
</script>

<template>
  <div class="setup-container">
    <n-card class="setup-card" :bordered="true">
      <div class="brand">
        <div class="brand-icon">🎬</div>
        <h1 class="brand-title">TG视频发布助手</h1>
        <n-text depth="3">首次运行，请完成基本设置</n-text>
      </div>

      <n-steps :current="currentStep" :status="'process'" style="margin: 28px 0 32px">
        <n-step v-if="needAdmin" title="管理员" />
        <n-step title="Telegram" />
        <n-step title="目录" />
        <n-step title="网络" />
      </n-steps>

      <!-- Step 1: Admin -->
      <template v-if="needAdmin && currentStep === 1">
        <n-alert type="info" closable style="margin-bottom: 20px">
          首次部署需要创建一个管理员账户，用于登录 Web UI。
        </n-alert>
        <n-form label-placement="top" label-width="80">
          <n-form-item label="用户名">
            <n-input v-model:value="adminForm.username" placeholder="admin" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="adminForm.password" type="password" placeholder="至少 4 位" show-password-on="click" />
          </n-form-item>
          <n-form-item label="确认密码">
            <n-input v-model:value="adminForm.confirm" type="password" placeholder="再次输入密码" show-password-on="click" />
          </n-form-item>
        </n-form>
        <n-button type="primary" block @click="nextStep">下一步</n-button>
      </template>

      <!-- Step 2: Telegram -->
      <template v-if="(!needAdmin && currentStep === 1) || (needAdmin && currentStep === 2)">
        <n-form label-placement="top">
          <n-form-item label="Bot Token">
            <n-input v-model:value="teleForm.bot_token" placeholder="123456:ABC-DEF..." />
          </n-form-item>
          <n-text depth="3" style="font-size: 12px; margin: -12px 0 16px; display: block;">
            打开 Telegram → 搜索 <strong>@BotFather</strong> → 发送 /newbot → 复制 Token
          </n-text>

          <div class="two-col">
            <n-form-item label="API ID">
              <n-input v-model:value="teleForm.api_id" placeholder="123456" />
            </n-form-item>
            <n-form-item label="API Hash">
              <n-input v-model:value="teleForm.api_hash" placeholder="abcdef123456789" />
            </n-form-item>
          </div>
          <n-text depth="3" style="font-size: 12px; margin: -12px 0 0; display: block;">
            访问 <strong>my.telegram.org/apps</strong> 登录后创建应用获得
          </n-text>
        </n-form>
        <n-space justify="space-between" style="margin-top: 24px">
          <n-button @click="prevStep()">上一步</n-button>
          <n-button type="primary" @click="nextStep">下一步</n-button>
        </n-space>
      </template>

      <!-- Step 3: Directories -->
      <template v-if="(!needAdmin && currentStep === 2) || (needAdmin && currentStep === 3)">
        <n-alert type="info" closable style="margin-bottom: 20px">
          压缩后的视频和缩略图会保存到对应目录，确保这些目录已挂载到容器且可写。
        </n-alert>
        <n-form label-placement="top">
          <n-form-item label="视频源目录">
            <n-input v-model:value="dirForm.video_source_dir" />
          </n-form-item>
          <n-form-item label="压缩输出目录">
            <n-input v-model:value="dirForm.output_dir" />
          </n-form-item>
          <n-form-item label="缩略图目录">
            <n-input v-model:value="dirForm.thumbnail_dir" />
          </n-form-item>
        </n-form>
        <n-space justify="space-between" style="margin-top: 24px">
          <n-button @click="currentStep--">上一步</n-button>
          <n-button type="primary" @click="nextStep">下一步</n-button>
        </n-space>
      </template>

      <!-- Step 4: Proxy -->
      <template v-if="(!needAdmin && currentStep === 3) || (needAdmin && currentStep === 4)">
        <n-alert type="warning" closable style="margin-bottom: 20px">
          中国大陆等地区访问 Telegram 需要代理。如果你的服务器可以直接访问 Telegram，跳过即可。
        </n-alert>

        <n-form label-placement="top">
          <n-form-item label="启用代理">
            <n-switch v-model:value="proxyForm.enabled" />
          </n-form-item>

          <template v-if="proxyForm.enabled">
            <n-form-item label="类型">
              <n-select v-model:value="proxyForm.type" :options="[
                { label: 'HTTP', value: 'http' },
                { label: 'MTProto', value: 'mtproto' },
              ]" />
            </n-form-item>
            <div class="two-col">
              <n-form-item label="地址">
                <n-input v-model:value="proxyForm.host" placeholder="host.docker.internal" />
              </n-form-item>
              <n-form-item label="端口">
                <n-input-number v-model:value="proxyForm.port" :min="1" :max="65535" style="width:100%" />
              </n-form-item>
            </div>
            <template v-if="proxyForm.type === 'mtproto'">
              <n-form-item label="Secret">
                <n-input v-model:value="proxyForm.pass" placeholder="64位 hex string" />
              </n-form-item>
            </template>
            <template v-else>
              <n-form-item label="用户名（可选）">
                <n-input v-model:value="proxyForm.user" />
              </n-form-item>
              <n-form-item label="密码（可选）">
                <n-input v-model:value="proxyForm.pass" type="password" />
              </n-form-item>
            </template>
          </template>
        </n-form>

        <n-space justify="space-between" style="margin-top: 24px">
          <n-button @click="currentStep--">上一步</n-button>
          <n-button type="primary" block style="flex:1;margin-left:12px" :loading="submitting" @click="doSetup">
            完成设置
          </n-button>
        </n-space>
      </template>
    </n-card>
  </div>
</template>

<style scoped>
.setup-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.setup-card {
  width: 520px;
  max-width: 90vw;
}
.brand {
  text-align: center;
}
.brand-icon {
  font-size: 40px;
  margin-bottom: 8px;
}
.brand-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
}
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 480px) {
  .two-col { grid-template-columns: 1fr; }
}
</style>
