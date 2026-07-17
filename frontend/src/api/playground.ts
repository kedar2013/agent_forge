import { useMutation } from '@tanstack/react-query'
import { api } from './client'
import type { PlaygroundRunRequest, PlaygroundRunResponse } from './types'

export function useRunPlayground() {
  return useMutation({
    mutationFn: (input: PlaygroundRunRequest) =>
      api.post<PlaygroundRunResponse>('/playground/run', input),
  })
}
