import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

type ButtonVariant = 'default' | 'outline' | 'ghost' | 'premium' | 'destructive'
type ButtonSize = 'sm' | 'md' | 'icon'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

const variantClasses: Record<ButtonVariant, string> = {
  default: 'border border-white/8 bg-white/[0.055] text-fg-100 hover:bg-white/[0.09]',
  outline: 'border border-ink-600/80 bg-ink-950/40 text-fg-300 hover:border-ink-500 hover:bg-ink-800/70 hover:text-fg-100',
  ghost: 'border border-transparent bg-transparent text-fg-400 hover:bg-white/[0.05] hover:text-fg-100',
  premium: 'border border-gold-400/25 bg-gold-400/[0.09] text-gold-300 shadow-[inset_0_1px_0_rgba(255,255,255,.05),0_0_24px_rgba(201,162,39,.07)] hover:border-gold-400/40 hover:bg-gold-400/[0.14]',
  destructive: 'border border-bear-500/30 bg-bear-500/[0.08] text-bear-400 hover:border-bear-400/45 hover:bg-bear-500/[0.14]',
}

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-[10px]',
  md: 'h-9 px-3.5 text-[11px]',
  icon: 'h-9 w-9',
}

export function Button({
  className,
  variant = 'default',
  size = 'md',
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'auric-control inline-flex shrink-0 items-center justify-center gap-2 rounded-lg font-bold tracking-[-0.01em] transition-[background-color,border-color,color,box-shadow,transform] duration-200 active:translate-y-px disabled:pointer-events-none disabled:opacity-40',
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    />
  )
}
