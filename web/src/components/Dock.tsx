import type { Quote } from '../lib/types'

interface DockProps {
  quote: Quote
  live: boolean
  view: string
  onNavigate: (key: string) => void
}

export function Dock({}: DockProps) {
  return (
    <div className="flex-1 bg-ink-900">
      <div className="p-4 text-fg-400 text-sm">Dock panel – UI loaded</div>
    </div>
  )
}
