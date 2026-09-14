import { useMemo } from 'react'
import { FileText, WarningCircle, X } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { isSettled } from '@/lib/school-labels'
import type { Assignment, CoursePlatform } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { AssignmentRow } from './assignment-row'
import { matchesCategory } from './grade-model'
import { Panel, PanelHeader } from './school-parts'

const DUE_LAST = Number.POSITIVE_INFINITY

function dueTime(assignment: Assignment): number {
  if (!assignment.due_at) return DUE_LAST
  const at = new Date(assignment.due_at).getTime()
  return Number.isNaN(at) ? DUE_LAST : at
}

/** Open work in deadline order; finished work newest first, under a divider. */
export function splitAssignments(rows: Assignment[]): { open: Assignment[]; done: Assignment[] } {
  const open = rows.filter((row) => !isSettled(row.status)).sort((a, b) => dueTime(a) - dueTime(b))
  const done = rows.filter((row) => isSettled(row.status)).sort((a, b) => dueTime(b) - dueTime(a))
  return { open, done }
}

function GroupLabel({ label, count }: { label: string; count: number }) {
  return (
    <li className="flex items-baseline gap-2 border-b border-border bg-muted/30 px-3 py-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="num text-xs text-muted-foreground">{count}</span>
    </li>
  )
}

function ListSkeleton() {
  return (
    <ul>
      {Array.from({ length: 5 }, (_, index) => (
        <li key={index} className="flex items-center gap-3 border-b border-border px-3 py-2.5 last:border-b-0">
          <Skeleton className="size-3.5 shrink-0 rounded-sm" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-[104px] shrink-0" />
          <Skeleton className="h-3.5 w-12 shrink-0" />
          <Skeleton className="h-8 w-[132px] shrink-0 rounded-md" />
        </li>
      ))}
    </ul>
  )
}

interface CourseAssignmentsProps {
  assignments: Assignment[] | undefined
  platforms: CoursePlatform[]
  now: Date
  /** The grade category selected upstairs, deep-linked as `?category=`. */
  category: string | null
  onClearCategory: () => void
  /** The assignment a `?assignment=` deep link asked to open. */
  openAssignmentId: number | null
  isPending: boolean
  isError: boolean
  onRetry: () => void
}

/**
 * The course's work, filtered by the selected Grade Center category. Matched by name, since the
 * API doesn't stamp a category on each row; a category matching nothing says so.
 */
export function CourseAssignments({
  assignments,
  platforms,
  now,
  category,
  onClearCategory,
  openAssignmentId,
  isPending,
  isError,
  onRetry,
}: CourseAssignmentsProps) {
  const rows = useMemo(() => {
    const all = assignments ?? []
    return category === null ? all : all.filter((row) => matchesCategory(row, category))
  }, [assignments, category])

  const { open, done } = useMemo(() => splitAssignments(rows), [rows])
  const total = assignments?.length ?? 0

  return (
    <Panel>
      <PanelHeader
        title="Work"
        icon={FileText}
        meta={
          rows.length > 0 ? (
            <>
              <span className="num">{String(open.length)}</span> open
            </>
          ) : undefined
        }
        action={
          category ? (
            <span className="flex h-6 items-center gap-1 rounded-sm border border-primary/45 bg-primary/8 pl-2 pr-1 text-xs text-primary">
              {category}
              <button
                type="button"
                onClick={onClearCategory}
                aria-label={`Clear the ${category} filter`}
                className="flex size-4 items-center justify-center rounded-sm transition-colors hover:bg-primary/12 focus-ring active:scale-[0.98]"
              >
                <X size={12} />
              </button>
            </span>
          ) : null
        }
      />

      {isPending ? (
        <ListSkeleton />
      ) : isError ? (
        <EmptyState
          size="inline"
          icon={WarningCircle}
          title="Could not load the work"
          description="The assignments endpoint did not respond. Check that the Semester OS server is still running."
          action={
            <Button size="sm" variant="outline" onClick={onRetry}>
              Try again
            </Button>
          }
        />
      ) : rows.length === 0 ? (
        <EmptyState
          size="inline"
          icon={FileText}
          title={category ? `Nothing filed under ${category}` : 'No assignments yet'}
          description={
            category
              ? `This category carries weight in the grade, but no assignment on file matches it${total > 0 ? ' yet' : ''}. Clear the filter to see the rest.`
              : 'They arrive when the harvest runs against Brightspace and Gradescope, or when you add one by hand.'
          }
          action={
            category ? (
              <Button size="sm" variant="outline" onClick={onClearCategory}>
                Clear filter
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className={cn(done.length > 0 && 'pb-0')}>
          {open.map((assignment) => (
            <AssignmentRow
              key={assignment.id}
              assignment={assignment}
              now={now}
              platforms={platforms}
              defaultOpen={assignment.id === openAssignmentId}
            />
          ))}

          {done.length > 0 ? <GroupLabel label="Done" count={done.length} /> : null}

          {done.map((assignment) => (
            <AssignmentRow
              key={assignment.id}
              assignment={assignment}
              now={now}
              platforms={platforms}
              defaultOpen={assignment.id === openAssignmentId}
            />
          ))}
        </ul>
      )}
    </Panel>
  )
}
