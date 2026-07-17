import { useMemo, useRef, useState, type RefObject } from 'react'
import { AlertTriangle, CircleSlash, DatabaseZap, Inbox, Percent, RotateCw, Trash2 } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  useDeleteCacheEntry,
  useDeleteCorrection,
  usePurgeAgentCache,
  useScilCacheEntries,
  useScilCorrections,
  useScilSummary,
  useScilTimeseries,
} from '../api/scil'
import EvalsTab from '../components/scil/EvalsTab'
import SimilarityInspector from '../components/scil/SimilarityInspector'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import ConfirmDialog from '../components/ui/ConfirmDialog'
import EmptyState from '../components/ui/EmptyState'
import LiveBadge from '../components/ui/LiveBadge'
import Select from '../components/ui/Select'
import SegmentedControl from '../components/ui/SegmentedControl'
import { Skeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'
import { useIsDarkMode } from '../lib/chartPalette'
import { getStoredRole } from '../lib/auth'

// Client-side grouping for the correction-memory filter: the backend only
// supports exact-match on error_signature, but each category (e.g.
// "Hallucination") spans multiple distinct signature values that share a
// common "Category:Detail" prefix (per the contract, e.g.
// "Hallucination:NoToolCall" / "Hallucination:Ungrounded"). We match
// case-insensitively on that prefix against whatever page of corrections is
// currently loaded, rather than trying to enumerate every exact signature
// server-side.
const CORRECTION_CATEGORIES: { label: string; value: string; prefix: string }[] = [
  { label: 'Hallucination', value: 'hallucination', prefix: 'hallucination' },
  { label: 'SQL', value: 'sql', prefix: 'sql' },
  { label: 'JSON', value: 'json', prefix: 'json' },
]

const RANGES = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
]

const RANGE_OPTIONS = RANGES.map((r) => ({ label: r.label, value: r.days }))

const TABS = [
  { label: 'Overview', value: 'overview' },
  { label: 'Evals', value: 'evals' },
] as const
type TabValue = (typeof TABS)[number]['value']

// Semantic, fixed colors per route (not positional): green = LLM avoided,
// blue = normal LLM call, amber = needed self-correction, slate = SCIL off.
const ROUTE_COLORS: Record<string, string> = {
  deterministic: '#4a3aa7',
  cache_hit: '#1baf7a',
  llm: '#2a78d6',
  llm_retry: '#eda100',
  disabled: '#94a3b8',
}

const ROUTE_LABELS: Record<string, string> = {
  deterministic: 'Template (0 LLM calls)',
  cache_hit: 'Cache hit (0 LLM calls)',
  llm: 'LLM call',
  llm_retry: 'LLM + self-correction retry',
  disabled: 'SCIL disabled',
}

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

export default function ScilDashboardPage() {
  // Cache/correction curation and workspace-wide cost metrics (the
  // "Overview" tab) are admin-only server-side — a developer only ever gets
  // the Evals tab (their own agents' eval suite + groundedness sampling),
  // so there's nothing to switch between and the tab control itself is
  // hidden rather than shown with one dead option.
  const isDeveloper = getStoredRole() === 'developer'
  const [tab, setTab] = useState<TabValue>(isDeveloper ? 'evals' : 'overview')
  const [rangeDays, setRangeDays] = useState(30)
  const [cacheOffset, setCacheOffset] = useState(0)
  const [correctionsOffset, setCorrectionsOffset] = useState(0)
  const [correctionCategory, setCorrectionCategory] = useState('')
  const [purgeTarget, setPurgeTarget] = useState<{ agentId: string; agentName: string } | null>(null)
  const isDark = useIsDarkMode()
  const cacheSectionRef = useRef<HTMLDivElement>(null)
  const correctionsSectionRef = useRef<HTMLDivElement>(null)

  function jumpTo(ref: RefObject<HTMLDivElement | null>, before?: () => void) {
    before?.()
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const { data: summary, isLoading: summaryLoading } = useScilSummary(rangeDays, !isDeveloper)
  const { data: timeseries, isLoading: tsLoading } = useScilTimeseries(rangeDays, !isDeveloper)
  const { data: cache, isLoading: cacheLoading } = useScilCacheEntries(cacheOffset, 25, !isDeveloper)
  const { data: corrections, isLoading: correctionsLoading } = useScilCorrections(
    correctionsOffset,
    25,
    undefined,
    !isDeveloper,
  )
  const deleteCacheEntry = useDeleteCacheEntry()
  const purgeAgentCache = usePurgeAgentCache()
  const deleteCorrection = useDeleteCorrection()

  const activeCategory = CORRECTION_CATEGORIES.find((c) => c.value === correctionCategory)
  const filteredCorrections = useMemo(() => {
    const items = corrections?.items ?? []
    if (!activeCategory) return items
    return items.filter((c) => c.error_signature.toLowerCase().startsWith(activeCategory.prefix))
  }, [corrections, activeCategory])

  const donutData = useMemo(
    () =>
      (summary?.routes ?? []).map((r) => ({
        name: ROUTE_LABELS[r.route] ?? r.route,
        route: r.route,
        value: r.count,
      })),
    [summary],
  )

  const routesInRange = useMemo(
    () => Array.from(new Set((timeseries ?? []).map((p) => p.route))).sort(),
    [timeseries],
  )
  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string>>()
    for (const point of timeseries ?? []) {
      const row = byDate.get(point.date) ?? { date: point.date }
      row[point.route] = point.count
      byDate.set(point.date, row)
    }
    return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)))
  }, [timeseries])

  const tooltipStyle = {
    fontSize: 12,
    borderRadius: 8,
    backgroundColor: isDark ? '#0f172a' : '#fff',
    color: isDark ? '#e2e8f0' : '#0f172a',
    border: `1px solid ${isDark ? '#1e293b' : '#e2e8f0'}`,
  }

  return (
    <>
      <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">SCIL Dashboard</h1>
            <LiveBadge />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {isDeveloper
              ? "Golden-question regression results and live groundedness sampling for the agents you created."
              : 'Self-Correcting Intelligence Layer — LLM calls avoided by the semantic cache, self-correction retry '
                + 'outcomes, and the cached/correction knowledge behind them.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!isDeveloper && (
            <SegmentedControl options={TABS} value={tab} onChange={setTab} aria-label="Dashboard section" />
          )}
          <SegmentedControl options={RANGE_OPTIONS} value={rangeDays} onChange={setRangeDays} aria-label="Date range" />
        </div>
      </div>

      {tab === 'evals' && <EvalsTab rangeDays={rangeDays} />}

      {tab === 'overview' && (
      <>

      {summaryLoading || !summary ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile icon={DatabaseZap} label="LLM calls avoided" value={summary.llm_calls_avoided.toLocaleString()} tone="success" onClick={() => jumpTo(cacheSectionRef)} />
          <StatTile icon={Percent} label="Cache hit rate" value={pct(summary.cache_hit_rate)} tone="brand" onClick={() => jumpTo(cacheSectionRef)} />
          <StatTile icon={RotateCw} label="Retried turns" value={summary.retried_turns.toLocaleString()} tone="warning" onClick={() => jumpTo(correctionsSectionRef)} />
          <StatTile icon={CircleSlash} label="Retry success rate" value={pct(summary.retry_success_rate)} tone="neutral" onClick={() => jumpTo(correctionsSectionRef)} />
          <StatTile
            icon={AlertTriangle}
            label="Hallucination flags"
            value={(summary.hallucination_flags ?? 0).toLocaleString()}
            tone="warning"
            onClick={() => jumpTo(correctionsSectionRef, () => setCorrectionCategory('hallucination'))}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <div className="mb-3 text-sm font-medium">Route distribution</div>
          {summaryLoading || !summary ? (
            <Skeleton className="h-64" />
          ) : !donutData.length ? (
            <EmptyState icon={Inbox} title="No SCIL traffic" message="No SCIL traffic in this range yet." />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={donutData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
                  {donutData.map((entry) => (
                    <Cell key={entry.route} fill={ROUTE_COLORS[entry.route] ?? '#64748b'} stroke="none" />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card className="lg:col-span-3">
          <div className="mb-3 text-sm font-medium">Requests over time, by route</div>
          {tsLoading ? (
            <Skeleton className="h-64" />
          ) : !chartData.length ? (
            <EmptyState icon={Inbox} title="No SCIL traffic" message="No SCIL traffic in this range yet." />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chartData} barCategoryGap="20%">
                <CartesianGrid vertical={false} stroke="currentColor" className="text-slate-100 dark:text-slate-800" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="currentColor" className="text-slate-400" tickLine={false} />
                <YAxis tick={{ fontSize: 11 }} stroke="currentColor" className="text-slate-400" tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [Number(value), ROUTE_LABELS[String(name)] ?? String(name)]} />
                <Legend wrapperStyle={{ fontSize: 12 }} formatter={(value) => ROUTE_LABELS[String(value)] ?? String(value)} />
                {routesInRange.map((route) => (
                  <Bar key={route} dataKey={route} stackId="a" fill={ROUTE_COLORS[route] ?? '#64748b'} radius={[2, 2, 0, 0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <div ref={cacheSectionRef} className="scroll-mt-4 space-y-3">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Semantic cache</h2>
        <SimilarityInspector />
        <Card className="overflow-x-auto p-0">
          {cacheLoading ? (
            <div className="p-4">
              <Skeleton className="h-24" />
            </div>
          ) : !cache?.items.length ? (
            <EmptyState
              icon={DatabaseZap}
              title="Nothing cached yet"
              message="Enable SCIL on an agent (model_config.scil.enabled) and run it twice."
            />
          ) : (
            <>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                  <tr>
                    <th className="px-4 py-2 font-medium">Agent</th>
                    <th className="px-4 py-2 font-medium">Input</th>
                    <th className="px-4 py-2 font-medium" title="This agent's currently-configured cache_similarity_threshold — a new question needs a cosine similarity at or above this to reuse this entry.">Threshold</th>
                    <th className="px-4 py-2 font-medium">Hits</th>
                    <th className="px-4 py-2 font-medium">Last hit</th>
                    <th className="px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {cache.items.map((entry) => (
                    <tr key={entry.id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                      <td className="px-4 py-2 font-medium whitespace-nowrap">{entry.agent_name ?? '—'}</td>
                      <td className="max-w-md truncate px-4 py-2 text-slate-600 dark:text-slate-400" title={entry.input_text}>
                        {entry.input_text}
                      </td>
                      <td className="px-4 py-2 tabular-nums text-slate-500">{entry.similarity_threshold.toFixed(2)}</td>
                      <td className="px-4 py-2 tabular-nums">{entry.hit_count}</td>
                      <td className="px-4 py-2 whitespace-nowrap text-slate-400">
                        {entry.last_hit_at ? new Date(entry.last_hit_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-4 py-2 text-right whitespace-nowrap">
                        <Button
                          variant="ghost"
                          tone="danger"
                          size="icon"
                          onClick={() => deleteCacheEntry.mutate(entry.id)}
                          title="Delete this cache entry"
                        >
                          <Trash2 size={14} />
                        </Button>
                        <Button
                          variant="ghost"
                          tone="danger"
                          size="xs"
                          className="ml-1"
                          onClick={() => setPurgeTarget({ agentId: entry.agent_id, agentName: entry.agent_name ?? 'this agent' })}
                        >
                          Purge agent
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-500 dark:border-slate-800">
                <span>
                  {cacheOffset + 1}–{Math.min(cacheOffset + cache.limit, cache.total)} of {cache.total}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={cacheOffset === 0}
                    onClick={() => setCacheOffset(Math.max(0, cacheOffset - cache.limit))}
                    className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
                  >
                    Prev
                  </button>
                  <button
                    disabled={cacheOffset + cache.limit >= cache.total}
                    onClick={() => setCacheOffset(cacheOffset + cache.limit)}
                    className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </Card>
      </div>

      <div ref={correctionsSectionRef} className="scroll-mt-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Correction memory</h2>
          <div className="w-44">
            <Select
              label="Filter by error type"
              hideLabel
              size="xs"
              value={correctionCategory}
              onChange={(e) => setCorrectionCategory(e.target.value)}
              options={CORRECTION_CATEGORIES.map((c) => ({ label: c.label, value: c.value }))}
              placeholder="All"
            />
          </div>
        </div>
        <Card className="overflow-x-auto p-0">
          {correctionsLoading ? (
            <div className="p-4">
              <Skeleton className="h-24" />
            </div>
          ) : !corrections?.items.length ? (
            <EmptyState
              icon={RotateCw}
              title="No corrections yet"
              message="These appear when a validation failure is fixed by an automatic retry."
            />
          ) : !filteredCorrections.length ? (
            <EmptyState
              icon={RotateCw}
              title="No matching corrections"
              message="No corrections on this page match the selected error-type filter. Try 'All' or a different page."
            />
          ) : (
            <>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                  <tr>
                    <th className="px-4 py-2 font-medium">Agent</th>
                    <th className="px-4 py-2 font-medium">Input</th>
                    <th className="px-4 py-2 font-medium">Error</th>
                    <th className="px-4 py-2 font-medium">Source</th>
                    <th className="px-4 py-2 font-medium">Reused</th>
                    <th className="px-4 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {filteredCorrections.map((c) => (
                    <tr key={c.id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                      <td className="px-4 py-2 font-medium whitespace-nowrap">{c.agent_name ?? '—'}</td>
                      <td className="max-w-xs truncate px-4 py-2 text-slate-600 dark:text-slate-400" title={c.input_text}>
                        {c.input_text}
                      </td>
                      <td className="px-4 py-2">
                        <Badge tone="warning" className="font-mono">
                          {c.error_signature}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-slate-500">{c.correction_source}</td>
                      <td className="px-4 py-2 tabular-nums">{c.reuse_count}</td>
                      <td className="px-4 py-2 text-right">
                        <Button
                          variant="ghost"
                          tone="danger"
                          size="icon"
                          onClick={() => deleteCorrection.mutate(c.id)}
                          title="Delete this correction"
                        >
                          <Trash2 size={14} />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-500 dark:border-slate-800">
                <span>
                  {correctionsOffset + 1}–{Math.min(correctionsOffset + corrections.limit, corrections.total)} of{' '}
                  {corrections.total}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={correctionsOffset === 0}
                    onClick={() => setCorrectionsOffset(Math.max(0, correctionsOffset - corrections.limit))}
                    className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
                  >
                    Prev
                  </button>
                  <button
                    disabled={correctionsOffset + corrections.limit >= corrections.total}
                    onClick={() => setCorrectionsOffset(correctionsOffset + corrections.limit)}
                    className="rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </Card>
      </div>
      </>
      )}
      </div>

      <ConfirmDialog
        open={purgeTarget !== null}
        title="Purge agent cache?"
        message={`Purge ALL cached answers for ${purgeTarget?.agentName ?? 'this agent'}?`}
        confirmLabel="Purge"
        danger
        onConfirm={() => {
          if (purgeTarget) purgeAgentCache.mutate(purgeTarget.agentId)
          setPurgeTarget(null)
        }}
        onCancel={() => setPurgeTarget(null)}
      />
    </>
  )
}
