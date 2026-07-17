import { useState } from 'react'
import { toast } from 'sonner'
import { useDeleteSkill } from '../../api/skills'
import type { Skill } from '../../api/types'
import Badge from '../ui/Badge'
import ConfirmDialog from '../ui/ConfirmDialog'
import EntityCard from '../ui/EntityCard'
import Modal from '../ui/Modal'
import SkillForm from './SkillForm'

export default function SkillCard({ skill, compact = false }: { skill: Skill; compact?: boolean }) {
  const deleteSkill = useDeleteSkill()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)

  function handleDelete() {
    deleteSkill.mutate(skill.id, {
      onSuccess: () => toast.success(`Skill "${skill.name}" deleted`),
      onError: (err) => toast.error((err as Error).message),
    })
    setConfirmDelete(false)
  }

  const badges = compact ? (
    <div className="hidden flex-wrap items-center gap-1 sm:flex">
      {(skill.tags ?? []).slice(0, 2).map((tag) => (
        <Badge key={tag} tone="violet">
          {tag}
        </Badge>
      ))}
    </div>
  ) : (
    <div className="flex flex-wrap items-center gap-1">
      {(skill.tags ?? []).map((tag) => (
        <Badge key={tag} tone="violet">
          {tag}
        </Badge>
      ))}
      {!!skill.few_shot_examples?.length && (
        <Badge tone="neutral">
          {skill.few_shot_examples.length} example{skill.few_shot_examples.length === 1 ? '' : 's'}
        </Badge>
      )}
    </div>
  )

  return (
    <>
      <EntityCard
        title={skill.name}
        badges={badges}
        description={skill.instruction_text || undefined}
        meta={`Updated ${new Date(skill.updated_at).toLocaleDateString()}`}
        compact={compact}
        onEdit={() => setEditing(true)}
        onDelete={() => setConfirmDelete(true)}
        entityLabel="skill"
      />

      <Modal open={editing} onClose={() => setEditing(false)} title={`Edit "${skill.name}"`} maxWidth="max-w-xl">
        <SkillForm skill={skill} onDone={() => setEditing(false)} />
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete skill?"
        message={`"${skill.name}" will be permanently deleted. Any agent it's attached to will lose it.`}
        confirmLabel="Delete"
        danger
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  )
}
