import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { ProgressJob, ProgressTask } from '@/types'

export const useTaskStore = defineStore('tasks', () => {
  const runningJobs = ref<ProgressJob[]>([])
  const publishTasks = ref<ProgressTask[]>([])

  const activeJobs = computed(() => runningJobs.value.filter(j => j.status === 'running'))
  const activeTasks = computed(() =>
    publishTasks.value.filter(t => t.status === 'running' || t.status === 'uploading' || t.status === 'queued')
  )
  const hasActive = computed(() => activeJobs.value.length > 0 || activeTasks.value.length > 0)

  function upsertJob(jobId: number, patch: Partial<ProgressJob>) {
    const idx = runningJobs.value.findIndex(j => j.id === jobId)
    if (idx >= 0) {
      Object.assign(runningJobs.value[idx], patch)
    } else if (patch.video_name) {
      runningJobs.value.push({
        id: jobId, video_name: '', status: 'running', progress: 0,
        eta_sec: 0, elapsed_sec: 0, speed: 0, fps: 0, error: '',
        ...patch,
      })
    }
  }

  function upsertTask(taskId: number, patch: Partial<ProgressTask>) {
    const t = publishTasks.value.find(p => p.id === taskId)
    if (t) {
      Object.assign(t, patch)
    } else if (patch.video_name) {
      publishTasks.value.unshift({
        id: taskId, video_id: null, video_name: '', channel_name: '',
        status: 'running', progress: 5, elapsed_sec: 0, eta_sec: 0,
        thumbnail_id: null, error: '',
        ...patch,
      })
    }
  }

  function clearDone() {
    runningJobs.value = runningJobs.value.filter(j => j.status === 'running')
    publishTasks.value = publishTasks.value.filter(
      t => t.status === 'running' || t.status === 'uploading' || t.status === 'queued'
    )
  }

  function handleWSMessage(msg: any) {
    switch (msg.type) {
      case 'job_start':
        upsertJob(msg.job_id, { video_name: msg.video, status: 'running', progress: 0 })
        break
      case 'progress':
        upsertJob(msg.job_id, {
          progress: msg.percent, eta_sec: msg.eta_sec || 0,
          elapsed_sec: msg.elapsed_sec || 0, speed: msg.speed || 0, fps: msg.fps || 0,
        })
        break
      case 'job_done':
        upsertJob(msg.job_id, { status: 'done', progress: 100 })
        break
      case 'job_skip':
        upsertJob(msg.job_id, { status: 'skipped', progress: 100 })
        break
      case 'job_error':
        upsertJob(msg.job_id, { status: 'failed', error: msg.error || '' })
        break
      case 'publish_progress':
        upsertTask(msg.task_id, {
          video_id: msg.video_id, video_name: msg.video_name,
          channel_name: msg.channel_name || '',
          progress: msg.progress || 5, elapsed_sec: msg.elapsed_sec || 0,
          eta_sec: msg.eta_sec || 0, thumbnail_id: msg.thumbnail_id || null,
          status: msg.step === 'uploading' ? 'uploading' : 'running',
        })
        break
      case 'publish_done':
        upsertTask(msg.task_id, { status: 'done', progress: 100 })
        break
      case 'publish_error':
        upsertTask(msg.task_id, { status: 'failed', error: msg.error || '' })
        break
      case 'publish_cancelled':
        upsertTask(msg.task_id, { status: 'cancelled' })
        break
    }
  }

  return { runningJobs, publishTasks, activeJobs, activeTasks, hasActive, upsertJob, upsertTask, clearDone, handleWSMessage }
})
