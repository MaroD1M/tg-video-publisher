import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchSettings, fetchStats } from '@/api/client'
import type { SettingsData, StatsData } from '@/types'

const CACHE_TTL = 30_000

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<SettingsData>({})
  const stats = ref<StatsData | null>(null)
  const loaded = ref(false)
  let lastSettingsFetch = 0
  let lastStatsFetch = 0

  async function loadSettings(force = false) {
    const now = Date.now()
    if (!force && loaded.value && now - lastSettingsFetch < CACHE_TTL) return settings.value
    const data = await fetchSettings()
    let dirs: string[] = []
    if (Array.isArray(data.video_source_dirs) && data.video_source_dirs.length) {
      dirs = data.video_source_dirs
    } else if (typeof data.video_source_dirs === 'string') {
      try {
        const parsed = JSON.parse(data.video_source_dirs)
        if (Array.isArray(parsed) && parsed.length) dirs = parsed
      } catch {}
    } else if (data.video_source_dir) {
      dirs = [data.video_source_dir]
    }
    settings.value = { ...data, video_source_dirs: dirs }
    lastSettingsFetch = now
    loaded.value = true
    return settings.value
  }

  async function loadStats(force = false) {
    const now = Date.now()
    if (!force && stats.value && now - lastStatsFetch < CACHE_TTL) return stats.value
    const data = await fetchStats()
    stats.value = data
    lastStatsFetch = now
    return data
  }

  return { settings, stats, loaded, loadSettings, loadStats }
})
