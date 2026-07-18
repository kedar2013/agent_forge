import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bot, Bug, LogOut, Menu, MessageSquarePlus, Send, User, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  ChatApiError,
  fetchChatHistory,
  fetchConversations,
  fetchOrchestrators,
  MissingApiKeyError,
  sendChatMessageStream,
  type ConversationSummary,
  type OrchestratorSummary,
} from '../api/chat'
import ApiKeyPrompt from '../components/chat/ApiKeyPrompt'
import { AssistantContent, BotAvatar, fmtTime } from '../components/chat/MessageRendering'
import { LiveThinking, ThoughtProcessSummary, stepFromEvent, type ThinkingStep } from '../components/chat/ThinkingSteps'
import Button from '../components/ui/Button'
import HelpButton from '../components/ui/HelpButton'
import Logo from '../components/ui/Logo'
import StudioCredit from '../components/ui/StudioCredit'
import Textarea from '../components/ui/Textarea'
import ThemeToggle from '../components/ui/ThemeToggle'
import UsageButton from '../components/ui/UsageButton'
import { groupConversationsByRecency } from '../lib/conversationGroups'
import { humanizeName } from '../lib/humanize'
import {
  clearUserSession,
  getLastActiveSessionId,
  getStoredRole,
  getStoredToken,
  getUserEmail,
  getUserToken,
  setLastActiveSessionId,
} from '../lib/auth'
import type { Provider } from '../lib/providerKeys'

interface Turn {
  role: 'user' | 'assistant'
  text: string
  at: number
  isError?: boolean
  thinkingSteps?: ThinkingStep[]
}

export default function ChatPage() {
  const navigate = useNavigate()
  // Chat is a separate white-labeled surface with no sidebar of its own —
  // this only lights up for someone who ALSO holds an admin-shell session
  // (reached chat via the "Chat" link in Layout.tsx's sidebar, e.g. a
  // developer testing an agent), so they have a way back to the Debug
  // Console without hunting for the URL. A pure chat_user account (only
  // ever logged in via /user-login) never has an admin-shell token, so
  // this stays hidden for them.
  const adminRole = getStoredToken() ? getStoredRole() : null
  const canReachAdminShell = adminRole === 'admin' || adminRole === 'developer'
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string>(() => getLastActiveSessionId() ?? crypto.randomUUID())
  const [turns, setTurns] = useState<Turn[]>([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  // The conversation list becomes a slide-over drawer below the `lg`
  // breakpoint, same pattern as Layout.tsx's admin-shell nav.
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(false)
  const [liveSteps, setLiveSteps] = useState<ThinkingStep[]>([])
  const [orchestrators, setOrchestrators] = useState<OrchestratorSummary[]>([])
  const [selectedBot, setSelectedBot] = useState<string>('')
  // Set when a turn fails with MissingApiKeyError — opens ApiKeyPrompt
  // instead of a normal error bubble. Remembers the message so it can be
  // resent once the visitor supplies a key, without retyping it.
  const [pendingKeyPrompt, setPendingKeyPrompt] = useState<{ provider: Provider; message: string } | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  async function refreshConversations(): Promise<ConversationSummary[]> {
    try {
      const list = await fetchConversations()
      setConversations(list)
      return list
    } catch {
      return []
    }
  }

  async function loadConversation(sessionId: string, agentNameHint?: string | null) {
    setActiveSessionId(sessionId)
    setLastActiveSessionId(sessionId)
    setHistoryLoaded(false)
    // Only restore a past conversation's remembered bot when there's more
    // than one to choose from. With exactly one orchestrator (the norm now),
    // restoring here would race the "force to the sole orchestrator" effect
    // below — this call is chained behind refreshConversations() +
    // fetchChatHistory() (two round trips) and can resolve AFTER that
    // effect already ran off fetchOrchestrators() (one round trip), silently
    // clobbering selectedBot back to a legacy agent_name like
    // credit_facility_analyst that isn't even reachable directly anymore.
    if (agentNameHint && orchestrators.length > 1) setSelectedBot(agentNameHint)
    try {
      const history = await fetchChatHistory(sessionId)
      const restored = history.flatMap((turn): Turn[] => [
        { role: 'user', text: turn.message, at: new Date(turn.created_at).getTime() },
        { role: 'assistant', text: turn.response_text, at: new Date(turn.created_at).getTime() },
      ])
      setTurns(restored)
    } catch {
      setTurns([])
    } finally {
      setHistoryLoaded(true)
    }
  }

  function handleNewConversation() {
    const id = crypto.randomUUID()
    setActiveSessionId(id)
    setLastActiveSessionId(id)
    setTurns([])
    setHistoryLoaded(true)
  }

  useEffect(() => {
    if (!getUserToken()) {
      navigate('/user-login')
      return
    }
    fetchOrchestrators()
      .then((list) => {
        setOrchestrators(list)
        setSelectedBot((current) => current || list[0]?.name || '')
      })
      .catch(() => {})
    refreshConversations().then((list) => {
      const last = getLastActiveSessionId()
      const target = list.find((c) => c.session_id === last) ?? list[0]
      if (target) {
        loadConversation(target.session_id, target.agent_name)
      } else {
        setHistoryLoaded(true)
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, pending])

  // With exactly one orchestrator (the norm now — see agent_forge_orchestrator),
  // the bot picker below is hidden (only rendered when orchestrators.length >
  // 1), so there is no way for the visitor to manually correct selectedBot —
  // it must always resolve to that one bot, overriding whatever a restored
  // past conversation's agent_name happened to be (e.g. a legacy session that
  // talked directly to a since-consolidated specialist like
  // credit_facility_analyst). Runs after both fetchOrchestrators and
  // loadConversation settle, regardless of which resolves first.
  useEffect(() => {
    if (orchestrators.length === 1) {
      setSelectedBot(orchestrators[0].name)
    }
  }, [orchestrators])

  function handleLogout() {
    clearUserSession()
    navigate('/user-login')
  }

  // Shared by the compose-box submit, clicking a chip in AssistantContent's
  // OptionsView (see MessageRendering.tsx), and ApiKeyPrompt's retry after a
  // visitor supplies a missing key — all three are "send this text as the
  // next message", same flow either way. skipUserTurn is for that last case
  // only: the user bubble for `message` is already in the transcript from
  // the failed first attempt, so retrying must not push a duplicate.
  async function submitMessage(message: string, opts?: { skipUserTurn?: boolean }) {
    if (!message || pending) return
    if (!opts?.skipUserTurn) {
      setTurns((prev) => [...prev, { role: 'user', text: message, at: Date.now() }])
    }
    setPending(true)
    setLiveSteps([])
    const wasNewConversation = !conversations.some((c) => c.session_id === activeSessionId)
    const stepsById = new Map<string, ThinkingStep>()
    try {
      const result = await sendChatMessageStream(
        message,
        activeSessionId,
        (event) => {
          const parsed = stepFromEvent(event)
          if (!parsed) return
          if ('doneId' in parsed) {
            const existing = stepsById.get(parsed.doneId)
            if (existing) stepsById.set(parsed.doneId, { ...existing, status: 'done' })
          } else {
            stepsById.set(parsed.id, parsed)
          }
          setLiveSteps(Array.from(stepsById.values()))
        },
        selectedBot || undefined,
      )
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', text: result.response_text, at: Date.now(), thinkingSteps: Array.from(stepsById.values()) },
      ])
      if (wasNewConversation) await refreshConversations()
    } catch (err) {
      if (err instanceof MissingApiKeyError) {
        setPendingKeyPrompt({ provider: err.provider, message })
        return
      }
      const detail = err instanceof ChatApiError ? err.message : 'Something went wrong.'
      setTurns((prev) => [...prev, { role: 'assistant', text: detail, at: Date.now(), isError: true }])
      toast.error('Message failed to send')
    } finally {
      setPending(false)
      setLiveSteps([])
    }
  }

  function handleSend(e: React.FormEvent) {
    e.preventDefault()
    const message = input.trim()
    if (!message || pending) return
    setInput('')
    submitMessage(message)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend(e)
    }
  }

  const groups = groupConversationsByRecency(conversations)
  const activeTitle = conversations.find((c) => c.session_id === activeSessionId)?.title ?? 'New conversation'

  return (
    <div className="flex h-screen flex-col lg:flex-row">
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-30 bg-slate-950/50 lg:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 transform flex-col border-r border-white/60 bg-white/95 backdrop-blur-xl transition-transform duration-200 ease-in-out dark:border-white/5 dark:bg-slate-950/95 lg:static lg:z-auto lg:w-64 lg:translate-x-0 lg:bg-white/70 lg:transition-none dark:lg:bg-slate-950/70 ${
          mobileNavOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-3">
          <div className="mb-3 flex items-center justify-between gap-2 px-1">
            <Logo size="sm" />
            <button
              onClick={() => setMobileNavOpen(false)}
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 lg:hidden dark:hover:bg-slate-800"
              aria-label="Close conversation list"
            >
              <X size={18} />
            </button>
          </div>
          <Button
            variant="outline"
            tone="neutral"
            onClick={() => {
              handleNewConversation()
              setMobileNavOpen(false)
            }}
            className="w-full"
            leftIcon={<MessageSquarePlus size={16} />}
          >
            New chat
          </Button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-2 pb-2">
          {groups.length === 0 && (
            <p className="px-2 text-xs text-slate-400">Your conversations will show up here.</p>
          )}
          {groups.map((group) => (
            <div key={group.label}>
              <div className="px-2 pb-1 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">
                {group.label}
              </div>
              <div className="space-y-0.5">
                {group.conversations.map((conv) => (
                  <button
                    key={conv.session_id}
                    onClick={() => {
                      loadConversation(conv.session_id, conv.agent_name)
                      setMobileNavOpen(false)
                    }}
                    className={`block w-full truncate rounded-md px-2.5 py-2 text-left text-sm ${
                      conv.session_id === activeSessionId
                        ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-950 dark:text-brand-300'
                        : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                    }`}
                    title={conv.title}
                  >
                    {conv.title}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="border-t border-slate-200 p-3 dark:border-slate-800">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="truncate text-xs text-slate-400">{getUserEmail()}</span>
            <div className="flex items-center gap-2">
              <UsageButton />
              <HelpButton />
              <ThemeToggle />
            </div>
          </div>
          {canReachAdminShell && (
            <Link
              to="/debug"
              title="Debug Console"
              className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <Bug size={14} /> Debug Console
            </Link>
          )}
          <button
            onClick={handleLogout}
            title="Log out"
            className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <LogOut size={14} /> Log out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-2 border-b border-white/60 bg-white/70 px-4 py-3 backdrop-blur-xl dark:border-white/5 dark:bg-slate-950/70">
          <div className="flex min-w-0 items-center gap-2">
            <button
              onClick={() => setMobileNavOpen(true)}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 lg:hidden dark:text-slate-300 dark:hover:bg-slate-800"
              aria-label="Open conversation list"
            >
              <Menu size={18} />
            </button>
            <div className="truncate text-sm font-semibold">{activeTitle}</div>
          </div>
          {orchestrators.length > 1 && (
            <label className="flex shrink-0 items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              Bot
              <select
                value={selectedBot}
                onChange={(e) => setSelectedBot(e.target.value)}
                title="Which bot new messages in this conversation go to"
                className="rounded-md border border-slate-300 bg-white/80 px-2 py-1 text-xs font-medium text-slate-700 focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                {orchestrators.map((o) => (
                  <option key={o.name} value={o.name}>
                    {humanizeName(o.name)}
                  </option>
                ))}
              </select>
            </label>
          )}
        </header>

        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-5">
          <div className="mx-auto max-w-3xl space-y-4">
            {historyLoaded && turns.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-slate-400">
                <BotAvatar />
                <p className="mt-2 text-sm">
                  Ask me about stocks, crypto, or currency &amp; metals prices — e.g. "what's Bitcoin trading at?"
                  or "compare gold to the S&amp;P 500 this year".
                </p>
              </div>
            )}
            {turns.map((turn, i) => (
              <div key={i} className={`flex items-end gap-2 ${turn.role === 'user' ? 'flex-row-reverse' : ''}`}>
                <div
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                    turn.role === 'user' ? 'bg-slate-700 text-white dark:bg-slate-600' : 'bg-brand-600 text-white'
                  }`}
                >
                  {turn.role === 'user' ? <User size={14} /> : <Bot size={14} />}
                </div>
                <div className={`flex max-w-[80%] flex-col ${turn.role === 'user' ? 'items-end' : 'items-start'}`}>
                  {turn.role === 'assistant' && !turn.isError && <ThoughtProcessSummary steps={turn.thinkingSteps ?? []} />}
                  <div
                    className={`rounded-2xl px-4 py-2.5 text-sm ${
                      turn.role === 'user'
                        ? 'rounded-br-sm bg-brand-600 text-white'
                        : turn.isError
                          ? 'rounded-bl-sm border border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300'
                          : 'rounded-bl-sm bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100'
                    }`}
                  >
                    {turn.role === 'assistant' && !turn.isError ? (
                      <AssistantContent text={turn.text} onOptionSelect={submitMessage} disabled={pending} />
                    ) : (
                      <span className="whitespace-pre-wrap">{turn.text}</span>
                    )}
                  </div>
                  <span className="mt-1 px-1 text-[11px] text-slate-400">{fmtTime(turn.at)}</span>
                </div>
              </div>
            ))}
            {pending && (
              <div className="flex items-end gap-2">
                <BotAvatar />
                <LiveThinking steps={liveSteps} />
              </div>
            )}
          </div>
        </div>

        <form onSubmit={handleSend} className="border-t border-white/60 bg-white/70 p-3 backdrop-blur-xl dark:border-white/5 dark:bg-slate-950/70">
          <div className="mx-auto flex max-w-3xl gap-2">
            <Textarea
              label="Message"
              rows={3}
              className="max-h-32 flex-1 resize-none py-2"
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                const el = e.target
                el.style.height = 'auto'
                el.style.height = `${Math.min(el.scrollHeight, 128)}px`
              }}
              onKeyDown={handleKeyDown}
              placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
            />
            <Button type="submit" disabled={pending || !input.trim()} className="self-end" leftIcon={<Send size={15} />}>
              Send
            </Button>
          </div>
          <StudioCredit className="mx-auto mt-2 max-w-2xl text-center" />
        </form>
      </div>

      {pendingKeyPrompt && (
        <ApiKeyPrompt
          provider={pendingKeyPrompt.provider}
          onClose={() => setPendingKeyPrompt(null)}
          onSubmit={() => {
            const { message } = pendingKeyPrompt
            setPendingKeyPrompt(null)
            submitMessage(message, { skipUserTurn: true })
          }}
        />
      )}
    </div>
  )
}
