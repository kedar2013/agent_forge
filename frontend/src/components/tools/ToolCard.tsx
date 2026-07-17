import { Wrench } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { useDeleteTool } from '../../api/tools'
import type { Tool } from '../../api/types'
import { TOOL_TYPE_ICON, TOOL_TYPE_TONE } from '../../lib/badgeTones'
import Badge from '../ui/Badge'
import ConfirmDialog from '../ui/ConfirmDialog'
import EntityAvatar from '../ui/EntityAvatar'
import EntityCard from '../ui/EntityCard'
import Modal from '../ui/Modal'
import ToolForm from './ToolForm'

export default function ToolCard({ tool, compact = false }: { tool: Tool; compact?: boolean }) {
  const deleteTool = useDeleteTool()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  // Falls back gracefully if the backend ever serves a tool_type this build
  // doesn't know about yet, rather than crashing the whole list.
  const icon = TOOL_TYPE_ICON[tool.tool_type] ?? Wrench
  const tone = TOOL_TYPE_TONE[tool.tool_type] ?? 'neutral'

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
        avatar={<EntityAvatar icon={icon} tone={tone} size={compact ? 28 : 40} />}
        badges={<Badge tone={tone}>{tool.tool_type}</Badge>}
        description={tool.description || undefined}
        meta={`Updated ${new Date(tool.updated_at).toLocaleDateString()}`}
        compact={compact}
        onEdit={() => setEditing(true)}
        onDelete={() => setConfirmDelete(true)}
        entityLabel="tool"
      />

      <Modal open={editing} onClose={() => setEditing(false)} title={`Edit "${tool.name}"`} maxWidth="max-w-3xl">
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
