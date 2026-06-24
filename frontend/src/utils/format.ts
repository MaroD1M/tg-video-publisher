export function formatSize(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1e6) return (bytes / 1e3).toFixed(1) + ' KB'
  if (bytes < 1e9) return (bytes / 1e6).toFixed(1) + ' MB'
  return (bytes / 1e9).toFixed(2) + ' GB'
}

export function formatDuration(seconds: number): string {
  if (!seconds) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  if (m > 0) return `${m}分${s}秒`
  return `${s}秒`
}

export function formatChannelLabel(c: { alias?: string | null; chat_name?: string | null; chat_id?: number }, maxLen = 16): string {
  const name = c.alias || c.chat_name || String(c.chat_id || '')
  return name.length > maxLen ? name.slice(0, maxLen) + '…' : name
}
