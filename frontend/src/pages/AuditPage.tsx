import { useState } from 'react'
import { Download, Eye, FileClock, Inbox } from 'lucide-react'
import { toast } from 'sonner'
import {
  downloadExport,
  useConfigAudit,
  useInvocationAudit,
  useInvocationDetail,
} from '../api/dashboards'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import LiveBadge from '../components/ui/LiveBadge'
import Modal from '../components/ui/Modal'
import Pagination from '../components/ui/Pagination'
import Select from '../components/ui/Select'
import { Skeleton } from '../components/ui/Skeleton'

const PAGE_SIZE = 25

const STATUS_OPTIONS = [
  { label: 'All statuses', value: '' },
  { label: 'Success', value: 'success' },
  { label: 'Error', value: 'error' },
  { label: 'Timeout', value: 'timeout' },
]

const ENTITY_TYPE_OPTIONS = [
  { label: 'All entities', value: '' },
  { label: 'Agent', value: 'agent' },
  { label: 'Tool', value: 'tool' },
  { label: 'Skill', value: 'skill' },
]

function statusTone(status: string): 'success' | 'danger' | 'warning' {
  if (status === 'success') return 'success'
  if (status === 'timeout') return 'warning'
  return 'danger'
}

function InvocationsPanel() {
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [detailId, setDetailId] = useState<string | null>(null)
  const { data, isLoading } = useInvocationAudit({ status: status || undefined, limit: PAGE_SIZE, offset })
  const { data: detail } = useInvocationDetail(detailId)

  async function handleExport(format: 'csv' | 'json') {
    try {
      await downloadExport('invocations', format, { status: status || undefined })
      toast.success(`Exported invocations.${format}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
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
        <div className="flex gap-2">
          <Button variant="outline" tone="neutral" size="xs" leftIcon={<Download size={13} />} onClick={() => handleExport('csv')}>
            CSV
          </Button>
          <Button variant="outline" tone="neutral" size="xs" leftIcon={<Download size={13} />} onClick={() => handleExport('json')}>
            JSON
          </Button>
        </div>
      </div>

      <Card className="overflow-x-auto p-0">
        {isLoading ? (
          <div className="p-4">
            <Skeleton className="h-32" />
          </div>
        ) : !data?.items.length ? (
          <EmptyState icon={Inbox} title="No invocations found" message="Invocations will show up here once agents start running." />
        ) : (
          <>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Latency</th>
                  <th className="px-4 py-2 font-medium">Cost</th>
                  <th className="px-4 py-2 font-medium">Invoked by</th>
                  <th className="px-4 py-2 font-medium">When</th>
                  <th className="px-4 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2 font-medium">{row.agent_name ?? '—'}</td>
                    <td className="px-4 py-2">
                      <Badge tone={statusTone(row.status)}>{row.status}</Badge>
                    </td>
                    <td className="px-4 py-2 tabular-nums">{row.latency_ms}ms</td>
                    <td className="px-4 py-2 tabular-nums">
                      {row.estimated_cost_usd != null ? `$${row.estimated_cost_usd.toFixed(4)}` : '—'}
                    </td>
                    <td className="px-4 py-2 text-slate-500">{row.invoked_by ?? '—'}</td>
                    <td className="px-4 py-2 text-slate-500">{new Date(row.created_at).toLocaleString()}</td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => setDetailId(row.id)}
                        className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                      >
                        <Eye size={13} /> expand
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              className="border-t border-slate-100 px-4 py-2 dark:border-slate-800"
              total={data.total}
              limit={data.limit}
              offset={data.offset}
              onChange={setOffset}
            />
          </>
        )}
      </Card>

      <Modal open={detailId !== null} onClose={() => setDetailId(null)} title="Invocation detail" maxWidth="max-w-2xl">
        {!detail ? (
          <Skeleton className="h-32" />
        ) : (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2 text-xs text-slate-500">
              <div>Agent: <span className="text-slate-700 dark:text-slate-300">{detail.agent_name}</span></div>
              <div>Status: <Badge tone={statusTone(detail.status)}>{detail.status}</Badge></div>
              <div>Latency: {detail.latency_ms}ms</div>
              <div>Trace: <code className="text-xs">{detail.trace_id}</code></div>
            </div>
            {detail.error_message && (
              <p className="rounded-md bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
                {detail.error_message}
              </p>
            )}
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Message</div>
              <p className="rounded-md bg-slate-50 p-2 font-mono text-xs dark:bg-slate-800">
                {detail.transcript?.message ?? '—'}
              </p>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Response</div>
              <p className="rounded-md bg-slate-50 p-2 font-mono text-xs dark:bg-slate-800">
                {detail.transcript?.response_text ?? '—'}
              </p>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

function ConfigChangesPanel() {
  const [entityType, setEntityType] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, isLoading } = useConfigAudit({ entity_type: entityType || undefined, limit: PAGE_SIZE, offset })

  async function handleExport(format: 'csv' | 'json') {
    try {
      await downloadExport('config-changes', format, { entity_type: entityType || undefined })
      toast.success(`Exported config_changes.${format}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Select
          label="Filter by entity type"
          hideLabel
          size="xs"
          value={entityType}
          onChange={(e) => {
            setEntityType(e.target.value)
            setOffset(0)
          }}
          options={ENTITY_TYPE_OPTIONS}
        />
        <div className="flex gap-2">
          <Button variant="outline" tone="neutral" size="xs" leftIcon={<Download size={13} />} onClick={() => handleExport('csv')}>
            CSV
          </Button>
          <Button variant="outline" tone="neutral" size="xs" leftIcon={<Download size={13} />} onClick={() => handleExport('json')}>
            JSON
          </Button>
        </div>
      </div>

      <Card className="overflow-x-auto p-0">
        {isLoading ? (
          <div className="p-4">
            <Skeleton className="h-32" />
          </div>
        ) : !data?.items.length ? (
          <EmptyState icon={FileClock} title="No config changes found" message="Changes to agents, tools, and skills will show up here." />
        ) : (
          <>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Entity</th>
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Actor</th>
                  <th className="px-4 py-2 font-medium">Diff</th>
                  <th className="px-4 py-2 font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2">
                      <Badge tone="neutral">{row.entity_type}</Badge>
                    </td>
                    <td className="px-4 py-2 font-medium">{row.action}</td>
                    <td className="px-4 py-2 text-slate-500">{row.actor ?? '—'}</td>
                    <td className="px-4 py-2 font-mono text-xs text-slate-500">
                      {row.diff ? JSON.stringify(row.diff).slice(0, 60) : '—'}
                    </td>
                    <td className="px-4 py-2 text-slate-500">{new Date(row.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              className="border-t border-slate-100 px-4 py-2 dark:border-slate-800"
              total={data.total}
              limit={data.limit}
              offset={data.offset}
              onChange={setOffset}
            />
          </>
        )}
      </Card>
    </div>
  )
}

export default function AuditPage() {
  const [tab, setTab] = useState<'invocations' | 'config'>('invocations')

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">Audit</h1>
          <LiveBadge />
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Searchable, append-only record of invocations and configuration changes.
        </p>
      </div>

      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-800">
        {(['invocations', 'config'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium capitalize ${
              tab === t
                ? 'border-brand-600 text-brand-600 dark:text-brand-400'
                : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            }`}
          >
            {t === 'config' ? 'Config changes' : 'Invocations'}
          </button>
        ))}
      </div>

      {tab === 'invocations' ? <InvocationsPanel /> : <ConfigChangesPanel />}
    </div>
  )
}
