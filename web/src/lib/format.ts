export function fmtPrice(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v) || v <= 0) return '—'
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function fmtMoney(v: number | undefined | null, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}$${v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

export function fmtPct(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v.toFixed(2)}%`
}

export function fmtTime(ts?: number | string, includeDate = false): string {
  if (!ts) return '—'
  const d = new Date(typeof ts === 'string' && !/^\d+$/.test(ts) ? ts : Number(ts))
  if (Number.isNaN(d.getTime())) return '—'
  return (includeDate ? d.toLocaleDateString() + ' ' : '') + d.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/* Additional financial formatting utilities */

export function fmtVolume(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return '—'

  if (Math.abs(v) >= 1_000_000) {
    return `${(v / 1_000_000).toFixed(2)}M`
  } else if (Math.abs(v) >= 1_000) {
    return `${(v / 1_000).toFixed(2)}K`
  } else {
    return v.toFixed(3)
  }
}

export function fmtNotional(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return '—'

  if (Math.abs(v) >= 1_000_000) {
    return `$${(v / 1_000_000).toFixed(2)}M`
  } else if (Math.abs(v) >= 1_000) {
    return `$${(v / 1_000).toFixed(2)}K`
  } else {
    return `$${v.toFixed(2)}`
  }
}

export function fmtRatio(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(2)
}

export function fmtSpread(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(4)
}

export function fmtPercentageChange(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${Math.abs(v).toFixed(2)}%`
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'

  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

export function truncateString(str: string, maxLength: number): string {
  if (!str || str.length <= maxLength) return str
  return str.slice(0, maxLength - 3) + '...'
}

export function formatLatency(ms: number): string {
  if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}