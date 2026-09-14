import { Fragment } from 'react'
import { CalendarBlank, WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { AddSyllabiState } from './add-syllabi-state'
import { formatClock, minutesOfDay } from '@/lib/school-time'
import type { SyncStatus } from '@/lib/school-types'
import {
  asClassItems,
  asExternalItems,
  asSittingItems,
  isPast,
  itemKey,
  mergeByStart,
  type TimedEvent,
  type TimedExternal,
  type TimedSitting,
} from './event-time'
import { ExternalRow, ExternalSyncBadge, externalSlot, SyncNowButton } from './external-parts'
import { Panel, PanelHeader, ScheduleRow, SittingRow } from './school-parts'

interface TodayTimelineProps {
  /** Today's class meetings only, resolved and sorted. */
  items: TimedEvent[]
  /** Today's external events (the feeds and Notes), resolved and sorted. */
  externals: TimedExternal[]
  /** Today's graded work with a time block (an exam), resolved and sorted. */
  sittings?: TimedSitting[]
  /** For the Timestamp Rule badge. Undefined until the status query answers. */
  syncStatus: SyncStatus | undefined
  colors: Map<number, number>
  now: Date
  isPending: boolean
  isError: boolean
  /** False only when the semester itself is still empty, which reads differently. */
  hasCourses: boolean
  onRetry: () => void
}

function NowLine({ now }: { now: Date }) {
  return (
    <li className="flex h-5 items-center" aria-hidden>
      <span className="num w-[112px] shrink-0 pl-3 pr-2 text-right text-xs font-medium text-primary">
        {formatClock(minutesOfDay(now))}
      </span>
      <span className="relative mr-3 h-px flex-1 bg-primary">
        <span className="absolute -top-[1.5px] left-0 size-1 rounded-full bg-primary" />
      </span>
    </li>
  )
}

function TimelineSkeleton() {
  return (
    <ul>
      {Array.from({ length: 4 }, (_, index) => (
        <li key={index} className="flex items-center gap-2 border-b border-border px-3 py-2.5 last:border-b-0">
          <Skeleton className="h-3.5 w-20 shrink-0" />
          <Skeleton className="h-3.5 w-16 shrink-0" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-16 shrink-0" />
        </li>
      ))}
    </ul>
  )
}

/** Today's schedule: classes, exams and external events interleaved by time around a now-line; past items dim to 55%. */
export function TodayTimeline({
  items,
  externals,
  sittings = [],
  syncStatus,
  colors,
  now,
  isPending,
  isError,
  hasCourses,
  onRetry,
}: TodayTimelineProps) {
  const rows = mergeByStart([...asClassItems(items), ...asSittingItems(sittings), ...asExternalItems(externals)])
  const remainingIndex = rows.findIndex((row) => !isPast(row, now))
  const nowIndex = remainingIndex === -1 ? rows.length : remainingIndex
  const classCount = items.length
  const sittingCount = sittings.length
  const eventCount = externals.filter((row) => row.external.source === 'notes').length
  const feedCount = externals.length - eventCount

  return (
    <Panel>
      {/* "Schedule", not "Today": the page title above it already says Today. */}
      <PanelHeader
        title="Schedule"
        meta={
          classCount > 0 || sittingCount > 0 || eventCount > 0 ? (
            <>
              {classCount > 0 ? (
                <>
                  <span className="num">{String(classCount)}</span> {classCount === 1 ? 'class' : 'classes'}
                </>
              ) : null}
              {sittingCount > 0 ? (
                <>
                  {classCount > 0 ? ' · ' : null}
                  <span className="num">{String(sittingCount)}</span> {sittingCount === 1 ? 'exam' : 'exams'}
                </>
              ) : null}
              {eventCount > 0 ? (
                <>
                  {classCount > 0 || sittingCount > 0 ? ' · ' : null}
                  <span className="num">{String(eventCount)}</span> {eventCount === 1 ? 'event' : 'events'}
                </>
              ) : null}
              {feedCount > 0 ? (
                <>
                  {' · '}
                  <span className="num">{String(feedCount)}</span> external
                </>
              ) : null}
            </>
          ) : undefined
        }
        // One sync badge for the panel, since events carry no age. Hidden on a day with no externals
        // unless a feed failed. Sync now stays put even when the badge hides.
        action={
          <>
            <ExternalSyncBadge status={syncStatus} quiet={feedCount === 0} />
            <SyncNowButton status={syncStatus} />
          </>
        }
      />

      {isPending ? (
        <TimelineSkeleton />
      ) : isError ? (
        <EmptyState
          size="inline"
          icon={WarningCircle}
          title="Could not load the schedule"
          description="The school endpoint did not respond. Check that the Semester OS server is still running."
          action={
            <Button size="sm" variant="outline" onClick={onRetry}>
              Try again
            </Button>
          }
        />
      ) : !hasCourses ? (
        <AddSyllabiState size="inline" />
      ) : rows.length === 0 ? (
        <EmptyState
          size="inline"
          icon={CalendarBlank}
          title="Nothing scheduled today"
          description="No class or event today. The week grid shows what is coming."
        />
      ) : (
        <ul className="py-1">
          {rows.map((row, index) => (
            <Fragment key={itemKey(row)}>
              {index === nowIndex ? <NowLine now={now} /> : null}
              {row.kind === 'class' ? (
                <ScheduleRow item={row} slot={colors.get(row.event.course_id)} past={isPast(row, now)} />
              ) : row.kind === 'sitting' ? (
                <SittingRow item={row} slot={colors.get(row.assignment.course_id)} past={isPast(row, now)} />
              ) : (
                <ExternalRow item={row} slot={externalSlot(row.external, colors)} past={isPast(row, now)} />
              )}
            </Fragment>
          ))}
          {nowIndex === rows.length ? <NowLine now={now} /> : null}
        </ul>
      )}
    </Panel>
  )
}
