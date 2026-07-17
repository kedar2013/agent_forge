import type { ReactNode } from 'react'

const paddingClasses = {
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6 sm:p-8',
} as const

export default function Card({
  children,
  className = '',
  hover = false,
  padding = 'md',
  onClick,
}: {
  children: ReactNode
  className?: string
  hover?: boolean
  padding?: keyof typeof paddingClasses
  onClick?: () => void
}) {
  return (
    <div
      onClick={onClick}
      className={`rounded-[--radius-card] border border-white/60 bg-white/70 ${paddingClasses[padding]} shadow-[inset_0_1px_0_rgba(255,255,255,0.5),var(--shadow-card)] backdrop-blur-md transition-all dark:border-white/10 dark:bg-slate-900/70 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.04),var(--shadow-card)] ${
        hover
          ? 'cursor-pointer hover:-translate-y-0.5 hover:border-brand-300/60 hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.5),var(--shadow-card-hover)] dark:hover:border-brand-500/30 dark:hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.06),var(--shadow-card-hover)]'
          : ''
      } ${className}`}
    >
      {children}
    </div>
  )
}
