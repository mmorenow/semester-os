/**
 * Clock, date and week helpers for School. The server sends 24h `HH:MM` and `YYYY-MM-DD`; the UI shows
 * `9:30a`, `11:59p`, and ranges sharing a meridiem as `9:30-10:20a`. Machine timestamps stay 24h in `lib/format.ts`.
 */

export const MINUTES_PER_DAY = 1440

const WEEKDAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

/** `"13:30"` becomes 810. Returns null for anything that is not `HH:MM`. */
export function parseHhMm(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim())
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null
  if (hours > 23 || minutes > 59) return null
  return hours * 60 + minutes
}

/** Minutes since local midnight for a Date. */
export function minutesOfDay(date: Date): number {
  return date.getHours() * 60 + date.getMinutes()
}

/** 810 becomes `1:30p`. */
export function formatClock(totalMinutes: number): string {
  const wrapped = ((Math.round(totalMinutes) % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY
  const hours24 = Math.floor(wrapped / 60)
  const minutes = wrapped % 60
  const meridiem = hours24 >= 12 ? 'p' : 'a'
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12
  return `${String(hours12)}:${pad2(minutes)}${meridiem}`
}

/** The 44px hour gutter can't fit `11:00a`, so on-the-hour ticks read `11a`. */
export function formatHourTick(totalMinutes: number): string {
  const full = formatClock(totalMinutes)
  return full.replace(':00', '')
}

/** A range that drops the shared meridiem: `9:30-10:20a`, `11:30a-1:20p`. */
export function formatClockRange(startMinutes: number, endMinutes: number): string {
  const start = formatClock(startMinutes)
  const end = formatClock(endMinutes)
  const sameMeridiem = start.slice(-1) === end.slice(-1)
  return sameMeridiem ? `${start.slice(0, -1)}-${end}` : `${start}-${end}`
}

/** A duration in minutes as a compact mono span: `24m`, `1h 05m`, `2h`. */
export function formatSpan(minutes: number): string {
  const total = Math.max(0, Math.round(minutes))
  if (total < 60) return `${String(total)}m`
  const hours = Math.floor(total / 60)
  const rest = total % 60
  return rest === 0 ? `${String(hours)}h` : `${String(hours)}h ${pad2(rest)}m`
}

/** `YYYY-MM-DD` in local time. `toISOString` would shift the day westward. */
export function toIsoDate(date: Date): string {
  return `${String(date.getFullYear())}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

/** Parses `YYYY-MM-DD` as local midnight, which `new Date(string)` does not. */
export function parseIsoDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim())
  if (!match) return null
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return Number.isNaN(date.getTime()) ? null : date
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

export function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

/** Monday of the week that contains `date`. */
export function startOfWeek(date: Date): Date {
  const day = date.getDay()
  const offset = day === 0 ? -6 : 1 - day
  return startOfDay(addDays(date, offset))
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  )
}

/** Whole days from `from` to `to`, ignoring the time of day. */
export function dayDelta(from: Date, to: Date): number {
  const a = startOfDay(from).getTime()
  const b = startOfDay(to).getTime()
  return Math.round((b - a) / 86_400_000)
}

export function shortWeekday(date: Date): string {
  return WEEKDAY_SHORT[date.getDay()]
}

export function longWeekday(date: Date): string {
  return date.toLocaleDateString('en-US', { weekday: 'long' })
}

/** `Aug 24`. */
export function shortMonthDay(date: Date): string {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** `Aug 24-28`, and `Aug 31-Sep 4` when the week crosses a month. */
export function weekRangeLabel(first: Date, last: Date): string {
  const sameMonth = first.getMonth() === last.getMonth() && first.getFullYear() === last.getFullYear()
  return sameMonth
    ? `${shortMonthDay(first)}-${String(last.getDate())}`
    : `${shortMonthDay(first)}-${shortMonthDay(last)}`
}

/** Urgency bands. With no score, this plus graded weight is the whole priority story. */
export type DueTone = 'overdue' | 'today' | 'soon' | 'later'

export interface DueLabel {
  label: string
  tone: DueTone
  /** Sortable timestamp; items with no due date sort last. */
  at: number
}

/**
 * Named within a week (`Wed 11:59p`), absolute beyond it (`Sep 4, 11:59p`), `2d overdue` once past.
 * With an `endsAt`, it shows a window (`Wed 8-10p`), measures urgency to the end, and reads as a past
 * date rather than overdue once closed. Sorting stays on the start.
 */
export function dueLabel(
  dueAt: string | null | undefined,
  now: Date,
  endsAt?: string | null,
): DueLabel | null {
  if (!dueAt) return null
  // Parse a bare `YYYY-MM-DD` as a local day; `new Date(string)` reads it as UTC and shows the day before.
  const dateOnly = parseIsoDate(dueAt)
  const date = dateOnly ?? new Date(dueAt)
  if (Number.isNaN(date.getTime())) return null

  const endDate = !dateOnly && endsAt ? new Date(endsAt) : null
  const windowEnd = endDate && !Number.isNaN(endDate.getTime()) && endDate.getTime() > date.getTime() ? endDate : null

  // A bare date means due that day: urgency flips at local end of day, and no clock is shown.
  const at = dateOnly ? addDays(dateOnly, 1).getTime() - 1 : date.getTime()
  const diffMs = (windowEnd ? windowEnd.getTime() : at) - now.getTime()

  const clock = dateOnly
    ? null
    : windowEnd
      ? formatClockRange(minutesOfDay(date), minutesOfDay(windowEnd))
      : formatClock(minutesOfDay(date))
  const suffix = clock ? ` ${clock}` : ''
  const days = dayDelta(now, date)

  if (diffMs < 0 && windowEnd) {
    if (days === 0) return { label: `Today${suffix}`, tone: 'later', at }
    if (days === -1) return { label: `Yesterday${suffix}`, tone: 'later', at }
    return { label: `${shortMonthDay(date)},${suffix}`, tone: 'later', at }
  }

  if (diffMs < 0) {
    if (dateOnly) {
      const overdueDays = dayDelta(date, now)
      return { label: `${String(overdueDays)}d overdue`, tone: 'overdue', at }
    }
    const overdueMinutes = Math.floor(-diffMs / 60_000)
    const overdueDays = dayDelta(date, now)
    const label = overdueDays >= 1 ? `${String(overdueDays)}d overdue` : `${formatSpan(overdueMinutes)} overdue`
    return { label, tone: 'overdue', at }
  }

  if (days <= 0) return { label: `Today${suffix}`, tone: 'today', at }
  if (days === 1) return { label: `Tomorrow${suffix}`, tone: 'soon', at }
  if (days < 7) return { label: `${shortWeekday(date)}${suffix}`, tone: days <= 3 ? 'soon' : 'later', at }
  return { label: clock ? `${shortMonthDay(date)}, ${clock}` : shortMonthDay(date), tone: 'later', at }
}

export const DUE_TONE_TEXT: Record<DueTone, string> = {
  overdue: 'text-signal-red',
  today: 'text-signal-amber',
  soon: 'text-foreground',
  later: 'text-muted-foreground',
}
