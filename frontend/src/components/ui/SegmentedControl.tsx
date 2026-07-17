export interface SegmentedControlOption<T extends string | number> {
  label: string
  value: T
}

export interface SegmentedControlProps<T extends string | number> {
  options: readonly SegmentedControlOption<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
  'aria-label'?: string
}

/** Pill-button toggle group — for time-range/window pickers and similar
 * small, mutually-exclusive option sets (not a full Tabs widget). */
export default function SegmentedControl<T extends string | number>({
  options,
  value,
  onChange,
  className = '',
  'aria-label': ariaLabel,
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={`flex gap-1 rounded-md border border-slate-200 p-0.5 dark:border-slate-800 ${className}`}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
            value === opt.value
              ? 'bg-brand-600 text-white'
              : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
