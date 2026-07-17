import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Tool, ToolCreateInput } from './types'

const KEY = ['tools'] as const

export function useTools() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<Tool[]>('/tools') })
}

export function useTool(id: string | undefined) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api.get<Tool>(`/tools/${id}`),
    enabled: !!id,
  })
}

export function useCreateTool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ToolCreateInput) => api.post<Tool>('/tools', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateTool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...input }: Partial<ToolCreateInput> & { id: string }) =>
      api.patch<Tool>(`/tools/${id}`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useDeleteTool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/tools/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
