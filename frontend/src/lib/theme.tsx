import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark' | 'midnight' | 'sunset' | 'forest' | 'rose' | 'system'
export type ResolvedTheme = 'light' | 'dark' | 'midnight' | 'sunset' | 'forest' | 'rose'

const STORAGE_KEY = 'agent-forge-theme'

// Which resolved themes are dark-based (get the `.dark` class + native
// color-scheme: dark — see index.css). "system" never resolves to one of
// these directly; it only ever picks plain light/dark, matching the OS.
const DARK_FAMILY: ResolvedTheme[] = ['dark', 'midnight', 'forest']

function getSystemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

function resolveTheme(theme: Theme): ResolvedTheme {
  if (theme === 'system') return getSystemPrefersDark() ? 'dark' : 'light'
  return theme
}

function applyResolvedTheme(theme: Theme) {
  const resolved = resolveTheme(theme)
  document.documentElement.dataset.theme = resolved
  document.documentElement.classList.toggle('dark', DARK_FAMILY.includes(resolved))
}

const ThemeContext = createContext<{ theme: Theme; setTheme: (t: Theme) => void } | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? 'system',
  )

  useEffect(() => {
    applyResolvedTheme(theme)
    if (theme !== 'system') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => applyResolvedTheme('system')
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [theme])

  function setTheme(t: Theme) {
    localStorage.setItem(STORAGE_KEY, t)
    setThemeState(t)
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
