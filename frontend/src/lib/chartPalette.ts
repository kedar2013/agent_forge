import { useEffect, useState } from 'react'

// Validated against this app's actual card surfaces (white / slate-900) via
// the dataviz skill's validator — fixed hue order is the CVD-safety
// mechanism, never reassigned per filter.
const LIGHT: string[] = [
  '#2a78d6', // blue
  '#1baf7a', // aqua
  '#eda100', // yellow
  '#008300', // green
  '#4a3aa7', // violet
  '#e34948', // red
  '#e87ba4', // magenta
  '#eb6834', // orange
]

const DARK: string[] = [
  '#3987e5',
  '#199e70',
  '#c98500',
  '#008300',
  '#9085e9',
  '#e66767',
  '#d55181',
  '#d95926',
]

/** Tracks the app's actual selected theme (light/dark/midnight via
 * ThemeProvider's `.dark` class on <html>), not just the OS preference —
 * so chart colors match whichever theme the user picked in the toggle. */
export function useIsDarkMode(): boolean {
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const target = document.documentElement
    const observer = new MutationObserver(() => setIsDark(target.classList.contains('dark')))
    observer.observe(target, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])
  return isDark
}

/** Stable color assignment: same key always gets the same slot for a given key list. */
export function buildCategoricalScale(keys: string[], isDark: boolean): Map<string, string> {
  const palette = isDark ? DARK : LIGHT
  const sorted = [...keys].sort()
  const map = new Map<string, string>()
  sorted.forEach((key, i) => map.set(key, palette[i % palette.length]))
  return map
}
