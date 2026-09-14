import { Link } from 'react-router-dom'
import { relativeAge } from '@/lib/format'
import type { Assignment } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { CourseMark } from './course-mark'
import { gradeLabel, gradeRatio, pct } from './grade-model'
import { Panel, PanelHeader } from './school-parts'

const WINDOW_DAYS = 7
const WINDOW_MS = WINDOW_DAYS * 86_400_000

/** Grades from the last week. The section renders only when non-empty. */
export function selectRecentlyGraded(assignments: Assignment[] | undefined, now: Date): Assignment[] {
  const floor = now.getTime() - WINDOW_MS
  return (assignments ?? [])
    .filter((assignment) => {
      if (assignment.grade_points === null || assignment.grade_points === undefined) return false
      if (!assignment.updated_at) return false
      const at = new Date(assignment.updated_at).getTime()
      return !Number.isNaN(at) && at >= floor
    })
    .sort((a, b) => new Date(b.updated_at ?? 0).getTime() - new Date(a.updated_at ?? 0).getTime())
}

/** The share earned, banded. A grade is a fact, so it gets the signal ramp. */
function ratioTone(ratio: number | null): string {
  if (ratio === null) return 'text-foreground'
  if (ratio >= 90) return 'text-signal-green'
  if (ratio >= 75) return 'text-foreground'
  return 'text-signal-amber'
}

export function RecentlyGraded({
  assignments,
  colors,
  now,
}: {
  assignments: Assignment[] | undefined
  colors: Map<number, number>
  now: Date
}) {
  const rows = selectRecentlyGraded(assignments, now)
  if (rows.length === 0) return null

  return (
    <Panel>
      <PanelHeader
        title="Recently graded"
        meta={
          <>
            last <span className="num">{String(WINDOW_DAYS)}</span> days
          </>
        }
      />
      <ul>
        {rows.slice(0, 5).map((assignment) => {
          const ratio = gradeRatio(assignment)
          return (
            <li key={assignment.id} className="border-b border-border last:border-b-0">
              <Link
                to={`/courses/${String(assignment.course_id)}?assignment=${String(assignment.id)}`}
                className="flex items-center gap-2 px-2 py-2 transition-colors duration-[80ms] hover:bg-muted/50 focus-ring-inset"
              >
                <CourseMark code={assignment.course_code} slot={colors.get(assignment.course_id)} size="xs" />
                <span className="min-w-0 flex-1 truncate text-sm text-foreground">{assignment.title}</span>
                {ratio !== null ? (
                  <span className={cn('num shrink-0 text-xs', ratioTone(ratio))}>{pct(ratio)}</span>
                ) : null}
                <span className="num w-[76px] shrink-0 text-right text-[13px] text-foreground">
                  {gradeLabel(assignment)}
                </span>
                <span className="num w-[56px] shrink-0 text-right text-xs text-muted-foreground">
                  {relativeAge(assignment.updated_at) ?? ''}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
