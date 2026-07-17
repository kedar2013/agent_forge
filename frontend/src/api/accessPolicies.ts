import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { AccessPolicy, AccessPolicyCreateInput, AccessPolicyUpdateInput } from './types'

const KEY = ['access-policies'] as const

export function useAccessPolicies() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<AccessPolicy[]>('/access-policies') })
}

export function useAccessPolicy(id: string | undefined) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api.get<AccessPolicy>(`/access-policies/${id}`),
    enabled: !!id,
  })
}

export function useCreateAccessPolicy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: AccessPolicyCreateInput) => api.post<AccessPolicy>('/access-policies', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateAccessPolicy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...input }: AccessPolicyUpdateInput & { id: string }) =>
      api.patch<AccessPolicy>(`/access-policies/${id}`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useDeleteAccessPolicy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/access-policies/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
