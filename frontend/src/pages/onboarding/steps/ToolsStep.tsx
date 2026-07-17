import { ArrowRight, Check, Database, Plus } from 'lucide-react'
import type { DataEntity, Tool } from '../../../api/types'
import Button from '../../../components/ui/Button'
import Card from '../../../components/ui/Card'

export interface ToolsStepProps {
  entities: DataEntity[]
  tools: Tool[]
  isCreatingTools: boolean
  onCreateAllTools: () => void
  onNext: () => void
  canAdvance: boolean
}

export default function ToolsStep({ entities, tools, isCreatingTools, onCreateAllTools, onNext, canAdvance }: ToolsStepProps) {
  const allCreated = entities.every((e) => tools.some((t) => t.config.entity_id === e.id))
  return (
    <Card padding="lg" className="space-y-6">
      <h2 className="text-lg font-semibold">Tools</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        One <code>data_query_tool</code> per entity, scoped to the access policy from step 2. The schema
        description the LLM reads and the input contract are generated from your data dictionary.
      </p>

      <Button
        onClick={onCreateAllTools}
        isPending={isCreatingTools}
        disabled={allCreated}
        loadingLabel="Creating…"
        leftIcon={<Plus size={15} />}
      >
        Create {entities.length > 1 ? 'all ' : ''}query tool{entities.length > 1 ? 's' : ''}
      </Button>

      <div className="space-y-2">
        {entities.map((entity) => {
          const created = tools.some((t) => t.config.entity_id === entity.id)
          return (
            <div
              key={entity.id}
              className="flex items-center justify-between rounded border border-slate-100 px-3 py-2 dark:border-slate-800"
            >
              <div className="flex items-center gap-2 text-sm">
                <Database size={14} className="text-slate-400" />
                <span className="font-medium">{entity.name}</span>
                <span className="text-xs text-slate-400">→ query_{entity.name}</span>
              </div>
              {created ? (
                <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                  <Check size={13} /> created
                </span>
              ) : (
                <span className="text-xs text-slate-400">pending</span>
              )}
            </div>
          )
        })}
      </div>

      <div className="flex justify-end pt-2">
        <Button disabled={!canAdvance} onClick={onNext} rightIcon={<ArrowRight size={15} />}>
          Next
        </Button>
      </div>
    </Card>
  )
}
