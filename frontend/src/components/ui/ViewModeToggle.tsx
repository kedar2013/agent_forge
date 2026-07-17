import { LayoutGrid, List } from 'lucide-react'
import type { ViewMode } from '../../lib/viewMode'

export default function ViewModeToggle({ mode, onChange }: { mode: ViewMode; onChange: (m: ViewMode) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900">
      {(['grid', 'list'] as const).map((m) => {
        const Icon = m === 'grid' ? LayoutGrid : List
        return (
          <button
            key={m}
            type="button"
            title={m === 'grid' ? 'Grid view' : 'List view'}
            aria-label={m === 'grid' ? 'Grid view' : 'List view'}
            onClick={() => onChange(m)}
            className={`flex h-7 w-7 items-center justify-center rounded transition-colors ${
              mode === m
                ? 'bg-gradient-to-br from-brand-600 to-accent-600 text-white'
                : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
            }`}
          >
            <Icon size={14} />
          </button>
        )
      })}
    </div>
  )
}
