import Modal from './Modal'

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger = false,
  maxWidth = 'max-w-sm',
  children,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  maxWidth?: string
  /** Extra content rendered between the message and the button row — e.g. a diff preview. */
  children?: React.ReactNode
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal open={open} onClose={onCancel} title={title} maxWidth={maxWidth}>
      <p className="text-sm text-slate-600 dark:text-slate-400">{message}</p>
      {children && <div className="mt-4">{children}</div>}
      <div className="mt-5 flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          className={`rounded-md px-3 py-1.5 text-sm font-medium text-white ${
            danger ? 'bg-red-600 hover:bg-red-700' : 'bg-brand-600 hover:bg-brand-700'
          }`}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
