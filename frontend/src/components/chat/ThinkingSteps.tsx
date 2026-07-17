import { ArrowRightLeft, Check, ChevronDown, Loader2, Wrench } from 'lucide-react'
import { humanizeName } from '../../lib/humanize'

export interface ThinkingStep {
  id: string
  kind: 'transfer' | 'tool'
  label: string
  status: 'active' | 'done'
}

/** Stable per-tool-name id, so a "tool_call_end" event can flip the
 * matching "tool_call_start" step straight to done via a Map lookup — no
 * fuzzy label matching needed. */
export function toolStepId(name: string): string {
  return `tool-${name}`
}

export function stepFromEvent(
  event: { type: string; to?: string; name?: string },
): ThinkingStep | { doneId: string } | null {
  if (event.type === 'transfer' && event.to) {
    return { id: `transfer-${event.to}`, kind: 'transfer', label: `Routing to ${humanizeName(event.to)}`, status: 'done' }
  }
  if (event.type === 'tool_call_start' && event.name) {
    return { id: toolStepId(event.name), kind: 'tool', label: humanizeName(event.name), status: 'active' }
  }
  if (event.type === 'tool_call_end' && event.name) {
    return { doneId: toolStepId(event.name) }
  }
  return null
}

/** Live progress while a request is in flight — a compact list of
 * transfers/tool-calls with spinner -> checkmark transitions. */
export function LiveThinking({ steps }: { steps: ThinkingStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-sm bg-slate-100 px-4 py-3 dark:bg-slate-800">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 dark:bg-slate-500"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    )
  }
  return (
    <div className="min-w-[180px] rounded-2xl rounded-bl-sm bg-slate-100 px-3.5 py-2.5 text-xs dark:bg-slate-800">
      <ul className="space-y-1.5">
        {steps.map((step) => (
          <li key={step.id} className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
            {step.status === 'active' ? (
              <Loader2 size={12} className="shrink-0 animate-spin text-brand-500" />
            ) : (
              <Check size={12} className="shrink-0 text-emerald-500" />
            )}
            {step.kind === 'transfer' ? (
              <ArrowRightLeft size={11} className="shrink-0 opacity-60" />
            ) : (
              <Wrench size={11} className="shrink-0 opacity-60" />
            )}
            <span className={step.status === 'active' ? '' : 'text-slate-500 dark:text-slate-400'}>{step.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Once a turn completes, its thinking steps collapse into this toggle
 * above the final answer — transparency without cluttering the transcript. */
export function ThoughtProcessSummary({ steps }: { steps: ThinkingStep[] }) {
  if (steps.length === 0) return null
  return (
    <details className="group mb-1.5">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-slate-500 hover:text-slate-700 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-200">
        <ChevronDown size={11} className="transition-transform group-open:rotate-180" />
        Thought process ({steps.length} step{steps.length === 1 ? '' : 's'})
      </summary>
      <ul className="mt-1.5 space-y-1 border-l border-slate-200 pl-3 text-[11px] text-slate-500 dark:border-slate-700 dark:text-slate-400">
        {steps.map((step) => (
          <li key={step.id} className="flex items-center gap-1.5">
            {step.kind === 'transfer' ? (
              <ArrowRightLeft size={10} className="shrink-0 opacity-60" />
            ) : (
              <Wrench size={10} className="shrink-0 opacity-60" />
            )}
            {step.label}
          </li>
        ))}
      </ul>
    </details>
  )
}
