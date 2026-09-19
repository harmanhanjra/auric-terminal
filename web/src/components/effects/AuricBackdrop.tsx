export function AuricBackdrop() {
  return (
    <div className="auric-backdrop pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
      <div className="auric-orb auric-orb-gold" />
      <div className="auric-orb auric-orb-cyan" />
      <div className="auric-beam auric-beam-one" />
      <div className="auric-beam auric-beam-two" />
      <div className="auric-vignette" />
      <div className="auric-noise" />
    </div>
  )
}
