import { ref } from 'vue'
import { fetchChats } from '@/api/client'
import type { Channel } from '@/types'
import { formatChannelLabel } from '@/utils/format'

let channelsCache: Channel[] | null = null
let channelsPromise: Promise<Channel[]> | null = null

export function useChannels() {
  const channels = ref<Channel[]>([])
  const loading = ref(false)

  async function load() {
    if (channelsCache) {
      channels.value = channelsCache
      return
    }
    if (channelsPromise) {
      channels.value = await channelsPromise
      return
    }
    loading.value = true
    try {
      channelsPromise = fetchChats().then(d => {
        const items = d.items || []
        channelsCache = items
        channelsPromise = null
        return items
      })
      channels.value = await channelsPromise
    } catch {
      channels.value = []
    }
    loading.value = false
  }

  function channelOptions(maxLen = 16) {
    return channels.value.map(c => ({
      label: formatChannelLabel(c, maxLen),
      value: c.chat_id,
    }))
  }

  return { channels, loading, load, channelOptions }
}
