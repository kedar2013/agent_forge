import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, CheckCircle2, ShieldCheck, Table2, Wrench } from 'lucide-react'
import type { AccessPolicy, DataEntity, Tool } from '../../api/types'
import Card from '../ui/Card'

interface LivingAgentCanvasProps {
  domainName: string
  domainDescription: string
  policy: AccessPolicy | null | undefined
  entities: DataEntity[]
  tools: Tool[]
  agentName: string
  agentDescription: string
  agentInstruction: string
  smokeResult: string | null
  publishedVersion: number | null
}

/** The onboarding wizard's live counterpart to its step forms — instead of
 * a plain progress bar, this renders the actual agent visibly assembling
 * itself as each step completes: name/description fade in, an access
 * badge clips on, entity/tool chips fly in one by one, the instruction
 * fills the card, and publish plays a one-shot "it's alive" animation.
 * Purely presentational — every prop is wizard state already collected by
 * useNewDomainWizard, nothing here calls the API. Animations are plain CSS
 * (see the canvas-* keyframes in src/index.css), no animation library. */
export default function LivingAgentCanvas({
  domainName,
  domainDescription,
  policy,
  entities,
  tools,
  agentName,
  agentDescription,
  agentInstruction,
  smokeResult,
  publishedVersion,
}: LivingAgentCanvasProps) {
  const hasStarted = domainName.trim().length > 0
  const hasAccess = policy !== undefined // undefined = not decided yet; null = explicitly skipped
  const hasEntities = entities.length > 0
  const hasTools = tools.length > 0
  const hasAgent = agentName.trim().length > 0
  const hasInstruction = agentInstruction.trim().length > 0
  const isPublished = publishedVersion !== null

  // One-shot particle burst the moment publish succeeds — never replayed on
  // a later re-render (e.g. switching steps back and forth) since it's
  // gated on the FALSE -> TRUE transition, not just "is published".
  const [justPublished, setJustPublished] = useState(false)
  const wasPublished = useRef(false)
  useEffect(() => {
    if (isPublished && !wasPublished.current) {
      setJustPublished(true)
      const timer = setTimeout(() => setJustPublished(false), 900)
      wasPublished.current = true
      return () => clearTimeout(timer)
    }
    wasPublished.current = isPublished
  }, [isPublished])

  const burstParticles = useMemo(
    () =>
      Array.from({ length: 10 }, (_, i) => {
        const angle = (i / 10) * Math.PI * 2
        const distance = 46 + Math.random() * 28
        return { dx: Math.cos(angle) * distance, dy: Math.sin(angle) * distance, delay: i * 18 }
      }),
    [],
  )

  return (
    <div className="sticky top-4">
      <Card className={`relative overflow-hidden ${isPublished ? 'animate-canvas-launch' : ''}`}>
        {justPublished && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center" aria-hidden="true">
            {burstParticles.map((p, i) => (
              <span
                key={i}
                className="animate-canvas-burst absolute h-1.5 w-1.5 rounded-full bg-gradient-to-r from-brand-500 to-accent-500"
                style={
                  {
                    '--burst-x': `${p.dx}px`,
                    '--burst-y': `${p.dy}px`,
                    animationDelay: `${p.delay}ms`,
                  } as React.CSSProperties
                }
              />
            ))}
          </div>
        )}

        <div className="flex items-center gap-3">
          <div
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-white transition-colors duration-500 ${
              hasAgent
                ? `bg-gradient-to-br from-brand-500 to-accent-500 ${!isPublished && hasInstruction ? 'animate-canvas-glow' : ''}`
                : 'animate-pulse border-2 border-dashed border-slate-300 text-slate-300 dark:border-slate-700 dark:text-slate-700'
            }`}
          >
            <Bot size={22} />
          </div>
          <div className="min-w-0 flex-1">
            {hasStarted ? (
              <h3
                key={agentName || domainName}
                className="animate-canvas-reveal truncate font-semibold text-slate-900 dark:text-slate-100"
              >
                {agentName || domainName}
              </h3>
            ) : (
              <h3 className="text-sm text-slate-300 dark:text-slate-700">Your agent…</h3>
            )}
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">
              {agentDescription || domainDescription || 'A description will appear here'}
            </p>
          </div>
          {isPublished && (
            <span className="animate-canvas-reveal shrink-0 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400">
              ● Live
            </span>
          )}
        </div>

        {hasAccess && (
          <div className="animate-canvas-reveal mt-4 flex items-center gap-1.5 text-xs">
            <ShieldCheck size={13} className="shrink-0 text-brand-500" />
            {policy ? (
              <span className="text-slate-600 dark:text-slate-300">
                Scoped by <strong>{policy.name}</strong>
              </span>
            ) : (
              <span className="text-slate-400">No access restrictions — every user sees all data</span>
            )}
          </div>
        )}

        {hasEntities && (
          <div className="mt-4">
            <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Data entities</div>
            <div className="space-y-1.5">
              {entities.map((e, i) => (
                <div
                  key={e.id}
                  className="animate-canvas-reveal rounded-md border border-slate-200 bg-slate-50/60 px-2.5 py-1.5 dark:border-slate-800 dark:bg-slate-900/40"
                  style={{ animationDelay: `${i * 90}ms` }}
                >
                  <div className="flex items-center gap-1.5 text-xs font-medium text-slate-700 dark:text-slate-200">
                    <Table2 size={12} className="shrink-0" /> {e.name}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {e.fields.slice(0, 4).map((f) => (
                      <span
                        key={f.name}
                        className="rounded bg-white px-1.5 py-0.5 text-[10px] text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                      >
                        {f.label || f.name}
                      </span>
                    ))}
                    {e.fields.length > 4 && (
                      <span className="text-[10px] text-slate-400">+{e.fields.length - 4} more</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {hasTools && (
          <div className="mt-4">
            <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Tools attached</div>
            <div className="flex flex-wrap gap-1.5">
              {tools.map((t, i) => (
                <span
                  key={t.id}
                  className="animate-canvas-reveal flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 dark:border-brand-900 dark:bg-brand-950 dark:text-brand-300"
                  style={{ animationDelay: `${i * 90}ms` }}
                >
                  <Wrench size={11} /> {t.name}
                </span>
              ))}
            </div>
          </div>
        )}

        {hasInstruction && (
          <div className="animate-canvas-reveal mt-4">
            <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">Instructions</div>
            <p className="max-h-24 overflow-y-auto rounded-md bg-slate-50 p-2.5 text-xs leading-relaxed whitespace-pre-wrap text-slate-600 dark:bg-slate-900/40 dark:text-slate-300">
              {agentInstruction}
            </p>
          </div>
        )}

        {smokeResult && !isPublished && (
          <div className="animate-canvas-reveal mt-4 flex items-center gap-1.5 rounded-md bg-emerald-50 px-2.5 py-1.5 text-xs text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400">
            <CheckCircle2 size={13} className="shrink-0" /> Verified with a real query — not a guess
          </div>
        )}

        {!hasStarted && (
          <p className="mt-3 text-xs text-slate-400">
            Fill in the form and watch your agent take shape here.
          </p>
        )}
      </Card>
    </div>
  )
}
