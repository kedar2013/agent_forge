import { useRef } from 'react'
import { Bot, CheckCircle2, FileText, Plus, Upload, Workflow } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useAgents, useImportAgent } from '../api/agents'
import AgentRegistry from '../components/agents/AgentRegistry'
import Button from '../components/ui/Button'
import PageHeader from '../components/ui/PageHeader'
import StatTile from '../components/ui/StatTile'
import ViewModeToggle from '../components/ui/ViewModeToggle'
import { useViewMode } from '../lib/viewMode'

export default function AgentsPage() {
  const { data: agents } = useAgents()
  const navigate = useNavigate()
  const importAgent = useImportAgent()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [viewMode, setViewMode] = useViewMode('agents')

  const published = agents?.filter((a) => a.status === 'published').length ?? 0
  const drafts = agents?.filter((a) => a.status === 'draft').length ?? 0
  const orchestrators = agents?.filter((a) => a.sub_agents.length > 0).length ?? 0

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const result = await importAgent.mutateAsync(data)
      const parts = []
      if (result.tools_created.length) parts.push(`${result.tools_created.length} new tool(s)`)
      if (result.skills_created.length) parts.push(`${result.skills_created.length} new skill(s)`)
      if (result.sub_agents_missing.length) parts.push(`${result.sub_agents_missing.length} sub-agent(s) not found`)
      toast.success(`Imported as "${result.agent_name}"${parts.length ? ` — ${parts.join(', ')}` : ''}`)
      navigate(`/agents/${result.agent_id}`)
    } catch (err) {
      toast.error(err instanceof SyntaxError ? 'That file is not valid JSON.' : (err as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agents"
        description="Compose, test, and publish ADK agents built from your tools and skills."
        actions={
          <>
            <ViewModeToggle mode={viewMode} onChange={setViewMode} />
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json"
              className="hidden"
              onChange={handleFileSelected}
            />
            <Button
              variant="outline"
              tone="neutral"
              onClick={() => fileInputRef.current?.click()}
              isPending={importAgent.isPending}
              loadingLabel="Importing…"
              leftIcon={<Upload size={16} />}
            >
              Import
            </Button>
            <Button to="/agents/new" leftIcon={<Plus size={16} />}>
              New Agent
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile icon={Bot} label="Total agents" value={agents?.length ?? 0} tone="brand" />
        <StatTile icon={CheckCircle2} label="Published" value={published} tone="success" />
        <StatTile icon={FileText} label="Drafts" value={drafts} tone="neutral" />
        <StatTile icon={Workflow} label="Orchestrators" value={orchestrators} tone="warning" />
      </div>

      <AgentRegistry viewMode={viewMode} />
    </div>
  )
}
