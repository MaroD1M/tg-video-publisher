<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NForm, NFormItem, NInput, NButton, NText, NModal, NSpace, NSteps, NStep, NDivider, useMessage } from 'naive-ui'
import { login, requestPasswordReset, confirmPasswordReset } from '@/api/client'

const router = useRouter()
const message = useMessage()

const form = ref({ username: '', password: '' })
const loading = ref(false)
const showReset = ref(false)
const resetStep = ref(1)
const resetForm = ref({ username: '', code: '', newPassword: '', confirmPassword: '' })
const resetLoading = ref(false)

async function doLogin() {
  if (!form.value.username || !form.value.password) {
    message.error('请填写用户名和密码')
    return
  }
  loading.value = true
  try {
    const data = await login(form.value.username, form.value.password)
    localStorage.setItem('access_token', data.token)
    localStorage.setItem('username', data.username)
    router.push('/')
  } catch (err: any) {
    const msg = err.response?.status === 429
      ? '尝试次数过多，请等待 15 分钟'
      : err.response?.status === 401
        ? '用户名或密码错误'
        : '登录失败，请检查网络连接'
    message.error(msg)
  }
  loading.value = false
}

async function doRequestReset() {
  if (!resetForm.value.username) { message.error('请输入用户名'); return }
  resetLoading.value = true
  try {
    await requestPasswordReset(resetForm.value.username)
    message.success('如果已配置管理员通知，验证码已发送至管理员 Telegram')
    resetStep.value = 2
  } catch { message.error('请求失败') }
  resetLoading.value = false
}

async function doConfirmReset() {
  if (resetForm.value.newPassword.length < 4) { message.error('新密码至少 4 位'); return }
  if (resetForm.value.newPassword !== resetForm.value.confirmPassword) { message.error('两次密码不一致'); return }
  resetLoading.value = true
  try {
    await confirmPasswordReset(resetForm.value.username, resetForm.value.code, resetForm.value.newPassword)
    message.success('密码已重置，请使用新密码登录')
    showReset.value = false
    resetStep.value = 1
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '重置失败')
  }
  resetLoading.value = false
}
</script>

<template>
  <div class="login-wrapper">
    <div class="login-card">
      <div class="brand">
        <div class="brand-icon">🎬</div>
        <h2 class="brand-title">TG视频发布助手</h2>
      </div>

      <n-form label-placement="top">
        <n-form-item label="用户名">
          <n-input
            v-model:value="form.username"
            placeholder="admin"
            @keyup.enter="doLogin"
            size="large"
          />
        </n-form-item>
        <n-form-item label="密码">
          <n-input
            v-model:value="form.password"
            type="password"
            placeholder="请输入密码"
            @keyup.enter="doLogin"
            show-password-on="click"
            size="large"
          />
        </n-form-item>
        <n-button
          type="primary"
          block
          :loading="loading"
          @click="doLogin"
          size="large"
        >
          登 录
        </n-button>
      </n-form>

      <div class="forgot">
        <n-button text type="primary" size="tiny" @click="showReset = true">
          忘记密码？
        </n-button>
      </div>
    </div>

    <n-modal v-model:show="showReset" title="重置密码" preset="card" :style="{ maxWidth: '440px' }">
      <div style="padding: 8px 0">
        <n-steps :current="resetStep" style="margin-bottom: 20px">
          <n-step title="验证身份" description="输入用户名" />
          <n-step title="输入验证码" description="管理员提供" />
        </n-steps>

        <div v-if="resetStep === 1">
          <n-form-item label="用户名">
            <n-input v-model:value="resetForm.username" placeholder="输入你的用户名" />
          </n-form-item>
          <n-text depth="3" style="font-size: 11px; display: block; margin-bottom: 12px;">
            系统将向管理员 Telegram 发送验证码，请联系管理员获取。
          </n-text>
          <n-button type="primary" block :loading="resetLoading" @click="doRequestReset">发送验证码</n-button>
        </div>

        <div v-else>
          <n-form-item label="验证码">
            <n-input v-model:value="resetForm.code" placeholder="管理员提供的验证码" />
          </n-form-item>
          <n-form-item label="新密码">
            <n-input v-model:value="resetForm.newPassword" type="password" placeholder="至少 4 位" />
          </n-form-item>
          <n-form-item label="确认新密码">
            <n-input v-model:value="resetForm.confirmPassword" type="password" placeholder="再次输入" />
          </n-form-item>
          <n-space justify="space-between" style="width: 100%">
            <n-button @click="resetStep = 1">上一步</n-button>
            <n-button type="primary" :loading="resetLoading" @click="doConfirmReset">重置密码</n-button>
          </n-space>
        </div>

        <n-divider style="margin: 16px 0" />
        <n-text depth="3" style="font-size: 11px; display: block;">
          如果无法联系管理员，也可以通过 SSH 执行命令重置：
        </n-text>
        <pre class="reset-cmd">docker exec -it tg-video-publisher \
  python -m app.cli.main reset-admin \
  --interactive</pre>
      </div>
      <template #footer>
        <n-button @click="showReset = false">关闭</n-button>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.login-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.login-card {
  width: 380px;
  max-width: 100%;
  padding: 32px 28px;
  border-radius: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
}
.brand {
  text-align: center;
  margin-bottom: 28px;
}
.brand-icon {
  font-size: 42px;
  margin-bottom: 8px;
}
.brand-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-brand);
}
.forgot {
  text-align: center;
  margin-top: 18px;
}
.reset-cmd {
  background: var(--bg-subtle);
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
