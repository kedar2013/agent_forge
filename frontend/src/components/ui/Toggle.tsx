import { useId } from 'react'

export interface ToggleProps {
  /** Visible label text, rendered next to the switch. */
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  /** Optional helper text below the label. */
  description?: string
  disabled?: boolean
  id?: string
}

/** Accessible switch/toggle primitive. Renders a `role="switch"` button
 * (brand-colored pill track + sliding circle) paired with a real
 * `<label htmlFor>` so clicking the label text also toggles the switch. */
export default function Toggle({ label, checked, onChange, description, disabled = false, id }: ToggleProps) {
  const autoId = useId()
  const toggleId = id ?? autoId

  return (
    <div className="flex items-start justify-between gap-3">
      <label htmlFor={toggleId} className={`select-none ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}>
        <span className="block text-sm font-medium text-slate-900 dark:text-slate-100">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">{description}</span>}
      </label>
      <button
        id={toggleId}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed dark:focus-visible:ring-offset-slate-900 ${
          checked ? 'bg-brand-600' : 'bg-slate-300 dark:bg-slate-700'
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-6' : 'translate-x-1'
          }`}
        />
      </button>
    </div>
  )
}
