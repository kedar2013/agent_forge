import { ArrowRight } from 'lucide-react'
import type { Tool } from '../../../api/types'
import Button from '../../../components/ui/Button'
import Card from '../../../components/ui/Card'
import Input from '../../../components/ui/Input'
import Textarea from '../../../components/ui/Textarea'
import { Ex, GuidedField } from '../../../components/ui/FieldGuide'
import { slugify } from '../slugify'

export interface AgentStepProps {
  domainName: string
  domainDescription: string
  tools: Tool[]
  agentName: string
  agentDescription: string
  agentInstruction: string
  onAgentNameChange: (v: string) => void
  onAgentDescriptionChange: (v: string) => void
  onAgentInstructionChange: (v: string) => void
  onUseSuggestedName: () => void
  onSubmit: () => void
  isSubmitting: boolean
  canSubmit: boolean
}

export default function AgentStep({
  domainName,
  domainDescription,
  tools,
  agentName,
  agentDescription,
  agentInstruction,
  onAgentNameChange,
  onAgentDescriptionChange,
  onAgentInstructionChange,
  onUseSuggestedName,
  onSubmit,
  isSubmitting,
  canSubmit,
}: AgentStepProps) {
  return (
    <Card padding="lg">
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) onSubmit()
        }}
      >
        <h2 className="text-lg font-semibold">Agent</h2>
        <GuidedField
          label="Name"
          guide={{
            title: 'Agent name',
            what: "The published agent's identifier — lowercase with underscores.",
            why: 'Shows up in the chat orchestrator list, dashboards, and the SCIL cache; renaming later requires a republish.',
            example: (
              <>
                Suggested: <Ex>{slugify(domainName) || 'sales'}_analyst</Ex>
              </>
            ),
          }}
        >
          <div className="flex gap-2">
            <Input
              label="Agent name"
              value={agentName}
              onChange={(e) => onAgentNameChange(e.target.value)}
              placeholder={`${slugify(domainName)}_analyst`}
            />
            {!agentName && domainName && (
              <Button type="button" variant="outline" tone="neutral" size="xs" onClick={onUseSuggestedName} className="shrink-0">
                Use suggestion
              </Button>
            )}
          </div>
        </GuidedField>
        <GuidedField
          label="Description"
          guide={{
            title: 'Agent description',
            what: 'What chat users see when picking this assistant.',
            why: 'Also read by orchestrators that route between specialists — a crisp description improves routing.',
            example: domainDescription ? <Ex>{domainDescription}</Ex> : undefined,
          }}
        >
          <Input
            label="Agent description"
            value={agentDescription}
            onChange={(e) => onAgentDescriptionChange(e.target.value)}
            placeholder={domainDescription}
          />
        </GuidedField>
        <GuidedField
          label="Instructions"
          guide={{
            title: 'Agent instructions',
            what: 'The system prompt. Leave blank for a solid default that names your tools and the safety rules.',
            why: 'The default already covers the essentials: use only listed columns, never invent values on errors, render results as tables.',
            warn:
              'If you write your own, keep the "never reference a column the tool doesn\'t list" rule — it\'s what keeps SQL hallucinations near zero.',
          }}
        >
          <Textarea
            label="Agent instructions"
            className="h-32"
            value={agentInstruction}
            onChange={(e) => onAgentInstructionChange(e.target.value)}
            placeholder={`Leave blank to use a generated instruction mentioning: ${tools.map((t) => t.name).join(', ')}`}
          />
        </GuidedField>
        <div className="flex justify-end pt-2">
          <Button type="submit" disabled={!canSubmit} isPending={isSubmitting} loadingLabel="Creating…" rightIcon={<ArrowRight size={15} />}>
            Create agent
          </Button>
        </div>
      </form>
    </Card>
  )
}
