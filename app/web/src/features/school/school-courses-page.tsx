import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { AddSyllabiState } from './add-syllabi-state'
import { isSettled } from '@/lib/school-labels'
import { useAssignments, useCourseSummaries, useCourses, useSchedule } from '@/lib/school-queries'
import { addDays, formatClock, formatSpan, isSameDay, shortWeekday, toIsoDate } from '@/lib/school-time'
import type { Assignment, Course, CourseDetail } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { buildCourseColors, cardClass, cardHoverClass, watermarkClass } from './course-color'
import { courseIcon } from './course-icon'
import { CourseMark } from './course-mark'
import { PlatformChips } from './course-platforms'
import { toTimedEvents, type TimedEvent } from './event-time'
import { pct } from './grade-model'
import { useNow } from './use-now'

/** A week ahead is enough to always find the next meeting of a live course. */
const LOOKAHEAD_DAYS = 7

function nextMeeting(items: TimedEvent[], courseId: number, now: Date): TimedEvent | null {
  return (
    items.find((item) => item.event.course_id === courseId && item.start.getTime() > now.getTime()) ?? null
  )
}

function nextDue(assignments: Assignment[], courseId: number, now: Date): Assignment | null {
  const open = assignments
    .filter((row) => row.course_id === courseId && !isSettled(row.status) && row.due_at)
    .sort((a, b) => new Date(a.due_at ?? 0).getTime() - new Date(b.due_at ?? 0).getTime())
  // Overdue open work outranks the next future item.
  return open.find((row) => new Date(row.due_at ?? 0).getTime() >= now.getTime()) ?? open[0] ?? null
}

/**
 * `border-border` flips on a course tint (darker than `--card`, lighter than a 32% tint).
 * Mixing from ink keeps a consistent hairline on every hue, at rest and on hover.
 */
const HAIRLINE = 'border-foreground/15'

function Answer({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    // Transparent: the cell sits on the course tint, and borders avoid punching `gap-px` holes in it.
    <div className={cn('flex min-w-0 flex-col gap-1 border-l px-4 py-3 first:border-l-0', HAIRLINE, className)}>
      <span className="text-xs text-foreground/75">{label}</span>
      {children}
    </div>
  )
}

const NONE = <span className="text-[13px] text-foreground/75">None scheduled</span>

interface CourseCardProps {
  course: Course
  slot: number | undefined
  summary: CourseDetail | undefined
  meeting: TimedEvent | null
  due: Assignment | null
  openCount: number
  now: Date
}

/**
 * A course card: next meeting, next due item, current standing. The card isn't an anchor, since
 * platform chips are links and `<a>` can't nest. An absolute overlay link covers it; the chips sit
 * above the overlay. Whole card tinted at 32/42 (see `course-color.ts`).
 */
function CourseCard({ course, slot, summary, meeting, due, openCount, now }: CourseCardProps) {
  const average = summary?.grade_summary?.overall.current_avg_pct
  const secured = summary?.grade_summary?.overall.secured_pct
  const Glyph = courseIcon(slot)

  const meetingLabel = (() => {
    if (!meeting) return null
    const today = isSameDay(meeting.start, now)
    const minutesAway = Math.round((meeting.start.getTime() - now.getTime()) / 60_000)
    if (today && minutesAway < 240) return `in ${formatSpan(minutesAway)}`
    return `${today ? 'Today' : shortWeekday(meeting.start)} ${formatClock(meeting.startMin)}`
  })()

  return (
    <div
      className={cn(
        // Hover is a border step plus 10 points of tint; press is the only transform.
        // `bg-card` stays under the tint because alphas were measured over `--card`.
        'focus-ring-overlay group relative flex flex-col overflow-hidden rounded-lg border border-border bg-card',
        'transition-colors duration-[120ms] hover:border-input active:scale-[0.995]',
      )}
    >
      {/* Route link overlay, the card's one tab stop; the card paints its ring (`overflow-hidden` would clip it).
          z-10 so the `relative` footer strip doesn't win the hit test; the chips take z-20. */}
      <Link
        to={`/courses/${String(course.id)}`}
        aria-label={`Open ${course.code}, ${course.title}`}
        className="absolute inset-0 z-10 rounded-lg focus-visible:outline-none"
      />

      <div
        className={cn(
          'flex flex-1 flex-col transition-colors duration-[120ms]',
          cardClass(slot),
          cardHoverClass(slot),
        )}
      >
        <div className="flex items-center gap-2 px-4 py-3">
          <Glyph size={20} aria-hidden className="shrink-0 text-foreground/75" />
          <CourseMark code={course.code} slot={slot} size="md" />
          <span className="min-w-0 flex-1 truncate text-sm text-foreground/90">{course.title}</span>
          {course.credit_hours ? (
            <span className="num shrink-0 text-[13px] text-foreground/75">
              {String(course.credit_hours)} cr
            </span>
          ) : null}
        </div>

        <div className={cn('grid grid-cols-3 border-t', HAIRLINE)}>
          <Answer label="Next class">
            {meetingLabel ? (
              <span
                className={cn(
                  'num truncate text-sm',
                  meeting && isSameDay(meeting.start, now) ? 'text-foreground' : 'text-foreground/90',
                )}
              >
                {meetingLabel}
              </span>
            ) : (
              NONE
            )}
            {meeting?.event.location ? (
              <span className="num truncate text-xs text-foreground/75">{meeting.event.location}</span>
            ) : null}
          </Answer>

          <Answer label="Next due">
            {due ? (
              <>
                <span className="truncate text-sm text-foreground">{due.title}</span>
                {/* `.num` on the figure only; mono for the whole sentence is too wide at 12px. */}
                <span className="truncate text-xs text-foreground/75">
                  {due.weight_pct === null || due.weight_pct === undefined ? (
                    'weight unknown'
                  ) : (
                    <>
                      <span className="num">{pct(due.weight_pct)}</span> of grade
                    </>
                  )}
                </span>
              </>
            ) : (
              <span className="text-[13px] text-foreground/75">Nothing open</span>
            )}
          </Answer>

          <Answer label="Standing">
            {average === null || average === undefined ? (
              <span className="text-[13px] text-foreground/75">Nothing graded</span>
            ) : (
              <span className="num text-sm text-foreground">{pct(average)}</span>
            )}
            <span className="truncate text-xs text-foreground/75">
              {secured === null || secured === undefined ? null : (
                <>
                  <span className="num">{pct(secured)}</span> secured ·{' '}
                </>
              )}
              <span className="num">{String(openCount)}</span> open
            </span>
          </Answer>
        </div>

        {/* Logos on opaque `bg-card` pills (brand hexes fail 3:1 on the tint). The 64px watermark sits whole
            in the strip, not under text, where it would fail contrast; `pr-20` reserves its space. */}
        <div className={cn('relative mt-auto flex min-h-[72px] items-center overflow-hidden border-t px-4 py-3', HAIRLINE)}>
          <Glyph
            size={64}
            aria-hidden
            className={cn('pointer-events-none absolute right-3 top-1/2 -translate-y-1/2', watermarkClass(slot))}
          />
          {/* Above the overlay so chips open their platform; the row passes the pointer through between chips. */}
          <PlatformChips
            platforms={course.platforms}
            mark
            onTint
            className="pointer-events-none relative z-20 pr-20 [&>*]:pointer-events-auto"
          />
        </div>
      </div>
    </div>
  )
}

/** Same geometry, no color: the skeleton can't know which course each card is. */
function CoursesSkeleton() {
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex items-center gap-2 px-4 py-3">
            <Skeleton className="size-5 shrink-0 rounded-sm" />
            <Skeleton className="h-8 w-[92px] shrink-0 rounded-sm" />
            <Skeleton className="h-4 flex-1" />
          </div>
          <div className="grid grid-cols-3 border-t border-border">
            {Array.from({ length: 3 }, (_, cell) => (
              <div key={cell} className="flex flex-col gap-1.5 border-l border-border px-4 py-3 first:border-l-0">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="h-3 w-28" />
              </div>
            ))}
          </div>
          <div className="flex min-h-[72px] items-center border-t border-border px-4 py-3">
            <Skeleton className="h-7 w-44 rounded-sm" />
          </div>
        </div>
      ))}
    </div>
  )
}

/** Every course this semester, each card answering before it is opened. */
export function SchoolCoursesPage() {
  const now = useNow()
  const courses = useCourses()
  const assignments = useAssignments()
  const schedule = useSchedule(toIsoDate(now), toIsoDate(addDays(now, LOOKAHEAD_DAYS)))
  const summaries = useCourseSummaries(courses.data)

  const colors = useMemo(() => buildCourseColors(courses.data), [courses.data])
  const ordered = useMemo(
    () => [...(courses.data ?? [])].sort((a, b) => a.code.localeCompare(b.code)),
    [courses.data],
  )
  const timed = useMemo(() => toTimedEvents(schedule.data), [schedule.data])
  const rows = assignments.data ?? []
  const term = courses.data?.[0]?.term

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">Courses</h1>
          <p className="lede text-muted-foreground">
            {ordered.length > 0 ? (
              <>
                <span className="num">{String(ordered.length)}</span> {ordered.length === 1 ? 'course' : 'courses'}
                {term ? ` · ${term}` : ''}
              </>
            ) : (
              'Every course this semester, with where its work actually lives.'
            )}
          </p>
        </div>
        {ordered.length > 0 ? (
          <Button size="sm" variant="outline" asChild>
            <Link to="/setup">Add a course</Link>
          </Button>
        ) : null}
      </header>

      {courses.isPending ? (
        <CoursesSkeleton />
      ) : courses.isError ? (
        <div className="rounded-lg border border-border bg-card">
          <EmptyState
            icon={WarningCircle}
            title="Could not load courses"
            description="The courses endpoint did not respond. Check that the Semester OS server is still running."
            action={
              <Button size="sm" variant="outline" onClick={() => void courses.refetch()}>
                Try again
              </Button>
            }
          />
        </div>
      ) : ordered.length === 0 ? (
        <div className="rounded-lg border border-border bg-card">
          <AddSyllabiState />
        </div>
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">
          {ordered.map((course) => (
            <CourseCard
              key={course.id}
              course={course}
              slot={colors.get(course.id)}
              summary={summaries.byId.get(course.id)}
              meeting={nextMeeting(timed, course.id, now)}
              due={nextDue(rows, course.id, now)}
              openCount={rows.filter((row) => row.course_id === course.id && !isSettled(row.status)).length}
              now={now}
            />
          ))}
        </div>
      )}
    </div>
  )
}
