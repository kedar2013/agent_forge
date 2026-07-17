import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export interface TraceSummary {
  invocation_id: string
  trace_id: string | null
  otel_trace_id: string | null
  agent_id: string | null
  agent_name: string | null
  status: string
  latency_ms: number
  tool_call_count: number
  invoked_by: string | null
  estimated_cost_usd: number | null
  created_at: string
}

export interface TraceListResponse {
  items: TraceSummary[]
  total: number
  limit: number
  offset: number
}

export interface SpanNode {
  id: string
  parent_id: string | null
  kind: 'root' | 'tool' | 'model' | 'transfer' | 'retry'
  name: string
  agent_name: string | null
  status: 'success' | 'error'
  start_offset_ms: number
  duration_ms: number
  input?: unknown
  output?: unknown
  error_message: string | null
}

export interface TraceDetail {
  summary: TraceSummary
  message: string | null
  response_text: string | null
  error_message: string | null
  spans: SpanNode[]
  spans_source: 'jaeger' | 'reconstructed'
  jaeger_trace_url: string | null
}

export interface TraceFilters {
  agent_id?: string
  status?: string
  limit?: number
  offset?: number
}

const KEY = ['debug-traces'] as const

export function useTraces(filters: TraceFilters) {
  const params = new URLSearchParams()
  if (filters.agent_id) params.set('agent_id', filters.agent_id)
  if (filters.status) params.set('status', filters.status)
  params.set('limit', String(filters.limit ?? 25))
  params.set('offset', String(filters.offset ?? 0))
  return useQuery({
    queryKey: [...KEY, filters],
    queryFn: () => api.get<TraceListResponse>(`/debug/traces?${params.toString()}`),
    refetchInterval: 15_000,
  })
}

export function useTraceDetail(invocationId: string | null) {
  return useQuery({
    queryKey: [...KEY, invocationId],
    queryFn: () => api.get<TraceDetail>(`/debug/traces/${invocationId}`),
    enabled: !!invocationId,
  })
}
