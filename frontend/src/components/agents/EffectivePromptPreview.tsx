import { ClipboardCheck, Eye } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { AttachedSkill } from '../../api/types'

/**
 * Mirrors backend/app/agent_runtime/builder.py:compose_instruction exactly —
 * base_instruction followed by each attached skill's instruction_text in
 * attach_order, separated by a "// skill: <name>" marker. Keep these two in
 * sync; this panel is only useful if it matches what the runtime actually sends.
 */
export default function EffectivePromptPreview({
  baseInstruction,
  skills,
  agentId,
}: {
  baseInstruction: string
  skills: AttachedSkill[]
  /** When provided, shows a shortcut into the System Prompt Evaluator
   * pre-selecting this agent — omit for contexts with no real agent yet
   * (e.g. a not-yet-saved draft). */
  agentId?: string
}) {
  const ordered = [...skills].sort((a, b) => a.attach_order - b.attach_order)

  return (
    <div className="rounded-[--radius-card] border border-slate-200 bg-white shadow-[--shadow-card] dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between gap-1.5 border-b border-slate-200 px-3 py-2 text-sm font-medium dark:border-slate-800">
        <span className="flex items-center gap-1.5">
          <Eye size={15} className="text-slate-400" /> Effective prompt preview
        </span>
        {agentId && (
          <Link
            to={`/prompt-evaluator?agent=${agentId}`}
            className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400"
          >
            <ClipboardCheck size={13} /> Evaluate prompt
          </Link>
        )}
      </div>
      <div className="max-h-[32rem] overflow-y-auto p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        <div>{baseInstruction || <span className="text-slate-400">(no base instruction yet)</span>}</div>
        {ordered.map((skill) => (
          <div key={skill.id} className="mt-3 border-l-2 border-brand-400 pl-3 dark:border-brand-500">
            <div className="mb-1 font-sans text-[11px] font-semibold text-brand-600 dark:text-brand-400">
              // skill: {skill.name}
            </div>
            <div>{skill.instruction_text}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
