import { useState } from 'react'
import { useTools } from '../../api/tools'
import type { AttachedTool } from '../../api/types'

export default function ToolAttachPanel({
  attached,
  onAttach,
  onDetach,
}: {
  attached: AttachedTool[]
  onAttach: (toolId: string) => void
  onDetach: (toolId: string) => void
}) {
  const { data: allTools } = useTools()
  const [picking, setPicking] = useState(false)

  const attachedIds = new Set(attached.map((t) => t.id))
  const available = (allTools ?? []).filter((t) => !attachedIds.has(t.id))

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Tools</span>
        <button
          type="button"
          onClick={() => setPicking((p) => !p)}
          className="text-xs font-medium text-brand-600 hover:underline"
        >
          {picking ? 'close' : '+ attach tool'}
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {attached.length === 0 && <span className="text-xs text-slate-500">none attached</span>}
        {attached.map((tool) => (
          <span
            key={tool.id}
            className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800"
          >
            <code>{tool.tool_type}</code>: {tool.name}
            <button
              type="button"
              onClick={() => onDetach(tool.id)}
              className="ml-1 text-slate-500 hover:text-red-600"
              aria-label={`Detach ${tool.name}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>

      {picking && (
        <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-800">
          {available.length === 0 && <p className="text-xs text-slate-500">No more tools to attach.</p>}
          {available.map((tool) => (
            <button
              key={tool.id}
              type="button"
              onClick={() => {
                onAttach(tool.id)
                setPicking(false)
              }}
              className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <code>{tool.tool_type}</code> — {tool.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
