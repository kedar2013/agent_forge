import { useState } from 'react'
import { useAgents } from '../../api/agents'
import type { AttachedSubagent } from '../../api/types'

export default function SubAgentAttachPanel({
  currentAgentId,
  attached,
  onAttach,
  onDetach,
}: {
  currentAgentId: string
  attached: AttachedSubagent[]
  onAttach: (agentId: string) => void
  onDetach: (agentId: string) => void
}) {
  const { data: allAgents } = useAgents()
  const [picking, setPicking] = useState(false)

  const attachedIds = new Set(attached.map((a) => a.id))
  const available = (allAgents ?? []).filter(
    (a) => a.status === 'published' && a.id !== currentAgentId && !attachedIds.has(a.id),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Sub-agents</span>
        <button
          type="button"
          onClick={() => setPicking((p) => !p)}
          className="text-xs font-medium text-brand-600 hover:underline"
        >
          {picking ? 'close' : '+ attach sub-agent'}
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {attached.length === 0 && <span className="text-xs text-slate-500">none attached</span>}
        {attached.map((sub) => (
          <span
            key={sub.id}
            className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800"
          >
            {sub.name}
            <button
              type="button"
              onClick={() => onDetach(sub.id)}
              className="ml-1 text-slate-500 hover:text-red-600"
              aria-label={`Detach ${sub.name}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>

      {picking && (
        <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-800">
          {available.length === 0 && (
            <p className="text-xs text-slate-500">No published agents available to delegate to.</p>
          )}
          {available.map((agent) => (
            <button
              key={agent.id}
              type="button"
              onClick={() => {
                onAttach(agent.id)
                setPicking(false)
              }}
              className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              {agent.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
