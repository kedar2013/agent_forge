import { useState } from 'react'
import { toast } from 'sonner'
import { useDeleteAccessPolicy } from '../../api/accessPolicies'
import type { AccessPolicy } from '../../api/types'
import Badge from '../ui/Badge'
import ConfirmDialog from '../ui/ConfirmDialog'
import EntityCard from '../ui/EntityCard'
import Modal from '../ui/Modal'
import AccessPolicyForm from './AccessPolicyForm'

export default function AccessPolicyCard({ policy }: { policy: AccessPolicy }) {
  const deletePolicy = useDeleteAccessPolicy()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)

  function handleDelete() {
    deletePolicy.mutate(policy.id, {
      onSuccess: () => toast.success(`Access policy "${policy.name}" deleted`),
      onError: (err) => toast.error((err as Error).message),
    })
    setConfirmDelete(false)
  }

  const personaCount = Object.keys(policy.rules).length

  return (
    <>
      <EntityCard
        title={policy.name}
        entityLabel="access policy"
        onEdit={() => setEditing(true)}
        onDelete={() => setConfirmDelete(true)}
        badges={
          <>
            <Badge tone={policy.resolver_config.type === 'mysql' ? 'info' : 'success'}>
              {policy.resolver_config.type}
            </Badge>
            <Badge tone="neutral">{personaCount} persona{personaCount === 1 ? '' : 's'}</Badge>
          </>
        }
        description={policy.description}
        meta={`Updated ${new Date(policy.updated_at).toLocaleDateString()}`}
      />

      <Modal open={editing} onClose={() => setEditing(false)} title={`Edit "${policy.name}"`} maxWidth="max-w-2xl">
        <AccessPolicyForm policy={policy} onDone={() => setEditing(false)} />
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete access policy?"
        message={`"${policy.name}" will be permanently deleted. Any tool referencing it will stop enforcing row-level access.`}
        confirmLabel="Delete"
        danger
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  )
}
