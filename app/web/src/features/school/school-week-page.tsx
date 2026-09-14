import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Books, CalendarX, CaretLeft, CaretRight, WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Toggle } from '@/components/ui/toggle'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { EmptyState } from '@/components/empty-state'
import { useAssignments, useCourses, useExternalEvents, useSchedule, useSyncStatus } from '@/lib/school-queries'
import {
  addDays,
  isSameDay,
  longWeekday,
  parseIsoDate,
  shortMonthDay,
  startOfWeek,
  toIsoDate,
  weekRangeLabel,
} from '@/lib/school-time'
import { buildCourseColors } from './course-color'
import {
  asClassItems,
  asExternalItems,
  asSittingItems,
  itemKey,
  mergeByStart,
  toTimedEvents,
  toTimedExternals,
  toTimedSittings,
  type TimedEvent,
  type TimedExternal,
  type TimedSitting,
} from './event-time'
import { ExternalRow, ExternalSyncBadge, externalSlot, SyncNowButton } from './external-parts'
import { Panel, PanelHeader, ScheduleRow, SittingRow } from './school-parts'
import { useNow } from './use-now'
import { HOUR_PX, WeekGrid } from './week-grid'

/** The grid opens on this many hours before the real window is known. */
const SKELETON_HOURS = 10

/** Weekend columns exist only when something is scheduled in them. */
function visibleDays(monday: Date, items: { start: Date }[]): Date[] {
  const week = Array.from({ length: 7 }, (_, index) => addDays(monday, index))
  return week.filter((day, index) => index < 5 || items.some((item) => isSameDay(item.start, day)))
}

function GridSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex border-b border-border">
        <div className="w-11 shrink-0" />
        {Array.from({ length: 5 }, (_, index) => (
          <div key={index} className="flex h-9 flex-1 items-center justify-center border-l border-border">
            <Skeleton className="h-3.5 w-12" />
          </div>
        ))}
      </div>
      <div className="flex" style={{ height: `${String(HOUR_PX * SKELETON_HOURS)}px` }}>
        <div className="w-11 shrink-0" />
        {Array.from({ length: 5 }, (_, column) => (
          <div key={column} className="relative flex-1 border-l border-border">
            {Array.from({ length: SKELETON_HOURS - 1 }, (_, line) => (
              <span
                key={line}
                className="absolute inset-x-0 h-px bg-border"
                style={{ top: `${String((line + 1) * HOUR_PX)}px` }}
              />
            ))}
            <Skeleton
              className="absolute inset-x-px rounded-sm"
              style={{ top: `${String(HOUR_PX * (column % 3))}px`, height: `${String(HOUR_PX * 0.8)}px` }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

/** Under 1024px the grid gives way to a day list; the data is identical. */
function WeekDayList({
  days,
  items,
  externals,
  sittings,
  colors,
}: {
  days: Date[]
  items: TimedEvent[]
  externals: TimedExternal[]
  sittings: TimedSitting[]
  colors: Map<number, number>
}) {
  const rows = mergeByStart([...asClassItems(items), ...asSittingItems(sittings), ...asExternalItems(externals)])
  return (
    <div className="flex flex-col gap-3">
      {days.map((day) => {
        const dayRows = rows.filter((row) => isSameDay(row.start, day))
        if (dayRows.length === 0) return null
        return (
          <Panel key={day.toDateString()}>
            <PanelHeader title={longWeekday(day)} meta={<span className="num">{shortMonthDay(day)}</span>} />
            <ul>
              {dayRows.map((row) =>
                row.kind === 'class' ? (
                  <ScheduleRow key={itemKey(row)} item={row} slot={colors.get(row.event.course_id)} />
                ) : row.kind === 'sitting' ? (
                  <SittingRow key={itemKey(row)} item={row} slot={colors.get(row.assignment.course_id)} />
                ) : (
                  <ExternalRow key={itemKey(row)} item={row} slot={externalSlot(row.external, colors)} />
                ),
              )}
            </ul>
          </Panel>
        )
      })}
    </div>
  )
}

/** The week as a time grid, Mon-Fri plus any weekend day that is used. */
export function SchoolWeekPage() {
  const now = useNow()

  // The visible week lives in the URL, so it's linkable and Back walks the weeks.
  const [params, setParams] = useSearchParams()
  const monday = useMemo(() => {
    const raw = params.get('week')
    const parsed = raw ? parseIsoDate(raw) : null
    return startOfWeek(parsed ?? new Date())
  }, [params])

  // The external layer is on by default; only `?external=0` is stored.
  const showExternal = params.get('external') !== '0'

  // True only for the render the toggle click produced, so paging weeks never animates.
  const [justRevealed, setJustRevealed] = useState(false)

  function goToWeek(day: Date) {
    setJustRevealed(false)
    const target = startOfWeek(day)
    const next = new URLSearchParams(params)
    // The current week is the bare route; only a week away from it needs a key.
    if (isSameDay(target, startOfWeek(new Date()))) next.delete('week')
    else next.set('week', toIsoDate(target))
    setParams(next)
  }

  function toggleExternal(on: boolean) {
    setJustRevealed(on)
    const next = new URLSearchParams(params)
    if (on) next.delete('external')
    else next.set('external', '0')
    setParams(next)
  }

  const start = toIsoDate(monday)
  const end = toIsoDate(addDays(monday, 6))
  const schedule = useSchedule(start, end)
  const courses = useCourses()
  const assignments = useAssignments()
  const external = useExternalEvents(start, end, showExternal)
  const syncStatus = useSyncStatus(showExternal)

  const colors = useMemo(() => buildCourseColors(courses.data), [courses.data])
  const items = useMemo(() => toTimedEvents(schedule.data), [schedule.data])
  const externalItems = useMemo(
    () => (showExternal ? toTimedExternals(external.data) : []),
    [external.data, showExternal],
  )
  const sittings = useMemo(() => {
    const weekEnd = addDays(monday, 7)
    return toTimedSittings(assignments.data).filter((item) => item.start >= monday && item.start < weekEnd)
  }, [assignments.data, monday])
  const days = visibleDays(monday, [...items, ...sittings, ...externalItems])
  const isThisWeek = isSameDay(monday, startOfWeek(now))
  // The label names the columns that are actually drawn, weekends included.
  const lastVisible = days.length > 0 ? days[days.length - 1] : addDays(monday, 4)

  const isPending = schedule.isPending || courses.isPending
  const isError = schedule.isError || courses.isError
  const hasCourses = courses.data === undefined || courses.data.length > 0

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">Week</h1>
          <p className="lede text-muted-foreground">
            <span className="num">{weekRangeLabel(monday, lastVisible)}</span>
            {courses.data?.[0]?.term ? ` · ${courses.data[0].term}` : ''}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* One sync badge per surface, beside the toggle; hidden with the layer, where it would describe nothing. */}
          {showExternal ? (
            <>
              <ExternalSyncBadge
                status={syncStatus.data}
                quiet={externalItems.every((item) => item.external.source === 'notes')}
              />
              <SyncNowButton status={syncStatus.data} size="sm" />
            </>
          ) : null}

          <Tooltip>
            <TooltipTrigger asChild>
              <Toggle
                variant="outline"
                size="sm"
                pressed={showExternal}
                onPressedChange={toggleExternal}
                aria-label="External calendar events"
              >
                External
              </Toggle>
            </TooltipTrigger>
            <TooltipContent>
              {showExternal
                ? 'Hide events from Outlook, Brightspace, Google and Notes. A pure class week is one click away.'
                : 'Show events from Outlook, Brightspace, Google and Notes beside the classes.'}
            </TooltipContent>
          </Tooltip>

          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Previous week"
            onClick={() => { goToWeek(addDays(monday, -7)) }}
          >
            <CaretLeft />
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isThisWeek}
            onClick={() => { goToWeek(new Date()) }}
          >
            Today
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Next week"
            onClick={() => { goToWeek(addDays(monday, 7)) }}
          >
            <CaretRight />
          </Button>
        </div>
      </header>

      {isPending ? (
        <GridSkeleton />
      ) : isError ? (
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="Could not load the week"
            description="The schedule endpoint did not respond. Check that the Semester OS server is still running."
            action={
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  void schedule.refetch()
                  void courses.refetch()
                }}
              >
                Try again
              </Button>
            }
          />
        </Panel>
      ) : !hasCourses ? (
        <Panel>
          <EmptyState
            icon={Books}
            title="No courses yet"
            description="Import a syllabus or connect Brightspace to fill this semester."
          />
        </Panel>
      ) : items.length === 0 && sittings.length === 0 && externalItems.length === 0 ? (
        <Panel>
          <EmptyState
            icon={CalendarX}
            title="Nothing scheduled this week"
            description={`No class or event falls in ${weekRangeLabel(monday, lastVisible)}.`}
          />
        </Panel>
      ) : (
        <>
          <div className="hidden lg:block">
            <WeekGrid
              days={days}
              items={items}
              externals={externalItems}
              sittings={sittings}
              colors={colors}
              now={now}
              animateExternal={justRevealed}
            />
          </div>
          <div className="lg:hidden">
            <WeekDayList days={days} items={items} externals={externalItems} sittings={sittings} colors={colors} />
          </div>
        </>
      )}
    </div>
  )
}
