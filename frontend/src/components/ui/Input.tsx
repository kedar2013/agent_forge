import { useId, type InputHTMLAttributes } from 'react'

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'size'> {
  /** Accessible name. Shown visually unless hideLabel (default) — pair with a
   * visible caption elsewhere (e.g. GuidedField's label) using the same text. */
  label: string
  id?: string
  hideLabel?: boolean
  error?: string
  /** 'xs' = compact inline-edit variant (table cells, dense config grids). */
  size?: 'sm' | 'xs'
}

const sizeClasses = {
  sm: 'rounded-md px-2 py-1.5 text-sm',
  xs: 'rounded px-1.5 py-0.5 text-xs',
} as const

const baseClass = 'w-full border border-slate-300 focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100'

/** Labelled <input> — always renders a real <label htmlFor> tied to the
 * input's id, even when visually hidden, so screen readers get a
 * programmatic name that purely-visual caption text doesn't provide. */
export default function Input({ label, id, hideLabel = true, error, size = 'sm', className = '', ...rest }: InputProps) {
  const autoId = useId()
  const inputId = id ?? autoId
  return (
    <div>
      <label htmlFor={inputId} className={hideLabel ? 'sr-only' : 'mb-1 block text-sm font-medium'}>
        {label}
      </label>
      <input
        id={inputId}
        className={`${baseClass} ${sizeClasses[size]} ${error ? 'border-red-400 focus:border-red-500' : ''} ${className}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : undefined}
        {...rest}
      />
      {error && (
        <p id={`${inputId}-error`} className="mt-1 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
