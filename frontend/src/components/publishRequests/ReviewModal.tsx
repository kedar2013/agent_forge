import { useState } from 'react'
import { toast } from 'sonner'
import { useApprovePublishRequest, useRejectPublishRequest } from '../../api/agents'
import Button from '../ui/Button'
import Textarea from '../ui/Textarea'

export default function ReviewModal({
  requestId,
  action,
  onClose,
}: {
  requestId: string
  action: 'approve' | 'reject'
  onClose: () => void
}) {
  const [note, setNote] = useState('')
  const approve = useApprovePublishRequest()
  const reject = useRejectPublishRequest()
  const mutation = action === 'approve' ? approve : reject

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    mutation.mutate(
      { id: requestId, review_note: note || undefined },
      {
        onSuccess: () => {
          toast.success(action === 'approve' ? 'Agent published' : 'Request rejected')
          onClose()
        },
        onError: (err) => toast.error((err as Error).message),
      },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <Textarea
        rows={3}
        label="Review note (optional)"
        hideLabel={false}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={
          action === 'approve'
            ? 'Visible to the developer who requested this.'
            : 'Why this was rejected — visible to the developer.'
        }
      />
      <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <Button type="button" variant="ghost" tone="neutral" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="submit"
          tone={action === 'approve' ? 'brand' : 'danger'}
          isPending={mutation.isPending}
          loadingLabel="Saving…"
        >
          {action === 'approve' ? 'Approve & publish' : 'Reject'}
        </Button>
      </div>
    </form>
  )
}
