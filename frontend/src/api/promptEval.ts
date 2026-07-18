import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export type PromptEvalScope = 'static' | 'effective'
export type PromptEvalMethod = 'deterministic' | 'judged'
export type PromptEvalSeverity = 'info' | 'warning' | 'critical'

export interface PromptEvalCriterionInfo {
  id: string
  label: string
  category: string
  method: PromptEvalMethod
  weight: number
  description: string
}

export interface PromptEvalRequest {
  agent_id?: string
  prompt_text?: string
  scope?: PromptEvalScope
  model?: string
}

export interface CriterionResultOut {
  id: string
  label: string
  category: string
  method: PromptEvalMethod
  weight: number
  score: number | null
  max_score: number
  applicable: boolean
  severity: PromptEvalSeverity
  rationale: string
  suggestion: string | null
}

export interface PromptEvalResult {
  id: string
  agent_id: string | null
  agent_name: string | null
  scope: string
  source_text: string
  overall_score: number
  criteria: CriterionResultOut[]
  summary: string | null
  suggested_rewrite: string | null
  model_used: string | null
  judge_error: string | null
  created_at: string
}

export interface PromptEvalRunSummary {
  id: string
  agent_id: string | null
  agent_name: string | null
  scope: string
  overall_score: number
  summary: string | null
  model_used: string | null
  judge_error: string | null
  created_by: string | null
  created_at: string
}

const CRITERIA_KEY = ['prompt-eval', 'criteria'] as const
const RUNS_KEY = ['prompt-eval', 'runs'] as const

export function usePromptEvalCriteria() {
  return useQuery({
    queryKey: CRITERIA_KEY,
    queryFn: () => api.get<PromptEvalCriterionInfo[]>('/prompt-eval/criteria'),
    staleTime: Infinity, // static catalog — never changes without a deploy
  })
}

export function useEvaluatePrompt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: PromptEvalRequest) => api.post<PromptEvalResult>('/prompt-eval/evaluate', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: RUNS_KEY }),
  })
}

export function usePromptEvalRuns(agentId?: string) {
  return useQuery({
    queryKey: [...RUNS_KEY, agentId ?? 'all'],
    queryFn: () =>
      api.get<PromptEvalRunSummary[]>(`/prompt-eval/runs${agentId ? `?agent_id=${agentId}` : ''}`),
  })
}

export function usePromptEvalRun(id: string | undefined) {
  return useQuery({
    queryKey: [...RUNS_KEY, 'detail', id ?? ''],
    queryFn: () => api.get<PromptEvalResult>(`/prompt-eval/runs/${id}`),
    enabled: !!id,
  })
}
