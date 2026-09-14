import { useMemo } from 'react'
import {
  useAssignments,
  useCourses,
  useExternalEvents,
  useSchedule,
  useSyncStatus,
} from '@/lib/school-queries'
import { addDays, longWeekday, shortMonthDay, toIsoDate } from '@/lib/school-time'
import { AddSyllabiState } from './add-syllabi-state'
import { buildCourseColors } from './course-color'
import { DuePanel } from './due-panel'
import { toTimedEvents, toTimedExternals, toTimedSittings } from './event-time'
import { RecentlyGraded } from './recently-graded'
import { TodayTimeline } from './today-timeline'
import { TodosWidget } from './todos-widget'
import { UpNextCard, UpNextSkeleton } from './up-next-card'
import { useNow } from './use-now'

/** Landing view at `/`: what's now or next, the rest of today, and what's due, without scrolling at 1280x800. */
export function SchoolTodayPage() {
  const now = useNow()
  const todayIso = toIsoDate(now)
  const tomorrowIso = toIsoDate(addDays(now, 1))

  // Tomorrow is fetched too so Up Next can roll forward after the last class.
  const schedule = useSchedule(todayIso, tomorrowIso)
  const courses = useCourses()
  const assignments = useAssignments()
  // Today only: Up Next rolls into tomorrow, but the timeline is about today.
  const external = useExternalEvents(todayIso, todayIso)
  const syncStatus = useSyncStatus()

  const colors = useMemo(() => buildCourseColors(courses.data), [courses.data])
  const timed = useMemo(() => toTimedEvents(schedule.data), [schedule.data])
  const todayItems = useMemo(() => timed.filter((item) => item.event.date === todayIso), [timed, todayIso])
  const todayExternal = useMemo(() => toTimedExternals(external.data), [external.data])
  const todaySittings = useMemo(
    () => toTimedSittings(assignments.data).filter((item) => toIsoDate(item.start) === todayIso),
    [assignments.data, todayIso],
  )

  const schedulePending = schedule.isPending || courses.isPending
  const scheduleError = schedule.isError || courses.isError
  const term = courses.data?.[0]?.term
  const noCourses = courses.data !== undefined && courses.data.length === 0

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Today</h1>
        <p className="lede text-muted-foreground">
          {longWeekday(now)}, <span className="num">{shortMonthDay(now)}</span>
          {term ? ` · ${term}` : ''}
        </p>
      </header>

      {noCourses ? (
        // Fresh install: only todos work without courses, so they stay beside the prompt.
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(300px,1fr)]">
          <div className="min-w-0 rounded-lg border border-border bg-card">
            <AddSyllabiState />
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            <TodosWidget now={now} />
          </div>
        </div>
      ) : (
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(300px,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          {schedulePending ? (
            <UpNextSkeleton />
          ) : (
            <UpNextCard items={timed} colors={colors} now={now} todayIso={todayIso} />
          )}

          <TodayTimeline
            items={todayItems}
            externals={todayExternal}
            sittings={todaySittings}
            syncStatus={syncStatus.data}
            colors={colors}
            now={now}
            isPending={schedulePending}
            isError={scheduleError}
            hasCourses={courses.data === undefined || courses.data.length > 0}
            onRetry={() => {
              void schedule.refetch()
              void courses.refetch()
              void external.refetch()
            }}
          />

          {/* Renders only when a grade landed this week. */}
          <RecentlyGraded assignments={assignments.data} colors={colors} now={now} />
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <DuePanel
            assignments={assignments.data}
            colors={colors}
            now={now}
            isPending={assignments.isPending}
            isError={assignments.isError}
            onRetry={() => void assignments.refetch()}
          />
          <TodosWidget now={now} />
        </div>
      </div>
      )}
    </div>
  )
}
