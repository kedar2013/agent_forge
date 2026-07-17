import type { AccessPolicy } from '../../../api/types'
import AccessPolicyForm from '../../../components/accessPolicies/AccessPolicyForm'
import Button from '../../../components/ui/Button'
import Card from '../../../components/ui/Card'

export interface AccessStepProps {
  policy: AccessPolicy | null | undefined
  addingPolicy: boolean
  onPolicyCreated: (p: AccessPolicy) => void
  onPolicyFormDone: () => void
  onChangePolicy: () => void
  onSkip: () => void
}

export default function AccessStep({
  policy,
  addingPolicy,
  onPolicyCreated,
  onPolicyFormDone,
  onChangePolicy,
  onSkip,
}: AccessStepProps) {
  return (
    <Card padding="lg" className="space-y-6">
      <h2 className="text-lg font-semibold">Identity &amp; access</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Defines how a logged-in user's persona is resolved, and what rows each persona may see — enforced
        mechanically on every query, regardless of what the LLM writes. Skip this if every user of this domain
        should see the same data.
      </p>
      {policy === undefined || addingPolicy ? (
        <AccessPolicyForm onCreated={onPolicyCreated} onDone={onPolicyFormDone} />
      ) : (
        <div className="flex items-center justify-between rounded border border-slate-200 p-3 dark:border-slate-700">
          <span className="text-sm">
            Using access policy <strong>{policy?.name}</strong>
          </span>
          <Button variant="ghost" size="xs" onClick={onChangePolicy}>
            Change
          </Button>
        </div>
      )}
      {policy === undefined && (
        <Button variant="ghost" tone="neutral" size="xs" onClick={onSkip}>
          Skip — every user sees the same data
        </Button>
      )}
    </Card>
  )
}
