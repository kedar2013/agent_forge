import { ChevronLeft, ChevronRight } from 'lucide-react'

export interface PaginationProps {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
  className?: string
}

/** Prev/next + "X–Y of Z" footer for offset-paginated lists/tables. Renders
 * nothing when everything already fits on one page. */
export default function Pagination({ total, limit, offset, onChange, className = '' }: PaginationProps) {
  if (total <= limit) return null
  const page = Math.floor(offset / limit) + 1
  const pageCount = Math.ceil(total / limit)
  return (
    <div className={`flex items-center justify-between text-xs text-slate-500 ${className}`}>
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(Math.max(0, offset - limit))}
          aria-label="Previous page"
          className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
        >
          <ChevronLeft size={14} />
        </button>
        <span>
          {page} / {pageCount}
        </span>
        <button
          type="button"
          disabled={page >= pageCount}
          onClick={() => onChange(offset + limit)}
          aria-label="Next page"
          className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}
