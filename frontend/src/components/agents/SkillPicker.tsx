import { useState } from 'react'
import { useSkills } from '../../api/skills'

export default function SkillPicker({
  attachedIds,
  onAttach,
}: {
  attachedIds: string[]
  onAttach: (skillId: string) => void
}) {
  const { data: allSkills } = useSkills()
  const [picking, setPicking] = useState(false)
  const attachedSet = new Set(attachedIds)
  const available = (allSkills ?? []).filter((s) => !attachedSet.has(s.id))

  return (
    <div>
      <button
        type="button"
        onClick={() => setPicking((p) => !p)}
        className="text-xs font-medium text-brand-600 hover:underline"
      >
        {picking ? 'close' : '+ attach skill'}
      </button>
      {picking && (
        <div className="mt-2 max-h-40 space-y-1 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-800">
          {available.length === 0 && <p className="text-xs text-slate-500">No more skills to attach.</p>}
          {available.map((skill) => (
            <button
              key={skill.id}
              type="button"
              onClick={() => {
                onAttach(skill.id)
                setPicking(false)
              }}
              className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              {skill.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
