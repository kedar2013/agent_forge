import { ArrowRight, Check, Plus } from 'lucide-react'
import type { DataEntity } from '../../../api/types'
import DataEntityForm from '../../../components/dataEntities/DataEntityForm'
import Button from '../../../components/ui/Button'
import Card from '../../../components/ui/Card'

export interface EntitiesStepProps {
  entities: DataEntity[]
  addingEntity: boolean
  onEntityCreated: (e: DataEntity) => void
  onEntityFormDone: () => void
  onAddAnother: () => void
  onNext: () => void
  canAdvance: boolean
}

export default function EntitiesStep({
  entities,
  addingEntity,
  onEntityCreated,
  onEntityFormDone,
  onAddAnother,
  onNext,
  canAdvance,
}: EntitiesStepProps) {
  return (
    <Card padding="lg" className="space-y-6">
      <h2 className="text-lg font-semibold">Data entities</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        The data dictionary for one table — pick a connection, pick a table, and the columns are read, labelled,
        and tagged for you. Add one entity per table this domain should query.
      </p>

      {entities.length > 0 && (
        <ul className="space-y-1">
          {entities.map((e) => (
            <li
              key={e.id}
              className="flex items-center gap-2 rounded border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800"
            >
              <Check size={14} className="text-emerald-500" />
              <span className="font-medium">{e.name}</span>
              <span className="text-xs text-slate-400">
                {e.source.table || e.source.collection} · {e.fields.length} fields
              </span>
            </li>
          ))}
        </ul>
      )}

      {addingEntity ? (
        <div className="rounded border border-slate-200 p-3 dark:border-slate-700">
          <DataEntityForm onCreated={onEntityCreated} onDone={onEntityFormDone} />
        </div>
      ) : (
        <Button variant="outline" tone="neutral" size="xs" onClick={onAddAnother} leftIcon={<Plus size={13} />}>
          Add another data entity
        </Button>
      )}

      <div className="flex justify-end pt-2">
        <Button disabled={!canAdvance} onClick={onNext} rightIcon={<ArrowRight size={15} />}>
          Next
        </Button>
      </div>
    </Card>
  )
}
