export function AuricBackdrop() {
  return (
    <div className="auric-backdrop pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
      <div className="terminal-grid absolute inset-0 opacity-60" />
      <div className="auric-vignette" />
    </div>
  )
}
