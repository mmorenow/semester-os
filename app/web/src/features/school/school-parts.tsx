import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Icon } from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatDateTime, relativeTime } from '@/lib/format'
import { MEETING_KIND_LABEL } from '@/lib/school-labels'
import { formatClockRange, parseHhMm } from '@/lib/school-time'
import type { CourseMeeting, MeetingKind } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { CourseMark } from './course-mark'
import type { TimedEvent, TimedSitting } from './event-time'

/** Badge sizing for the app as call-site overrides; the shared `Badge` primitive keeps shadcn's `h-5`. */
export const SCHOOL_BADGE = 'h-6 px-2 font-normal text-[13px]'

/** A discrete surface. Panels never nest: inside one, hairlines do the work. */
export function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <section className={cn('flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-card', className)}>
      {children}
    </section>
  )
}

export function PanelHeader({
  title,
  icon: Glyph,
  meta,
  action,
}: {
  title: string
  /**
   * Optional section glyph: Phosphor regular, 20px, `muted-foreground` at 75% (3.69:1 light,
   * 4.50:1 dark on `--card`, over the 3:1 non-text gate). Never a course color.
   */
  icon?: Icon
  meta?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
      {Glyph ? <Glyph size={20} aria-hidden className="shrink-0 text-muted-foreground/75" /> : null}
      {/* 17px semibold name; the count stays at 13px muted. */}
      <h2 className="section-title text-foreground">{title}</h2>
      {meta ? <span className="truncate text-[13px] text-muted-foreground">{meta}</span> : null}
      {action ? <div className="ml-auto flex items-center gap-1">{action}</div> : null}
    </div>
  )
}

/** Lectures are the default and get no badge; labs and PSOs do. */
export function MeetingKindBadge({ kind }: { kind: MeetingKind }) {
  if (kind === 'lecture') return null
  return (
    // `h-5 px-1.5`: a 16px pill can't hold 12px type, the floor. Local override, not a variant.
    <Badge variant="outline" className="h-5 px-1.5 font-normal text-xs text-muted-foreground">
      {MEETING_KIND_LABEL[kind]}
    </Badge>
  )
}

/** One meeting as a list row, shared by Today's timeline and the week's narrow list. Links to the course page. */
export function ScheduleRow({
  item,
  slot,
  past = false,
}: {
  item: TimedEvent
  slot: number | undefined
  past?: boolean
}) {
  return (
    <li className="border-b border-border last:border-b-0">
      <Link
        to={`/courses/${String(item.event.course_id)}`}
        aria-label={`Open ${item.event.course_code}`}
        className={cn(
          'flex items-stretch transition-[background-color,opacity] duration-[80ms] hover:bg-muted/50 focus-ring-inset',
          past && 'opacity-55 hover:opacity-100',
        )}
      >
        {/* 112px: the widest range, `11:30a-1:20p`, is 86px at 12px mono. Shared with `NowLine` and `ExternalRow`. */}
        <span className="num flex w-[112px] shrink-0 items-center justify-end py-2 pl-3 pr-2 text-xs text-muted-foreground">
          {formatClockRange(item.startMin, item.endMin)}
        </span>
        <div className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2">
          <CourseMark code={item.event.course_code} slot={slot} />
          <span className="truncate text-sm text-foreground/90">{item.event.course_title}</span>
          <MeetingKindBadge kind={item.event.kind} />
          {item.event.location ? (
            <span className="num ml-auto shrink-0 text-xs text-muted-foreground">{item.event.location}</span>
          ) : null}
        </div>
      </Link>
    </li>
  )
}

/** Graded work with a time and room (an exam) as a schedule row, titled by the work and linking to it. */
export function SittingRow({
  item,
  slot,
  past = false,
}: {
  item: TimedSitting
  slot: number | undefined
  past?: boolean
}) {
  const { assignment } = item
  return (
    <li className="border-b border-border last:border-b-0">
      <Link
        to={`/courses/${String(assignment.course_id)}?assignment=${String(assignment.id)}`}
        aria-label={`Open ${assignment.title}, ${assignment.course_code}`}
        className={cn(
          'flex items-stretch transition-[background-color,opacity] duration-[80ms] hover:bg-muted/50 focus-ring-inset',
          past && 'opacity-55 hover:opacity-100',
        )}
      >
        <span className="num flex w-[112px] shrink-0 items-center justify-end py-2 pl-3 pr-2 text-xs text-muted-foreground">
          {formatClockRange(item.startMin, item.endMin)}
        </span>
        <div className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2">
          <CourseMark code={assignment.course_code} slot={slot} />
          <span className="truncate text-sm font-medium text-foreground">{assignment.title}</span>
          {assignment.location ? (
            <span className="num ml-auto shrink-0 text-xs text-muted-foreground">{assignment.location}</span>
          ) : null}
        </div>
      </Link>
    </li>
  )
}

/** Recurring meeting on one line: the clock as `.figure-num`, days at 14px, room at 13px muted, CRN at the end. */
export function MeetingLine({ meeting }: { meeting: CourseMeeting }) {
  const startMin = parseHhMm(meeting.start_time)
  const range = startMin === null ? meeting.start_time : formatClockRange(startMin, startMin + meeting.duration_min)

  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="figure-num text-foreground">{range}</span>
      <span className="num text-sm text-foreground/90">{meeting.days.join('')}</span>
      <MeetingKindBadge kind={meeting.kind} />
      {meeting.location ? (
        <span className="num text-[13px] text-muted-foreground">{meeting.location}</span>
      ) : null}
      {meeting.crn ? (
        <span className="num ml-auto shrink-0 text-[13px] text-muted-foreground">CRN {meeting.crn}</span>
      ) : null}
    </li>
  )
}

/**
 * Harvested data states its age beside the data; older than a day is an amber badge.
 * Callers decide whether a feed exists (see `PlatformList`); this always says "Never synced" when asked.
 */
export function SyncAge({
  at,
  source,
  className,
}: {
  at: string | null | undefined
  /** What would fill this surface, named in the tooltip. */
  source?: string
  className?: string
}) {
  if (!at) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className={cn(SCHOOL_BADGE, 'text-muted-foreground', className)}>
            Never synced
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          {source ? `Nothing harvested yet from ${source}.` : 'Nothing harvested yet.'}
        </TooltipContent>
      </Tooltip>
    )
  }

  const stamped = formatDateTime(at)
  const ageMs = Date.now() - new Date(at).getTime()

  // An unreadable age says so rather than rendering as "Synced just now".
  if (!Number.isFinite(ageMs)) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className={cn(SCHOOL_BADGE, 'text-muted-foreground', className)}>
            Unknown
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          {source
            ? `${source} reported a sync time Semester OS cannot read.`
            : 'The recorded sync time cannot be read.'}
        </TooltipContent>
      </Tooltip>
    )
  }

  if (ageMs > 86_400_000) {
    const days = Math.floor(ageMs / 86_400_000)
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className={cn(SCHOOL_BADGE, 'border-signal-amber/45 text-signal-amber', className)}>
            <span className="num">Stale {String(days)}d</span>
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          Last synced {stamped ?? at}
          {source ? ` from ${source}` : ''}.
        </TooltipContent>
      </Tooltip>
    )
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('num text-[13px] text-muted-foreground', className)}>
          Synced {relativeTime(at) ?? 'just now'}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        Last synced {stamped ?? at}
        {source ? ` from ${source}` : ''}.
      </TooltipContent>
    </Tooltip>
  )
}
