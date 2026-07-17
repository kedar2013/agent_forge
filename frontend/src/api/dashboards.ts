import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import { getStoredToken } from '../lib/auth'
import type {
  AgentHealthRow,
  AgentUsageRow,
  ConfigChangeListResponse,
  InvocationDetail,
  InvocationListResponse,
  MonitoringSummary,
  ToolHealthRow,
  ToolUsageRow,
  UsageSummary,
  UsageTimeseriesPoint,
  UserUsageRow,
} from './types'

// --- Monitoring ---

export function useMonitoringSummary(windowHours: number) {
  return useQuery({
    queryKey: ['dashboards', 'monitoring', 'summary', windowHours],
    queryFn: () => api.get<MonitoringSummary>(`/dashboards/monitoring/summary?window_hours=${windowHours}`),
    refetchInterval: 30_000,
  })
}

export function useAgentHealth(windowHours: number) {
  return useQuery({
    queryKey: ['dashboards', 'monitoring', 'agents', windowHours],
    queryFn: () => api.get<AgentHealthRow[]>(`/dashboards/monitoring/agents?window_hours=${windowHours}`),
    refetchInterval: 30_000,
  })
}

export function useToolHealth(windowHours: number) {
  return useQuery({
    queryKey: ['dashboards', 'monitoring', 'tools', windowHours],
    queryFn: () => api.get<ToolHealthRow[]>(`/dashboards/monitoring/tools?window_hours=${windowHours}`),
    refetchInterval: 30_000,
  })
}

// --- Usage ---

export function useUsageSummary(rangeDays: number) {
  return useQuery({
    queryKey: ['dashboards', 'usage', 'summary', rangeDays],
    queryFn: () => api.get<UsageSummary>(`/dashboards/usage/summary?range_days=${rangeDays}`),
    refetchInterval: 30_000,
  })
}

export function useUsageTimeseries(rangeDays: number) {
  return useQuery({
    queryKey: ['dashboards', 'usage', 'timeseries', rangeDays],
    queryFn: () => api.get<UsageTimeseriesPoint[]>(`/dashboards/usage/timeseries?range_days=${rangeDays}`),
    refetchInterval: 30_000,
  })
}

export function useAgentUsage(rangeDays: number) {
  return useQuery({
    queryKey: ['dashboards', 'usage', 'agents', rangeDays],
    queryFn: () => api.get<AgentUsageRow[]>(`/dashboards/usage/agents?range_days=${rangeDays}`),
    refetchInterval: 30_000,
  })
}

export function useToolUsage(rangeDays: number) {
  return useQuery({
    queryKey: ['dashboards', 'usage', 'tools', rangeDays],
    queryFn: () => api.get<ToolUsageRow[]>(`/dashboards/usage/tools?range_days=${rangeDays}`),
    refetchInterval: 30_000,
  })
}

export function useUserUsage(rangeDays: number) {
  return useQuery({
    queryKey: ['dashboards', 'usage', 'users', rangeDays],
    queryFn: () => api.get<UserUsageRow[]>(`/dashboards/usage/users?range_days=${rangeDays}`),
    refetchInterval: 30_000,
  })
}

// --- Audit ---

export interface InvocationFilters {
  agent_id?: string
  status?: string
  from_date?: string
  to_date?: string
  limit?: number
  offset?: number
}

function toQueryString(filters: Record<string, unknown>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return params.toString()
}

export function useInvocationAudit(filters: InvocationFilters) {
  const qs = toQueryString(filters as Record<string, unknown>)
  return useQuery({
    queryKey: ['dashboards', 'audit', 'invocations', filters],
    queryFn: () => api.get<InvocationListResponse>(`/dashboards/audit/invocations?${qs}`),
    refetchInterval: 30_000,
  })
}

export function useInvocationDetail(id: string | null) {
  return useQuery({
    queryKey: ['dashboards', 'audit', 'invocation', id],
    queryFn: () => api.get<InvocationDetail>(`/dashboards/audit/invocations/${id}`),
    enabled: !!id,
  })
}

export interface ConfigChangeFilters {
  entity_type?: string
  entity_id?: string
  from_date?: string
  to_date?: string
  limit?: number
  offset?: number
}

export function useConfigAudit(filters: ConfigChangeFilters) {
  const qs = toQueryString(filters as Record<string, unknown>)
  return useQuery({
    queryKey: ['dashboards', 'audit', 'config-changes', filters],
    queryFn: () => api.get<ConfigChangeListResponse>(`/dashboards/audit/config-changes?${qs}`),
    refetchInterval: 30_000,
  })
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL

export async function downloadExport(
  kind: 'invocations' | 'config-changes',
  format: 'csv' | 'json',
  filters: Record<string, unknown> = {},
): Promise<void> {
  const qs = toQueryString({ ...filters, format })
  const res = await fetch(`${BASE_URL}/dashboards/audit/${kind}/export?${qs}`, {
    headers: { Authorization: `Bearer ${getStoredToken() ?? ''}` },
  })
  if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${kind}.${format}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
