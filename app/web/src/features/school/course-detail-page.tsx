import { useCallback, useMemo, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import {
  Books,
  Browsers,
  CalendarBlank,
  CaretRight,
  ChalkboardTeacher,
  WarningCircle,
  type Icon,
} from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { useAssignments, useCourse } from '@/lib/school-queries'
import type { Course } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { CourseAnnouncements } from './course-announcements'
import { CourseAssignments } from './course-assignments'
import { courseSlot, roomClass } from './course-color'
import { CourseMark } from './course-mark'
import { readCourseContacts } from './course-people'
import { PlatformList } from './course-platforms'
import { CourseContacts, PolicyFacts } from './course-policy'
import { GradeCenter, GradeCenterSkeleton } from './grade-center'
import { readGradingScheme } from './grading-scheme'
import { MeetingLine, Panel } from './school-parts'
import { useNow } from './use-now'

/** Courses › CS 180. 13px, not micro: it's the route's only way back. */
function Breadcrumb({ code }: { code: string | undefined }) {
  const crumb = 'rounded-sm text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-ring'
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1">
      <Link to="/courses" className={crumb}>
        Courses
      </Link>
      {code ? (
        <>
          <CaretRight size={12} className="text-muted-foreground" aria-hidden />
          <span className="num text-[13px] text-foreground" aria-current="page">
            {code}
          </span>
        </>
      ) : null}
    </nav>
  )
}

/** Instructors, with mailto links. */
function InstructorLine({ course }: { course: Course }) {
  const { instructors } = readCourseContacts(course)
  if (instructors.length === 0) return null

  return (
    <div className="flex items-center gap-2 border-t border-border pt-2">
      <ChalkboardTeacher size={16} aria-hidden className="shrink-0 text-muted-foreground/75" />
      {/* 16px between people, 8px within one, so co-instructors read as separate names. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
        {instructors.map((person) => (
          <span key={person.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-sm text-foreground/90">{person.name}</span>
            {person.email ? (
              <a
                href={`mailto:${person.email}`}
                className="num rounded-sm text-[13px] text-primary underline underline-offset-2 hover:no-underline focus-ring"
              >
                {person.email}
              </a>
            ) : null}
          </span>
        ))}
      </div>
    </div>
  )
}

/** Zone label with `PanelHeader`'s glyph and type, without its bordered 36px row. */
function SectionLabel({ icon: Glyph, children }: { icon: Icon; children: ReactNode }) {
  return (
    <h2 className="section-title flex items-center gap-2 text-foreground">
      <Glyph size={20} aria-hidden className="shrink-0 text-muted-foreground/75" />
      {children}
    </h2>
  )
}

function CourseHeader({ course, slot }: { course: Course; slot: number | undefined }) {
  const meta = [
    course.term,
    course.credit_hours ? `${String(course.credit_hours)} cr` : null,
  ].filter((value): value is string => Boolean(value))

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      {/* Course room tint at 16%: the muted lede under the code caps it at 24%. */}
      <div className={cn('flex flex-col gap-1.5 px-4 py-3.5', roomClass(slot))}>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          {/* The route's h1 is the course code; the title is data, hence mono. */}
          <h1>
            <CourseMark code={course.code} slot={slot} size="page" />
          </h1>
          {meta.length > 0 ? (
            <span className="num shrink-0 text-[13px] text-muted-foreground">{meta.join(' · ')}</span>
          ) : null}
        </div>
        <p className="lede min-w-0 truncate text-muted-foreground">{course.title}</p>
      </div>

      {/* `items-start` keeps each zone its own height; borders draw the dividers, not a `gap-px` ground. */}
      <div className="relative grid items-start border-t border-border md:grid-cols-2">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-1/2 hidden w-px bg-border md:block"
        />

        <div className="flex flex-col gap-2 px-4 py-3">
          <SectionLabel icon={CalendarBlank}>Meets</SectionLabel>
          {course.meetings.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {course.meetings.map((meeting) => (
                <MeetingLine key={meeting.id} meeting={meeting} />
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted-foreground">No meeting times recorded.</p>
          )}
          <InstructorLine course={course} />
        </div>

        <div className="flex flex-col gap-2 border-t border-border px-4 py-3 md:border-t-0">
          <SectionLabel icon={Browsers}>Lives on</SectionLabel>
          <PlatformList platforms={course.platforms} />
        </div>
      </div>
    </div>
  )
}

function HeaderSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      {/* Shaped like the real header: a 28px code chip over a 16px title. */}
      <div className="flex flex-col gap-2 px-4 py-3.5">
        <div className="flex items-center justify-between gap-4">
          <Skeleton className="h-[39px] w-44 rounded-md" />
          <Skeleton className="h-3 w-24" />
        </div>
        <Skeleton className="h-5 w-72 max-w-full" />
      </div>
      {/* Shaped like the real zones. */}
      <div className="relative grid items-start border-t border-border md:grid-cols-2">
        <div aria-hidden className="absolute inset-y-0 left-1/2 hidden w-px bg-border md:block" />
        <div className="flex flex-col gap-2 px-4 py-3">
          <Skeleton className="h-6 w-28" />
          <Skeleton className="h-6 w-36" />
          <Skeleton className="h-4 w-40" />
        </div>
        <div className="flex flex-col gap-2 border-t border-border px-4 py-3 md:border-t-0">
          <Skeleton className="h-6 w-28" />
          <div className="flex flex-wrap gap-x-3 gap-y-2">
            <Skeleton className="h-7 w-28 rounded-sm" />
            <Skeleton className="h-7 w-32 rounded-sm" />
            <Skeleton className="h-7 w-24 rounded-sm" />
          </div>
        </div>
      </div>
    </div>
  )
}

/** One course end to end. A Grade Center segment filters the work list and writes `?category=` to the URL. */
export function CourseDetailPage() {
  const params = useParams<{ id: string }>()
  const rawId = Number(params.id)
  const courseId = Number.isFinite(rawId) && rawId > 0 ? rawId : null

  const now = useNow()
  const [searchParams, setSearchParams] = useSearchParams()
  const category = searchParams.get('category')
  const rawAssignment = Number(searchParams.get('assignment'))
  const openAssignmentId = Number.isFinite(rawAssignment) && rawAssignment > 0 ? rawAssignment : null

  const course = useCourse(courseId)
  const assignments = useAssignments(courseId === null ? {} : { course_id: courseId })

  const slot = useMemo(() => courseSlot(course.data?.color), [course.data?.color])
  const insights = useMemo(() => readGradingScheme(course.data?.grading_scheme).insights, [course.data])

  const setCategory = useCallback(
    (next: string | null) => {
      setSearchParams(
        (current) => {
          const params_ = new URLSearchParams(current)
          if (next === null) params_.delete('category')
          else params_.set('category', next)
          return params_
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  if (courseId === null) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb code={undefined} />
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="That is not a course id"
            description="The address after /courses/ has to be the numeric id of a course."
            action={
              <Button asChild size="sm" variant="outline">
                <Link to="/courses">Back to courses</Link>
              </Button>
            }
          />
        </Panel>
      </div>
    )
  }

  if (course.isError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb code={undefined} />
        <Panel>
          <EmptyState
            icon={Books}
            title="Could not load this course"
            description="The course endpoint did not answer for this id. It may not exist, or the Semester OS server may have stopped."
            action={
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => void course.refetch()}>
                  Try again
                </Button>
                <Button asChild size="sm" variant="ghost">
                  <Link to="/courses">All courses</Link>
                </Button>
              </div>
            }
          />
        </Panel>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb code={course.data?.code} />

      {course.isPending || !course.data ? <HeaderSkeleton /> : <CourseHeader course={course.data} slot={slot} />}

      {course.isPending ? (
        <GradeCenterSkeleton />
      ) : (
        <GradeCenter
          courseId={courseId}
          summary={course.data?.grade_summary}
          slot={slot}
          selected={category}
          onSelect={setCategory}
          insights={insights}
        />
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,1fr)]">
        <CourseAssignments
          assignments={assignments.data}
          platforms={course.data?.platforms ?? []}
          now={now}
          category={category}
          onClearCategory={() => { setCategory(null) }}
          openAssignmentId={openAssignmentId}
          isPending={assignments.isPending}
          isError={assignments.isError}
          onRetry={() => void assignments.refetch()}
        />

        <div className="flex min-w-0 flex-col gap-4">
          <PolicyFacts course={course.data} />
          <CourseAnnouncements courseId={courseId} />
          <CourseContacts course={course.data} />
        </div>
      </div>
    </div>
  )
}
