import { clsx } from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant =
  | 'default'
  | 'primary'
  | 'sell'
  | 'ghost'
  | 'outline'
  | 'premium'
  | 'danger'
  | 'destructive'

type Size = 'sm' | 'md' | 'icon'

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
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={clsx(
        'auric-control inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg font-semibold',
        'transition-[background-color,border-color,color,box-shadow,transform] duration-200 active:translate-y-px',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-400/45',
        'disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-40',
        size === 'sm' && 'h-7 px-2.5 text-[11px]',
        size === 'md' && 'h-9 px-3.5 text-xs',
        size === 'icon' && 'h-9 w-9',
        variant === 'default' &&
          'border border-white/[0.08] bg-white/[0.055] text-fg-100 hover:bg-white/[0.09]',
        variant === 'primary' &&
          'border border-bull-400/25 bg-bull-500 text-white shadow-[0_0_20px_rgba(22,199,132,.08)] hover:bg-bull-400',
        variant === 'sell' &&
          'border border-bear-400/25 bg-bear-500 text-white shadow-[0_0_20px_rgba(234,57,67,.08)] hover:bg-bear-400',
        (variant === 'danger' || variant === 'destructive') &&
          'border border-bear-500/30 bg-bear-500/[0.09] text-bear-400 hover:border-bear-400/45 hover:bg-bear-500/[0.14]',
        variant === 'ghost' &&
          'border border-transparent bg-transparent text-fg-400 hover:bg-white/[0.05] hover:text-fg-100',
        variant === 'outline' &&
          'border border-ink-600/80 bg-ink-950/40 text-fg-300 hover:border-ink-500 hover:bg-ink-800/70 hover:text-fg-100',
        variant === 'premium' &&
          'border border-gold-400/25 bg-gold-400/[0.09] text-gold-300 shadow-[inset_0_1px_0_rgba(255,255,255,.05),0_0_24px_rgba(201,162,39,.07)] hover:border-gold-400/40 hover:bg-gold-400/[0.14]',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
