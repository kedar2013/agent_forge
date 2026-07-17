import { useState } from 'react'
import { Plus, ShieldCheck } from 'lucide-react'
import { useAccessPolicies } from '../api/accessPolicies'
import AccessPolicyCard from '../components/accessPolicies/AccessPolicyCard'
import AccessPolicyForm from '../components/accessPolicies/AccessPolicyForm'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import { CardGridSkeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'

export default function AccessPoliciesPage() {
  const { data: policies, isLoading, error } = useAccessPolicies()
  const [showForm, setShowForm] = useState(false)

  const mysqlCount = policies?.filter((p) => p.resolver_config.type === 'mysql').length ?? 0
  const mongoCount = policies?.filter((p) => p.resolver_config.type === 'mongo').length ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="Access Policies"
        description="Row-level security rules a mysql_query_tool/mongo_query_tool can enforce — what each persona is allowed to see, resolved from the logged-in user's identity."
        actions={
          <Button onClick={() => setShowForm(true)} leftIcon={<Plus size={16} />}>
            New Access Policy
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <StatTile icon={ShieldCheck} label="Total policies" value={policies?.length ?? 0} tone="brand" />
        <StatTile icon={ShieldCheck} label="MySQL-backed" value={mysqlCount} tone="neutral" />
        <StatTile icon={ShieldCheck} label="Mongo-backed" value={mongoCount} tone="success" />
      </div>

      {isLoading && <CardGridSkeleton />}
      {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
      {!isLoading && !policies?.length && (
        <EmptyState
          icon={ShieldCheck}
          title="No access policies yet"
          message="An access policy resolves a logged-in user's persona and scope, then gates what a query tool can return — the same pattern Credit Facility Analysis uses for GCM/GSG/Non-GSG/CCB."
          action={
            <Button onClick={() => setShowForm(true)}>
              + New Access Policy
            </Button>
          }
        />
      )}
      {!isLoading && !!policies?.length && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {policies.map((policy) => (
            <AccessPolicyCard key={policy.id} policy={policy} />
          ))}
        </div>
      )}

      <Modal open={showForm} onClose={() => setShowForm(false)} title="New Access Policy" maxWidth="max-w-2xl">
        <AccessPolicyForm onDone={() => setShowForm(false)} />
      </Modal>
    </div>
  )
}
