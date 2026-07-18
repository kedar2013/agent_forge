import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface DurableRunEntry {
  id: string
  agent_id: string | null
  agent_name: string | null
  status: string
  adk_session_id: string | null
  adk_invocation_id: string | null
  error_category: string | null
  error_message: string | null
  invoked_by: string | null
  created_at: string
  age_seconds: number
  is_stale: boolean
}

export interface DurableRunListResponse {
  items: DurableRunEntry[]
  total: number
  limit: number
  offset: number
}

export interface DurableRunResumeResponse {
  id: string
  status: string
  response_text: string | null
  error_message: string | null
}

export interface CircuitBreakerEntry {
  key: string
  state: string
  consecutive_failures: number
  cooldown_remaining_seconds: number | null
}

const KEY = ['reliability'] as const

export function useDurableRuns(status: string | undefined, offset: number, limit = 25) {
  return useQuery({
    queryKey: [...KEY, 'runs', status ?? 'all', offset, limit],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
      if (status) params.set('status', status)
      return api.get<DurableRunListResponse>(`/reliability/runs?${params.toString()}`)
    },
    refetchInterval: 15_000,
  })
}

export function useCircuitBreakers() {
  return useQuery({
    queryKey: [...KEY, 'circuit-breakers'],
    queryFn: () => api.get<CircuitBreakerEntry[]>('/reliability/circuit-breakers'),
    refetchInterval: 15_000,
  })
}

export function useResumeDurableRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (invocationLogId: string) =>
      api.post<DurableRunResumeResponse>(`/reliability/runs/${invocationLogId}/resume`),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY, 'runs'] }),
  })
}
