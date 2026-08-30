import { clsx } from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'sell' | 'ghost' | 'outline' | 'danger'
type Size = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  children: ReactNode
  className?: string
}

export function Button({
  variant = 'ghost',
  size = 'md',
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-semibold transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-500/60',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' && 'h-7 px-2.5 text-[11px]',
        size === 'md' && 'h-9 px-3.5 text-xs',
        variant === 'primary' &&
          'bg-bull-500 text-white hover:bg-bull-400 active:bg-bull-500',
        variant === 'sell' &&
          'bg-bear-500 text-white hover:bg-bear-400 active:bg-bear-500',
        variant === 'danger' &&
          'bg-bear-500/90 text-white hover:bg-bear-500',
        variant === 'ghost' &&
          'text-fg-300 hover:bg-ink-700 hover:text-fg-100',
        variant === 'outline' &&
          'border border-ink-600 bg-ink-800 text-fg-200 hover:border-ink-500 hover:bg-ink-700',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}