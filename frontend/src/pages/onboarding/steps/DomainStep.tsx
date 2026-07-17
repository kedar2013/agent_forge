import { ArrowRight } from 'lucide-react'
import Button from '../../../components/ui/Button'
import Card from '../../../components/ui/Card'
import Input from '../../../components/ui/Input'
import { Ex, GuidedField } from '../../../components/ui/FieldGuide'

export interface DomainStepProps {
  domainName: string
  domainDescription: string
  onDomainNameChange: (v: string) => void
  onDomainDescriptionChange: (v: string) => void
  onNext: () => void
  canAdvance: boolean
}

export default function DomainStep({
  domainName,
  domainDescription,
  onDomainNameChange,
  onDomainDescriptionChange,
  onNext,
  canAdvance,
}: DomainStepProps) {
  return (
    <Card padding="lg">
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault()
          if (canAdvance) onNext()
        }}
      >
        <h2 className="text-lg font-semibold">Name this domain</h2>
        <GuidedField
          label="Domain name"
          guide={{
            title: 'Domain name',
            what: 'A human name for this whole capability — the business area, not the table.',
            why: 'Seeds the suggested agent name and the agent\'s self-description in chat.',
            example: (
              <>
                <Ex>Loan Portfolio Analysis</Ex> <Ex>Sales Analytics</Ex> <Ex>Vendor Spend</Ex>
              </>
            ),
          }}
        >
          <Input
            label="Domain name"
            value={domainName}
            onChange={(e) => onDomainNameChange(e.target.value)}
            placeholder="e.g. Sales Analytics"
          />
        </GuidedField>
        <GuidedField
          label="Description"
          guide={{
            title: 'Domain description',
            what: 'One sentence on what questions this domain answers, for teammates browsing agents later.',
            why: "Becomes the agent's description — chat users see it when picking an assistant.",
            example: <Ex>Order volumes, revenue and rep performance across regions</Ex>,
          }}
        >
          <Input
            label="Domain description"
            value={domainDescription}
            onChange={(e) => onDomainDescriptionChange(e.target.value)}
          />
        </GuidedField>
        <p className="text-xs text-slate-400">
          This wizard configures how Eärendil accesses and gates data that already exists — it doesn't create
          databases or tables.
        </p>
        <div className="flex justify-end pt-2">
          <Button type="submit" disabled={!canAdvance} rightIcon={<ArrowRight size={15} />}>
            Next
          </Button>
        </div>
      </form>
    </Card>
  )
}
