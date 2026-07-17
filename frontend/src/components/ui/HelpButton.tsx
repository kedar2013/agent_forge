import { useState } from 'react'
import { HelpCircle } from 'lucide-react'
import Badge from './Badge'
import Logo from './Logo'
import Modal from './Modal'
import StudioCredit from './StudioCredit'

const CAPABILITIES = [
  'Compose agents from tools, skills, and sub-agents — no code required',
  'Live playground with full tool-call tracing',
  'Market Intelligence: stocks, crypto, forex/metals, and Indian mutual funds',
  'Monitoring, usage, and a tamper-evident audit log',
]

const STACK = [
  'FastAPI',
  'PostgreSQL',
  'Google ADK',
  'Gemini',
  'React 19',
  'TypeScript',
  'Tailwind v4',
]

const SHORTCUTS: [string, string][] = [
  ['Ctrl / Cmd + K', 'Open the command palette'],
  ['Esc', 'Close the current dialog'],
]

export default function HelpButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Help & about"
        aria-label="Help & about"
        className="flex h-5 w-5 items-center justify-center rounded-full text-slate-400 transition-colors hover:text-slate-600 dark:hover:text-slate-300"
      >
        <HelpCircle size={13} />
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title="About Agent Forge" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="flex flex-col items-center gap-2 text-center">
            <Logo size="lg" withWordmark={false} />
            <h3 className="text-lg font-semibold">Agent Forge</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Compose, test, and publish AI agents without touching code.
            </p>
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-400 uppercase">Capabilities</h4>
            <ul className="space-y-1 text-sm text-slate-600 dark:text-slate-300">
              {CAPABILITIES.map((c) => (
                <li key={c} className="flex gap-2">
                  <span className="text-brand-500">•</span> {c}
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-400 uppercase">Built with</h4>
            <div className="flex flex-wrap gap-1.5">
              {STACK.map((s) => (
                <Badge key={s} tone="neutral">
                  {s}
                </Badge>
              ))}
            </div>
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-400 uppercase">Shortcuts</h4>
            <div className="space-y-1 text-sm">
              {SHORTCUTS.map(([keys, desc]) => (
                <div key={keys} className="flex items-center justify-between">
                  <span className="text-slate-500 dark:text-slate-400">{desc}</span>
                  <kbd className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] dark:border-slate-700">
                    {keys}
                  </kbd>
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-slate-100 pt-3 text-center dark:border-slate-800">
            <StudioCredit />
          </div>
        </div>
      </Modal>
    </>
  )
}
