import { useState } from 'react'
import { Activity, AlertTriangle, Gauge, Users, Wrench } from 'lucide-react'
import { useAgentHealth, useMonitoringSummary, useToolHealth } from '../api/dashboards'
import Badge from '../components/ui/Badge'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import LiveBadge from '../components/ui/LiveBadge'
import SegmentedControl from '../components/ui/SegmentedControl'
import { Skeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'
import { AGENT_STATUS_TONE, TOOL_TYPE_TONE } from '../lib/badgeTones'

const WINDOWS = [
  { label: '1h', hours: 1 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 24 * 7 },
  { label: '30d', hours: 24 * 30 },
]

const WINDOW_OPTIONS = WINDOWS.map((w) => ({ label: w.label, value: w.hours }))

function fmtMs(ms: number | null): string {
  if (ms === null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}

function fmtPct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

export default function MonitoringPage() {
  const [windowHours, setWindowHours] = useState(24)
  const { data: summary, isLoading: summaryLoading } = useMonitoringSummary(windowHours)
  const { data: agents, isLoading: agentsLoading } = useAgentHealth(windowHours)
  const { data: tools, isLoading: toolsLoading } = useToolHealth(windowHours)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">Monitoring</h1>
            <LiveBadge />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Health and reliability across every agent and tool.
          </p>
        </div>
        <SegmentedControl options={WINDOW_OPTIONS} value={windowHours} onChange={setWindowHours} aria-label="Time window" />
      </div>

      {summaryLoading || !summary ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile
            icon={AlertTriangle}
            label="Error rate"
            value={fmtPct(summary.error_rate)}
            tone={summary.error_rate > 0.05 ? 'warning' : 'success'}
          />
          <StatTile icon={Gauge} label="p50 latency" value={fmtMs(summary.p50_latency_ms)} tone="brand" />
          <StatTile icon={Gauge} label="p95 latency" value={fmtMs(summary.p95_latency_ms)} tone="brand" />
          <StatTile icon={Users} label="Active agents" value={summary.active_agents_count} tone="neutral" />
        </div>
      )}

      <div>
        <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-700 dark:text-slate-300">
          <Activity size={15} /> Per-agent health
        </h2>
        <Card className="overflow-x-auto p-0">
          {agentsLoading ? (
            <div className="p-4">
              <Skeleton className="h-24" />
            </div>
          ) : !agents?.length ? (
            <EmptyState icon={Users} title="No agent activity" message="No invocations in this window yet." />
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Invocations</th>
                  <th className="px-4 py-2 font-medium">Error rate</th>
                  <th className="px-4 py-2 font-medium">p95 latency</th>
                  <th className="px-4 py-2 font-medium">Last invocation</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => (
                  <tr key={a.agent_id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2 font-medium">{a.name}</td>
                    <td className="px-4 py-2">
                      <Badge tone={AGENT_STATUS_TONE[a.status as keyof typeof AGENT_STATUS_TONE] ?? 'neutral'}>
                        {a.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 tabular-nums">{a.invocation_count}</td>
                    <td className={`px-4 py-2 tabular-nums ${a.error_rate > 0.05 ? 'text-red-600 dark:text-red-400' : ''}`}>
                      {fmtPct(a.error_rate)}
                    </td>
                    <td className="px-4 py-2 tabular-nums">{fmtMs(a.p95_latency_ms)}</td>
                    <td className="px-4 py-2 text-slate-500">
                      {a.last_invocation_at ? new Date(a.last_invocation_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Per-tool health</h2>
        <Card className="overflow-x-auto p-0">
          {toolsLoading ? (
            <div className="p-4">
              <Skeleton className="h-24" />
            </div>
          ) : !tools?.length ? (
            <EmptyState icon={Wrench} title="No tool activity" message="No tool calls in this window yet." />
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Tool</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Calls</th>
                  <th className="px-4 py-2 font-medium">Error rate</th>
                  <th className="px-4 py-2 font-medium">Avg latency</th>
                </tr>
              </thead>
              <tbody>
                {tools.map((t) => (
                  <tr key={t.tool_id ?? t.name} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2 font-medium">{t.name}</td>
                    <td className="px-4 py-2">
                      <Badge tone={TOOL_TYPE_TONE[t.tool_type]}>{t.tool_type}</Badge>
                    </td>
                    <td className="px-4 py-2 tabular-nums">{t.call_count}</td>
                    <td className={`px-4 py-2 tabular-nums ${t.error_rate > 0.1 ? 'text-red-600 dark:text-red-400' : ''}`}>
                      {fmtPct(t.error_rate)}
                    </td>
                    <td className="px-4 py-2 tabular-nums">{fmtMs(t.avg_latency_ms)}</td>
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
