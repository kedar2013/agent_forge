import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Skill, SkillCreateInput } from './types'

const KEY = ['skills'] as const

export function useSkills() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<Skill[]>('/skills') })
}

export function useSkill(id: string | undefined) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api.get<Skill>(`/skills/${id}`),
    enabled: !!id,
  })
}

export function useCreateSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: SkillCreateInput) => api.post<Skill>('/skills', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...input }: Partial<SkillCreateInput> & { id: string }) =>
      api.patch<Skill>(`/skills/${id}`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useDeleteSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/skills/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
