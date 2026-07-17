import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export interface AppUser {
  id: string
  email: string
  soeid: string | null
  role: 'admin' | 'viewer' | 'chat_user'
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
}

export interface CreateNamedUserInput {
  email: string
  password: string
  role: 'admin' | 'viewer' | 'chat_user'
  soeid?: string
}

export interface UpdateUserInput {
  id: string
  soeid?: string | null
  role?: 'admin' | 'viewer' | 'chat_user'
}

const KEY = ['users'] as const

export function useUsers() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<AppUser[]>('/auth/users') })
}

export function useApproveUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api.post<AppUser>(`/auth/${userId}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useRejectUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api.post<AppUser>(`/auth/${userId}/reject`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useCreateNamedUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateNamedUserInput) => api.post<AppUser>('/auth/users', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...patch }: UpdateUserInput) => api.patch<AppUser>(`/auth/users/${id}`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
