import { clsx } from 'clsx'
import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

interface ModalProps {
  id: string
  title: string
  subtitle?: string
  badges?: string[]
  children: ReactNode
}

export function Modal({ id, title, subtitle, badges, children }: ModalProps) {
  useEffect(() => {
    const el = document.getElementById(`modal-${id}`)
    if (!el) return
    const close = () => el.classList.remove('open')
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close()
    })
    return () => document.removeEventListener('keydown', (e) => {
      if (e.key === 'Escape') close()
    })
  }, [id])

  return (
    <div
      id={`modal-${id}`}
      className="fixed inset-0 z-50 hidden items-center justify-center bg-ink-950/80 p-6 backdrop-blur-md"
    >
      <div
        className={clsx(
          'flex max-h-[88vh] w-full max-w-[920px] flex-col overflow-hidden rounded-2xl border border-ink-600 bg-ink-900 shadow-[0_30px_80px_rgba(0,0,0,0.6)]',
        )}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-ink-700/70 p-5">
          <div>
            <h2 className="text-[17px] font-bold tracking-[-0.03em] text-fg-100">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[11px] text-fg-400">{subtitle}</p>}
            {badges && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {badges.map((b) => (
                  <span
                    key={b}
                    className="rounded bg-gold-600/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em] text-gold-300 ring-1 ring-gold-600/20"
                  >
                    {b}
                  </span>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={() => document.getElementById(`modal-${id}`)?.classList.remove('open')}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-ink-700 bg-ink-800 text-fg-300 transition-colors hover:bg-ink-700 hover:text-fg-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

export function openModal(id: string) {
  document.getElementById(`modal-${id}`)?.classList.add('open')
}
