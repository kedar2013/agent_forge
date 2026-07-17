import { useState } from 'react'
import { Rocket } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMyPublishRequests, usePublishRequests } from '../api/agents'
import ApproveRejectButtons from '../components/ui/ApproveRejectButtons'
import Badge, { type BadgeTone } from '../components/ui/Badge'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import ReviewModal from '../components/publishRequests/ReviewModal'
import { Skeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'

const STATUS_TONE: Record<string, BadgeTone> = { pending: 'warning', approved: 'success', rejected: 'danger' }

export default function PublishRequestsPage({ mine = false }: { mine?: boolean }) {
  const [statusFilter, setStatusFilter] = useState<'pending' | 'approved' | 'rejected'>('pending')
  const adminQuery = usePublishRequests(statusFilter)
  const mineQuery = useMyPublishRequests()
  const { data: allRequests, isLoading } = mine ? mineQuery : adminQuery
  const requests = mine ? allRequests?.filter((r) => r.status === statusFilter) : allRequests
  const [reviewing, setReviewing] = useState<{ id: string; action: 'approve' | 'reject' } | null>(null)

  const pendingCount = (mine ? allRequests?.filter((r) => r.status === 'pending').length : statusFilter === 'pending' ? requests?.length : undefined) ?? undefined

  return (
    <div className="space-y-6">
      <PageHeader
        title={mine ? 'My publish requests' : 'Publish requests'}
        description={
          mine
            ? 'Agents you asked to publish, and what an admin decided — nothing goes live until approved.'
            : 'Every agent a developer tries to publish lands here first — nothing goes live until you approve it.'
        }
      />

      <div className="grid grid-cols-3 gap-4">
        <StatTile icon={Rocket} label="Pending review" value={pendingCount ?? '—'} tone="warning" />
      </div>

      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-800">
        {(['pending', 'approved', 'rejected'] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium capitalize ${
              statusFilter === s
                ? 'border-brand-600 text-brand-600 dark:text-brand-400'
                : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {!isLoading && (!requests || requests.length === 0) && (
        <EmptyState icon={Rocket} title="Nothing here" message={`No ${statusFilter} publish requests.`} />
      )}

      {!isLoading && requests && requests.length > 0 && (
        <div className="space-y-2">
          {requests.map((req) => (
            <Card key={req.id} className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Link
                    to={`/agents/${req.agent_id}`}
                    className="text-sm font-medium text-brand-600 hover:underline dark:text-brand-400"
                  >
                    Agent {req.agent_id.slice(0, 8)}
                  </Link>
                  <Badge tone={STATUS_TONE[req.status]}>{req.status}</Badge>
                  {req.published_version != null && <Badge tone="success">v{req.published_version}</Badge>}
                </div>
                <div className="mt-0.5 text-xs text-slate-400">
                  Requested by {req.requested_by ?? 'unknown'} · {new Date(req.created_at).toLocaleString()}
                </div>
                {req.review_note && (
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">"{req.review_note}"</p>
                )}
              </div>
              {!mine && req.status === 'pending' && (
                <div className="shrink-0">
                  <ApproveRejectButtons
                    onApprove={() => setReviewing({ id: req.id, action: 'approve' })}
                    onReject={() => setReviewing({ id: req.id, action: 'reject' })}
                  />
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={reviewing !== null}
        onClose={() => setReviewing(null)}
        title={reviewing?.action === 'approve' ? 'Approve & publish' : 'Reject request'}
        maxWidth="max-w-md"
      >
        {reviewing && <ReviewModal requestId={reviewing.id} action={reviewing.action} onClose={() => setReviewing(null)} />}
      </Modal>
    </div>
  )
}
