import { useState } from 'react'
import { Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { useUpdateUser } from '../../api/users'
import type { AppUser } from '../../api/users'
import Button from '../ui/Button'
import Input from '../ui/Input'

export default function SoeidCell({ user }: { user: AppUser }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(user.soeid ?? '')
  const updateUser = useUpdateUser()

  function save() {
    const soeid = value.trim() || null
    updateUser.mutate(
      { id: user.id, soeid },
      {
        onSuccess: () => {
          toast.success(soeid ? `SOEID set to ${soeid}` : 'SOEID cleared')
          setEditing(false)
        },
        onError: (err) => toast.error((err as Error).message),
      },
    )
  }

  if (!editing) {
    return (
      <button
        onClick={() => {
          setValue(user.soeid ?? '')
          setEditing(true)
        }}
        className="flex items-center gap-1 text-slate-600 hover:text-brand-600 dark:text-slate-300 dark:hover:text-brand-400"
      >
        {user.soeid ?? <span className="text-slate-400">not set</span>}
        <Pencil size={12} />
      </button>
    )
  }

  return (
    <div className="flex items-center gap-1">
      <Input
        autoFocus
        label="SOEID"
        size="xs"
        className="w-24"
        value={value}
        placeholder="aa12345"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') save()
          if (e.key === 'Escape') setEditing(false)
        }}
      />
      <Button size="xs" onClick={save} isPending={updateUser.isPending} loadingLabel="Save">
        Save
      </Button>
      <Button size="xs" variant="ghost" tone="neutral" onClick={() => setEditing(false)}>
        Cancel
      </Button>
    </div>
  )
}
