import type { LucideIcon } from 'lucide-react'
import type { BadgeTone } from './Badge'

/** Same tone system as Badge, rendered as a two-stop gradient instead of a
 * flat fill — used for the solid ("active") avatar state below. */
const TONE_GRADIENT: Record<BadgeTone, string> = {
  neutral: 'from-slate-400 to-slate-500',
  success: 'from-emerald-400 to-emerald-600',
  warning: 'from-amber-400 to-amber-600',
  danger: 'from-red-400 to-red-600',
  brand: 'from-brand-500 to-accent-500',
  info: 'from-blue-400 to-blue-600',
  violet: 'from-violet-400 to-violet-600',
  teal: 'from-teal-400 to-teal-600',
  amber: 'from-amber-400 to-orange-500',
}

export type EntityAvatarState = 'active' | 'ghost' | 'muted'

/** Shared icon-circle avatar — the one visual identity every entity tile
 * (agent, tool, skill) and every creation form's live preview
 * (PreviewCardShell) uses, so a future style tweak (a new gradient, a
 * different ghost treatment) happens in exactly one place.
 *
 * - "ghost": ✕ hasn't come to life yet (a still-forming preview, or —
 *   for AgentCard — a draft that's never been published).
 * - "active": a real, valid, currently-usable thing. `glow` adds the
 *   idle animated pulse (see canvas-glow in index.css) reserved for
 *   "and it's genuinely running right now" (a published agent), not
 *   used indiscriminately on every active avatar.
 * - "muted": exists, but retired/inactive (an archived agent). */
export default function EntityAvatar({
  icon: Icon,
  tone = 'brand',
  state = 'active',
  glow = false,
  size = 40,
}: {
  icon: LucideIcon
  tone?: BadgeTone
  state?: EntityAvatarState
  glow?: boolean
  size?: number
}) {
  const iconSize = Math.round(size * 0.5)

  if (state === 'ghost') {
    return (
      <div
        style={{ width: size, height: size }}
        className="flex shrink-0 animate-pulse items-center justify-center rounded-full border-2 border-dashed border-slate-300 text-slate-300 dark:border-slate-700 dark:text-slate-700"
      >
        <Icon size={iconSize} />
      </div>
    )
  }

  return (
    <div
      style={{ width: size, height: size }}
      className={`flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-white transition-opacity duration-500 ${TONE_GRADIENT[tone]} ${
        state === 'muted' ? 'opacity-40 grayscale' : ''
      } ${glow ? 'animate-canvas-glow' : ''}`}
    >
      <Icon size={iconSize} />
    </div>
  )
}
