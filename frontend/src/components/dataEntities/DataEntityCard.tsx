import { useState } from 'react'
import { toast } from 'sonner'
import { useDeleteDataEntity } from '../../api/dataEntities'
import type { DataEntity } from '../../api/types'
import Badge from '../ui/Badge'
import ConfirmDialog from '../ui/ConfirmDialog'
import EntityCard from '../ui/EntityCard'
import Modal from '../ui/Modal'
import DataEntityForm from './DataEntityForm'

export default function DataEntityCard({ entity }: { entity: DataEntity }) {
  const deleteEntity = useDeleteDataEntity()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)

  function handleDelete() {
    deleteEntity.mutate(entity.id, {
      onSuccess: () => toast.success(`Data entity "${entity.name}" deleted`),
      onError: (err) => toast.error((err as Error).message),
    })
    setConfirmDelete(false)
  }

  const table = entity.source.table || entity.source.collection || '?'

  return (
    <>
      <EntityCard
        title={entity.name}
        entityLabel="data entity"
        onEdit={() => setEditing(true)}
        onDelete={() => setConfirmDelete(true)}
        badges={
          <>
            <Badge tone={entity.connection.type === 'mysql' ? 'info' : 'success'}>{entity.connection.type}</Badge>
            <Badge tone="neutral">{table}</Badge>
            <Badge tone="neutral">{entity.fields.length} field{entity.fields.length === 1 ? '' : 's'}</Badge>
          </>
        }
        description={entity.description}
        meta={`Updated ${new Date(entity.updated_at).toLocaleDateString()}`}
      />

      <Modal open={editing} onClose={() => setEditing(false)} title={`Edit "${entity.name}"`} maxWidth="max-w-3xl">
        <DataEntityForm entity={entity} onDone={() => setEditing(false)} />
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete data entity?"
        message={`"${entity.name}" will be permanently deleted. Any data_query_tool built from it will stop working until re-pointed at another entity.`}
        confirmLabel="Delete"
        danger
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  )
}
