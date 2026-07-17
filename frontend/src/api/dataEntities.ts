import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  ConnectionInfo,
  DataConnection,
  DataEntity,
  DataEntityCreateInput,
  DataEntityUpdateInput,
  IntrospectedField,
  TableInfo,
  TestConnectionResult,
} from './types'

const KEY = ['data-entities'] as const

export function useDataEntities() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<DataEntity[]>('/data-entities') })
}

export function useDataEntity(id: string | undefined) {
  return useQuery({
    queryKey: [...KEY, id],
    queryFn: () => api.get<DataEntity>(`/data-entities/${id}`),
    enabled: !!id,
  })
}

export function useCreateDataEntity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: DataEntityCreateInput) => api.post<DataEntity>('/data-entities', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateDataEntity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...input }: DataEntityUpdateInput & { id: string }) =>
      api.patch<DataEntity>(`/data-entities/${id}`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useDeleteDataEntity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/data-entities/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useIntrospectSource() {
  return useMutation({
    mutationFn: ({ connection, table }: { connection: DataConnection; table: string }) =>
      api.post<{ fields: IntrospectedField[]; primary_key: string | null }>('/data-entities/introspect', {
        connection,
        table,
      }),
  })
}

/** MySQL connections discovered from the backend's own .env — lets the UI
 * offer a picker instead of asking admins to blind-type an env prefix. */
export function useConnections() {
  return useQuery({
    queryKey: [...KEY, 'connections'],
    queryFn: () => api.get<ConnectionInfo[]>('/data-entities/connections'),
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (prefix: string) =>
      api.post<TestConnectionResult>('/data-entities/test-connection', { connection_env_prefix: prefix }),
  })
}

export function useListTables() {
  return useMutation({
    mutationFn: (prefix: string) =>
      api.post<{ tables: TableInfo[] }>('/data-entities/list-tables', { connection_env_prefix: prefix }),
  })
}
