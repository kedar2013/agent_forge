import { Bot } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAgents } from '../../api/agents'
import type { ViewMode } from '../../lib/viewMode'
import EmptyState from '../ui/EmptyState'
import { CardGridSkeleton } from '../ui/Skeleton'
import AgentCard from './AgentCard'

export default function AgentRegistry({ viewMode = 'grid' }: { viewMode?: ViewMode }) {
  const { data: agents, isLoading, error } = useAgents()

  if (isLoading) return <CardGridSkeleton />
  if (error) return <p className="text-sm text-red-600">{(error as Error).message}</p>
  if (!agents?.length) {
    return (
      <EmptyState
        icon={Bot}
        title="No agents yet"
        message="Compose tools and skills into a working ADK agent, test it in the playground, then publish it."
        action={
          <Link
            to="/agents/new"
            className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
          >
            + New Agent
          </Link>
        }
      />
    )
  }

  return (
    <div className={viewMode === 'grid' ? 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3' : 'flex flex-col gap-2'}>
      {agents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} compact={viewMode === 'list'} />
      ))}
    </div>
  )
}
