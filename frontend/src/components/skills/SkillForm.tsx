import { useState } from 'react'
import { Sparkles, Users } from 'lucide-react'
import { toast } from 'sonner'
import {
  useAddSkillCollaborator,
  useCreateSkill,
  useRemoveSkillCollaborator,
  useSkillCollaborators,
  useUpdateSkill,
} from '../../api/skills'
import type { FewShotExample, Skill } from '../../api/types'
import ManageCollaboratorsModal from '../collaborators/ManageCollaboratorsModal'
import PreviewCardShell from '../creation/PreviewCardShell'
import { getStoredRole, getUserEmail } from '../../lib/auth'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Textarea from '../ui/Textarea'
import FewShotEditor from './FewShotEditor'

export default function SkillForm({ skill, onDone }: { skill?: Skill; onDone: () => void }) {
  const [name, setName] = useState(skill?.name ?? '')
  const [instructionText, setInstructionText] = useState(skill?.instruction_text ?? '')
  const [tags, setTags] = useState((skill?.tags ?? []).join(', '))
  const [examples, setExamples] = useState<FewShotExample[]>(skill?.few_shot_examples ?? [])
  const createSkill = useCreateSkill()
  const updateSkill = useUpdateSkill()
  const isEditing = !!skill
  const pending = createSkill.isPending || updateSkill.isPending

  const [showCollaborators, setShowCollaborators] = useState(false)
  const { data: collaborators, isLoading: collaboratorsLoading } = useSkillCollaborators(
    showCollaborators ? skill?.id : undefined,
  )
  const addCollaborator = useAddSkillCollaborator(skill?.id ?? '')
  const removeCollaborator = useRemoveSkillCollaborator(skill?.id ?? '')
  // Same rule as AgentBuilderPage: only the skill's creator (or an admin)
  // manages who else can edit it — see config_api/skills.py's _require_is_owner.
  const canManageAccess = isEditing && (getStoredRole() === 'admin' || skill.created_by === getUserEmail())

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const input = {
      name,
      instruction_text: instructionText,
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      few_shot_examples: examples.filter((ex) => ex.input || ex.output),
    }
    const onSuccess = () => {
      toast.success(isEditing ? `Skill "${name}" updated` : `Skill "${name}" created`)
      onDone()
    }
    const onError = (err: unknown) => toast.error((err as Error).message)

    if (isEditing) {
      updateSkill.mutate({ id: skill.id, ...input }, { onSuccess, onError })
    } else {
      createSkill.mutate(input, { onSuccess, onError })
    }
  }

  const tagList = tags.split(',').map((t) => t.trim()).filter(Boolean)

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_240px]">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Name"
          hideLabel={false}
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <Textarea
          label="Instruction text"
          hideLabel={false}
          required
          className="h-32 font-mono"
          value={instructionText}
          onChange={(e) => setInstructionText(e.target.value)}
          placeholder="e.g. Always explain answers using grade-8-level vocabulary and short sentences."
        />

        <Input
          label="Tags (comma-separated)"
          hideLabel={false}
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="formatting, tone"
        />

        <FewShotEditor value={examples} onChange={setExamples} />

        <div className="flex items-center justify-between gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
          {canManageAccess ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              leftIcon={<Users size={14} />}
              onClick={() => setShowCollaborators(true)}
            >
              Manage access
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="outline" tone="neutral" onClick={onDone}>
              Cancel
            </Button>
            <Button type="submit" isPending={pending} loadingLabel="Saving…">
              {isEditing ? 'Save changes' : 'Create skill'}
            </Button>
          </div>
        </div>

        {showCollaborators && skill && (
          <ManageCollaboratorsModal
            resourceLabel="skill"
            collaborators={collaborators}
            isLoading={collaboratorsLoading}
            addMutation={addCollaborator}
            onRemove={(email) => removeCollaborator.mutate(email)}
            onClose={() => setShowCollaborators(false)}
          />
        )}
      </form>

      <PreviewCardShell
        icon={Sparkles}
        isActive={name.trim().length > 0}
        title={name || 'Your skill'}
        emptyHint="Your skill…"
      >
        {tagList.length > 0 && (
          <div className="animate-canvas-reveal mt-4 flex flex-wrap gap-1.5">
            {tagList.map((tag) => (
              <Badge key={tag} tone="violet">
                {tag}
              </Badge>
            ))}
          </div>
        )}
        {instructionText.trim().length > 0 && (
          <div className="animate-canvas-reveal mt-4">
            <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">
              Instructions
            </div>
            <p className="max-h-28 overflow-y-auto rounded-md bg-slate-50 p-2.5 text-xs leading-relaxed whitespace-pre-wrap text-slate-600 dark:bg-slate-900/40 dark:text-slate-300">
              {instructionText}
            </p>
          </div>
        )}
        {examples.some((ex) => ex.input || ex.output) && (
          <p className="animate-canvas-reveal mt-3 text-xs text-slate-500 dark:text-slate-400">
            {examples.filter((ex) => ex.input || ex.output).length} few-shot example
            {examples.filter((ex) => ex.input || ex.output).length === 1 ? '' : 's'}
          </p>
        )}
        {name.trim().length === 0 && (
          <p className="mt-3 text-xs text-slate-400">Fill in the form and watch your skill take shape here.</p>
        )}
      </PreviewCardShell>
    </div>
  )
}
