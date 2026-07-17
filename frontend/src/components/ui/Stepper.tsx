import { Check } from 'lucide-react'

export interface StepperProps {
  steps: readonly string[]
  currentIndex: number
  orientation?: 'horizontal' | 'vertical'
  className?: string
}

function Circle({ state }: { state: 'done' | 'current' | 'upcoming' }) {
  return (
    <div
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors ${
        state === 'done'
          ? 'bg-brand-600 text-white shadow-[0_0_0_1px_rgba(91,63,230,0.12),var(--shadow-card)]'
          : state === 'current'
            ? 'border-2 border-brand-600 bg-brand-50 text-brand-600 dark:bg-brand-950 dark:text-brand-400'
            : 'border border-slate-300 text-slate-400 dark:border-slate-700'
      }`}
      aria-hidden="true"
    >
      {state === 'done' ? <Check size={14} /> : null}
    </div>
  )
}

/** Non-interactive multi-step progress indicator. Uses the WAI-ARIA APG
 * step-indicator pattern (nav > ol > li[aria-current="step"]) rather than
 * role="tablist" — tablist/tab implies an interactive, arrow-key-navigable
 * widget with associated tabpanels, which this isn't (no click-to-jump). */
export default function Stepper({ steps, currentIndex, orientation = 'horizontal', className = '' }: StepperProps) {
  const liveAnnouncement = (
    <span className="sr-only" role="status" aria-live="polite">
      Step {currentIndex + 1} of {steps.length}: {steps[currentIndex]}
    </span>
  )

  if (orientation === 'vertical') {
    return (
      <nav aria-label="Onboarding progress" className={className}>
        {liveAnnouncement}
        <ol>
          {steps.map((label, i) => {
            const state = i < currentIndex ? 'done' : i === currentIndex ? 'current' : 'upcoming'
            return (
              <li key={label} aria-current={state === 'current' ? 'step' : undefined} className="relative flex gap-3 pb-7 last:pb-0">
                {i < steps.length - 1 && (
                  <div
                    className={`absolute top-7 left-3.5 h-[calc(100%-1.75rem)] w-px ${
                      state === 'done' ? 'bg-brand-400' : 'bg-slate-200 dark:bg-slate-700'
                    }`}
                    aria-hidden="true"
                  />
                )}
                <Circle state={state} />
                <span
                  className={`pt-1 text-sm leading-tight transition-colors ${
                    state === 'current'
                      ? 'font-semibold text-slate-900 dark:text-slate-100'
                      : state === 'done'
                        ? 'text-slate-600 dark:text-slate-300'
                        : 'text-slate-400 dark:text-slate-600'
                  }`}
                >
                  {label}
                </span>
              </li>
            )
          })}
        </ol>
      </nav>
    )
  }

  return (
    <nav aria-label="Onboarding progress" className={className}>
      {liveAnnouncement}
      <ol className="flex flex-wrap items-center gap-2">
        {steps.map((label, i) => {
          const state = i < currentIndex ? 'done' : i === currentIndex ? 'current' : 'upcoming'
          return (
            <li key={label} aria-current={state === 'current' ? 'step' : undefined} className="flex items-center gap-2">
              <div
                className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium ${
                  state === 'done'
                    ? 'bg-brand-600 text-white'
                    : state === 'current'
                      ? 'border-2 border-brand-600 text-brand-600 dark:text-brand-400'
                      : 'border border-slate-300 text-slate-400 dark:border-slate-700'
                }`}
                aria-hidden="true"
              >
                {state === 'done' ? <Check size={13} /> : i + 1}
              </div>
              <span
                className={`text-xs ${state === 'current' ? 'font-semibold text-slate-900 dark:text-slate-100' : 'text-slate-400'}`}
              >
                {label}
              </span>
              {i < steps.length - 1 && <div className="h-px w-6 bg-slate-200 dark:bg-slate-700" aria-hidden="true" />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
