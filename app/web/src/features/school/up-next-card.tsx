import { Link } from 'react-router-dom'
import { Skeleton } from '@/components/ui/skeleton'
import { formatClock, formatClockRange, formatSpan } from '@/lib/school-time'
import { cn } from '@/lib/utils'
import { CourseMark } from './course-mark'
import { isRunning, type TimedEvent } from './event-time'
import { MeetingKindBadge } from './school-parts'

interface UpNextCardProps {
  /** Today's and tomorrow's events, already resolved and sorted. */
  items: TimedEvent[]
  colors: Map<number, number>
  now: Date
  todayIso: string
}

/** Now or next: a running class with its time left and the one after; rolls to tomorrow when today is done. */
export function UpNextCard({ items, colors, now, todayIso }: UpNextCardProps) {
  const current = items.find((item) => isRunning(item, now)) ?? null
  const next = items.find((item) => item.start.getTime() > now.getTime()) ?? null
  const focus = current ?? next

  // Keep the card when nothing is next so the page doesn't reflow.
  if (!focus) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-3">
        <h2 className="section-title text-foreground">Up next</h2>
        <p className="lede mt-1.5 text-foreground">Nothing left today or tomorrow</p>
        <p className="mt-1 text-[13px] text-muted-foreground">The week grid shows the rest of the semester.</p>
      </div>
    )
  }

  const slot = colors.get(focus.event.course_id)
  const isToday = focus.event.date === todayIso
  const minutesAway = Math.round((focus.start.getTime() - now.getTime()) / 60_000)
  const minutesLeft = Math.round((focus.end.getTime() - now.getTime()) / 60_000)

  const label = current ? 'In class' : isToday ? 'Up next' : 'Tomorrow'
  const trailing = current
    ? `${formatSpan(minutesLeft)} left`
    : isToday && minutesAway < 720
      ? `in ${formatSpan(minutesAway)}`
      : formatClock(focus.startMin)

  const then = current && next && next !== current && next.event.date === todayIso ? next : null

  return (
    <Link
      to={`/courses/${String(focus.event.course_id)}`}
      aria-label={`Open ${focus.event.course_code}`}
      className={cn(
        'focus-ring block rounded-lg border border-border bg-card px-4 py-3',
        'transition-colors duration-[120ms] hover:border-input active:scale-[0.995]',
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        {/* The tile's name and Today's first h2. */}
        <h2 className="section-title text-foreground">{label}</h2>
        {/* 22px, not the 34px display tier: Today's hierarchy tops out here. */}
        <span className="figure-num text-foreground">{trailing}</span>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <CourseMark code={focus.event.course_code} slot={slot} size="md" />
        <span className="lede min-w-0 flex-1 truncate text-foreground">{focus.event.course_title}</span>
        <MeetingKindBadge kind={focus.event.kind} />
      </div>

      <p className="num mt-1 text-[13px] text-muted-foreground">
        {formatClockRange(focus.startMin, focus.endMin)}
        {focus.event.location ? ` · ${focus.event.location}` : ''}
      </p>

      {then ? (
        <p className="mt-2.5 border-t border-border pt-2.5 text-[13px] text-muted-foreground">
          Then <span className="num text-foreground/90">{then.event.course_code}</span> at{' '}
          <span className="num">{formatClock(then.startMin)}</span>
          {then.event.location ? <span className="num"> · {then.event.location}</span> : null}
        </p>
      ) : null}
    </Link>
  )
}

export function UpNextSkeleton() {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <Skeleton className="h-6 w-20" />
        <Skeleton className="h-6 w-24" />
      </div>
      <Skeleton className="mt-2.5 h-8 w-60" />
      <Skeleton className="mt-2 h-4 w-40" />
    </div>
  )
}
