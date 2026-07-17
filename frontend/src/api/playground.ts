import { useMutation } from '@tanstack/react-query'
import { getStoredToken } from '../lib/auth'
import { parseError, providerKeyHeaders } from './chat'
import type { PlaygroundRunRequest, PlaygroundRunResponse } from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL

// Not routed through the shared `api` client (client.ts): Playground needs
// the provider-key headers and MissingApiKeyError parsing that only
// api/chat.ts's fetch-based helpers provide (see backend/app/agent_runtime/
// byok.py — a developer-role caller with no key on file gets exactly the
// same missing_api_key response chat does).
async function runPlayground(input: PlaygroundRunRequest): Promise<PlaygroundRunResponse> {
  const res = await fetch(`${BASE_URL}/playground/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getStoredToken() ?? ''}`,
      ...providerKeyHeaders(),
    },
    body: JSON.stringify(input),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export function useRunPlayground() {
  return useMutation({ mutationFn: runPlayground })
}
