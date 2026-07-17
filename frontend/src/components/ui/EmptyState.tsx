import type { LucideIcon } from 'lucide-react'

export default function EmptyState({
  icon: Icon,
  title,
  message,
  action,
}: {
  icon: LucideIcon
  title: string
  message: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[--radius-card] border border-dashed border-slate-300 px-6 py-16 text-center dark:border-slate-700">
      <div className="mb-3 rounded-full bg-slate-100 p-3 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
        <Icon size={24} />
      </div>
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
