import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface ScilRouteCount {
  route: string
  count: number
  llm_calls: number
}

export interface ScilMetricsSummary {
  total_requests: number
  llm_calls: number
  llm_calls_avoided: number
  cache_hit_rate: number
  retried_turns: number
  retry_success_rate: number
  avg_latency_ms_by_route: Record<string, number>
  routes: ScilRouteCount[]
  hallucination_flags: number
}

export interface ScilTimeseriesPoint {
  date: string
  route: string
  count: number
  llm_calls: number
}

export interface ScilCacheEntry {
  id: number
  agent_id: string
  agent_name: string | null
  input_text: string
  output_type: string
  hit_count: number
  validated: boolean
  created_at: string
  last_hit_at: string | null
  similarity_threshold: number
}

export interface ScilCacheListResponse {
  items: ScilCacheEntry[]
  total: number
  limit: number
  offset: number
}

export interface ScilCacheSimilarityCheckResult {
  similarity: number
  threshold: number
  would_hit: boolean
}

export function useCheckCacheSimilarity() {
  return useMutation({
    mutationFn: (payload: { agent_id: string; text_a: string; text_b: string }) =>
      api.post<ScilCacheSimilarityCheckResult>('/scil/cache/similarity-check', payload),
  })
}

export interface ScilCorrectionEntry {
  id: number
  agent_id: string
  agent_name: string | null
  input_text: string
  error_signature: string
  error_detail: string
  correction_source: string
  reuse_count: number
  created_at: string
}

export interface ScilCorrectionListResponse {
  items: ScilCorrectionEntry[]
  total: number
  limit: number
  offset: number
}

const KEY = ['scil'] as const

export function useScilSummary(rangeDays: number) {
  const from = new Date(Date.now() - rangeDays * 86_400_000).toISOString()
  return useQuery({
    queryKey: [...KEY, 'summary', rangeDays],
    queryFn: () => api.get<ScilMetricsSummary>(`/scil/metrics/summary?from_date=${encodeURIComponent(from)}`),
    refetchInterval: 30_000,
  })
}

export function useScilTimeseries(rangeDays: number) {
  return useQuery({
    queryKey: [...KEY, 'timeseries', rangeDays],
    queryFn: () => api.get<ScilTimeseriesPoint[]>(`/scil/metrics/timeseries?range_days=${rangeDays}`),
    refetchInterval: 30_000,
  })
}

export function useScilCacheEntries(offset: number, limit = 25) {
  return useQuery({
    queryKey: [...KEY, 'cache', offset, limit],
    queryFn: () => api.get<ScilCacheListResponse>(`/scil/cache/entries?limit=${limit}&offset=${offset}`),
    refetchInterval: 30_000,
  })
}

export function useScilCorrections(offset: number, limit = 25, errorSignature?: string) {
  return useQuery({
    queryKey: [...KEY, 'corrections', offset, limit, errorSignature ?? null],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
      if (errorSignature) params.set('error_signature', errorSignature)
      return api.get<ScilCorrectionListResponse>(`/scil/corrections?${params.toString()}`)
    },
    refetchInterval: 30_000,
  })
}

export function useDeleteCacheEntry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/scil/cache/entries/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function usePurgeAgentCache() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string) => api.post<void>('/scil/cache/purge', { agent_id: agentId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useDeleteCorrection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/scil/corrections/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

// --- Eval framework: golden-question regression suite ----------------------

export interface ScilEvalCaseEntry {
  id: number
  agent_id: string
  question: string
  expected_criteria: string
  is_active: boolean
  created_at: string
  last_passed: boolean | null
  last_run_at: string | null
}

export interface ScilEvalRunResult {
  case_id: number
  question: string
  passed: boolean
  actual_response: string
  judge_reasoning: string
  latency_ms: number
}

export interface ScilEvalBatchSummary {
  batch_id: string
  agent_id: string
  total: number
  passed: number
  results: ScilEvalRunResult[]
  created_at: string
}

export function useEvalCases(agentId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, 'eval-cases', agentId],
    queryFn: () => api.get<ScilEvalCaseEntry[]>(`/scil/eval/cases?agent_id=${agentId}`),
    enabled: !!agentId,
  })
}

export function useCreateEvalCase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { agent_id: string; question: string; expected_criteria: string }) =>
      api.post<ScilEvalCaseEntry>('/scil/eval/cases', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY, 'eval-cases'] }),
  })
}

export function useDeleteEvalCase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/scil/eval/cases/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY, 'eval-cases'] }),
  })
}

export function useLatestEvalBatch(agentId: string | undefined) {
  return useQuery({
    queryKey: [...KEY, 'eval-runs-latest', agentId],
    queryFn: () => api.get<ScilEvalBatchSummary>(`/scil/eval/runs/latest?agent_id=${agentId}`),
    enabled: !!agentId,
    retry: false,
  })
}

export function useRunEvalBatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (agentId: string) => api.post<ScilEvalBatchSummary>('/scil/eval/run', { agent_id: agentId }),
    onSuccess: (_data, agentId) => {
      qc.invalidateQueries({ queryKey: [...KEY, 'eval-cases', agentId] })
      qc.invalidateQueries({ queryKey: [...KEY, 'eval-runs-latest', agentId] })
    },
  })
}

// --- Eval framework: sampled live-traffic groundedness ----------------------

export interface ScilGroundednessSummaryPoint {
  date: string
  grounded: number
  ungrounded: number
}

export interface ScilGroundednessSampleEntry {
  id: number
  agent_id: string
  agent_name: string | null
  input_text: string
  grounded: boolean
  reason: string | null
  created_at: string
}

export interface ScilGroundednessSummary {
  total_samples: number
  grounded_rate: number
  timeseries: ScilGroundednessSummaryPoint[]
  recent_flagged: ScilGroundednessSampleEntry[]
}

export function useGroundednessSummary(rangeDays: number, agentId?: string) {
  return useQuery({
    queryKey: [...KEY, 'groundedness-summary', rangeDays, agentId ?? null],
    queryFn: () => {
      const params = new URLSearchParams({ range_days: String(rangeDays) })
      if (agentId) params.set('agent_id', agentId)
      return api.get<ScilGroundednessSummary>(`/scil/eval/groundedness/summary?${params.toString()}`)
    },
    refetchInterval: 30_000,
  })
}
