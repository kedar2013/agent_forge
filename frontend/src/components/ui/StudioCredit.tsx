export default function StudioCredit({ className = '' }: { className?: string }) {
  return (
    <p className={`text-[11px] text-slate-400 dark:text-slate-500 ${className}`}>
      Developed by{' '}
      <span className="font-medium text-slate-500 dark:text-slate-400">Kedar's Eärendil Studio</span>
    </p>
  )
}
