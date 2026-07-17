import type { SpanNode } from '../../api/debug'

function formatPayload(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const KIND_LABEL: Record<string, { request: string; response: string }> = {
  root: { request: 'Message', response: 'Final response' },
  tool: { request: 'Request (what the AI sent the tool)', response: 'Response (what the tool returned)' },
  model: { request: 'Request', response: "AI's response" },
}

export default function SpanDetail({ span }: { span: SpanNode }) {
  const labels = KIND_LABEL[span.kind]
  const hasInput = span.input !== undefined && span.input !== null
  const hasOutput = span.output !== undefined && span.output !== null
  if (!labels || (!hasInput && !hasOutput && !span.error_message)) {
    return span.error_message ? (
      <p className="mt-1.5 rounded-md bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
        {span.error_message}
      </p>
    ) : null
  }
  return (
    <div className="mt-1.5 ml-3 space-y-1.5 border-l-2 border-slate-200 pl-3 dark:border-slate-700">
      {hasInput && (
        <div>
          <div className="mb-0.5 text-[10px] font-semibold tracking-wide text-slate-500 uppercase">{labels.request}</div>
          <pre className="max-h-48 overflow-auto rounded-md bg-slate-50 p-2 font-mono text-xs whitespace-pre-wrap dark:bg-slate-800">
            {formatPayload(span.input)}
          </pre>
        </div>
      )}
      {hasOutput && (
        <div>
          <div className="mb-0.5 text-[10px] font-semibold tracking-wide text-slate-500 uppercase">{labels.response}</div>
          <pre className="max-h-48 overflow-auto rounded-md bg-slate-50 p-2 font-mono text-xs whitespace-pre-wrap dark:bg-slate-800">
            {formatPayload(span.output)}
          </pre>
        </div>
      )}
      {span.error_message && (
        <p className="rounded-md bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">{span.error_message}</p>
      )}
    </div>
  )
}
