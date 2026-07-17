import type { ReactNode } from 'react'

export interface PageHeaderProps {
  title: string
  description?: string
  /** Rendered inline next to the title, e.g. a <LiveBadge />. */
  badge?: ReactNode
  /** Right-aligned action row (buttons, toggles). */
  actions?: ReactNode
  className?: string
}

/** Gradient page title + subtitle + right-aligned action slot — the header
 * block repeated across every top-level admin page. */
export default function PageHeader({ title, description, badge, actions, className = '' }: PageHeaderProps) {
  return (
    <div className={`flex items-center justify-between gap-4 ${className}`}>
      <div>
        <div className="flex items-center gap-2">
          <h1 className="bg-gradient-to-r from-brand-600 to-accent-500 bg-clip-text text-xl font-bold tracking-tight text-transparent dark:from-brand-300 dark:to-accent-400">
            {title}
          </h1>
          {badge}
        </div>
        {description && <p className="text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
