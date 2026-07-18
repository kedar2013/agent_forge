import { useState } from 'react'
import { AlertTriangle, Inbox, PlayCircle, ShieldAlert, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { useCircuitBreakers, useDurableRuns, useResumeDurableRun, type DurableRunEntry } from '../api/reliability'
import Badge, { type BadgeTone } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import LiveBadge from '../components/ui/LiveBadge'
import SegmentedControl from '../components/ui/SegmentedControl'
import { Skeleton } from '../components/ui/Skeleton'

const STATUS_FILTERS = [
  { label: 'All', value: '' },
  { label: 'Running', value: 'running' },
  { label: 'Error', value: 'error' },
  { label: 'Success', value: 'success' },
] as const

const STATUS_TONE: Record<string, BadgeTone> = {
  running: 'info',
  success: 'success',
  error: 'danger',
  timeout: 'warning',
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

function RunRow({ run }: { run: DurableRunEntry }) {
  const resume = useResumeDurableRun()

  return (
    <tr className="border-b border-slate-50 last:border-0 dark:border-slate-900">
      <td className="px-4 py-2 font-medium whitespace-nowrap">{run.agent_name ?? '—'}</td>
      <td className="px-4 py-2">
        <Badge tone={STATUS_TONE[run.status] ?? 'neutral'}>{run.status}</Badge>
        {run.is_stale && (
          <Badge tone="warning" className="ml-1">
            stale
          </Badge>
        )}
      </td>
      <td className="max-w-xs truncate px-4 py-2 font-mono text-xs text-slate-500" title={run.adk_session_id ?? ''}>
        {run.adk_session_id ?? '—'}
      </td>
      <td className="px-4 py-2 tabular-nums text-slate-500">{formatAge(run.age_seconds)}</td>
      <td className="max-w-xs truncate px-4 py-2 text-slate-600 dark:text-slate-400" title={run.error_message ?? ''}>
        {run.error_category ?? '—'}
      </td>
      <td className="px-4 py-2 text-right whitespace-nowrap">
        {run.status === 'running' && (
          <Button
            variant="ghost"
            tone={run.is_stale ? 'brand' : 'neutral'}
            size="xs"
            isPending={resume.isPending}
            onClick={() =>
              resume.mutate(run.id, {
                onSuccess: (res) =>
                  toast.success(res.status === 'success' ? 'Run resumed successfully' : `Resumed — ended in ${res.status}`),
                onError: (err) => toast.error((err as Error).message),
              })
            }
          >
            <PlayCircle size={14} className="mr-1" />
            Resume
          </Button>
        )}
      </td>
    </tr>
  )
}

export default function ReliabilityDashboardPage() {
  const [status, setStatus] = useState<string>('')
  const [offset, setOffset] = useState(0)
  const { data: runs, isLoading: runsLoading } = useDurableRuns(status || undefined, offset)
  const { data: breakers, isLoading: breakersLoading } = useCircuitBreakers()

  const stuckCount = (runs?.items ?? []).filter((r) => r.is_stale).length
  const openBreakers = (breakers ?? []).filter((b) => b.state !== 'closed').length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">Reliability</h1>
            <LiveBadge />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Durable-execution runs (opt-in via <code>model_config.durable_execution</code>) — in-flight/stuck turns
            you can resume without re-running already-completed tool calls, and live circuit-breaker state for
            flaky downstream tools.
          </p>
        </div>
        <SegmentedControl
          options={STATUS_FILTERS.map((f) => ({ label: f.label, value: f.value }))}
          value={status}
          onChange={(v) => {
            setStatus(v)
            setOffset(0)
          }}
          aria-label="Status filter"
        />
      </div>

      {stuckCount > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          <AlertTriangle size={16} />
          {stuckCount} run{stuckCount === 1 ? '' : 's'} look stuck (still &quot;running&quot; well past a normal
          turn) — likely a crashed process. Resume them below.
        </div>
      )}

      <Card className="overflow-x-auto p-0">
        {runsLoading ? (
          <div className="p-4">
            <Skeleton className="h-24" />
          </div>
        ) : !runs?.items.length ? (
          <EmptyState
            icon={Inbox}
            title="No durable-execution runs"
            message="Enable model_config.durable_execution.enabled on an agent and run it — this is empty for every agent that hasn't opted in, by design."
          />
        ) : (
          <>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Session</th>
                  <th className="px-4 py-2 font-medium">Age</th>
                  <th className="px-4 py-2 font-medium">Error</th>
                  <th className="px-4 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {runs.items.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-500 dark:border-slate-800">
              <span>
                {offset + 1}–{Math.min(offset + runs.limit, runs.total)} of {runs.total}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - runs.limit))}
                  className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
                >
                  Prev
                </button>
                <button
                  disabled={offset + runs.limit >= runs.total}
                  onClick={() => setOffset(offset + runs.limit)}
                  className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </Card>

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Circuit breakers</h2>
          {openBreakers > 0 && <Badge tone="danger">{openBreakers} open</Badge>}
        </div>
        <Card className="overflow-x-auto p-0">
          {breakersLoading ? (
            <div className="p-4">
              <Skeleton className="h-16" />
            </div>
          ) : !breakers?.length ? (
            <EmptyState
              icon={Zap}
              title="No breaker activity"
              message="Every tool call has succeeded (or none have failed enough in a row to trip a breaker) since the last restart."
            />
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Tool</th>
                  <th className="px-4 py-2 font-medium">State</th>
                  <th className="px-4 py-2 font-medium">Consecutive failures</th>
                  <th className="px-4 py-2 font-medium">Cooldown remaining</th>
                </tr>
              </thead>
              <tbody>
                {breakers.map((b) => (
                  <tr key={b.key} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2 font-mono text-xs">{b.key}</td>
                    <td className="px-4 py-2">
                      <Badge tone={b.state === 'closed' ? 'success' : b.state === 'open' ? 'danger' : 'warning'}>
                        {b.state === 'open' && <ShieldAlert size={12} />}
                        {b.state}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 tabular-nums">{b.consecutive_failures}</td>
                    <td className="px-4 py-2 tabular-nums text-slate-500">
                      {b.cooldown_remaining_seconds != null ? `${Math.round(b.cooldown_remaining_seconds)}s` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  )
}
