import { useId, type SelectHTMLAttributes } from 'react'

export interface SelectOption {
  label: string
  value: string
  /** Optional <optgroup> label. Consecutive options sharing the same group
   *  render together under one <optgroup>; ungrouped options render as
   *  plain <option>s in place. Existing flat option lists are unaffected. */
  group?: string
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'size'> {
  label: string
  id?: string
  hideLabel?: boolean
  error?: string
  size?: 'sm' | 'xs'
  options: SelectOption[]
  placeholder?: string
}

const sizeClasses = {
  sm: 'rounded-md px-2 py-1.5 text-sm',
  xs: 'rounded px-1.5 py-0.5 text-xs',
} as const

/** Splits options into ordered segments, breaking whenever `group` changes
 *  (including transitions to/from undefined), so consecutive same-group
 *  options render under one <optgroup> without reordering anything. */
function groupOptions(options: SelectOption[]): { group?: string; items: SelectOption[] }[] {
  const segments: { group?: string; items: SelectOption[] }[] = []
  for (const opt of options) {
    const last = segments[segments.length - 1]
    if (last && last.group === opt.group) {
      last.items.push(opt)
    } else {
      segments.push({ group: opt.group, items: [opt] })
    }
  }
  return segments
}

const baseClass =
  'w-full border border-slate-300 bg-white focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100'

/** Labelled <select> — same accessible-label contract as Input/Textarea. */
export default function Select({
  label,
  id,
  hideLabel = true,
  error,
  size = 'sm',
  options,
  placeholder,
  className = '',
  ...rest
}: SelectProps) {
  const autoId = useId()
  const selectId = id ?? autoId
  return (
    <div>
      <label htmlFor={selectId} className={hideLabel ? 'sr-only' : 'mb-1 block text-sm font-medium'}>
        {label}
      </label>
      <select
        id={selectId}
        className={`${baseClass} ${sizeClasses[size]} ${error ? 'border-red-400 focus:border-red-500' : ''} ${className}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${selectId}-error` : undefined}
        {...rest}
      >
        {placeholder != null && <option value="">{placeholder}</option>}
        {groupOptions(options).map((segment, i) => {
          const rendered = segment.items.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))
          return segment.group ? (
            <optgroup key={`${segment.group}-${i}`} label={segment.group}>
              {rendered}
            </optgroup>
          ) : (
            rendered
          )
        })}
      </select>
      {error && (
        <p id={`${selectId}-error`} className="mt-1 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
