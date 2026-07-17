import { ChevronDown, ChevronRight, History } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { useAgentVersions, useRollbackAgent } from '../../api/agents'
import type { Agent, AgentVersion } from '../../api/types'
import ConfirmDialog from '../ui/ConfirmDialog'
import VersionDiff, { hasSnapshotChanges, type SnapshotLike } from './VersionDiff'

function agentAsSnapshot(agent: Agent): SnapshotLike {
  return {
    name: agent.name,
    description: agent.description,
    base_instruction: agent.base_instruction,
    model_config: agent.model_config,
    output_schema: agent.output_schema,
    output_key: agent.output_key,
    tools: agent.tools.map((t) => ({ id: t.id, name: t.name })),
    skills: agent.skills.map((s) => ({ id: s.id, name: s.name })),
    sub_agents: agent.sub_agents.map((s) => ({ id: s.id, name: s.name })),
  }
}

export default function VersionHistory({ agent }: { agent: Agent }) {
  const { data: versions, isLoading } = useAgentVersions(agent.id)
  const rollbackAgent = useRollbackAgent(agent.id)
  const [pendingVersion, setPendingVersion] = useState<AgentVersion | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  function toggle(version: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(version)) next.delete(version)
      else next.add(version)
      return next
    })
  }

  async function handleRollback(version: AgentVersion) {
    try {
      const result = await rollbackAgent.mutateAsync(version.version)
      toast.success(`Rolled back to v${version.version}, published as v${result.version}`)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setPendingVersion(null)
    }
  }

  if (isLoading) return <p className="text-sm text-slate-500">Loading versions…</p>
  if (!versions?.length) return <p className="text-sm text-slate-500">No published versions yet.</p>

  const sorted = versions.slice().sort((a, b) => b.version - a.version)
  const liveSnapshot = agentAsSnapshot(agent)
  const currentPublished = sorted.find((v) => v.version === agent.current_version) ?? null
  const draftHasChanges = currentPublished ? hasSnapshotChanges(currentPublished.snapshot, liveSnapshot) : false

  return (
    <>
      {draftHasChanges && currentPublished && (
        <div className="mb-4 rounded-md border border-amber-300/70 bg-amber-50 p-3 dark:border-amber-500/30 dark:bg-amber-950/30">
          <div className="mb-2 text-xs font-semibold text-amber-800 dark:text-amber-300">
            Unpublished changes since v{currentPublished.version}
          </div>
          <VersionDiff before={currentPublished.snapshot} after={liveSnapshot} />
        </div>
      )}

      <div className="space-y-2">
        {sorted.map((v, i) => {
          const previous = sorted[i + 1] ?? null
          const isExpanded = expanded.has(v.version)
          const isCurrent = v.version === agent.current_version

          return (
            <div key={v.id} className="rounded-md border border-slate-200 text-sm dark:border-slate-800">
              <div className="flex items-center justify-between px-3 py-2">
                <button
                  type="button"
                  onClick={() => toggle(v.version)}
                  className="flex items-center gap-1.5 text-left"
                >
                  {isExpanded ? (
                    <ChevronDown size={14} className="text-slate-400" />
                  ) : (
                    <ChevronRight size={14} className="text-slate-400" />
                  )}
                  <span className="font-medium">v{v.version}</span>
                  {isCurrent && (
                    <span className="rounded-full bg-brand-100 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700 dark:bg-brand-900/40 dark:text-brand-300">
                      current
                    </span>
                  )}
                  <span className="text-slate-500">
                    published {new Date(v.published_at).toLocaleString()}
                    {v.published_by ? ` by ${v.published_by}` : ''}
                  </span>
                </button>
                {!isCurrent && (
                  <button
                    type="button"
                    onClick={() => setPendingVersion(v)}
                    className="shrink-0 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                  >
                    Roll back to this version
                  </button>
                )}
              </div>
              {isExpanded && (
                <div className="border-t border-slate-200 px-3 py-2.5 dark:border-slate-800">
                  <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                    <History size={12} /> Changes vs. {previous ? `v${previous.version}` : 'nothing (initial version)'}
                  </div>
                  <VersionDiff before={previous?.snapshot ?? null} after={v.snapshot} />
                </div>
              )}
            </div>
          )
        })}
      </div>

      <ConfirmDialog
        open={pendingVersion !== null}
        title={`Roll back to version ${pendingVersion?.version}?`}
        message="Restores the draft to look like that version, then publishes it as a brand-new version — nothing in the history is deleted or overwritten. Tools or skills that version used but have since been deleted are simply skipped."
        confirmLabel={rollbackAgent.isPending ? 'Rolling back…' : 'Roll back'}
        maxWidth="max-w-2xl"
        onConfirm={() => pendingVersion && handleRollback(pendingVersion)}
        onCancel={() => setPendingVersion(null)}
      >
        {pendingVersion && (
          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
              What this would change, right now
            </div>
            <VersionDiff before={liveSnapshot} after={pendingVersion.snapshot} />
          </div>
        )}
      </ConfirmDialog>
    </>
  )
}
