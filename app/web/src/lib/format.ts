const DAY_MS = 86_400_000
const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/

function parseLocalDateOnly(value: string): Date | null {
  const match = DATE_ONLY_RE.exec(value)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2]) - 1
  const day = Number(match[3])
  const parsed = new Date(year, month, day)
  if (
    parsed.getFullYear() !== year ||
    parsed.getMonth() !== month ||
    parsed.getDate() !== day
  ) {
    return null
  }
  return parsed
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null
  // Due dates arrive as calendar dates. Parsing `YYYY-MM-DD` directly uses
  // UTC, which can display as the previous day in US time zones.
  const parsed = parseLocalDateOnly(value) ?? new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function daysSince(value: string | null | undefined): number | null {
  const date = parseDate(value)
  if (!date) return null
  if (value && DATE_ONLY_RE.test(value)) {
    const today = new Date()
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate())
    return Math.floor((todayStart.getTime() - date.getTime()) / DAY_MS)
  }
  return Math.floor((Date.now() - date.getTime()) / DAY_MS)
}

/** Short relative age for dense table cells: "3d ago", "5w ago", "Today". */
export function relativeAge(value: string | null | undefined): string | null {
  const days = daysSince(value)
  if (days === null) return null
  if (days <= 0) return 'Today'
  if (days === 1) return '1d ago'
  if (days < 14) return `${days}d ago`
  if (days < 60) return `${Math.floor(days / 7)}w ago`
  return `${Math.floor(days / 30)}mo ago`
}

/** Relative age for run timestamps, where minutes matter. */
export function relativeTime(value: string | null | undefined): string | null {
  const date = parseDate(value)
  if (!date) return null
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 14) return `${days}d ago`
  return `${Math.floor(days / 7)}w ago`
}

/** Durations: `4s`, `1m 04s`. Zero-padded so a ticking figure keeps its width. */
export function formatElapsedMs(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}m ${String(rest).padStart(2, '0')}s`
}

export function formatDuration(startedAt?: string | null, finishedAt?: string | null): string | null {
  const start = parseDate(startedAt)
  if (!start) return null
  const end = parseDate(finishedAt) ?? new Date()
  return formatElapsedMs(end.getTime() - start.getTime())
}

export function formatDate(value: string | null | undefined): string | null {
  const date = parseDate(value)
  if (!date) return null
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

/** Day and 24 hour clock for schedule timestamps: "Aug 1, 07:30". */
export function formatDateTime(value: string | null | undefined): string | null {
  const date = parseDate(value)
  if (!date) return null
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatWeekLabel(value: string): string {
  const date = parseDate(value)
  if (!date) return value
  return date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' })
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '0%'
  return `${Math.round(value)}%`
}

/** Title-cases a raw source or enum value the server did not label. */
export function humanize(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase())
}
