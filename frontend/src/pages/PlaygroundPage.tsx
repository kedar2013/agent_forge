import { Link, useParams } from 'react-router-dom'
import { useAgent } from '../api/agents'
import PlaygroundChat from '../components/playground/PlaygroundChat'

export default function PlaygroundPage() {
  const { id } = useParams<{ id: string }>()
  const { data: agent } = useAgent(id)

  if (!id) return null

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Playground {agent ? `— ${agent.name}` : ''}</h1>
        <Link to={`/agents/${id}`} className="text-sm text-brand-600 hover:underline">
          ← back to builder
        </Link>
      </div>
      <PlaygroundChat agentId={id} />
    </div>
  )
}
