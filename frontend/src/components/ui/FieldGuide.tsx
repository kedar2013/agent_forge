/**
 * The intelligent field-guide system for the domain-onboarding wizard.
 *
 * Every field gets a guide with four layers of help, and the guidance is
 * LIVE — examples are computed from the wizard's actual state (real
 * connection prefixes discovered from the backend's .env, real table and
 * column names, the domain name the admin just typed), not canned
 * placeholder text:
 *
 *   what     — one sentence: what this value is
 *   why      — the downstream consequence: what this exact string becomes
 *              in the generated SQL tool / agent / policy
 *   example  — a live, copy-able example drawn from current context
 *   warn     — the mistake people actually make, when there is one
 *
 * Two surfaces, one content source:
 *   - A companion "Guide rail" (right column on wide screens) that follows
 *     focus: click into any field and the rail explains it while you type.
 *   - An ⓘ toggle on each label for keyboard/mobile users, revealing the
 *     same content inline under the field.
 */

import { createContext, useContext, useState, type ReactNode } from 'react'
import { Compass, Info, Lightbulb, TriangleAlert, Wand2 } from 'lucide-react'

export interface GuideContent {
  title: string
  what: string
  why: string
  example?: ReactNode
  warn?: string
}

const GuideContext = createContext<{
  active: GuideContent | null
  setActive: (g: GuideContent | null) => void
} | null>(null)

export function GuideProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<GuideContent | null>(null)
  return <GuideContext.Provider value={{ active, setActive }}>{children}</GuideContext.Provider>
}

/** Wraps one labelled field. Focus anywhere inside pushes the guide to the
 * rail (when a GuideProvider is present); the ⓘ button reveals the same
 * guidance inline for keyboard/mobile use. */
export function GuidedField({ guide, label, children }: { guide: GuideContent; label: string; children: ReactNode }) {
  const ctx = useContext(GuideContext)
  const [pinnedOpen, setPinnedOpen] = useState(false)

  return (
    <div onFocusCapture={() => ctx?.setActive(guide)} className="block text-sm">
      <span className="mb-1 flex items-center gap-1.5 font-medium">
        {label}
        <button
          type="button"
          aria-label={`Explain ${label}`}
          onClick={() => {
            setPinnedOpen((v) => !v)
            ctx?.setActive(guide)
          }}
          className={`rounded-full p-0.5 transition-colors ${
            pinnedOpen ? 'text-brand-600 dark:text-brand-400' : 'text-slate-300 hover:text-brand-500 dark:text-slate-600'
          }`}
        >
          <Info size={13} />
        </button>
      </span>
      {children}
      {pinnedOpen && (
        <div className="mt-1.5 space-y-1.5 rounded-md border border-brand-100 bg-brand-50/50 p-2.5 text-xs dark:border-brand-900 dark:bg-brand-950/40">
          <GuideBody guide={guide} compact />
        </div>
      )}
    </div>
  )
}

function GuideBody({ guide, compact = false }: { guide: GuideContent; compact?: boolean }) {
  return (
    <>
      <p className={compact ? 'text-slate-600 dark:text-slate-300' : 'text-sm text-slate-600 dark:text-slate-300'}>
        {guide.what}
      </p>
      <p className="flex items-start gap-1.5 text-xs text-slate-500 dark:text-slate-400">
        <Wand2 size={13} className="mt-0.5 shrink-0 text-accent-500" />
        <span>{guide.why}</span>
      </p>
      {guide.example != null && (
        <div className="flex items-start gap-1.5 text-xs">
          <Lightbulb size={13} className="mt-0.5 shrink-0 text-amber-500" />
          <div className="min-w-0 text-slate-600 dark:text-slate-300">{guide.example}</div>
        </div>
      )}
      {guide.warn && (
        <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
          <TriangleAlert size={13} className="mt-0.5 shrink-0" />
          <span>{guide.warn}</span>
        </p>
      )}
    </>
  )
}

/** The focus-following companion panel. Render once, in a sticky right
 * column. Shows a friendly default until the first field is focused. */
export function GuideRail() {
  const ctx = useContext(GuideContext)
  const active = ctx?.active ?? null

  return (
    <div className="sticky top-4 rounded-[--radius-card] border border-slate-200 bg-white/70 p-5 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold tracking-wide text-slate-400 uppercase">
        <Compass size={14} className="text-brand-500" /> Field guide
      </div>
      {active ? (
        <div className="space-y-3">
          <div className="text-sm font-semibold">{active.title}</div>
          <GuideBody guide={active} />
        </div>
      ) : (
        <p className="text-xs leading-relaxed text-slate-400">
          Click into any field and this panel explains what it is, what it becomes downstream, and shows a live
          example from your own data.
        </p>
      )}
    </div>
  )
}

/** Inline `<code>` chip for guide examples. */
export function Ex({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] break-all dark:bg-slate-800">
      {children}
    </code>
  )
}
