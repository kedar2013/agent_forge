import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { getStoredToken } from '../lib/auth'
import type { Agent, AgentCreateInput, AgentUpdateInput, AgentVersion, PublishRequest, PublishResult } from './types'

const KEY = ['agents'] as const
const agentKey = (id: string) => [...KEY, id] as const
const versionsKey = (id: string) => [...KEY, id, 'versions'] as const

export function useAgents() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<Agent[]>('/agents') })
}

export function useAgent(id: string | undefined) {
  return useQuery({
    queryKey: agentKey(id ?? ''),
    queryFn: () => api.get<Agent>(`/agents/${id}`),
    enabled: !!id,
  })
}

export function useAgentVersions(id: string | undefined) {
  return useQuery({
    queryKey: versionsKey(id ?? ''),
    queryFn: () => api.get<AgentVersion[]>(`/agents/${id}/versions`),
    enabled: !!id,
  })
}

export function useCreateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: AgentCreateInput) => api.post<Agent>('/agents', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateAgent(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: AgentUpdateInput) => api.patch<Agent>(`/agents/${id}`, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKey(id) })
      qc.invalidateQueries({ queryKey: KEY })
    },
  })
}

export function useArchiveAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<Agent>(`/agents/${id}/archive`),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: agentKey(id) })
      qc.invalidateQueries({ queryKey: KEY })
    },
  })
}

export function useCloneAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<Agent>(`/agents/${id}/clone`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useRollbackAgent(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (version: number) =>
      api.post<AgentVersion>(`/agents/${id}/versions/${version}/rollback`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKey(id) })
      qc.invalidateQueries({ queryKey: versionsKey(id) })
      qc.invalidateQueries({ queryKey: KEY })
    },
  })
}

export interface AgentImportResult {
  agent_id: string
  agent_name: string
  tools_created: string[]
  tools_reused: string[]
  skills_created: string[]
  skills_reused: string[]
  sub_agents_linked: string[]
  sub_agents_missing: string[]
}

export async function exportAgent(id: string, name: string): Promise<void> {
  const base = import.meta.env.VITE_API_BASE_URL
  const res = await fetch(`${base}/agents/${id}/export`, {
    headers: { Authorization: `Bearer ${getStoredToken() ?? ''}` },
  })
  if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name.replace(/[^a-z0-9_-]+/gi, '_')}.agent.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function useImportAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (exportData: unknown) => api.post<AgentImportResult>('/agents/import', exportData),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function usePublishAgent(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (published_by?: string) =>
      api.post<PublishResult>(`/agents/${id}/publish`, { published_by }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKey(id) })
      qc.invalidateQueries({ queryKey: versionsKey(id) })
      qc.invalidateQueries({ queryKey: KEY })
      qc.invalidateQueries({ queryKey: PUBLISH_REQUESTS_KEY })
    },
  })
}

// --- Publish-request review queue (developer publish -> admin approval) ---

const PUBLISH_REQUESTS_KEY = ['publish-requests'] as const

export function usePublishRequests(status?: string) {
  return useQuery({
    queryKey: [...PUBLISH_REQUESTS_KEY, status ?? 'pending'],
    queryFn: () => api.get<PublishRequest[]>(`/agents/publish-requests?status=${status ?? 'pending'}`),
  })
}

export function useMyPublishRequests() {
  return useQuery({
    queryKey: [...PUBLISH_REQUESTS_KEY, 'mine'],
    queryFn: () => api.get<PublishRequest[]>('/agents/publish-requests/mine'),
  })
}

export function useApprovePublishRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, review_note }: { id: string; review_note?: string }) =>
      api.post<PublishRequest>(`/agents/publish-requests/${id}/approve`, { review_note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PUBLISH_REQUESTS_KEY })
      qc.invalidateQueries({ queryKey: KEY })
    },
  })
}

export function useRejectPublishRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, review_note }: { id: string; review_note?: string }) =>
      api.post<PublishRequest>(`/agents/publish-requests/${id}/reject`, { review_note }),
    onSuccess: () => qc.invalidateQueries({ queryKey: PUBLISH_REQUESTS_KEY }),
  })
}

function useAgentMutation(id: string) {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: agentKey(id) })
  return { invalidate }
}

export function useAttachTool(agentId: string) {
  const { invalidate } = useAgentMutation(agentId)
  return useMutation({
    mutationFn: (tool_id: string) => api.post<void>(`/agents/${agentId}/tools`, { tool_id }),
    onSuccess: invalidate,
  })
}

export function useDetachTool(agentId: string) {
  const { invalidate } = useAgentMutation(agentId)
  return useMutation({
    mutationFn: (toolId: string) => api.delete<void>(`/agents/${agentId}/tools/${toolId}`),
    onSuccess: invalidate,
  })
}

export function useAttachSkill(agentId: string) {
  const { invalidate } = useAgentMutation(agentId)
  return useMutation({
    mutationFn: ({ skill_id, attach_order }: { skill_id: string; attach_order: number }) =>
      api.post<void>(`/agents/${agentId}/skills`, { skill_id, attach_order }),
    onSuccess: invalidate,
  })
}

export function useDetachSkill(agentId: string) {
  const { invalidate } = useAgentMutation(agentId)
  return useMutation({
    mutationFn: (skillId: string) => api.delete<void>(`/agents/${agentId}/skills/${skillId}`),
    onSuccess: invalidate,
  })
}

export function useAttachSubagent(agentId: string) {
  const { invalidate } = useAgentMutation(agentId)
  return useMutation({
    mutationFn: (child_agent_id: string) =>
      api.post<void>(`/agents/${agentId}/subagents`, { child_agent_id }),
    onSuccess: invalidate,
  })
}

export function useDetachSubagent(agentId: string) {
  const { invalidate } = useAgentMutation(agentId)
  return useMutation({
    mutationFn: (childId: string) => api.delete<void>(`/agents/${agentId}/subagents/${childId}`),
    onSuccess: invalidate,
  })
}
