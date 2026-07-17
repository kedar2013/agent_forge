import { Check, CircleDashed, FlaskConical, Rocket } from 'lucide-react'
import type { AccessPolicy, DataEntity, Tool } from '../../../api/types'
import Button from '../../../components/ui/Button'
import Card from '../../../components/ui/Card'

export interface PublishStepProps {
  policy: AccessPolicy | null | undefined
  entities: DataEntity[]
  tools: Tool[]
  agentName: string
  smokeResult: string | null
  isRunningSmokeTest: boolean
  onRunSmokeTest: () => void
  canPublish: boolean
  isPublishing: boolean
  publishError: boolean
  publishedVersion: number | null
  onPublish: () => void
  onOpenPlayground: () => void
  onOpenAgent: () => void
}

export default function PublishStep({
  policy,
  entities,
  tools,
  agentName,
  smokeResult,
  isRunningSmokeTest,
  onRunSmokeTest,
  canPublish,
  isPublishing,
  publishError,
  publishedVersion,
  onPublish,
  onOpenPlayground,
  onOpenAgent,
}: PublishStepProps) {
  return (
    <Card padding="lg" className="space-y-6">
      <h2 className="text-lg font-semibold">Test &amp; publish</h2>
      <ul className="space-y-2 text-sm">
        <li className="flex items-center gap-2">
          <Check size={14} className="text-emerald-500" /> Access policy:{' '}
          {policy ? <strong>{policy.name}</strong> : <span className="text-slate-400">none (shared visibility)</span>}
        </li>
        <li className="flex items-center gap-2">
          <Check size={14} className="text-emerald-500" /> {entities.length} data entit{entities.length === 1 ? 'y' : 'ies'}:{' '}
          {entities.map((e) => e.name).join(', ')}
        </li>
        <li className="flex items-center gap-2">
          <Check size={14} className="text-emerald-500" /> {tools.length} tool(s): {tools.map((t) => t.name).join(', ')}
        </li>
        <li className="flex items-center gap-2">
          <Check size={14} className="text-emerald-500" /> Agent: <strong>{agentName}</strong>
        </li>
      </ul>

      <div className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium">Smoke test — one real question against your data</span>
          <Button
            variant="outline"
            tone="brand"
            size="xs"
            onClick={onRunSmokeTest}
            isPending={isRunningSmokeTest}
            loadingLabel="Running…"
            leftIcon={<FlaskConical size={13} />}
          >
            {smokeResult ? 'Run again' : 'Run smoke test'}
          </Button>
        </div>
        {smokeResult ? (
          <p className="rounded bg-emerald-50 p-2 text-xs whitespace-pre-wrap text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
            {smokeResult}
          </p>
        ) : (
          <p className="text-xs text-slate-400">
            Runs the draft agent in the playground with a row-count question — proves the connection, tool, and
            policy all work before anything goes live.
          </p>
        )}
      </div>

      {publishedVersion === null ? (
        <Button
          onClick={onPublish}
          disabled={!canPublish}
          isPending={isPublishing}
          loadingLabel="Publishing…"
          rightIcon={<Rocket size={15} />}
          title={canPublish ? undefined : 'Run the smoke test first'}
        >
          Publish
        </Button>
      ) : (
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
            <Check size={15} /> Published as version {publishedVersion}.
          </p>
          <div className="flex gap-2">
            <Button onClick={onOpenPlayground}>Open playground</Button>
            <Button variant="outline" tone="neutral" onClick={onOpenAgent}>
              Open agent
            </Button>
          </div>
        </div>
      )}
      {publishError && (
        <p className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400">
          <CircleDashed size={14} className="mt-0.5 shrink-0" />
          Publish failed — check the error toast. If it mentions a required playground run, the smoke test above
          satisfies it; run it once more and retry.
        </p>
      )}
    </Card>
  )
}
