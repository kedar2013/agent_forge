import { useMemo, useState } from 'react'
import { CheckCircle2, FlaskConical, Inbox, Play, ShieldAlert, Trash2, XCircle } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useAgents } from '../../api/agents'
import {
  useCreateEvalCase,
  useDeleteEvalCase,
  useEvalCases,
  useGroundednessSummary,
  useLatestEvalBatch,
  useRunEvalBatch,
} from '../../api/scil'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Card from '../ui/Card'
import EmptyState from '../ui/EmptyState'
import Select from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import StatTile from '../ui/StatTile'
import Textarea from '../ui/Textarea'
import { useIsDarkMode } from '../../lib/chartPalette'
import { getStoredRole, getUserEmail } from '../../lib/auth'

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

export default function EvalsTab({ rangeDays }: { rangeDays: number }) {
  const { data: agents, isLoading: agentsLoading } = useAgents()
  const [agentId, setAgentId] = useState('')
  const [question, setQuestion] = useState('')
  const [criteria, setCriteria] = useState('')
  const isDark = useIsDarkMode()
  // A developer can list every agent in the workspace (config_api/agents.py's
  // list_agents is read-visible team-wide), but the backend's SCIL eval/
  // groundedness endpoints 404 on any agent a developer didn't create (see
  // app/scil_api/router.py's _get_owned_agent) — filter the picker down to
  // match, so nothing selectable here ever dead-ends into a 404.
  const isDeveloper = getStoredRole() === 'developer'
  const myEmail = getUserEmail()

  const evalCandidates = useMemo(
    () =>
      (agents ?? [])
        .filter((a) => a.status === 'published')
        .filter((a) => !isDeveloper || a.created_by === myEmail)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [agents, isDeveloper, myEmail],
  )

  const { data: cases, isLoading: casesLoading } = useEvalCases(agentId || undefined)
  const { data: latestBatch } = useLatestEvalBatch(agentId || undefined)
  const { data: groundedness, isLoading: groundednessLoading } = useGroundednessSummary(rangeDays, agentId || undefined)
  const createCase = useCreateEvalCase()
  const deleteCase = useDeleteEvalCase()
  const runBatch = useRunEvalBatch()

  const chartData = useMemo(
    () => (groundedness?.timeseries ?? []).map((p) => ({ date: p.date, Grounded: p.grounded, Ungrounded: p.ungrounded })),
    [groundedness],
  )

  const tooltipStyle = {
    fontSize: 12,
    borderRadius: 8,
    backgroundColor: isDark ? '#0f172a' : '#fff',
    color: isDark ? '#e2e8f0' : '#0f172a',
    border: `1px solid ${isDark ? '#1e293b' : '#e2e8f0'}`,
  }

  function handleAddCase() {
    if (!agentId || !question.trim() || !criteria.trim()) return
    createCase.mutate(
      { agent_id: agentId, question: question.trim(), expected_criteria: criteria.trim() },
      { onSuccess: () => { setQuestion(''); setCriteria('') } },
    )
  }

  return (
    <div className="space-y-6">
      <div className="w-72">
        <Select
          label="Agent"
          hideLabel
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          options={evalCandidates.map((a) => ({ label: a.name, value: a.id }))}
          placeholder={agentsLoading ? 'Loading agents…' : 'Select an agent to evaluate'}
        />
      </div>

      {!agentId ? (
        <EmptyState
          icon={FlaskConical}
          title="Pick an agent"
          message="Select a published agent above to see its regression suite and live groundedness sampling."
        />
      ) : (
        <>
          {/* Live groundedness sampling */}
          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">
              Live-traffic groundedness sampling
            </h2>
            <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
              A random sample of this agent's real successful turns (rate set by{' '}
              <code className="rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">model_config.scil.eval_sample_rate</code>
              ), scored fire-and-forget by an LLM judge — never blocks or retries the live response.
            </p>
            {groundednessLoading || !groundedness ? (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-2">
                <Skeleton className="h-20" />
                <Skeleton className="h-20" />
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-2">
                <StatTile icon={FlaskConical} label="Samples scored" value={groundedness.total_samples.toLocaleString()} tone="neutral" />
                <StatTile icon={ShieldAlert} label="Grounded rate" value={pct(groundedness.grounded_rate)} tone={groundedness.grounded_rate < 0.9 && groundedness.total_samples > 0 ? 'warning' : 'success'} />
              </div>
            )}

            <Card className="mt-4">
              {groundednessLoading ? (
                <Skeleton className="h-56" />
              ) : !chartData.length ? (
                <EmptyState
                  icon={Inbox}
                  title="No samples yet"
                  message="Set eval_sample_rate > 0 on this agent's SCIL config and let some real traffic through."
                />
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={chartData} barCategoryGap="20%">
                    <CartesianGrid vertical={false} stroke="currentColor" className="text-slate-100 dark:text-slate-800" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="currentColor" className="text-slate-400" tickLine={false} />
                    <YAxis tick={{ fontSize: 11 }} stroke="currentColor" className="text-slate-400" tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="Grounded" stackId="a" fill="#1baf7a" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="Ungrounded" stackId="a" fill="#dc4f4f" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>

            {!!groundedness?.recent_flagged.length && (
              <Card className="mt-4 overflow-x-auto p-0">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                    <tr>
                      <th className="px-4 py-2 font-medium">Question</th>
                      <th className="px-4 py-2 font-medium">Why flagged</th>
                      <th className="px-4 py-2 font-medium">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groundedness.recent_flagged.map((s) => (
                      <tr key={s.id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                        <td className="max-w-xs truncate px-4 py-2 text-slate-600 dark:text-slate-400" title={s.input_text}>
                          {s.input_text}
                        </td>
                        <td className="max-w-sm truncate px-4 py-2" title={s.reason ?? ''}>
                          <Badge tone="danger">{s.reason ?? 'Ungrounded'}</Badge>
                        </td>
                        <td className="px-4 py-2 whitespace-nowrap text-slate-400">{new Date(s.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            )}
          </div>

          {/* Golden-question regression suite */}
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Golden-question regression suite</h2>
                {latestBatch && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Last run {new Date(latestBatch.created_at).toLocaleString()}: {latestBatch.passed}/{latestBatch.total} passed
                  </p>
                )}
              </div>
              <Button
                leftIcon={<Play size={14} />}
                isPending={runBatch.isPending}
                loadingLabel="Running…"
                disabled={!cases?.length}
                onClick={() => runBatch.mutate(agentId)}
              >
                Run now
              </Button>
            </div>

            <Card className="overflow-x-auto p-0">
              {casesLoading ? (
                <div className="p-4">
                  <Skeleton className="h-24" />
                </div>
              ) : !cases?.length ? (
                <EmptyState icon={FlaskConical} title="No golden cases yet" message="Add a known question and what a correct answer must contain below." />
              ) : (
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-100 text-xs text-slate-500 dark:border-slate-800">
                    <tr>
                      <th className="px-4 py-2 font-medium">Question</th>
                      <th className="px-4 py-2 font-medium">Expected criteria</th>
                      <th className="px-4 py-2 font-medium">Last result</th>
                      <th className="px-4 py-2 font-medium" />
                    </tr>
                  </thead>
                  <tbody>
                    {cases.map((c) => (
                      <tr key={c.id} className="border-b border-slate-50 last:border-0 dark:border-slate-900">
                        <td className="max-w-xs truncate px-4 py-2 text-slate-700 dark:text-slate-300" title={c.question}>
                          {c.question}
                        </td>
                        <td className="max-w-xs truncate px-4 py-2 text-slate-500" title={c.expected_criteria}>
                          {c.expected_criteria}
                        </td>
                        <td className="px-4 py-2">
                          {c.last_passed === null ? (
                            <Badge tone="neutral">Not run yet</Badge>
                          ) : c.last_passed ? (
                            <Badge tone="success" className="inline-flex items-center gap-1">
                              <CheckCircle2 size={12} /> Pass
                            </Badge>
                          ) : (
                            <Badge tone="danger" className="inline-flex items-center gap-1">
                              <XCircle size={12} /> Fail
                            </Badge>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <Button variant="ghost" tone="danger" size="icon" onClick={() => deleteCase.mutate(c.id)} title="Delete this case">
                            <Trash2 size={14} />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>

            <Card className="mt-3 space-y-2">
              <div className="text-xs font-medium text-slate-600 dark:text-slate-300">Add a golden question</div>
              <Textarea
                label="Question"
                placeholder="e.g. What's the current utilization percent for Tesla Inc?"
                rows={2}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
              <Textarea
                label="Expected criteria"
                placeholder="What a correct answer must contain — e.g. a specific utilization percentage sourced from real data, not a refusal or a guess."
                rows={2}
                value={criteria}
                onChange={(e) => setCriteria(e.target.value)}
              />
              <div className="flex justify-end">
                <Button
                  size="sm"
                  isPending={createCase.isPending}
                  disabled={!question.trim() || !criteria.trim()}
                  onClick={handleAddCase}
                >
                  Add case
                </Button>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}