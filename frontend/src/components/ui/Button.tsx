import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: 'primary' | 'outline' | 'ghost'
  tone?: 'brand' | 'neutral' | 'danger'
  size?: 'xs' | 'sm' | 'icon'
  isPending?: boolean
  loadingLabel?: ReactNode
  leftIcon?: ReactNode
  rightIcon?: ReactNode
  children?: ReactNode
  /** When set, renders a React Router `Link` instead of a `<button>` — for
   * "New X" actions that navigate rather than submit/mutate. */
  to?: string
  className?: string
}

const sizeClasses = {
  xs: 'px-2.5 py-1.5 text-xs',
  sm: 'px-3 py-1.5 text-sm',
  icon: 'p-1.5',
} as const

function variantClasses(variant: NonNullable<ButtonProps['variant']>, tone: NonNullable<ButtonProps['tone']>): string {
  if (variant === 'primary') {
    if (tone === 'danger') return 'bg-red-600 text-white hover:bg-red-700'
    if (tone === 'neutral') return 'bg-slate-800 text-white hover:bg-slate-900 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-white'
    return 'bg-brand-600 text-white hover:bg-brand-700'
  }
  if (variant === 'outline') {
    if (tone === 'brand') return 'border border-brand-300 text-brand-600 hover:bg-brand-50 dark:border-brand-800 dark:hover:bg-brand-950'
    if (tone === 'danger') return 'border border-red-200 text-red-600 hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950'
    return 'border border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800'
  }
  // ghost
  if (tone === 'brand') return 'text-brand-600 hover:text-brand-700'
  if (tone === 'danger') return 'text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950'
  return 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
}

/** Shared button primitive covering every treatment used across the app:
 * solid brand/danger CTA (primary), bordered secondary/brand/danger
 * (outline), plain text links and icon-only actions (ghost). Pass `to` to
 * render a navigating `Link` instead of a `<button>`. */
export default function Button({
  variant = 'primary',
  tone = 'brand',
  size = 'sm',
  isPending = false,
  loadingLabel,
  leftIcon,
  rightIcon,
  children,
  disabled,
  className = '',
  type = 'button',
  to,
  ...rest
}: ButtonProps) {
  const iconHoverBg =
    size === 'icon' ? (tone === 'danger' ? 'hover:bg-red-50 dark:hover:bg-red-950' : 'hover:bg-slate-100 dark:hover:bg-slate-800') : ''
  const shape = size === 'icon' ? `rounded-md ${sizeClasses.icon}` : variant === 'ghost' ? 'font-medium' : `rounded-md font-medium ${sizeClasses[size]}`
  const sharedClassName = `inline-flex items-center gap-1.5 whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${shape} ${iconHoverBg} ${variantClasses(variant, tone)} ${className}`

  if (to) {
    return (
      <Link to={to} className={sharedClassName} aria-disabled={disabled || isPending || undefined}>
        {!isPending && leftIcon}
        {isPending ? (loadingLabel ?? children) : children}
        {!isPending && rightIcon}
      </Link>
    )
  }

  return (
    <button type={type} disabled={disabled || isPending} className={sharedClassName} {...rest}>
      {!isPending && leftIcon}
      {isPending ? (loadingLabel ?? children) : children}
      {!isPending && rightIcon}
    </button>
  )
}
