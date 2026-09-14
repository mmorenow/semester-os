import { parseHhMm, parseIsoDate } from '@/lib/school-time'
import { isAllDay, type Assignment, type ExternalEvent, type ScheduleEvent } from '@/lib/school-types'

/** A schedule event with its clock strings resolved into real local times. */
export interface TimedEvent {
  event: ScheduleEvent
  start: Date
  end: Date
  /** Minutes since midnight, which is what the grid positions against. */
  startMin: number
  endMin: number
}

/** The same resolution for an external event: a feed's, or one written from Notes. */
export interface TimedExternal {
  external: ExternalEvent
  start: Date
  end: Date
  startMin: number
  endMin: number
  /** True when the feed gave a day and no hour. */
  allDay: boolean
  /** Start equals end. Brightspace deadlines look like this; a point never becomes a block. */
  instant: boolean
}

/**
 * Graded work that occupies a room, e.g. an exam from `due_at` to `ends_at`. The server sends
 * instants (`Z`) or offset-less campus wall times, which the browser reads as local, as intended.
 */
export interface TimedSitting {
  assignment: Assignment
  start: Date
  end: Date
  startMin: number
  endMin: number
}

/** Resolve and sort events; unreadable dates or times are dropped, not drawn at midnight. */
export function toTimedEvents(events: ScheduleEvent[] | undefined): TimedEvent[] {
  const resolved: TimedEvent[] = []
  for (const event of events ?? []) {
    const day = parseIsoDate(event.date)
    const startMin = parseHhMm(event.start)
    const endMin = parseHhMm(event.end)
    if (!day || startMin === null || endMin === null) continue
    const start = new Date(day)
    start.setMinutes(startMin)
    const end = new Date(day)
    end.setMinutes(endMin)
    resolved.push({ event, start, end, startMin, endMin })
  }
  return resolved.sort((a, b) => a.start.getTime() - b.start.getTime())
}

/** Same for external feeds. Inactive events (soft-deleted cancellations) are dropped. */
export function toTimedExternals(events: ExternalEvent[] | undefined): TimedExternal[] {
  const resolved: TimedExternal[] = []
  for (const external of events ?? []) {
    if (external.is_active === 0 || external.is_active === false) continue
    const day = parseIsoDate(external.date)
    if (!day) continue

    const allDay = isAllDay(external)
    const startMin = allDay ? 0 : parseHhMm(external.start)
    const endMin = allDay ? 24 * 60 : parseHhMm(external.end)
    if (startMin === null || endMin === null) continue

    const start = new Date(day)
    start.setMinutes(startMin)
    const end = new Date(day)
    end.setMinutes(endMin)
    resolved.push({ external, start, end, startMin, endMin, allDay, instant: !allDay && endMin <= startMin })
  }
  return resolved.sort((a, b) => a.start.getTime() - b.start.getTime())
}

const BARE_DATE = /^\d{4}-\d{2}-\d{2}$/

/** Assignments with a timed `due_at` and a later `ends_at`. A block past midnight ends with its first day. */
export function toTimedSittings(assignments: Assignment[] | undefined): TimedSitting[] {
  const resolved: TimedSitting[] = []
  for (const assignment of assignments ?? []) {
    if (assignment.status === 'dropped' || !assignment.due_at || !assignment.ends_at) continue
    if (BARE_DATE.test(assignment.due_at.trim())) continue
    const start = new Date(assignment.due_at)
    const end = new Date(assignment.ends_at)
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) continue
    const startMin = start.getHours() * 60 + start.getMinutes()
    const sameDay = end.toDateString() === start.toDateString()
    const endMin = sameDay ? end.getHours() * 60 + end.getMinutes() : 24 * 60
    resolved.push({ assignment, start, end, startMin, endMin })
  }
  return resolved.sort((a, b) => a.start.getTime() - b.start.getTime())
}

/** One item on the week grid or Today timeline. A union so externals share lane-splitting with classes. */
export type GridItem =
  | ({ kind: 'class' } & TimedEvent)
  | ({ kind: 'external' } & TimedExternal)
  | ({ kind: 'sitting' } & TimedSitting)

export function asClassItems(items: TimedEvent[]): GridItem[] {
  return items.map((item) => ({ kind: 'class', ...item }))
}

export function asExternalItems(items: TimedExternal[]): GridItem[] {
  return items.map((item) => ({ kind: 'external', ...item }))
}

export function asSittingItems(items: TimedSitting[]): GridItem[] {
  return items.map((item) => ({ kind: 'sitting', ...item }))
}

const KIND_ORDER: Record<GridItem['kind'], number> = { class: 0, sitting: 1, external: 2 }

/** Every kind in one chronological pass. Ties keep classes first, then graded work. */
export function mergeByStart(items: GridItem[]): GridItem[] {
  return [...items].sort(
    (a, b) => a.start.getTime() - b.start.getTime() || KIND_ORDER[a.kind] - KIND_ORDER[b.kind],
  )
}

/** Stable key for an external occurrence; ids are per source, so the source is part of it. */
export function externalKey(external: ExternalEvent): string {
  return `${external.source}:${String(external.id)}-${external.date}-${external.start}`
}

/** A stable React key. Ids collide across the tables, the kind and source separate them. */
export function itemKey(item: GridItem): string {
  if (item.kind === 'class') return `class-${String(item.event.meeting_id)}-${item.event.date}-${item.event.start}`
  if (item.kind === 'sitting') return `sitting-${String(item.assignment.id)}`
  return `ext-${externalKey(item.external)}`
}

export function isPast(item: { end: Date }, now: Date): boolean {
  return item.end.getTime() <= now.getTime()
}

export function isRunning(item: { start: Date; end: Date }, now: Date): boolean {
  return item.start.getTime() <= now.getTime() && now.getTime() < item.end.getTime()
}
