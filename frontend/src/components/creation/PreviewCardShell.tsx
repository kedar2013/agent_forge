import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import Card from '../ui/Card'

/** Generic "live preview" shell shared by every everyday creation form
 * (New Agent, New Tool, New Skill) — the same ghost-until-named,
 * fade-in-on-reveal visual language as the domain-onboarding wizard's
 * LivingAgentCanvas, generalized into a reusable primitive rather than
 * duplicated per entity type. Each caller supplies its own icon/title/
 * subtitle and whatever type-specific detail goes in `children`; this
 * component only owns the avatar-and-header choreography. */
export default function PreviewCardShell({
  icon: Icon,
  isActive,
  title,
  subtitle,
  emptyHint,
  children,
}: {
  icon: LucideIcon
  /** True once there's enough info (usually just a non-empty name) to
   * treat this as a real thing taking shape rather than a blank slate. */
  isActive: boolean
  title: string
  subtitle?: string
  emptyHint: string
  children?: ReactNode
}) {
  return (
    <div className="sticky top-4">
      <Card>
        <div className="flex items-center gap-3">
          <div
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-white transition-colors duration-500 ${
              isActive
                ? 'animate-canvas-glow bg-gradient-to-br from-brand-500 to-accent-500'
                : 'animate-pulse border-2 border-dashed border-slate-300 text-slate-300 dark:border-slate-700 dark:text-slate-700'
            }`}
          >
            <Icon size={22} />
          </div>
          <div className="min-w-0 flex-1">
            {isActive ? (
              <h3 key={title} className="animate-canvas-reveal truncate font-semibold text-slate-900 dark:text-slate-100">
                {title}
              </h3>
            ) : (
              <h3 className="text-sm text-slate-300 dark:text-slate-700">{emptyHint}</h3>
            )}
            {subtitle && <p className="truncate text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
        </div>
        {children}
      </Card>
    </div>
  )
}
