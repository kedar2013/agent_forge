import { Database, Plus, Radio, Wrench } from 'lucide-react'
import { useState } from 'react'
import { useTools } from '../api/tools'
import ToolCard from '../components/tools/ToolCard'
import ToolForm from '../components/tools/ToolForm'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import { CardGridSkeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'
import ViewModeToggle from '../components/ui/ViewModeToggle'
import { useViewMode } from '../lib/viewMode'

export default function ToolsPage() {
  const { data: tools, isLoading, error } = useTools()
  const [showForm, setShowForm] = useState(false)
  const [viewMode, setViewMode] = useViewMode('tools')

  const mcpCount = tools?.filter((t) => t.tool_type === 'mcp_tool').length ?? 0
  const dataCount = tools?.filter((t) => t.tool_type === 'sql_tool' || t.tool_type === 'retrieval_tool').length ?? 0
  const httpCount = tools?.filter((t) => t.tool_type === 'http_tool').length ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tools"
        description="Declarative capabilities agents can call — HTTP, SQL, MCP, retrieval."
        actions={
          <>
            <ViewModeToggle mode={viewMode} onChange={setViewMode} />
            <Button onClick={() => setShowForm(true)} leftIcon={<Plus size={16} />}>
              New Tool
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile icon={Wrench} label="Total tools" value={tools?.length ?? 0} tone="brand" />
        <StatTile icon={Radio} label="MCP" value={mcpCount} tone="success" />
        <StatTile icon={Database} label="Data (SQL / retrieval)" value={dataCount} tone="warning" />
        <StatTile icon={Wrench} label="HTTP" value={httpCount} tone="neutral" />
      </div>

      {isLoading && <CardGridSkeleton />}
      {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
      {!isLoading && !tools?.length && (
        <EmptyState
          icon={Wrench}
          title="No tools yet"
          message="Tools are declarative capabilities — HTTP calls, SQL queries, MCP bindings, or retrieval lookups — that you can attach to any agent."
          action={
            <Button onClick={() => setShowForm(true)}>
              + New Tool
            </Button>
          }
        />
      )}
      {!isLoading && !!tools?.length && (
        <div className={viewMode === 'grid' ? 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3' : 'flex flex-col gap-2'}>
          {tools.map((tool) => (
            <ToolCard key={tool.id} tool={tool} compact={viewMode === 'list'} />
          ))}
        </div>
      )}

      <Modal open={showForm} onClose={() => setShowForm(false)} title="New Tool" maxWidth="max-w-3xl">
        <ToolForm onDone={() => setShowForm(false)} />
      </Modal>
    </div>
  )
}
