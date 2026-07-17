import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, Search, Sparkles, Wrench } from 'lucide-react'
import { useAgents } from '../api/agents'
import { useSkills } from '../api/skills'
import { useTools } from '../api/tools'

interface Result {
  kind: 'agent' | 'tool' | 'skill'
  id: string
  name: string
  subtitle: string
  path: string
}

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const { data: agents } = useAgents()
  const { data: tools } = useTools()
  const { data: skills } = useSkills()

  const allResults = useMemo<Result[]>(() => {
    const agentResults: Result[] = (agents ?? []).map((a) => ({
      kind: 'agent',
      id: a.id,
      name: a.name,
      subtitle: a.sub_agents.length > 0 ? 'Orchestrator' : a.status,
      path: `/agents/${a.id}`,
    }))
    const toolResults: Result[] = (tools ?? []).map((t) => ({
      kind: 'tool',
      id: t.id,
      name: t.name,
      subtitle: t.tool_type,
      path: '/tools',
    }))
    const skillResults: Result[] = (skills ?? []).map((s) => ({
      kind: 'skill',
      id: s.id,
      name: s.name,
      subtitle: 'Skill',
      path: '/skills',
    }))
    return [...agentResults, ...toolResults, ...skillResults]
  }, [agents, tools, skills])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return allResults.slice(0, 20)
    return allResults.filter((r) => r.name.toLowerCase().includes(q) || r.subtitle.toLowerCase().includes(q)).slice(0, 20)
  }, [allResults, query])

  useEffect(() => {
    setActiveIndex(0)
  }, [query])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActiveIndex(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  function go(result: Result) {
    navigate(result.path)
    onClose()
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const result = filtered[activeIndex]
      if (result) go(result)
    }
  }

  if (!open) return null

  const icons = { agent: Bot, tool: Wrench, skill: Sparkles }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-[12vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-[--radius-card] border border-slate-200 bg-white shadow-[--shadow-card-hover] dark:border-slate-800 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
          <Search size={16} className="shrink-0 text-slate-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Jump to an agent, tool, or skill…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
          <kbd className="hidden shrink-0 rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-400 sm:block dark:border-slate-700">
            Esc
          </kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-1.5">
          {filtered.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-slate-400">No matches.</p>
          )}
          {filtered.map((r, i) => {
            const Icon = icons[r.kind]
            return (
              <button
                key={`${r.kind}-${r.id}`}
                onClick={() => go(r)}
                onMouseEnter={() => setActiveIndex(i)}
                className={`flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm ${
                  i === activeIndex
                    ? 'bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300'
                    : 'text-slate-700 dark:text-slate-200'
                }`}
              >
                <Icon size={15} className="shrink-0 text-slate-400" />
                <span className="min-w-0 flex-1 truncate font-medium">{r.name}</span>
                <span className="shrink-0 text-xs text-slate-400">{r.subtitle}</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
