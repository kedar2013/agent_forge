const SIZES = {
  sm: { mark: 22, text: 'text-sm' },
  md: { mark: 28, text: 'text-base' },
  lg: { mark: 40, text: 'text-xl' },
} as const

export default function Logo({
  size = 'md',
  withWordmark = true,
  className = '',
}: {
  size?: keyof typeof SIZES
  withWordmark?: boolean
  className?: string
}) {
  const { mark, text } = SIZES[size]
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <img
        src="/favicon.svg"
        alt="Eärendil"
        width={mark}
        height={mark}
        className="shrink-0 drop-shadow-[0_2px_8px_rgba(94,63,230,0.35)]"
      />
      {withWordmark && (
        <span className={`bg-gradient-to-r from-brand-600 to-accent-500 bg-clip-text font-bold tracking-tight text-transparent dark:from-brand-300 dark:to-accent-400 ${text}`}>
          Eärendil
        </span>
      )}
    </div>
  )
}
