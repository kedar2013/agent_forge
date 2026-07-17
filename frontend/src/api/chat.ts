import { getUserToken } from '../lib/auth'
import { getProviderKey, type Provider } from '../lib/providerKeys'

const BASE_URL = import.meta.env.VITE_API_BASE_URL

export class ChatApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Thrown when the bot's model provider needs a key the visitor hasn't
 * supplied yet — see backend/app/agent_runtime/byok.py's MissingApiKeyError,
 * whose `detail` shape this mirrors. Caught in ChatPage/PlaygroundChat to
 * open a provider-scoped key prompt instead of a generic error bubble. */
export class MissingApiKeyError extends ChatApiError {
  provider: Provider
  constructor(provider: Provider, message: string) {
    super(400, message)
    this.provider = provider
  }
}

async function parseError(res: Response): Promise<never> {
  let detail = res.statusText
  try {
    const body = await res.json()
    if (body.detail && typeof body.detail === 'object' && body.detail.error === 'missing_api_key') {
      throw new MissingApiKeyError(body.detail.provider, body.detail.message)
    }
    detail = body.detail ?? JSON.stringify(body)
  } catch (err) {
    if (err instanceof MissingApiKeyError) throw err
    // not JSON — fall back to statusText
  }
  throw new ChatApiError(res.status, detail)
}

/** Both provider-key headers, only set when the caller actually has a key
 * stored — omitting an empty header rather than sending a blank string. */
function providerKeyHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const geminiKey = getProviderKey('gemini')
  const anthropicKey = getProviderKey('anthropic')
  if (geminiKey) headers['X-Gemini-Api-Key'] = geminiKey
  if (anthropicKey) headers['X-Anthropic-Api-Key'] = anthropicKey
  return headers
}

export interface RegisterInput {
  email: string
  password: string
  // Self-serve roles only — omit for the default chat_user. "developer" gets
  // agent-onboarding + chat access, still admin-approved like any signup,
  // and every agent they later publish goes through its own review queue.
  role?: 'chat_user' | 'developer'
}

export interface LoginInput {
  email: string
  password: string
}

export interface LoginResult {
  token: string
  email: string
  role: 'admin' | 'viewer' | 'chat_user' | 'developer'
}

export async function register(input: RegisterInput): Promise<void> {
  const res = await fetch(`${BASE_URL}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) await parseError(res)
}

export async function login(input: LoginInput): Promise<LoginResult> {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

/** Verifies an admin-token login attempt server-side — see the matching
 * backend endpoint's docstring for why this can never be a client-side
 * comparison (Vite bakes VITE_* values into the shipped JS bundle). */
export async function verifyAdminToken(token: string): Promise<boolean> {
  const res = await fetch(`${BASE_URL}/auth/verify-admin-token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  return res.ok
}

export interface ChatToolCall {
  name: string
  input: unknown
  output: unknown
}

export interface ChatMessageResult {
  response_text: string
  tool_calls: ChatToolCall[]
  latency_ms: number
  session_id: string
}

export interface ChatHistoryTurn {
  message: string
  response_text: string
  created_at: string
}

export async function fetchChatHistory(sessionId: string): Promise<ChatHistoryTurn[]> {
  const res = await fetch(`${BASE_URL}/chat/history?session_id=${encodeURIComponent(sessionId)}`, {
    headers: { Authorization: `Bearer ${getUserToken() ?? ''}` },
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export interface ConversationSummary {
  session_id: string
  title: string
  last_message_at: string
  message_count: number
  agent_name: string | null
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(`${BASE_URL}/chat/conversations`, {
    headers: { Authorization: `Bearer ${getUserToken() ?? ''}` },
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export interface OrchestratorSummary {
  name: string
  description: string | null
  is_multi_specialist: boolean
}

/** Every bot the current user can pick to talk to — a multi-specialist
 * orchestrator (routes to several domain specialists) or a standalone
 * agent, both surfaced the same way. */
export async function fetchOrchestrators(): Promise<OrchestratorSummary[]> {
  const res = await fetch(`${BASE_URL}/chat/orchestrators`, {
    headers: { Authorization: `Bearer ${getUserToken() ?? ''}` },
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export interface MyUsageDayPoint {
  date: string
  invocations: number
  cost_usd: number
}

export interface MyUsageAgentRow {
  agent_name: string
  invocation_count: number
  total_tokens: number
  total_cost_usd: number
}

export interface MyUsageSummary {
  total_invocations: number
  total_tokens: number
  total_cost_usd: number
  error_count: number
  last_active: string | null
  by_day: MyUsageDayPoint[]
  by_agent: MyUsageAgentRow[]
}

export async function fetchMyUsage(rangeDays = 30): Promise<MyUsageSummary> {
  const res = await fetch(`${BASE_URL}/chat/usage?range_days=${rangeDays}`, {
    headers: { Authorization: `Bearer ${getUserToken() ?? ''}` },
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function sendChatMessage(
  message: string,
  sessionId: string,
  stateDelta?: Record<string, unknown>,
  agentName?: string,
): Promise<ChatMessageResult> {
  const res = await fetch(`${BASE_URL}/chat/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getUserToken() ?? ''}`,
      ...providerKeyHeaders(),
    },
    body: JSON.stringify({ message, session_id: sessionId, state_delta: stateDelta, agent_name: agentName }),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export type ChatStreamEvent =
  | { type: 'transfer'; to: string }
  | { type: 'tool_call_start'; name: string; input: Record<string, unknown> }
  | { type: 'tool_call_end'; name: string }
  | { type: 'error'; message: string }
  | {
      type: 'done'
      response_text: string
      tool_calls: ChatToolCall[]
      latency_ms: number
      session_id: string
    }

/** Streaming twin of sendChatMessage — calls onEvent live as the agent
 * transfers/calls tools, so the UI can show progress instead of a blank
 * wait during multi-tool-call chains. Resolves with the same shape
 * sendChatMessage returns, once the "done" event arrives. */
export async function sendChatMessageStream(
  message: string,
  sessionId: string,
  onEvent: (event: ChatStreamEvent) => void,
  agentName?: string,
): Promise<ChatMessageResult> {
  const res = await fetch(`${BASE_URL}/chat/message/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getUserToken() ?? ''}`,
      ...providerKeyHeaders(),
    },
    body: JSON.stringify({ message, session_id: sessionId, agent_name: agentName }),
  })
  if (!res.ok) await parseError(res)
  if (!res.body) throw new ChatApiError(0, 'No response body from the server.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResult: ChatMessageResult | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      const event = JSON.parse(line) as ChatStreamEvent
      onEvent(event)
      if (event.type === 'error') throw new ChatApiError(502, event.message)
      if (event.type === 'done') {
        finalResult = {
          response_text: event.response_text,
          tool_calls: event.tool_calls,
          latency_ms: event.latency_ms,
          session_id: event.session_id,
        }
      }
    }
  }

  if (!finalResult) throw new ChatApiError(0, 'The stream ended without a response.')
  return finalResult
}
