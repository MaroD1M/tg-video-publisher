import { ref, watchEffect } from 'vue'
import { darkTheme, lightTheme } from 'naive-ui'
import type { GlobalTheme } from 'naive-ui'

const isDark = ref(localStorage.getItem('theme') !== 'light')
const theme = ref<GlobalTheme | null>(isDark.value ? darkTheme : lightTheme)

watchEffect(() => {
  const dark = isDark.value
  localStorage.setItem('theme', dark ? 'dark' : 'light')
  theme.value = dark ? darkTheme : lightTheme
  document.documentElement.style.setProperty('--body-bg', dark ? '#0a0a0f' : '#f5f5f5')
  const root = document.documentElement.style
  root.setProperty('--bg-subtle', dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)')
  root.setProperty('--bg-hover', dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)')
  root.setProperty('--bg-card', dark ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.8)')
  root.setProperty('--border-subtle', dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)')
  root.setProperty('--text-brand', dark ? '#e0e0f0' : '#1a1a2e')
  root.setProperty('--text-secondary', dark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)')
  root.setProperty('--color-green', '#63e2b7')
  root.setProperty('--color-red', '#e64e4e')
  root.setProperty('--color-purple', '#8b5cf6')
  root.setProperty('--bg-purple', dark ? 'rgba(139,92,246,0.08)' : 'rgba(139,92,246,0.07)')
  root.setProperty('--border-purple', dark ? 'rgba(139,92,246,0.15)' : 'rgba(139,92,246,0.2)')
  root.setProperty('--bg-green', dark ? 'rgba(99,226,183,0.06)' : 'rgba(99,226,183,0.1)')
})

export function useTheme() {
  function toggle() {
    isDark.value = !isDark.value
  }

  return { isDark, theme, toggle }
}
