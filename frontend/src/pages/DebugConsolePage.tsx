import { useState } from 'react'
import { AlertTriangle, Bug, ExternalLink, RefreshCw } from 'lucide-react'
import { useAgents } from '../api/agents'
import { useTraceDetail, useTraces } from '../api/debug'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import LiveBadge from '../components/ui/LiveBadge'
import Modal from '../components/ui/Modal'
import Pagination from '../components/ui/Pagination'
import Select from '../components/ui/Select'
import { Skeleton } from '../components/ui/Skeleton'
import Waterfall from '../components/debug/Waterfall'

const STATUS_OPTIONS = [
  { label: 'All statuses', value: '' },
  { label: 'Success', value: 'success' },
  { label: 'Error', value: 'error' },
  { label: 'Timeout', value: 'timeout' },
]

function statusTone(status: string): 'success' | 'danger' {
  return status === 'success' ? 'success' : 'danger'
}

function TraceDetailPanel({ invocationId, onClose }: { invocationId: string; onClose: () => void }) {
  const { data: detail, isLoading } = useTraceDetail(invocationId)

  return (
    <Modal open onClose={onClose} title="Trace detail" maxWidth="max-w-4xl">
      {isLoading || !detail ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(detail.summary.status)}>{detail.summary.status}</Badge>
            <Badge tone="neutral">{detail.summary.agent_name ?? 'unknown agent'}</Badge>
            <Badge tone={detail.spans_source === 'jaeger' ? 'brand' : 'neutral'}>
              {detail.spans_source === 'jaeger' ? 'Live spans (Jaeger)' : 'Reconstructed (approximate timing)'}
            </Badge>
            {detail.jaeger_trace_url && (
              <a
                href={detail.jaeger_trace_url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
              >
                Open in Jaeger <ExternalLink size={12} />
              </a>
            )}
          </div>

          {detail.error_message && (
            <p className="flex items-start gap-2 rounded-md bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {detail.error_message}
            </p>
          )}

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-500">Waterfall</span>
              <span className="text-[11px] text-slate-400">Click a step to see its request/response</span>
            </div>
            <Card className="overflow-x-auto">
              <Waterfall spans={detail.spans} />
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Message</div>
              <p className="rounded-md bg-slate-50 p-2 font-mono text-xs whitespace-pre-wrap dark:bg-slate-800">
                {detail.message ?? '—'}
              </p>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Response</div>
              <p className="rounded-md bg-slate-50 p-2 font-mono text-xs whitespace-pre-wrap dark:bg-slate-800">
                {detail.response_text ?? '—'}
              </p>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}

export default function DebugConsolePage() {
  const [agentId, setAgentId] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: agents } = useAgents()
  const { data, isLoading, refetch, isFetching } = useTraces({ agent_id: agentId || undefined, status: status || undefined, offset })

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">Debug Console</h1>
          <LiveBadge />
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Trace exactly what happened across a multi-agent turn — which specialist handled it, every tool call, and
          how long each step took.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <Select
            label="Filter by agent"
            hideLabel
            size="xs"
            value={agentId}
            onChange={(e) => {
              setAgentId(e.target.value)
              setOffset(0)
            }}
            options={[{ label: 'All agents', value: '' }, ...(agents?.map((a) => ({ label: a.name, value: a.id })) ?? [])]}
          />
          <Select
            label="Filter by status"
            hideLabel
            size="xs"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              setOffset(0)
            }}
            options={STATUS_OPTIONS}
          />
        </div>
        <Button
          variant="outline"
          tone="neutral"
          size="xs"
          onClick={() => refetch()}
          leftIcon={<RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} />}
        >
          Refresh
        </Button>
      </div>

      <Card className="overflow-x-auto p-0">
        {isLoading ? (
          <div className="p-4">
            <Skeleton className="h-32" />
          </div>
        ) : !data?.items.length ? (
          <EmptyState icon={Bug} title="No traces yet" message="Run something in the Playground or Chat to see it here." />
        ) : (
          <>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Latency</th>
                  <th className="px-4 py-2 font-medium">Tool calls</th>
                  <th className="px-4 py-2 font-medium">Invoked by</th>
                  <th className="px-4 py-2 font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr
                    key={row.invocation_id}
                    onClick={() => setSelectedId(row.invocation_id)}
                    className="cursor-pointer border-b border-slate-50 last:border-0 hover:bg-slate-50 dark:border-slate-900 dark:hover:bg-slate-900"
                  >
                    <td className="px-4 py-2 font-medium">{row.agent_name ?? '—'}</td>
                    <td className="px-4 py-2">
                      <Badge tone={statusTone(row.status)}>{row.status}</Badge>
                    </td>
                    <td className="px-4 py-2 tabular-nums">{row.latency_ms}ms</td>
                    <td className="px-4 py-2 tabular-nums">{row.tool_call_count}</td>
                    <td className="px-4 py-2 text-slate-500">{row.invoked_by ?? '—'}</td>
                    <td className="px-4 py-2 text-slate-500">{new Date(row.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              className="border-t border-slate-100 px-4 py-2 dark:border-slate-800"
              total={data.total}
              limit={data.limit}
              offset={offset}
              onChange={setOffset}
            />
          </>
        )}
      </Card>

      {selectedId && <TraceDetailPanel invocationId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
