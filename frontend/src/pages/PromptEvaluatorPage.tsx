import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { diffWordsWithSpace } from 'diff'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Copy,
  FileText,
  History,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { useAgents } from '../api/agents'
import {
  useEvaluatePrompt,
  usePromptEvalCriteria,
  usePromptEvalRun,
  usePromptEvalRuns,
  type CriterionResultOut,
  type PromptEvalResult,
  type PromptEvalScope,
} from '../api/promptEval'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import PageHeader from '../components/ui/PageHeader'
import SegmentedControl from '../components/ui/SegmentedControl'
import Select from '../components/ui/Select'
import { Skeleton } from '../components/ui/Skeleton'
import Textarea from '../components/ui/Textarea'

type InputMode = 'agent' | 'text'

const CATEGORY_LABELS: Record<string, string> = {
  structure: 'Structure',
  clarity: 'Clarity',
  output: 'Output Format',
  tooling: 'Tool Usage',
  safety: 'Safety & Guardrails',
  consistency: 'Consistency',
  platform: 'Platform Conventions',
}

function scoreTone(score: number | null): 'success' | 'warning' | 'danger' | 'neutral' {
  if (score == null) return 'neutral'
  if (score >= 4) return 'success'
  if (score === 3) return 'warning'
  return 'danger'
}

function overallTone(score: number): string {
  if (score >= 80) return 'from-emerald-500 to-teal-600'
  if (score >= 60) return 'from-amber-400 to-orange-500'
  return 'from-red-500 to-rose-600'
}

function SeverityIcon({ severity }: { severity: CriterionResultOut['severity'] }) {
  if (severity === 'critical') return <XCircle size={14} className="text-red-500" />
  if (severity === 'warning') return <AlertTriangle size={14} className="text-amber-500" />
  return <CheckCircle2 size={14} className="text-emerald-500" />
}

function CriterionRow({ criterion }: { criterion: CriterionResultOut }) {
  if (!criterion.applicable) {
    return (
      <div className="flex items-start gap-2 py-2 text-slate-400 dark:text-slate-500">
        <span className="mt-0.5 shrink-0 text-xs">—</span>
        <div className="text-xs">
          <span className="font-medium">{criterion.label}</span> — not applicable. {criterion.rationale}
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-2 border-t border-slate-100 py-2.5 first:border-t-0 dark:border-slate-800">
      <span className="mt-0.5 shrink-0"><SeverityIcon severity={criterion.severity} /></span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-800 dark:text-slate-200">{criterion.label}</span>
          <Badge tone={scoreTone(criterion.score)}>{criterion.score}/{criterion.max_score}</Badge>
          <span className="text-[10px] uppercase tracking-wide text-slate-400">{criterion.method}</span>
        </div>
        <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">{criterion.rationale}</p>
        {criterion.suggestion && (
          <p className="mt-1 rounded bg-brand-50 px-2 py-1 text-xs text-brand-700 dark:bg-brand-950 dark:text-brand-300">
            <span className="font-semibold">Suggestion: </span>
            {criterion.suggestion}
          </p>
        )}
      </div>
    </div>
  )
}

function TextDiffView({ before, after }: { before: string; after: string }) {
  const parts = diffWordsWithSpace(before, after)
  return (
    <div className="max-h-96 overflow-y-auto rounded-md border border-slate-200 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap dark:border-slate-800">
      {parts.map((part, i) => (
        <span
          key={i}
          className={
            part.added
              ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300'
              : part.removed
                ? 'text-red-700 line-through decoration-red-400/70 dark:text-red-400'
                : ''
          }
        >
          {part.value}
        </span>
      ))}
    </div>
  )
}

function ResultPanel({ result }: { result: PromptEvalResult }) {
  const [showRewrite, setShowRewrite] = useState(true)
  const grouped = useMemo(() => {
    const map = new Map<string, CriterionResultOut[]>()
    for (const c of result.criteria) {
      const list = map.get(c.category) ?? []
      list.push(c)
      map.set(c.category, list)
    }
    return map
  }, [result.criteria])

  return (
    <div className="space-y-4">
      <Card className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div
          className={`flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br text-2xl font-bold text-white shadow-lg ${overallTone(result.overall_score)}`}
        >
          {Math.round(result.overall_score)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              {result.agent_name ?? 'Pasted prompt text'}
            </h3>
            <Badge tone="neutral">{result.scope}</Badge>
            {result.model_used && <Badge tone="info">judge: {result.model_used}</Badge>}
          </div>
          {result.summary && <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{result.summary}</p>}
          {result.judge_error && (
            <p className="mt-1 flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
              <AlertTriangle size={12} /> {result.judge_error}
            </p>
          )}
        </div>
      </Card>

      <Card>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Rubric breakdown</h4>
        <div className="space-y-4">
          {[...grouped.entries()].map(([category, items]) => (
            <div key={category}>
              <div className="mb-1 text-xs font-semibold text-slate-500 dark:text-slate-400">
                {CATEGORY_LABELS[category] ?? category}
              </div>
              {items.map((c) => (
                <CriterionRow key={c.id} criterion={c} />
              ))}
            </div>
          ))}
        </div>
      </Card>

      {result.suggested_rewrite && (
        <Card>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
              <Sparkles size={13} className="text-brand-500" /> Suggested rewrite
            </h4>
            <div className="flex items-center gap-2">
              <SegmentedControl
                aria-label="Rewrite view"
                value={showRewrite ? 'diff' : 'plain'}
                onChange={(v) => setShowRewrite(v === 'diff')}
                options={[
                  { label: 'Diff', value: 'diff' },
                  { label: 'Plain text', value: 'plain' },
                ]}
              />
              <Button
                variant="outline"
                size="xs"
                leftIcon={<Copy size={12} />}
                onClick={() => navigator.clipboard.writeText(result.suggested_rewrite ?? '')}
              >
                Copy
              </Button>
            </div>
          </div>
          {showRewrite ? (
            <TextDiffView before={result.source_text} after={result.suggested_rewrite} />
          ) : (
            <div className="max-h-96 overflow-y-auto rounded-md border border-slate-200 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap dark:border-slate-800">
              {result.suggested_rewrite}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

export default function PromptEvaluatorPage() {
  const [searchParams] = useSearchParams()
  const preselectedAgentId = searchParams.get('agent') ?? ''
  const [mode, setMode] = useState<InputMode>('agent')
  const [agentId, setAgentId] = useState(preselectedAgentId)
  const [scope, setScope] = useState<PromptEvalScope>('effective')
  const [promptText, setPromptText] = useState('')
  const [displayResult, setDisplayResult] = useState<PromptEvalResult | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const agentsQuery = useAgents()
  const criteriaQuery = usePromptEvalCriteria()
  const runsQuery = usePromptEvalRuns(mode === 'agent' ? agentId || undefined : undefined)
  const runDetailQuery = usePromptEvalRun(selectedRunId ?? undefined)
  const evaluateMutation = useEvaluatePrompt()

  useEffect(() => {
    if (selectedRunId && runDetailQuery.data) {
      setDisplayResult(runDetailQuery.data)
    }
  }, [selectedRunId, runDetailQuery.data])

  function handleEvaluate() {
    setSelectedRunId(null)
    evaluateMutation.mutate(
      mode === 'agent' ? { agent_id: agentId, scope } : { prompt_text: promptText, scope: 'static' },
      { onSuccess: (data) => setDisplayResult(data) }
    )
  }

  const canEvaluate = mode === 'agent' ? !!agentId : promptText.trim().length > 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Prompt Evaluator"
        description="Score an agent's instruction (or any pasted prompt) against a prompt-engineering rubric, with concrete suggested fixes."
      />

      <Card>
        <div className="mb-4 flex items-center justify-between">
          <SegmentedControl
            aria-label="Input mode"
            value={mode}
            onChange={(v) => {
              setMode(v)
              setDisplayResult(null)
              setSelectedRunId(null)
            }}
            options={[
              { label: 'Existing agent', value: 'agent' },
              { label: 'Paste prompt text', value: 'text' },
            ]}
          />
          {mode === 'agent' && (
            <SegmentedControl
              aria-label="Evaluation scope"
              value={scope}
              onChange={setScope}
              options={[
                { label: 'Effective (base + skills)', value: 'effective' },
                { label: 'Base instruction only', value: 'static' },
              ]}
            />
          )}
        </div>

        {mode === 'agent' ? (
          <Select
            label="Agent"
            hideLabel={false}
            placeholder="Select an agent to evaluate..."
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            options={(agentsQuery.data ?? []).map((a) => ({ label: `${a.name} (${a.status})`, value: a.id }))}
          />
        ) : (
          <Textarea
            label="Prompt text"
            hideLabel={false}
            size="sm"
            rows={10}
            placeholder="Paste a system prompt / agent instruction to evaluate..."
            value={promptText}
            onChange={(e) => setPromptText(e.target.value)}
          />
        )}

        {evaluateMutation.isError && (
          <p className="mt-2 text-xs text-red-600 dark:text-red-400">
            {(evaluateMutation.error as Error)?.message ?? 'Evaluation failed.'}
          </p>
        )}

        <div className="mt-4">
          <Button
            leftIcon={<ClipboardCheck size={15} />}
            disabled={!canEvaluate}
            isPending={evaluateMutation.isPending}
            loadingLabel="Evaluating..."
            onClick={handleEvaluate}
          >
            Evaluate
          </Button>
        </div>
      </Card>

      {evaluateMutation.isPending && (
        <Card>
          <Skeleton className="mb-3 h-6 w-1/3" />
          <Skeleton className="mb-2 h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </Card>
      )}

      {displayResult && !evaluateMutation.isPending && <ResultPanel result={displayResult} />}

      {!displayResult && !evaluateMutation.isPending && (
        <EmptyState
          icon={FileText}
          title="No evaluation yet"
          message="Pick an agent or paste prompt text above, then click Evaluate to see a rubric-scored report."
        />
      )}

      <Card>
        <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
          <History size={13} /> Recent evaluations{mode === 'agent' && agentId ? ' for this agent' : ''}
        </h4>
        {runsQuery.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : !runsQuery.data?.length ? (
          <p className="text-xs text-slate-400">No evaluation runs yet.</p>
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {runsQuery.data.map((run) => (
              <button
                key={run.id}
                onClick={() => setSelectedRunId(run.id)}
                className={`flex w-full items-center justify-between gap-3 py-2 text-left text-xs hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
                  selectedRunId === run.id ? 'bg-slate-50 dark:bg-slate-800/50' : ''
                }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-700 dark:text-slate-300">
                      {run.agent_name ?? 'Pasted text'}
                    </span>
                    <Badge tone="neutral">{run.scope}</Badge>
                  </div>
                  <p className="mt-0.5 truncate text-slate-500 dark:text-slate-400">{run.summary}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={run.overall_score >= 80 ? 'success' : run.overall_score >= 60 ? 'warning' : 'danger'}>
                    {Math.round(run.overall_score)}
                  </Badge>
                  <span className="text-slate-400">{new Date(run.created_at).toLocaleString()}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>

      {criteriaQuery.data && (
        <details className="rounded-[--radius-card] border border-slate-200 p-3 text-xs dark:border-slate-800">
          <summary className="cursor-pointer font-medium text-slate-600 dark:text-slate-400">
            What's being checked ({criteriaQuery.data.length} criteria)
          </summary>
          <div className="mt-2 space-y-1.5">
            {criteriaQuery.data.map((c) => (
              <div key={c.id}>
                <span className="font-medium text-slate-700 dark:text-slate-300">{c.label}</span>{' '}
                <span className="text-[10px] uppercase text-slate-400">({c.method})</span>
                <p className="text-slate-500 dark:text-slate-400">{c.description}</p>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}
