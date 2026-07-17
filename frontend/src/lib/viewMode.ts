import { useEffect, useState } from 'react'

export type ViewMode = 'grid' | 'list'

export function useViewMode(key: string, initial: ViewMode = 'grid') {
  const storageKey = `agent-forge-view-${key}`
  const [mode, setMode] = useState<ViewMode>(
    () => (localStorage.getItem(storageKey) as ViewMode | null) ?? initial,
  )

  useEffect(() => {
    localStorage.setItem(storageKey, mode)
  }, [mode, storageKey])

  return [mode, setMode] as const
}
