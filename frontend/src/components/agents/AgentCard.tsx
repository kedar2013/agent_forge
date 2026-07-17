import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Archive, Bot, Copy, Download, History, Sparkles, Wrench, Workflow } from 'lucide-react'
import { toast } from 'sonner'
import { exportAgent, useArchiveAgent, useCloneAgent } from '../../api/agents'
import type { Agent } from '../../api/types'
import { AGENT_STATUS_TONE } from '../../lib/badgeTones'
import Badge from '../ui/Badge'
import Card from '../ui/Card'
import ConfirmDialog from '../ui/ConfirmDialog'
import EntityAvatar, { type EntityAvatarState } from '../ui/EntityAvatar'
import Modal from '../ui/Modal'
import VersionHistory from './VersionHistory'

export default function AgentCard({ agent, compact = false }: { agent: Agent; compact?: boolean }) {
  const navigate = useNavigate()
  const archiveAgent = useArchiveAgent()
  const cloneAgent = useCloneAgent()
  const [confirmArchive, setConfirmArchive] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const isOrchestrator = agent.sub_agents.length > 0
  const avatarState: EntityAvatarState =
    agent.status === 'draft' ? 'ghost' : agent.status === 'archived' ? 'muted' : 'active'

  function handleArchive() {
    archiveAgent.mutate(agent.id, {
      onSuccess: () => toast.success(`${agent.name} archived`),
      onError: (err) => toast.error((err as Error).message),
    })
    setConfirmArchive(false)
  }

  function handleClone() {
    cloneAgent.mutate(agent.id, {
      onSuccess: (created) => {
        toast.success(`Cloned as "${created.name}"`)
        navigate(`/agents/${created.id}`)
      },
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleExport() {
    exportAgent(agent.id, agent.name).catch((err) => toast.error((err as Error).message))
  }

  const actionButtons = (
    <>
      <button
        onClick={handleClone}
        disabled={cloneAgent.isPending}
        title="Duplicate"
        className="rounded p-1 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40 dark:hover:bg-slate-800 dark:hover:text-slate-200"
      >
        <Copy size={15} />
      </button>
      <button
        onClick={handleExport}
        title="Export as JSON"
        className="rounded p-1 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
      >
        <Download size={15} />
      </button>
      <button
        onClick={() => setHistoryOpen(true)}
        title="Version history"
        className="rounded p-1 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
      >
        <History size={15} />
      </button>
      {agent.status !== 'archived' && (
        <button
          onClick={() => setConfirmArchive(true)}
          title="Archive"
          className="rounded p-1 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950"
        >
          <Archive size={15} />
        </button>
      )}
    </>
  )

  return (
    <>
      {compact ? (
        <Card
          hover
          className={`flex items-center gap-3 py-2.5 ${
            isOrchestrator ? 'border-l-4 border-l-violet-500 dark:border-l-violet-400' : ''
          }`}
        >
          <Link to={`/agents/${agent.id}`} className="flex min-w-0 flex-1 items-center gap-2">
            <EntityAvatar
              icon={isOrchestrator ? Workflow : Bot}
              tone={AGENT_STATUS_TONE[agent.status]}
              state={avatarState}
              glow={agent.status === 'published'}
              size={28}
            />
            <span className="truncate text-sm font-semibold text-slate-900 hover:text-brand-600 dark:text-slate-100 dark:hover:text-brand-400">
              {agent.name}
            </span>
            <Badge tone={AGENT_STATUS_TONE[agent.status]}>{agent.status}</Badge>
          </Link>
          <span className="hidden shrink-0 items-center gap-3 text-xs text-slate-400 sm:flex">
            <span className="flex items-center gap-1" title="Attached tools">
              <Wrench size={13} /> {agent.tools.length}
            </span>
            <span className="flex items-center gap-1" title="Sub-agents">
              <Workflow size={13} /> {agent.sub_agents.length}
            </span>
            <span>v{agent.current_version}</span>
          </span>
          <div className="flex shrink-0 items-center gap-1">{actionButtons}</div>
        </Card>
      ) : (
        <Card
          hover
          className={`flex flex-col gap-3 ${
            isOrchestrator
              ? 'border-l-4 border-l-violet-500 bg-violet-50/40 dark:border-l-violet-400 dark:bg-violet-950/20'
              : ''
          }`}
        >
          <div className="flex items-start justify-between gap-2">
            <Link to={`/agents/${agent.id}`} className="flex min-w-0 flex-1 items-center gap-2.5">
              <EntityAvatar
                icon={isOrchestrator ? Workflow : Bot}
                tone={AGENT_STATUS_TONE[agent.status]}
                state={avatarState}
                glow={agent.status === 'published'}
                size={40}
              />
              <h3 className="truncate font-semibold text-slate-900 hover:text-brand-600 dark:text-slate-100 dark:hover:text-brand-400">
                {agent.name}
              </h3>
            </Link>
            <div className="flex shrink-0 items-center gap-1.5">
              {isOrchestrator && <Badge tone="violet">Orchestrator</Badge>}
              <Badge tone={AGENT_STATUS_TONE[agent.status]}>{agent.status}</Badge>
            </div>
          </div>

          <p className="line-clamp-2 min-h-[2.5rem] text-sm text-slate-500 dark:text-slate-400">
            {agent.description || <span className="italic text-slate-400">No description</span>}
          </p>

          <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
            <span className="flex items-center gap-1" title="Attached tools">
              <Wrench size={14} /> {agent.tools.length}
            </span>
            <span className="flex items-center gap-1" title="Attached skills">
              <Sparkles size={14} /> {agent.skills.length}
            </span>
            <span
              className={`flex items-center gap-1 ${isOrchestrator ? 'font-semibold text-violet-600 dark:text-violet-400' : ''}`}
              title="Sub-agents"
            >
              <Workflow size={14} /> {agent.sub_agents.length}
            </span>
            <span className="ml-auto">v{agent.current_version}</span>
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 pt-2 text-xs text-slate-400 dark:border-slate-800">
            <span>{new Date(agent.updated_at).toLocaleDateString()}</span>
            <div className="flex items-center gap-1">{actionButtons}</div>
          </div>
        </Card>
      )}

      <ConfirmDialog
        open={confirmArchive}
        title="Archive agent?"
        message={`"${agent.name}" will be marked archived. You can't undo this from the UI yet.`}
        confirmLabel="Archive"
        danger
        onConfirm={handleArchive}
        onCancel={() => setConfirmArchive(false)}
      />

      <Modal
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title={`${agent.name} — version history`}
        maxWidth="max-w-3xl"
      >
        <VersionHistory agent={agent} />
      </Modal>
    </>
  )
}
