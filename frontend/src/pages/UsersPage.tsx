import { useState } from 'react'
import { MessageSquare, Plus, ShieldCheck, UserCog, Users as UsersIcon } from 'lucide-react'
import { toast } from 'sonner'
import { useApproveUser, useRejectUser, useUsers } from '../api/users'
import ApproveRejectButtons from '../components/ui/ApproveRejectButtons'
import Badge, { type BadgeTone } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import EmptyState from '../components/ui/EmptyState'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import { Skeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'
import CreateAccountForm from '../components/users/CreateAccountForm'
import SoeidCell from '../components/users/SoeidCell'

const STATUS_TONE = { pending: 'warning', approved: 'success', rejected: 'danger' } as const
const ROLE_TONE: Record<string, BadgeTone> = { admin: 'brand', viewer: 'info', chat_user: 'neutral' }

export default function UsersPage() {
  const { data: users, isLoading } = useUsers()
  const approve = useApproveUser()
  const reject = useRejectUser()
  const [showForm, setShowForm] = useState(false)

  const pending = users?.filter((u) => u.status === 'pending') ?? []
  const decided = users?.filter((u) => u.status !== 'pending') ?? []
  const staffCount = users?.filter((u) => u.role === 'admin' || u.role === 'viewer').length ?? 0
  const chatUserCount = users?.filter((u) => u.role === 'chat_user' && u.status === 'approved').length ?? 0

  function handleApprove(id: string, email: string) {
    approve.mutate(id, {
      onSuccess: () => toast.success(`${email} approved — they can now sign in and chat`),
      onError: (err) => toast.error((err as Error).message),
    })
  }

  function handleReject(id: string, email: string) {
    reject.mutate(id, {
      onSuccess: () => toast.success(`${email} rejected`),
      onError: (err) => toast.error((err as Error).message),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Approve chat-only signups, or create named admin/viewer accounts directly."
        actions={
          <Button onClick={() => setShowForm(true)} leftIcon={<Plus size={16} />}>
            New account
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile icon={UsersIcon} label="Total accounts" value={users?.length ?? 0} tone="brand" />
        <StatTile icon={UserCog} label="Pending approval" value={pending.length} tone="warning" />
        <StatTile icon={ShieldCheck} label="Admins / viewers" value={staffCount} tone="success" />
        <StatTile icon={MessageSquare} label="Chat users" value={chatUserCount} tone="neutral" />
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      )}

      {!isLoading && (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">
            Pending approval {pending.length > 0 && `(${pending.length})`}
          </h2>
          {pending.length === 0 ? (
            <EmptyState icon={UserCog} title="Nothing to review" message="No pending registrations right now." />
          ) : (
            <div className="space-y-2">
              {pending.map((user) => (
                <Card key={user.id} className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">{user.email}</div>
                    <div className="flex items-center gap-2 text-xs text-slate-400">
                      <span>Registered {new Date(user.created_at).toLocaleString()}</span>
                      <span>&middot;</span>
                      <span className="flex items-center gap-1">
                        SOEID: <SoeidCell user={user} />
                      </span>
                    </div>
                  </div>
                  <ApproveRejectButtons
                    onApprove={() => handleApprove(user.id, user.email)}
                    onReject={() => handleReject(user.id, user.email)}
                  />
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {!isLoading && decided.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Decided</h2>
          <div className="table-wrap overflow-hidden rounded-[--radius-card] border border-slate-200 dark:border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-2 font-medium">Email</th>
                  <th className="px-4 py-2 font-medium">SOEID</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Registered</th>
                </tr>
              </thead>
              <tbody>
                {decided.map((user) => (
                  <tr key={user.id} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="px-4 py-2">{user.email}</td>
                    <td className="px-4 py-2">
                      <SoeidCell user={user} />
                    </td>
                    <td className="px-4 py-2">
                      <Badge tone={ROLE_TONE[user.role]}>{user.role}</Badge>
                    </td>
                    <td className="px-4 py-2">
                      <Badge tone={STATUS_TONE[user.status]}>{user.status}</Badge>
                    </td>
                    <td className="px-4 py-2 text-slate-400">{new Date(user.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal open={showForm} onClose={() => setShowForm(false)} title="New account" maxWidth="max-w-md">
        <CreateAccountForm onDone={() => setShowForm(false)} />
      </Modal>
    </div>
  )
}
