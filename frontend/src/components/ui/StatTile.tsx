import type { LucideIcon } from 'lucide-react'
import Card from './Card'

export default function StatTile({
  icon: Icon,
  label,
  value,
  tone = 'brand',
  onClick,
}: {
  icon: LucideIcon
  label: string
  value: string | number
  tone?: 'brand' | 'success' | 'warning' | 'neutral'
  /** When set, the whole tile becomes a button that jumps to whatever this
   * stat summarizes (e.g. "Cache hit rate" -> the semantic cache table). */
  onClick?: () => void
}) {
  const toneClasses: Record<string, string> = {
    brand: 'bg-gradient-to-br from-brand-500 to-accent-600 text-white shadow-[--shadow-glow-brand]',
    success: 'bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-[0_6px_16px_-4px_rgba(16,185,129,0.5)]',
    warning: 'bg-gradient-to-br from-amber-400 to-orange-500 text-white shadow-[0_6px_16px_-4px_rgba(245,158,11,0.5)]',
    neutral: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  }

  return (
    <Card hover onClick={onClick} className="group flex items-center gap-3">
      <div className={`rounded-lg p-2.5 transition-transform group-hover:scale-105 ${toneClasses[tone]}`}>
        <Icon size={20} />
      </div>
      <div>
        <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">
          {value}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
      </div>
    </Card>
  )
}
