import { useState } from 'react'
import { Users } from 'lucide-react'
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
import { getStoredRole, getUserEmail } from '../../lib/auth'
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

  return (
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
  )
}
