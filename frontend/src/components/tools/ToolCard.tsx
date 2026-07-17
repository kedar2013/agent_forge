import { useState } from 'react'
import { toast } from 'sonner'
import { useDeleteTool } from '../../api/tools'
import type { Tool } from '../../api/types'
import { TOOL_TYPE_TONE } from '../../lib/badgeTones'
import Badge from '../ui/Badge'
import ConfirmDialog from '../ui/ConfirmDialog'
import EntityCard from '../ui/EntityCard'
import Modal from '../ui/Modal'
import ToolForm from './ToolForm'

export default function ToolCard({ tool, compact = false }: { tool: Tool; compact?: boolean }) {
  const deleteTool = useDeleteTool()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)

  function handleDelete() {
    deleteTool.mutate(tool.id, {
      onSuccess: () => toast.success(`Tool "${tool.name}" deleted`),
      onError: (err) => toast.error((err as Error).message),
    })
    setConfirmDelete(false)
  }

  return (
    <>
      <EntityCard
        title={tool.name}
        badges={<Badge tone={TOOL_TYPE_TONE[tool.tool_type]}>{tool.tool_type}</Badge>}
        description={tool.description || undefined}
        meta={`Updated ${new Date(tool.updated_at).toLocaleDateString()}`}
        compact={compact}
        onEdit={() => setEditing(true)}
        onDelete={() => setConfirmDelete(true)}
        entityLabel="tool"
      />

      <Modal open={editing} onClose={() => setEditing(false)} title={`Edit "${tool.name}"`} maxWidth="max-w-xl">
        <ToolForm tool={tool} onDone={() => setEditing(false)} />
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete tool?"
        message={`"${tool.name}" will be permanently deleted. Any agent it's attached to will lose it.`}
        confirmLabel="Delete"
        danger
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  )
}
