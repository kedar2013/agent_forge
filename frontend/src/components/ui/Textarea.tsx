import { useId, type TextareaHTMLAttributes } from 'react'

export interface TextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  /** Accessible name. Shown visually unless hideLabel (default). */
  label: string
  id?: string
  hideLabel?: boolean
  error?: string
  size?: 'sm' | 'xs'
}

const sizeClasses = {
  sm: 'rounded-md px-3 py-2 text-sm',
  xs: 'rounded px-2 py-1 text-xs',
} as const

const baseClass =
  'w-full border border-slate-300 focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 resize-y'

/** Labelled <textarea> */
export default function Textarea({
  label,
  id,
  hideLabel = true,
  error,
  size = 'sm',
  className = '',
  ...rest
}: TextareaProps) {
  const autoId = useId()
  const textareaId = id ?? autoId

  return (
    <div className="w-full max-w-5xl">
      <label
        htmlFor={textareaId}
        className={
          hideLabel
            ? 'sr-only'
            : 'mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200'
        }
      >
        {label}
      </label>

      <textarea
        id={textareaId}
        className={`
          ${baseClass}
          ${sizeClasses[size]}
          ${error ? 'border-red-400 focus:border-red-500' : ''}
          ${className}
        `}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${textareaId}-error` : undefined}
        {...rest}
      />

      {error && (
        <p
          id={`${textareaId}-error`}
          className="mt-1 text-xs text-red-600 dark:text-red-400"
        >
          {error}
        </p>
      )}
    </div>
  )
}