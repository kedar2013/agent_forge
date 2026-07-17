import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

export default function Modal({
  open,
  onClose,
  title,
  children,
  maxWidth = 'max-w-lg',
}: {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  maxWidth?: string
}) {
  useEffect(() => {
    if (!open) return
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/50 p-4 pt-16 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        className={`w-full ${maxWidth} rounded-[--radius-card] border border-white/60 bg-white/85 shadow-[inset_0_1px_0_rgba(255,255,255,0.6),var(--shadow-card-hover)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/85 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05),var(--shadow-card-hover)]`}
      >
        <div className="flex items-center justify-between border-b border-slate-200/70 px-5 py-3 dark:border-white/10">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          >
            <X size={18} />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
