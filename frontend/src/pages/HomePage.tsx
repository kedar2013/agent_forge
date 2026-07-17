import { useState } from 'react'
import { Bot, CheckCircle2, FileText, Plus, Wrench } from 'lucide-react'
import { useAgents } from '../api/agents'
import { useTools } from '../api/tools'
import { useSkills } from '../api/skills'
import AgentCard from '../components/agents/AgentCard'
import MarketIntelligenceSection from '../components/home/MarketIntelligenceSection'
import StatTile from '../components/ui/StatTile'
import { CardGridSkeleton } from '../components/ui/Skeleton'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import ToolForm from '../components/tools/ToolForm'
import SkillForm from '../components/skills/SkillForm'

export default function HomePage() {
  const { data: agents, isLoading: agentsLoading } = useAgents()
  const { data: tools } = useTools()
  const { data: skills } = useSkills()
  const [modal, setModal] = useState<'tool' | 'skill' | null>(null)

  const publishedCount = agents?.filter((a) => a.status === 'published').length ?? 0
  const draftCount = agents?.filter((a) => a.status === 'draft').length ?? 0
  const recent = [...(agents ?? [])]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 6)

  return (
    <div className="space-y-8">
      <PageHeader
        title="Welcome to Eärendil"
        description="Compose, test, and publish Google ADK agents without touching code."
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile icon={Bot} label="Agents" value={agents?.length ?? 0} tone="brand" />
        <StatTile icon={CheckCircle2} label="Published" value={publishedCount} tone="success" />
        <StatTile icon={FileText} label="Drafts" value={draftCount} tone="neutral" />
        <StatTile icon={Wrench} label="Tools" value={tools?.length ?? 0} tone="warning" />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button to="/agents/new" leftIcon={<Plus size={16} />}>
          New Agent
        </Button>
        <Button variant="outline" tone="neutral" onClick={() => setModal('tool')} leftIcon={<Plus size={16} />}>
          New Tool
        </Button>
        <Button variant="outline" tone="neutral" onClick={() => setModal('skill')} leftIcon={<Plus size={16} />}>
          New Skill
        </Button>
        <span className="ml-2 self-center text-xs text-slate-400">
          {skills?.length ?? 0} skills in your library
        </span>
      </div>

      <MarketIntelligenceSection agents={agents} />

      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
          Recently updated agents
        </h2>
        {agentsLoading && <CardGridSkeleton count={3} />}
        {!agentsLoading && recent.length === 0 && (
          <EmptyState
            icon={Bot}
            title="No agents yet"
            message="Create your first agent to start composing tools and skills into a working ADK agent."
            action={<Button to="/agents/new">+ New Agent</Button>}
          />
        )}
        {!agentsLoading && recent.length > 0 && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {recent.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </div>

      <Modal open={modal === 'tool'} onClose={() => setModal(null)} title="New Tool" maxWidth="max-w-xl">
        <ToolForm onDone={() => setModal(null)} />
      </Modal>
      <Modal open={modal === 'skill'} onClose={() => setModal(null)} title="New Skill" maxWidth="max-w-xl">
        <SkillForm onDone={() => setModal(null)} />
      </Modal>
    </div>
  )
}
