import { Link } from 'react-router-dom'
import { CheckCircle, FileText, WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { isSettled } from '@/lib/school-labels'
import { isSameDay } from '@/lib/school-time'
import type { Assignment } from '@/lib/school-types'
import { DueRow } from './assignment-row'
import { Panel, PanelHeader, SyncAge } from './school-parts'

const WINDOW_DAYS = 7
const WINDOW_MS = WINDOW_DAYS * 86_400_000

interface DuePanelProps {
  assignments: Assignment[] | undefined
  colors: Map<number, number>
  now: Date
  isPending: boolean
  isError: boolean
  onRetry: () => void
}

/** Due within a week plus open overdue items. No score: weight and date are shown as themselves. */
export function selectDue(assignments: Assignment[] | undefined, now: Date): Assignment[] {
  const horizon = now.getTime() + WINDOW_MS
  return (assignments ?? [])
    .filter((assignment) => {
      if (!assignment.due_at) return false
      const at = new Date(assignment.due_at).getTime()
      if (Number.isNaN(at)) return false
      if (at < now.getTime()) return !isSettled(assignment.status)
      return at <= horizon
    })
    .sort((a, b) => new Date(a.due_at ?? 0).getTime() - new Date(b.due_at ?? 0).getTime())
}

/** True when today had work and all of it is done, as opposed to a day with nothing due. */
function isDayResolved(assignments: Assignment[] | undefined, now: Date): boolean {
  let due = 0
  for (const assignment of assignments ?? []) {
    if (!assignment.due_at) continue
    const at = new Date(assignment.due_at)
    if (Number.isNaN(at.getTime()) || !isSameDay(at, now)) continue
    if (!isSettled(assignment.status)) return false
    due += 1
  }
  return due > 0
}

/** The newest write across the rows is what "synced" means for this panel. */
function latestUpdate(assignments: Assignment[] | undefined): string | null {
  let newest: number | null = null
  let raw: string | null = null
  for (const assignment of assignments ?? []) {
    if (!assignment.updated_at) continue
    const at = new Date(assignment.updated_at).getTime()
    if (Number.isNaN(at)) continue
    if (newest === null || at > newest) {
      newest = at
      raw = assignment.updated_at
    }
  }
  return raw
}

function DueSkeleton() {
  return (
    <ul>
      {Array.from({ length: 4 }, (_, index) => (
        <li key={index} className="border-b border-border px-2 py-2.5 last:border-b-0">
          <div className="flex items-baseline gap-2">
            <Skeleton className="h-3.5 w-16 shrink-0" />
            <Skeleton className="h-3.5 flex-1" />
            <Skeleton className="h-3.5 w-16 shrink-0" />
          </div>
          <Skeleton className="mt-1.5 h-3 w-24" />
        </li>
      ))}
    </ul>
  )
}

/** What is due. Rows expand in place; the link to the course page is inside. */
export function DuePanel({ assignments, colors, now, isPending, isError, onRetry }: DuePanelProps) {
  const rows = selectDue(assignments, now)
  const syncedAt = latestUpdate(assignments)
  const resolved = isDayResolved(assignments, now)

  return (
    <Panel>
      <PanelHeader
        title="Due"
        meta={
          rows.length > 0 ? (
            <>
              next <span className="num">{String(WINDOW_DAYS)}</span> days
            </>
          ) : undefined
        }
        action={
          isPending || isError ? null : (
            <div className="flex items-center gap-2">
              <SyncAge at={syncedAt} source="Brightspace" />
              <Link
                to="/assignments"
                className="rounded-sm text-xs text-muted-foreground transition-colors hover:text-foreground focus-ring"
              >
                All
              </Link>
            </div>
          )
        }
      />

      {isPending ? (
        <DueSkeleton />
      ) : isError ? (
        <EmptyState
          size="inline"
          icon={WarningCircle}
          title="Could not load assignments"
          description="The assignments endpoint did not respond. Check that the Semester OS server is still running."
          action={
            <Button size="sm" variant="outline" onClick={onRetry}>
              Try again
            </Button>
          }
        />
      ) : rows.length === 0 ? (
        // Today's work is done: say so once.
        <EmptyState
          size="inline"
          icon={resolved ? CheckCircle : FileText}
          iconTone={resolved ? 'text-signal-green' : undefined}
          title={
            resolved
              ? 'Nothing due today'
              : assignments && assignments.length > 0
                ? 'Nothing due this week'
                : 'No assignments yet'
          }
          description={
            resolved
              ? 'Everything today asked for has been handed in.'
              : assignments && assignments.length > 0
                ? 'Every open item is further out than seven days.'
                : 'They arrive when the harvest runs against Brightspace and Gradescope.'
          }
          action={
            assignments && assignments.length > 0 ? (
              <Button asChild size="sm" variant="outline">
                <Link to="/assignments">See everything</Link>
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="max-h-[420px] overflow-y-auto">
          {rows.map((assignment) => (
            <DueRow
              key={assignment.id}
              assignment={assignment}
              slot={colors.get(assignment.course_id)}
              now={now}
            />
          ))}
        </ul>
      )}
    </Panel>
  )
}
