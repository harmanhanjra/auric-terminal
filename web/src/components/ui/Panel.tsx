import { clsx } from 'clsx'
import type { HTMLAttributes, ReactNode } from 'react'

interface PanelProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  label?: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}

export function Panel({ label, right, children, className, ...props }: PanelProps) {
  return (
    <section
      className={clsx(
        'auric-surface flex min-h-0 flex-col rounded-xl',
        className,
      )}
      {...props}
    >
      {(label || right) && (
        <header className="flex h-9 shrink-0 items-center justify-between border-b border-white/[0.055] px-3">
          <h2 className="text-[10px] font-bold uppercase tracking-[0.12em] text-fg-400">
            {label}
          </h2>
          {right && <div className="flex items-center gap-2">{right}</div>}
        </header>
      )}
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  )
}
