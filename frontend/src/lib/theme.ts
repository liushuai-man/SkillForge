import { useLayoutEffect, useState } from 'react'

export type Theme = 'system' | 'light' | 'dark'
const key = 'skillforge-vm-theme'

function savedTheme(): Theme {
  try {
    const saved = localStorage.getItem(key)
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* Storage may be unavailable; the session remains usable. */ }
  return 'system'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(savedTheme)
  const [systemDark, setSystemDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches)
  const [storageWarning, setStorageWarning] = useState('')
  const resolved = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useLayoutEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const change = () => setSystemDark(media.matches)
    change()
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = resolved
    document.documentElement.style.colorScheme = resolved
    try { localStorage.setItem(key, theme); setStorageWarning('') }
    catch { setStorageWarning('无法保存主题偏好，本次会话仍可切换主题。') }
  }, [theme, resolved])

  return { theme, setTheme, resolved, storageWarning }
}
