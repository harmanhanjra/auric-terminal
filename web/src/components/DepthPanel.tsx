import type { Quote } from '../lib/types'

export function DepthPanel({}: { quote: Quote }) {
  return (
    <div className="p-3 border-b border-ink-700/70">
      <div className="text-fg-400 text-xs">Market Depth – stub</div>
    </div>
  )
}
