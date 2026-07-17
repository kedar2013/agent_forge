import { useState } from 'react'
import { UserPlus, X } from 'lucide-react'
import { ApiError } from '../../api/client'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Modal from '../ui/Modal'
import { Skeleton } from '../ui/Skeleton'

interface CollaboratorEntry {
  user_email: string
  added_by: string | null
  created_at: string
}

interface CollaboratorMutation {
  mutate: (email: string, opts?: { onSuccess?: () => void; onError?: (err: unknown) => void }) => void
  isPending: boolean
}

/** Shared by AgentBuilderPage and SkillsPage — the shape (list + add-by-email
 * + remove) and the backend contract (GET/POST/DELETE .../collaborators) are
 * identical for both resource types, see config_api/agents.py and
 * config_api/skills.py's "Collaborators" sections. Only the resource's own
 * creator or an admin ever sees the button that opens this (enforced by the
 * caller, not this component) — someone merely added as a collaborator can't
 * grant that same access to anyone else. */
export default function ManageCollaboratorsModal({
  resourceLabel,
  collaborators,
  isLoading,
  addMutation,
  onRemove,
  onClose,
}: {
  resourceLabel: string
  collaborators: CollaboratorEntry[] | undefined
  isLoading: boolean
  addMutation: CollaboratorMutation
  onRemove: (email: string) => void
  onClose: () => void
}) {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)

  function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = email.trim()
    if (!trimmed) return
    setError(null)
    addMutation.mutate(trimmed, {
      onSuccess: () => setEmail(''),
      onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not add that collaborator.'),
    })
  }

  return (
    <Modal open onClose={onClose} title="Manage collaborators" maxWidth="max-w-md">
      <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">
        Anyone added here can edit this {resourceLabel} just like you can, without becoming its owner. Only
        you (or an admin) can add or remove collaborators.
      </p>

      {isLoading ? (
        <Skeleton className="h-16" />
      ) : !collaborators?.length ? (
        <p className="mb-3 text-xs text-slate-400">No collaborators yet.</p>
      ) : (
        <ul className="mb-3 space-y-1.5">
          {collaborators.map((c) => (
            <li
              key={c.user_email}
              className="flex items-center justify-between rounded-md bg-slate-50 px-2.5 py-1.5 text-sm dark:bg-slate-800"
            >
              <span className="truncate">{c.user_email}</span>
              <button
                type="button"
                onClick={() => onRemove(c.user_email)}
                className="ml-2 shrink-0 text-slate-400 hover:text-red-600 dark:hover:text-red-400"
                title="Remove collaborator"
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleAdd} className="flex items-end gap-2">
        <div className="flex-1">
          <Input
            label="Add by email"
            hideLabel={false}
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              setError(null)
            }}
            placeholder="colleague@company.com"
          />
        </div>
        <Button
          type="submit"
          size="sm"
          isPending={addMutation.isPending}
          disabled={!email.trim()}
          leftIcon={<UserPlus size={14} />}
        >
          Add
        </Button>
      </form>
      {error && <p className="mt-1.5 text-xs text-red-600">{error}</p>}
    </Modal>
  )
}
