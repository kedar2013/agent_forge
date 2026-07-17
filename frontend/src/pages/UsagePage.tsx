import { useMemo, useState } from 'react'
import { Bot, Coins, Hash, Inbox, Layers, Users, Wrench } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useAgentUsage, useToolUsage, useUsageSummary, useUsageTimeseries, useUserUsage } from '../api/dashboards'
import Badge, { type BadgeTone } from '../components/ui/Badge'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import LiveBadge from '../components/ui/LiveBadge'
import SegmentedControl from '../components/ui/SegmentedControl'
import { Skeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'
import { buildCategoricalScale, useIsDarkMode } from '../lib/chartPalette'

const ROLE_TONE: Record<string, BadgeTone> = { admin: 'brand', viewer: 'info', chat_user: 'neutral' }

const RANGES = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
]

const RANGE_OPTIONS = RANGES.map((r) => ({ label: r.label, value: r.days }))

type Metric = 'invocations' | 'cost'

const METRIC_OPTIONS: { label: string; value: Metric }[] = [
  { label: 'Invocations', value: 'invocations' },
  { label: 'Cost ($)', value: 'cost' },
]

function fmtCost(x: number): string {
  return `$${x.toFixed(x < 1 ? 4 : 2)}`
}

function fmtTokens(x: number): string {
  if (x >= 1_000_000) return `${(x / 1_000_000).toFixed(1)}M`
  if (x >= 1_000) return `${(x / 1_000).toFixed(1)}K`
  return String(x)
}

export default function UsagePage() {
  const [rangeDays, setRangeDays] = useState(30)
  const [metric, setMetric] = useState<Metric>('invocations')
  const isDark = useIsDarkMode()

  const { data: summary, isLoading: summaryLoading } = useUsageSummary(rangeDays)
  const { data: timeseries, isLoading: tsLoading } = useUsageTimeseries(rangeDays)
  const { data: agentUsage, isLoading: agentsLoading } = useAgentUsage(rangeDays)
  const { data: toolUsage, isLoading: toolsLoading } = useToolUsage(rangeDays)
  const { data: userUsage, isLoading: usersLoading } = useUserUsage(rangeDays)

  const agentNames = useMemo(
    () => Array.from(new Set((timeseries ?? []).map((p) => p.agent_name))),
    [timeseries],
  )
  const colorScale = useMemo(() => buildCategoricalScale(agentNames, isDark), [agentNames, isDark])

  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string>>()
    for (const point of timeseries ?? []) {
      const row = byDate.get(point.date) ?? { date: point.date }
      row[point.agent_name] = metric === 'invocations' ? point.invocations : point.cost_usd
      byDate.set(point.date, row)
    }
    return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)))
  }, [timeseries, metric])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">Usage</h1>
            <LiveBadge />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Volume, tokens, and estimated cost across every agent.
          </p>
        </div>
        <SegmentedControl options={RANGE_OPTIONS} value={rangeDays} onChange={setRangeDays} aria-label="Date range" />
      </div>

      {summaryLoading || !summary ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile icon={Hash} label="Invocations" value={summary.total_invocations.toLocaleString()} tone="brand" />
          <StatTile icon={Coins} label="Estimated cost" value={fmtCost(summary.total_cost_usd)} tone="warning" />
          <StatTile icon={Layers} label="Total tokens" value={fmtTokens(summary.total_tokens)} tone="neutral" />
          <StatTile icon={Bot} label="Unique agents" value={summary.unique_agents} tone="success" />
        </div>
      )}

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <span className="text-sm font-medium">Usage over time, by agent</span>
          <SegmentedControl options={METRIC_OPTIONS} value={metric} onChange={setMetric} aria-label="Metric" />
        </div>
        {tsLoading ? (
          <Skeleton className="h-72" />
        ) : !chartData.length ? (
          <EmptyState icon={Inbox} title="No usage data" message="No usage data in this range yet." />
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData} barCategoryGap="20%" barGap={2}>
              <CartesianGrid vertical={false} stroke="currentColor" className="text-slate-100 dark:text-slate-800" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11 }}
                stroke="currentColor"
                className="text-slate-400"
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11 }}
                stroke="currentColor"
                className="text-slate-400"
                tickLine={false}
                axisLine={false}
                tickFormatter={metric === 'cost' ? (v) => `$${v}` : undefined}
              />
              <Tooltip
                formatter={(value, name) => [
                  metric === 'cost' ? fmtCost(Number(value)) : Number(value),
                  String(name),
                ]}
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 8,
                  backgroundColor: isDark ? '#0f172a' : '#fff',
                  color: isDark ? '#e2e8f0' : '#0f172a',
                  border: `1px solid ${isDark ? '#1e293b' : '#e2e8f0'}`,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {agentNames.map((name) => (
                <Bar key={name} dataKey={name} stackId="a" fill={colorScale.get(name)} radius={[2, 2, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Usage by agent</h2>
        <Card className="overflow-x-auto p-0">
          {agentsLoading ? (
            <div className="p-4">
              <Skeleton className="h-24" />
            </div>
          ) : !agentUsage?.length ? (
            <EmptyState icon={Bot} title="No agent usage" message="No usage yet." />
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Invocations</th>
                  <th className="px-4 py-2 font-medium">Tokens</th>
                  <th className="px-4 py-2 font-medium">Total cost</th>
                  <th className="px-4 py-2 font-medium">Avg cost / call</th>
                </tr>
              </thead>
              <tbody>
                {agentUsage.map((a) => (
                  <tr key={a.agent_id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2 font-medium">{a.name}</td>
                    <td className="px-4 py-2 tabular-nums">{a.invocation_count.toLocaleString()}</td>
                    <td className="px-4 py-2 tabular-nums">{fmtTokens(a.total_tokens)}</td>
                    <td className="px-4 py-2 tabular-nums">{fmtCost(a.total_cost_usd)}</td>
                    <td className="px-4 py-2 tabular-nums">{fmtCost(a.avg_cost_per_invocation)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Tool usage</h2>
        <Card className="overflow-x-auto p-0">
          {toolsLoading ? (
            <div className="p-4">
              <Skeleton className="h-24" />
            </div>
          ) : !toolUsage?.length ? (
            <EmptyState icon={Wrench} title="No tool usage" message="No tool calls yet." />
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">Tool</th>
                  <th className="px-4 py-2 font-medium">Calls</th>
                  <th className="px-4 py-2 font-medium">Used by</th>
                </tr>
              </thead>
              <tbody>
                {toolUsage.map((t) => (
                  <tr key={t.tool_id ?? t.name} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2 font-medium">{t.name}</td>
                    <td className="px-4 py-2 tabular-nums">{t.call_count.toLocaleString()}</td>
                    <td className="px-4 py-2 text-slate-500">{t.agent_names.join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Usage by user</h2>
        <Card className="overflow-x-auto p-0">
          {usersLoading ? (
            <div className="p-4">
              <Skeleton className="h-24" />
            </div>
          ) : !userUsage?.length ? (
            <EmptyState icon={Users} title="No user usage" message="No usage yet." />
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2 font-medium">User</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Invocations</th>
                  <th className="px-4 py-2 font-medium">Tokens</th>
                  <th className="px-4 py-2 font-medium">Cost</th>
                  <th className="px-4 py-2 font-medium">Errors</th>
                  <th className="px-4 py-2 font-medium">Last active</th>
                </tr>
              </thead>
              <tbody>
                {userUsage.map((u) => (
                  <tr key={u.user_key} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                    <td className="px-4 py-2 font-medium">
                      {u.email ?? <span className="font-mono text-xs text-slate-400">{u.user_key}</span>}
                    </td>
                    <td className="px-4 py-2">
                      {u.role ? (
                        <Badge tone={ROLE_TONE[u.role]}>{u.role}</Badge>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 tabular-nums">{u.invocation_count.toLocaleString()}</td>
                    <td className="px-4 py-2 tabular-nums">{fmtTokens(u.total_tokens)}</td>
                    <td className="px-4 py-2 tabular-nums">{fmtCost(u.total_cost_usd)}</td>
                    <td className="px-4 py-2 tabular-nums">
                      {u.error_count > 0 ? (
                        <span className="text-red-600 dark:text-red-400">{u.error_count}</span>
                      ) : (
                        '0'
                      )}
                    </td>
                    <td className="px-4 py-2 text-slate-400">
                      {u.last_active ? new Date(u.last_active).toLocaleString() : '—'}
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
