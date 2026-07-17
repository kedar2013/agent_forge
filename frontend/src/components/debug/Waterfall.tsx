import { useState } from 'react'
import { ChevronDown, ChevronRight, MessageSquare, RotateCw, Wrench, ArrowRightLeft } from 'lucide-react'
import type { SpanNode } from '../../api/debug'
import SpanDetail from './SpanDetail'

const KIND_BAR_CLASS: Record<string, string> = {
  root: 'bg-brand-500',
  tool: 'bg-accent-500',
  model: 'bg-violet-500',
  transfer: 'bg-slate-400 dark:bg-slate-500',
  retry: 'bg-amber-500',
}

const KIND_ICON: Record<string, typeof Wrench> = {
  tool: Wrench,
  model: MessageSquare,
  transfer: ArrowRightLeft,
  retry: RotateCw,
}

export default function Waterfall({ spans }: { spans: SpanNode[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const total = Math.max(1, ...spans.map((s) => s.start_offset_ms + Math.max(s.duration_ms, 1)))

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-1.5">
      {spans.map((span) => {
        const leftPct = (span.start_offset_ms / total) * 100
        const widthPct = Math.max((span.duration_ms / total) * 100, 0.6)
        const isExpanded = expanded.has(span.id)
        const expandable = span.kind !== 'transfer'
        const Icon = KIND_ICON[span.kind]
        return (
          <div key={span.id}>
            <button
              type="button"
              onClick={() => expandable && toggle(span.id)}
              className={`flex w-full items-center gap-2 rounded text-xs ${expandable ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800' : 'cursor-default'}`}
            >
              <span className="w-4 shrink-0 text-slate-400">
                {expandable ? isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} /> : null}
              </span>
              <div
                className={`flex w-40 shrink-0 items-center gap-1 truncate text-left font-mono ${span.kind === 'root' ? 'font-semibold' : 'text-slate-500 dark:text-slate-400'}`}
              >
                {Icon && <Icon size={11} className="shrink-0" />}
                <span className="truncate">{span.name}</span>
              </div>
              <div className="relative h-5 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                <div
                  className={`absolute top-0 h-5 rounded ${span.status === 'error' ? 'bg-red-500' : KIND_BAR_CLASS[span.kind] ?? 'bg-accent-500'}`}
                  style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                  title={`${span.duration_ms}ms`}
                />
              </div>
              <div className="w-28 shrink-0 text-right tabular-nums text-slate-500">
                {span.duration_ms}ms{span.agent_name ? ` · ${span.agent_name}` : ''}
              </div>
            </button>
            {isExpanded && <SpanDetail span={span} />}
          </div>
        )
      })}
    </div>
  )
}
