import { useEffect, useRef, useState } from 'react'
import { Bot, Send, User, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import { useRunPlayground } from '../../api/playground'
import type { ToolCallTrace } from '../../api/types'
import { markTestedIfPending } from '../../lib/testGate'
import { AssistantContent, fmtTime, TypingIndicator } from '../chat/MessageRendering'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Textarea from '../ui/Textarea'

interface Turn {
  role: 'user' | 'assistant'
  text: string
  toolCalls?: ToolCallTrace[]
  turnIndex: number
  at: number
  isError?: boolean
}

export default function PlaygroundChat({ agentId }: { agentId: string }) {
  const sessionIdRef = useRef(crypto.randomUUID())
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [stateText, setStateText] = useState('{}')
  const [stateError, setStateError] = useState<string | null>(null)
  const runPlayground = useRunPlayground()
  const nextTurnIndex = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, runPlayground.isPending])

  // Shared by the compose-box submit AND by clicking a chip in
  // AssistantContent's OptionsView — same "send this value as the next
  // message" flow as ChatPage.tsx's submitMessage.
  async function submitMessage(message: string) {
    if (!message) return

    let stateDelta: Record<string, unknown> | undefined
    try {
      const parsed = stateText.trim() ? JSON.parse(stateText) : {}
      stateDelta = Object.keys(parsed).length ? parsed : undefined
      setStateError(null)
    } catch {
      setStateError('Session state must be valid JSON.')
      return
    }

    const turnIndex = nextTurnIndex.current++
    setTurns((prev) => [...prev, { role: 'user', text: message, turnIndex, at: Date.now() }])

    try {
      const result = await runPlayground.mutateAsync({
        agent_id: agentId,
        message,
        session_id: sessionIdRef.current,
        state_delta: stateDelta,
      })
      setTurns((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: result.response_text,
          toolCalls: result.tool_calls,
          turnIndex,
          at: Date.now(),
        },
      ])
      markTestedIfPending(agentId)
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', text: (err as Error).message, turnIndex, at: Date.now(), isError: true },
      ])
      toast.error('Playground run failed — see the chat for details')
    }
  }

  function handleSend(e: React.FormEvent) {
    e.preventDefault()
    const message = input.trim()
    if (!message) return
    setInput('')
    submitMessage(message)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend(e)
    }
  }

  const allToolCalls = turns.flatMap((t) =>
    (t.toolCalls ?? []).map((call) => ({ ...call, turnIndex: t.turnIndex })),
  )

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Card className="col-span-1 flex h-[75vh] flex-col p-0 lg:col-span-2">
        <details className="border-b border-slate-200 px-4 py-2 text-xs dark:border-slate-800">
          <summary className="cursor-pointer font-medium text-slate-600 dark:text-slate-300">
            Session state (optional)
          </summary>
          <div className="mt-2">
            <textarea
              rows={2}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              value={stateText}
              onChange={(e) => {
                setStateText(e.target.value)
                setStateError(null)
              }}
              placeholder='{"grade": 7, "subject": "SST", "book_id": 6, "language": "english"}'
            />
            <p className="mt-1 text-slate-500">
              Seeds ADK session state for this conversation — needed for agents whose
              instructions reference <code>{'{variable}'}</code> placeholders (grade, subject,
              language, book_id, …). Sent with every message in this session.
            </p>
            {stateError && <p className="mt-1 text-red-600">{stateError}</p>}
          </div>
        </details>
        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
          {turns.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-slate-400">
              <Bot size={28} className="text-slate-300 dark:text-slate-600" />
              <p className="text-sm">Send a message to start testing this draft agent.</p>
            </div>
          )}
          {turns.map((turn, i) => (
            <div key={i} className={`flex items-end gap-2 ${turn.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <div
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                  turn.role === 'user'
                    ? 'bg-slate-700 text-white dark:bg-slate-600'
                    : 'bg-brand-600 text-white'
                }`}
              >
                {turn.role === 'user' ? <User size={14} /> : <Bot size={14} />}
              </div>
              <div className={`flex max-w-[80%] flex-col ${turn.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div
                  className={`rounded-2xl px-4 py-2.5 text-sm ${
                    turn.role === 'user'
                      ? 'rounded-br-sm bg-brand-600 text-white'
                      : turn.isError
                        ? 'rounded-bl-sm border border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300'
                        : 'rounded-bl-sm bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100'
                  }`}
                >
                  {turn.role === 'assistant' && !turn.isError ? (
                    <AssistantContent text={turn.text} onOptionSelect={submitMessage} disabled={runPlayground.isPending} />
                  ) : (
                    <span className="whitespace-pre-wrap">{turn.text}</span>
                  )}
                </div>
                <span className="mt-1 px-1 text-[11px] text-slate-400">{fmtTime(turn.at)}</span>
              </div>
            </div>
          ))}
          {runPlayground.isPending && (
            <div className="flex items-end gap-2">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white">
                <Bot size={14} />
              </div>
              <TypingIndicator />
            </div>
          )}
        </div>
        <form onSubmit={handleSend} className="flex gap-2 border-t border-slate-200 p-3 dark:border-slate-800">
          <Textarea
            label="Message"
            rows={1}
            className="max-h-32 flex-1 resize-none py-2"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
          />
          <Button type="submit" disabled={runPlayground.isPending || !input.trim()} className="self-end" leftIcon={<Send size={15} />}>
            Send
          </Button>
        </form>
      </Card>

      <Card className="h-[75vh] overflow-y-auto">
        <div className="mb-2 flex items-center gap-1.5 text-sm font-medium">
          <Wrench size={14} className="text-slate-400" /> Tool call trace
        </div>
        {allToolCalls.length === 0 && <p className="text-xs text-slate-500">No tool calls yet.</p>}
        <div className="space-y-2">
          {allToolCalls.map((call, i) => (
            <div key={i} className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
              <div className="mb-1 flex items-center justify-between">
                <span className="font-mono font-semibold">{call.name}</span>
                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500 dark:bg-slate-800">
                  turn {call.turnIndex}
                </span>
              </div>
              <div className="mb-1">
                <span className="text-slate-500">input: </span>
                <code className="break-all">{JSON.stringify(call.input)}</code>
              </div>
              <div>
                <span className="text-slate-500">output: </span>
                <code className="break-all">{JSON.stringify(call.output)}</code>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
