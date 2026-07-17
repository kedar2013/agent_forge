import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { AttachedSkill } from '../../api/types'

function Row({
  skill,
  index,
  onRemove,
}: {
  skill: AttachedSkill
  index: number
  onRemove: (id: string) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: skill.id,
  })

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`flex items-center gap-2 rounded border border-slate-200 bg-white px-2 py-1.5 text-sm dark:border-slate-800 dark:bg-slate-900 ${
        isDragging ? 'opacity-50' : ''
      }`}
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="cursor-grab touch-none px-1 text-slate-400 active:cursor-grabbing"
        aria-label="Drag to reorder"
      >
        ⠿
      </button>
      <span className="w-6 shrink-0 text-xs text-slate-400">{index}</span>
      <span className="flex-1 truncate">{skill.name}</span>
      <button
        type="button"
        onClick={() => onRemove(skill.id)}
        className="text-xs text-red-600 hover:underline"
      >
        remove
      </button>
    </div>
  )
}

export default function SkillAttachList({
  skills,
  onReorder,
  onRemove,
}: {
  skills: AttachedSkill[]
  onReorder: (newOrderIds: string[]) => void
  onRemove: (skillId: string) => void
}) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const ordered = [...skills].sort((a, b) => a.attach_order - b.attach_order)

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = ordered.findIndex((s) => s.id === active.id)
    const newIndex = ordered.findIndex((s) => s.id === over.id)
    const moved = arrayMove(ordered, oldIndex, newIndex)
    onReorder(moved.map((s) => s.id))
  }

  if (!ordered.length) {
    return <p className="text-sm text-slate-500">No skills attached yet.</p>
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={ordered.map((s) => s.id)} strategy={verticalListSortingStrategy}>
        <div className="space-y-1">
          {ordered.map((skill, i) => (
            <Row key={skill.id} skill={skill} index={i} onRemove={onRemove} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  )
}
