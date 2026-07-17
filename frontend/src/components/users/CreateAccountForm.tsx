import { useState } from 'react'
import { toast } from 'sonner'
import { useCreateNamedUser } from '../../api/users'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Select from '../ui/Select'

const ROLE_OPTIONS = [
  { label: 'Admin — full access, can configure everything', value: 'admin' },
  { label: 'Viewer — read-only, no config changes', value: 'viewer' },
  { label: 'Chat user — chatbot only, nothing else', value: 'chat_user' },
]

export default function CreateAccountForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'admin' | 'viewer' | 'chat_user'>('viewer')
  const [soeid, setSoeid] = useState('')
  const createUser = useCreateNamedUser()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    createUser.mutate(
      { email, password, role, soeid: soeid.trim() || undefined },
      {
        onSuccess: () => {
          toast.success(`${email} created as ${role} — pre-approved, can sign in now`)
          onDone()
        },
        onError: (err) => toast.error((err as Error).message),
      },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <Input
        type="email"
        required
        label="Email"
        hideLabel={false}
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Input
        type="password"
        required
        minLength={8}
        label="Password"
        hideLabel={false}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Select
        label="Role"
        hideLabel={false}
        value={role}
        onChange={(e) => setRole(e.target.value as typeof role)}
        options={ROLE_OPTIONS}
      />
      <div>
        <Input
          label="SOEID (optional)"
          hideLabel={false}
          value={soeid}
          placeholder="aa12345"
          onChange={(e) => setSoeid(e.target.value)}
        />
        <span className="mt-1 block text-xs text-slate-400">
          Corporate id — grants access to any domain dataset keyed by this same id. Can be set later.
        </span>
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <Button type="button" variant="ghost" tone="neutral" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" isPending={createUser.isPending} loadingLabel="Creating…">
          Create account
        </Button>
      </div>
    </form>
  )
}
