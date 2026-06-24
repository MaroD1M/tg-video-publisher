import { ref, onUnmounted } from 'vue'

export function useWebSocket(
  url: string,
  onMessage: (event: MessageEvent) => void,
) {
  const ws = ref<WebSocket | null>(null)
  let reconnectTimer: number | undefined
  let reconnectAttempts = 0
  let mounted = true

  function connect() {
    if (!mounted) return
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const token = localStorage.getItem('access_token')
    const fullUrl = `${protocol}//${location.host}${url}?token=${token || ''}`
    ws.value = new WebSocket(fullUrl)
    ws.value.onmessage = onMessage
    ws.value.onclose = () => {
      if (!mounted) return
      const delay = Math.min((reconnectAttempts || 1) * 5000, 60000)
      reconnectAttempts = (reconnectAttempts || 1) + 1
      reconnectTimer = window.setTimeout(connect, delay)
    }
    ws.value.onerror = () => { ws.value?.close() }
    ws.value.onopen = () => { reconnectAttempts = 0 }
  }

  function disconnect() {
    mounted = false
    if (reconnectTimer) clearTimeout(reconnectTimer)
    ws.value?.close()
    ws.value = null
  }

  onUnmounted(disconnect)

  return { ws, connect, disconnect }
}
