import { Bot, ClipboardList, Layers, ListChecks } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Button from '../ui/Button'

export function tryParseJson(text: string): unknown | null {
  const trimmed = text.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null
  try {
    return JSON.parse(trimmed)
  } catch {
    return null
  }
}

function QuizView({ data }: { data: { chapter_title?: string; questions: any[] } }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-brand-700 dark:text-brand-400">
        <ClipboardList size={14} /> {data.chapter_title ?? 'Practice questions'}
      </div>
      {data.questions.map((q, i) => (
        <div key={i} className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="mb-1.5 font-medium">
            {i + 1}. {q.question}
          </div>
          {Array.isArray(q.options) && (
            <ul className="mb-1.5 ml-4 list-disc space-y-0.5 text-slate-600 dark:text-slate-400">
              {q.options.map((opt: string, j: number) => (
                <li key={j} className={opt === q.correct_answer ? 'font-medium text-emerald-600 dark:text-emerald-400' : ''}>
                  {opt}
                </li>
              ))}
            </ul>
          )}
          {!q.options && (
            <p className="mb-1.5 text-emerald-600 dark:text-emerald-400">Answer: {q.correct_answer}</p>
          )}
          <p className="text-xs text-slate-500">{q.explanation}</p>
          {q.page_number != null && <p className="mt-0.5 text-xs text-slate-400">page {q.page_number}</p>}
        </div>
      ))}
    </div>
  )
}

function FlashcardView({ data }: { data: { cards: any[] } }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {data.cards.map((c, i) => (
        <div key={i} className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-900">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-brand-700 dark:text-brand-400">
            <Layers size={13} /> {c.term}
          </div>
          <p className="text-slate-600 dark:text-slate-400">{c.definition}</p>
          {c.page_number != null && <p className="mt-1 text-xs text-slate-400">page {c.page_number}</p>}
        </div>
      ))}
    </div>
  )
}

export interface SelectableOption {
  label: string
  /** Sent back as the next user message when clicked. Falls back to `label`. */
  value?: string
}

/**
 * Convention any agent's instruction text can opt into (see e.g.
 * app/domains/credit_facility/seed_agent.py) for "pick one of these"
 * moments — disambiguating a company/fund/ticker name, choosing among
 * several matching records, confirming which of N results was meant, etc.
 * The agent's FULL response_text must be exactly this JSON shape (nothing
 * else parses as an options list — mixed prose+JSON falls through to the
 * generic-JSON-dump branch below, same as the quiz/flashcard conventions):
 *
 *   { "type": "options", "prompt": "...", "options": [{"label": "...", "value": "..."}] }
 */
export interface OptionsPayload {
  type: 'options'
  prompt?: string
  options: SelectableOption[]
}

function OptionsView({
  data,
  onSelect,
  disabled,
}: {
  data: OptionsPayload
  onSelect?: (value: string) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-2">
      {data.prompt && (
        <div className="flex items-start gap-1.5 text-sm">
          <ListChecks size={15} className="mt-0.5 shrink-0 text-brand-600 dark:text-brand-400" />
          <span>{data.prompt}</span>
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {data.options.map((opt, i) => (
          <Button
            key={i}
            type="button"
            variant="outline"
            tone="brand"
            size="xs"
            disabled={disabled}
            onClick={() => onSelect?.(opt.value ?? opt.label)}
          >
            {opt.label}
          </Button>
        ))}
      </div>
    </div>
  )
}

export function AssistantContent({
  text,
  onOptionSelect,
  disabled,
}: {
  text: string
  onOptionSelect?: (value: string) => void
  disabled?: boolean
}) {
  const parsed = tryParseJson(text)
  if (parsed && typeof parsed === 'object') {
    if (Array.isArray((parsed as any).questions)) return <QuizView data={parsed as any} />
    if (Array.isArray((parsed as any).cards)) return <FlashcardView data={parsed as any} />
    if ((parsed as any).type === 'options' && Array.isArray((parsed as any).options)) {
      return <OptionsView data={parsed as OptionsPayload} onSelect={onOptionSelect} disabled={disabled} />
    }
    return (
      <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100 dark:bg-black">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    )
  }
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-ul:my-1.5 prose-headings:my-2">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
}

export function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 rounded-2xl rounded-bl-sm bg-slate-100 px-4 py-3 dark:bg-slate-800">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 dark:bg-slate-500"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  )
}

export function BotAvatar() {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white">
      <Bot size={14} />
    </div>
  )
}

export function fmtTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
