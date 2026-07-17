import type { MouseEvent, ReactNode } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import Button from './Button'
import Card from './Card'

export interface EntityCardProps {
  title: string
  /** An <EntityAvatar> — optional so AccessPolicy/DataEntity cards (which
   * don't pass one) render exactly as before; Tool/Skill cards opt in. */
  avatar?: ReactNode
  /** Row of <Badge> elements. */
  badges?: ReactNode
  description?: ReactNode
  /** Footer text in full mode, trailing text in compact mode — e.g. "Updated Jan 2, 2026". */
  meta?: ReactNode
  compact?: boolean
  /** Opens the entity for editing — also fired by clicking the card itself. */
  onEdit: () => void
  onDelete: () => void
  /** Noun used in action aria-labels, e.g. "tool" → "Edit tool" / "Delete tool". */
  entityLabel: string
}

/** Generic "list item" card: title, badges, description, meta footer, and
 * edit/delete actions. Shared visual shell for Tool/Skill/AccessPolicy/
 * DataEntity cards — each of those still owns its own state (which
 * modal/confirm-dialog is open) and delete mutation; this component is
 * rendering only. */
export default function EntityCard({
  title,
  avatar,
  badges,
  description,
  meta,
  compact = false,
  onEdit,
  onDelete,
  entityLabel,
}: EntityCardProps) {
  function stop(e: MouseEvent, fn: () => void) {
    e.stopPropagation()
    fn()
  }

  const actionButtons = (
    <>
      <Button
        variant="ghost"
        tone="neutral"
        size="icon"
        onClick={(e) => stop(e, onEdit)}
        aria-label={`Edit ${entityLabel}`}
      >
        <Pencil size={15} />
      </Button>
      <Button
        variant="ghost"
        tone="danger"
        size="icon"
        onClick={(e) => stop(e, onDelete)}
        aria-label={`Delete ${entityLabel}`}
      >
        <Trash2 size={15} />
      </Button>
    </>
  )

  if (compact) {
    return (
      <Card hover onClick={onEdit} className="group flex items-center gap-3 py-2.5">
        {avatar}
        <span className="truncate text-sm font-semibold text-slate-900 group-hover:text-brand-600 dark:text-slate-100 dark:group-hover:text-brand-400">
          {title}
        </span>
        {badges}
        {meta && <span className="ml-auto shrink-0 text-xs text-slate-400">{meta}</span>}
        <div className="flex shrink-0 items-center gap-1">{actionButtons}</div>
      </Card>
    )
  }

  return (
    <Card hover onClick={onEdit} className="group flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          {avatar}
          <h3 className="truncate font-semibold text-slate-900 group-hover:text-brand-600 dark:text-slate-100 dark:group-hover:text-brand-400">
            {title}
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">{actionButtons}</div>
      </div>
      {badges && <div className="flex items-center gap-2">{badges}</div>}
      <p className="line-clamp-2 min-h-[2.5rem] text-sm text-slate-500 dark:text-slate-400">
        {description || <span className="italic text-slate-400">No description</span>}
      </p>
      {meta && <div className="border-t border-slate-100 pt-2 text-xs text-slate-400 dark:border-slate-800">{meta}</div>}
    </Card>
  )
}
