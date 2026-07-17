import { Check, X } from 'lucide-react'
import Button from './Button'

export interface ApproveRejectButtonsProps {
  onApprove: () => void
  onReject: () => void
  isApproving?: boolean
  isRejecting?: boolean
  approveLabel?: string
  rejectLabel?: string
}

/** The Approve/Reject button pair used for pending-user and publish-request
 * review rows — callbacks may fire a mutation directly or open a review
 * modal, this component only renders the pair. */
export default function ApproveRejectButtons({
  onApprove,
  onReject,
  isApproving = false,
  isRejecting = false,
  approveLabel = 'Approve',
  rejectLabel = 'Reject',
}: ApproveRejectButtonsProps) {
  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" tone="danger" size="xs" onClick={onReject} isPending={isRejecting} leftIcon={<X size={13} />}>
        {rejectLabel}
      </Button>
      <Button variant="primary" size="xs" onClick={onApprove} isPending={isApproving} leftIcon={<Check size={13} />}>
        {approveLabel}
      </Button>
    </div>
  )
}
