import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { useAgents } from '../../api/agents'
import { useCheckCacheSimilarity } from '../../api/scil'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Select from '../ui/Select'
import Textarea from '../ui/Textarea'

/** Answers "why didn't X hit the cache for Y" directly: runs the same
 * normalize -> embed -> cosine pipeline the real cache lookup uses, against
 * the selected agent's live configured threshold — read-only, writes
 * nothing, safe to run against production agents. */
export default function SimilarityInspector() {
  const { data: agents } = useAgents()
  const [agentId, setAgentId] = useState('')
  const [textA, setTextA] = useState('')
  const [textB, setTextB] = useState('')
  const check = useCheckCacheSimilarity()

  const agentOptions = useMemo(
    () => (agents ?? []).filter((a) => a.status === 'published').sort((a, b) => a.name.localeCompare(b.name)),
    [agents],
  )

  function handleCheck() {
    if (!agentId || !textA.trim() || !textB.trim()) return
    check.mutate({ agent_id: agentId, text_a: textA.trim(), text_b: textB.trim() })
  }

  return (
    <Card className="space-y-3">
      <div>
        <div className="text-sm font-medium">Cache similarity inspector</div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          See why two questions did or didn't share a cache entry — computes the real cosine similarity between them
          with the same pipeline the cache uses, against the selected agent's live threshold. Read-only, nothing is
          cached or written.
        </p>
      </div>

      <div className="w-64">
        <Select
          label="Agent"
          hideLabel
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          options={agentOptions.map((a) => ({ label: a.name, value: a.id }))}
          placeholder="Select an agent"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Textarea label="Question A" placeholder="e.g. What is Apple's current share price?" rows={2} value={textA} onChange={(e) => setTextA(e.target.value)} />
        <Textarea label="Question B" placeholder="e.g. What's Apple's stock price" rows={2} value={textB} onChange={(e) => setTextB(e.target.value)} />
      </div>

      <div className="flex items-center gap-3">
        <Button
          leftIcon={<Search size={14} />}
          size="sm"
          isPending={check.isPending}
          disabled={!agentId || !textA.trim() || !textB.trim()}
          onClick={handleCheck}
        >
          Check similarity
        </Button>

        {check.data && (
          <div className="flex items-center gap-2 text-sm">
            <span className="font-mono text-base tabular-nums">{check.data.similarity.toFixed(4)}</span>
            <span className="text-slate-400">vs threshold {check.data.threshold.toFixed(2)}</span>
            {check.data.would_hit ? (
              <Badge tone="success">Would hit the cache</Badge>
            ) : (
              <Badge tone="danger">Would NOT hit — below threshold</Badge>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
