import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('username')
      if (window.location.pathname !== '/login') {
        window.location.replace('/login')
      }
    }
    return Promise.reject(err)
  }
)

export default api

export async function login(username: string, password: string) {
  const { data } = await api.post('/auth/login', { username, password })
  return data
}

export async function getMe() {
  const { data } = await api.get('/auth/me')
  return data
}

export async function hasUsers() {
  const { data } = await api.get('/auth/has-users')
  return data
}

export async function changePassword(oldPassword: string, newPassword: string) {
  const { data } = await api.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
  return data
}

export async function requestPasswordReset(username: string) {
  const { data } = await api.post('/auth/request-reset', { username })
  return data
}

export async function confirmPasswordReset(username: string, resetToken: string, newPassword: string) {
  const { data } = await api.post('/auth/reset-password', { username, reset_token: resetToken, new_password: newPassword })
  return data
}

export async function fetchSettings() {
  const { data } = await api.get('/settings')
  return data
}

export async function updateSettings(settings: Record<string, string>) {
  const { data } = await api.put('/settings', settings)
  return data
}

export async function completeSetup(settings: Record<string, string>) {
  const { data } = await api.post('/settings/setup', settings)
  return data
}

export async function getSetupStatus() {
  const { data } = await api.get('/setup/status')
  return data
}

export async function fetchVideos(params: Record<string, any>) {
  const { data } = await api.get('/videos', { params })
  return data
}

export async function scanDirectory(path: string) {
  const { data } = await api.post('/videos/scan', null, { params: { path } })
  return data
}

export async function submitCompress(videoIds: number[], preset: string = 'balanced', targetSizeMb: number = 1000, targetWidth: number = 0, targetHeight: number = 0, scheduleId: number = 0, publishAfter: boolean = false, publishChannelId: number = 0) {
  const { data } = await api.post('/compress', { video_ids: videoIds, preset, target_size_mb: targetSizeMb, target_width: targetWidth, target_height: targetHeight, schedule_id: scheduleId, publish_after: publishAfter, publish_channel_id: publishChannelId })
  return data
}

export async function fetchCompressJobs() {
  const { data } = await api.get('/compress')
  return data
}

export async function cancelCompressJob(jobId: number) {
  const { data } = await api.post(`/compress/${jobId}/cancel`)
  return data
}

export async function pauseJob(jobId: number) {
  const { data } = await api.post(`/compress/${jobId}/pause`)
  return data
}

export async function resumeJob(jobId: number) {
  const { data } = await api.post(`/compress/${jobId}/resume`)
  return data
}

export async function retryCompressJob(jobId: number) {
  const { data } = await api.post(`/compress/${jobId}/retry`)
  return data
}

export async function fetchThumbnails() {
  const { data } = await api.get('/thumbnails')
  return data
}

export function getThumbnailImage(id: number) {
  return `/api/thumbnails/${id}/image`
}

export async function fetchSchedules() {
  const { data } = await api.get('/schedules')
  return data
}

export async function createSchedule(body: Record<string, any>) {
  const { data } = await api.post('/schedules', body)
  return data
}

export async function updateSchedule(id: number, body: Record<string, any>) {
  const { data } = await api.put(`/schedules/${id}`, body)
  return data
}

export async function deleteSchedule(id: number) {
  const { data } = await api.delete(`/schedules/${id}`)
  return data
}

export async function triggerSchedule(id: number) {
  const { data } = await api.post(`/schedules/${id}/trigger`)
  return data
}

export async function fetchLogs(params: Record<string, any>) {
  const { data } = await api.get('/logs', { params })
  return data
}

export async function fetchLogsWithFilters(p: { search?: string; chat_id?: number; date_from?: string; date_to?: string; success?: boolean; page?: number; page_size?: number }) {
  const params: Record<string, any> = {}
  if (p.search) params.search = p.search
  if (p.chat_id) params.chat_id = p.chat_id
  if (p.date_from) params.date_from = p.date_from
  if (p.date_to) params.date_to = p.date_to
  if (p.success !== undefined) params.success = p.success
  if (p.page) params.page = p.page
  if (p.page_size) params.page_size = p.page_size
  const { data } = await api.get('/logs', { params })
  return data
}

export async function testProxy() {
  const { data } = await api.post('/settings/proxy/test')
  return data
}

export async function applySettings() {
  const { data } = await api.post('/settings/apply')
  return data
}

export async function fetchStats() {
  const { data } = await api.get('/stats')
  return data
}

export async function fetchDiskUsage() {
  const { data } = await api.get('/disk')
  return data
}

export async function deleteVideo(videoId: number) {
  const { data } = await api.delete(`/videos/${videoId}`)
  return data
}

export async function publishNow(videoId: number, channelId: number, title: string = '') {
  const { data } = await api.post(`/videos/${videoId}/publish`, { channel_id: channelId, title })
  return data
}

export async function fetchChats() {
  const { data } = await api.get('/chats')
  return data
}

export async function verifyChat(chatId: number) {
  const { data } = await api.post('/chats/verify', null, { params: { chat_id: chatId } })
  return data
}

export async function refreshChats() {
  const { data } = await api.post('/chats/refresh')
  return data
}

export async function setChatAlias(chatId: number, alias: string) {
  const { data } = await api.put(`/chats/${chatId}/alias`, { alias })
  return data
}

export async function browseDirectory(path: string) {
  const { data } = await api.get('/videos/browse', { params: { path } })
  return data
}

export async function estimateCompressedSize(videoPath: string, preset: string, targetSizeMb: number) {
  const { data } = await api.get('/videos/estimate-size', { params: { path: videoPath, preset, target_size_mb: targetSizeMb } })
  return data
}

export async function fetchVersion() {
  const { data } = await api.get('/version')
  return data
}

export async function checkVersion() {
  const { data } = await api.get('/version/check')
  return data
}

export async function fetchPublishTasks(params: Record<string, any> = {}) {
  const { data } = await api.get('/publish', { params })
  return data
}

export async function cancelPublishTask(taskId: number) {
  const { data } = await api.post(`/publish/${taskId}/cancel`)
  return data
}

export async function retryPublishTask(taskId: number) {
  const { data } = await api.post(`/publish/${taskId}/retry`)
  return data
}

export async function regenerateThumbnail(thumbId: number) {
  const { data } = await api.post(`/thumbnails/${thumbId}/regenerate`)
  return data
}

export async function generateThumbnail(videoId: number, layout?: string) {
  const { data } = await api.post('/thumbnails/generate', null, { params: { video_id: videoId, layout: layout || '3x3' } })
  return data
}

export async function deleteCompressJob(jobId: number) {
  const { data } = await api.delete(`/compress/${jobId}`)
  return data
}

export async function batchDeleteCompress(status: string = '') {
  const { data } = await api.post('/compress/batch-delete', null, { params: { status } })
  return data
}

export async function pausePublishTask(taskId: number) {
  const { data } = await api.post(`/publish/${taskId}/pause`)
  return data
}

export async function resumePublishTask(taskId: number) {
  const { data } = await api.post(`/publish/${taskId}/resume`)
  return data
}

export async function reorderPublishTask(taskId: number, direction: string) {
  const { data } = await api.post(`/publish/${taskId}/reorder`, null, { params: { direction } })
  return data
}

export async function deletePublishTask(taskId: number) {
  const { data } = await api.delete(`/publish/${taskId}`)
  return data
}

export async function fetchNotificationConfig() {
  const { data } = await api.get('/settings/notifications')
  return data
}

export async function updateNotificationConfig(body: Record<string, any>) {
  const { data } = await api.put('/settings/notifications', body)
  return data
}

export async function batchConfigCompress(body: Record<string, any>) {
  const { data } = await api.put('/compress/batch-config', body)
  return data
}

export async function batchAddToSchedule(scheduleId: number, videoIds: number[]) {
  const { data } = await api.post(`/schedules/${scheduleId}/batch-add`, { video_ids: videoIds })
  return data
}

export async function batchPublish(videoIds: number[], channelId: number) {
  const { data } = await api.post('/publish/batch', { video_ids: videoIds, channel_id: channelId })
  return data
}

export async function updateCompressSettings(jobId: number, updates: Record<string, any>) {
  const { data } = await api.put(`/compress/${jobId}/settings`, updates)
  return data
}

export async function fetchDiskCleanup() {
  const { data } = await api.get('/disk/cleanup')
  return data
}

export async function executeDiskCleanup(body: Record<string, any>) {
  const { data } = await api.post('/disk/cleanup', body)
  return data
}

export async function deletePublishLog(logId: number) {
  const { data } = await api.delete(`/logs/${logId}`)
  return data
}
