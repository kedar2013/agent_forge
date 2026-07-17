import { useEffect, useState } from 'react'
import { BarChart3, Bot, Coins, Hash, LayoutList, LineChart as LineChartIcon, TriangleAlert } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchMyUsage, type MyUsageSummary } from '../../api/chat'
import { useIsDarkMode } from '../../lib/chartPalette'
import Modal from './Modal'
import StatTile from './StatTile'

type View = 'chart' | 'by_agent'

function fmtCost(x: number): string {
  return `$${x.toFixed(x < 1 ? 4 : 2)}`
}

function fmtTokens(x: number): string {
  if (x >= 1_000_000) return `${(x / 1_000_000).toFixed(1)}M`
  if (x >= 1_000) return `${(x / 1_000).toFixed(1)}K`
  return String(x)
}

export default function UsageButton() {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<View>('chart')
  const [usage, setUsage] = useState<MyUsageSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const isDark = useIsDarkMode()
  const tooltipStyle = {
    fontSize: 12,
    borderRadius: 8,
    backgroundColor: isDark ? '#0f172a' : '#fff',
    color: isDark ? '#e2e8f0' : '#0f172a',
    border: `1px solid ${isDark ? '#1e293b' : '#e2e8f0'}`,
  }

  useEffect(() => {
    if (!open) return
    setLoading(true)
    fetchMyUsage(30)
      .then(setUsage)
      .catch(() => setUsage(null))
      .finally(() => setLoading(false))
  }, [open])

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="My usage"
        aria-label="My usage"
        className="flex h-5 w-5 items-center justify-center rounded-full text-slate-400 transition-colors hover:text-slate-600 dark:hover:text-slate-300"
      >
        <BarChart3 size={13} />
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title="My usage (last 30 days)" maxWidth="max-w-lg">
        {loading && <p className="text-sm text-slate-500">Loading…</p>}
        {!loading && !usage && <p className="text-sm text-slate-500">Couldn't load your usage right now.</p>}
        {!loading && usage && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <StatTile icon={Hash} label="Messages" value={usage.total_invocations} tone="brand" />
              <StatTile icon={Coins} label="Cost" value={fmtCost(usage.total_cost_usd)} tone="success" />
              <StatTile icon={Bot} label="Tokens" value={fmtTokens(usage.total_tokens)} tone="neutral" />
              <StatTile icon={TriangleAlert} label="Errors" value={usage.error_count} tone="warning" />
            </div>

            <div className="flex items-center gap-1 rounded-full border border-slate-200 bg-white p-0.5 text-xs dark:border-slate-800 dark:bg-slate-900">
              <button
                onClick={() => setView('chart')}
                className={`flex flex-1 items-center justify-center gap-1 rounded-full px-2 py-1 font-medium transition-colors ${
                  view === 'chart'
                    ? 'bg-gradient-to-r from-brand-600 to-accent-600 text-white'
                    : 'text-slate-500 hover:text-slate-700 dark:text-slate-400'
                }`}
              >
                <LineChartIcon size={12} /> Over time
              </button>
              <button
                onClick={() => setView('by_agent')}
                className={`flex flex-1 items-center justify-center gap-1 rounded-full px-2 py-1 font-medium transition-colors ${
                  view === 'by_agent'
                    ? 'bg-gradient-to-r from-brand-600 to-accent-600 text-white'
                    : 'text-slate-500 hover:text-slate-700 dark:text-slate-400'
                }`}
              >
                <LayoutList size={12} /> By specialist
              </button>
            </div>

            {view === 'chart' &&
              (usage.by_day.length === 0 ? (
                <p className="py-6 text-center text-sm text-slate-400">No activity yet in this range.</p>
              ) : (
                <div className="h-48 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={usage.by_day}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-slate-200 dark:stroke-slate-800" />
                      <XAxis
                        dataKey="date"
                        tick={{ fontSize: 10 }}
                        stroke="currentColor"
                        className="text-slate-400"
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 10 }}
                        allowDecimals={false}
                        stroke="currentColor"
                        className="text-slate-400"
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Line type="monotone" dataKey="invocations" name="messages" stroke="#5b3fe6" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ))}

            {view === 'by_agent' &&
              (usage.by_agent.length === 0 ? (
                <p className="py-6 text-center text-sm text-slate-400">No activity yet in this range.</p>
              ) : (
                <div className="h-48 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={usage.by_agent} layout="vertical" margin={{ left: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-slate-200 dark:stroke-slate-800" />
                      <XAxis
                        type="number"
                        tick={{ fontSize: 10 }}
                        allowDecimals={false}
                        stroke="currentColor"
                        className="text-slate-400"
                        tickLine={false}
                      />
                      <YAxis
                        type="category"
                        dataKey="agent_name"
                        tick={{ fontSize: 10 }}
                        width={110}
                        stroke="currentColor"
                        className="text-slate-400"
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Bar dataKey="invocation_count" name="messages" fill="#5b3fe6" radius={4} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ))}
          </div>
        )}
      </Modal>
    </>
  )
}
