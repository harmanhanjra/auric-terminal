import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/utils'

interface SurfaceProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  elevated?: boolean
  interactive?: boolean
}

export function Surface({
  children,
  className,
  elevated = false,
  interactive = false,
  ...props
}: SurfaceProps) {
  return (
    <div
      className={cn(
        'auric-surface relative overflow-hidden rounded-xl border border-white/[0.065] bg-ink-900/78',
        elevated && 'auric-surface-elevated',
        interactive && 'auric-surface-interactive',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
