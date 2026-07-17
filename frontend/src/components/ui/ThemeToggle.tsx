import { useEffect, useRef, useState } from 'react'
import { Check, Flower2, Gem, Monitor, Moon, Sun, Sunset, TreePine } from 'lucide-react'
import { useTheme, type Theme } from '../../lib/theme'

const OPTIONS: { value: Theme; icon: typeof Sun; label: string; swatch: string }[] = [
  { value: 'light', icon: Sun, label: 'Light', swatch: 'linear-gradient(135deg, #6d61f0, #8b5cf6)' },
  { value: 'dark', icon: Moon, label: 'Dark', swatch: 'linear-gradient(135deg, #5b3fe6, #7c3aed)' },
  { value: 'midnight', icon: Gem, label: 'Midnight', swatch: 'linear-gradient(135deg, #06b6d4, #10b981)' },
  { value: 'sunset', icon: Sunset, label: 'Sunset', swatch: 'linear-gradient(135deg, #ea580c, #e11d48)' },
  { value: 'rose', icon: Flower2, label: 'Rose', swatch: 'linear-gradient(135deg, #db2777, #c026d3)' },
  { value: 'forest', icon: TreePine, label: 'Forest', swatch: 'linear-gradient(135deg, #059669, #65a30d)' },
  { value: 'system', icon: Monitor, label: 'System', swatch: 'linear-gradient(135deg, #94a3b8, #475569)' },
]

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const current = OPTIONS.find((o) => o.value === theme) ?? OPTIONS[0]

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        title={`Theme: ${current.label}`}
        aria-label="Change theme"
        onClick={() => setOpen((o) => !o)}
        className="flex h-5 w-5 items-center justify-center rounded-full text-slate-400 transition-colors hover:text-slate-600 dark:hover:text-slate-300"
      >
        <current.icon size={13} />
      </button>

      {open && (
        <div className="absolute right-0 bottom-full z-50 mb-2 w-40 rounded-[--radius-card] border border-white/60 bg-white/95 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.5),var(--shadow-card-hover)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/95">
          {OPTIONS.map(({ value, icon: Icon, label, swatch }) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setTheme(value)
                setOpen(false)
              }}
              className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs font-medium transition-colors ${
                theme === value
                  ? 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100'
                  : 'text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/60'
              }`}
            >
              <span
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-white"
                style={{ background: swatch }}
              >
                <Icon size={9} />
              </span>
              <span className="flex-1">{label}</span>
              {theme === value && <Check size={13} className="text-brand-600 dark:text-brand-400" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
