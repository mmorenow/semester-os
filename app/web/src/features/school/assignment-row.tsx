import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowSquareOut, CaretRight, Check } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Markdown } from '@/components/markdown'
import {
  ASSIGNMENT_STATUS_LABEL,
  ASSIGNMENT_STATUS_TONE,
  NEXT_STATUS,
  isSettled,
} from '@/lib/school-labels'
import { useUpdateAssignment } from '@/lib/school-queries'
import type { Assignment, CoursePlatform } from '@/lib/school-types'
import { DUE_TONE_TEXT, dueLabel } from '@/lib/school-time'
import { cn } from '@/lib/utils'
import {
  AssignmentBody,
  AssignmentStatusSelect,
  DueCell,
  GradeCell,
  KindBadge,
  WeightCell,
} from './assignment-parts'
import { CourseMark } from './course-mark'
import { gradeLabel, pct } from './grade-model'

/**
 * 220ms out-cubic entrance. The body mounts on open, keeping closed rows out of the tab order;
 * closing unmounts, so there is no exit animation.
 */

const EXPAND = 'animate-in fade-in-0 slide-in-from-top-1 duration-[220ms] ease-enter'

function Caret({ open }: { open: boolean }) {
  return (
    <CaretRight
      size={14}
      className={cn(
        'shrink-0 text-muted-foreground transition-transform duration-[220ms] ease-enter',
        open && 'rotate-90',
      )}
      aria-hidden
    />
  )
}

interface RowProps {
  assignment: Assignment
  now: Date
  platforms?: CoursePlatform[]
  /** Opened by a deep link (`?assignment=`) rather than by a click. */
  defaultOpen?: boolean
}

export function AssignmentRow({ assignment, now, platforms, defaultOpen = false }: RowProps) {
  const [open, setOpen] = useState(defaultOpen)
  const settled = isSettled(assignment.status)

  return (
    <li
      className={cn(
        'flex flex-col border-b border-border transition-colors duration-[80ms] last:border-b-0',
        open ? 'bg-muted/40' : 'hover:bg-muted/50',
        settled && !open && 'opacity-55 hover:opacity-100',
      )}
    >
      {/* A sibling of the expander: a button inside role="button" isn't reliably reachable. */}
      <div className="flex items-center gap-2 pr-3">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? 'Collapse' : 'Expand'} ${assignment.title}`}
          onClick={() => { setOpen((value) => !value) }}
          className="flex min-w-0 flex-1 items-center gap-2 py-2 pl-3 text-left focus-ring-inset"
        >
          <Caret open={open} />
          <span className="min-w-0 flex-1 truncate text-sm text-foreground">{assignment.title}</span>
          <KindBadge kind={assignment.kind} />
          {/* Measured at 13px mono: widest date 108px, weight 31px, grade `100/100` 55px. */}
          <span className="w-[112px] shrink-0 text-right">
            <DueCell assignment={assignment} now={now} />
          </span>
          <span className="w-[48px] shrink-0">
            <WeightCell assignment={assignment} />
          </span>
          <span className="w-[64px] shrink-0">
            <GradeCell assignment={assignment} />
          </span>
        </button>
        <AssignmentStatusSelect assignment={assignment} className="shrink-0" />
      </div>

      {open ? (
        <div className={cn('border-t border-border bg-muted/20 px-3 py-3', EXPAND)}>
          <AssignmentBody assignment={assignment} now={now} platforms={platforms} />
        </div>
      ) : null}
    </li>
  )
}

/** Compact row for Today. No grades or notes; those live on the course page. */
export function DueRow({
  assignment,
  slot,
  now,
}: {
  assignment: Assignment
  slot: number | undefined
  now: Date
}) {
  const [open, setOpen] = useState(false)
  const update = useUpdateAssignment()
  const due = dueLabel(assignment.due_at, now, assignment.ends_at)
  const settled = isSettled(assignment.status)
  const grade = gradeLabel(assignment)
  const weight = assignment.weight_pct
  const room = assignment.location?.trim() || null
  const showMeta =
    room !== null || (weight !== null && weight !== undefined) || grade !== null || assignment.status !== 'pending'
  const next = NEXT_STATUS[assignment.status]

  function advance() {
    if (!next) return
    update.mutate(
      { id: assignment.id, patch: { status: next.to } },
      {
        onError: (error: unknown) => {
          toast.error('Could not update the assignment', {
            description: error instanceof Error ? error.message : 'The server rejected the request.',
          })
        },
      },
    )
  }

  return (
    <li
      className={cn(
        'group flex flex-col border-b border-border transition-colors duration-[80ms] last:border-b-0',
        open ? 'bg-muted/40' : 'hover:bg-muted/50',
        settled && !open && 'opacity-55 hover:opacity-100',
      )}
    >
      <div className="flex items-start">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? 'Collapse' : 'Expand'} ${assignment.title}`}
          onClick={() => { setOpen((value) => !value) }}
          className="flex min-w-0 flex-1 items-start gap-2 px-2 py-2 text-left focus-ring-inset"
        >
          <span className="flex h-5 items-center">
            <Caret open={open} />
          </span>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <CourseMark code={assignment.course_code} slot={slot} size="xs" />
              <span className="truncate text-sm text-foreground">{assignment.title}</span>
              {due ? (
                <span className={cn('num ml-auto shrink-0 text-[13px]', DUE_TONE_TEXT[due.tone])}>{due.label}</span>
              ) : null}
            </div>

            {showMeta ? (
              <div className="mt-0.5 flex items-center gap-2 pl-[26px]">
                {/* Room first: for an exam it decides where to go. */}
                {room ? <span className="num truncate text-xs text-foreground/90">{room}</span> : null}
                {weight !== null && weight !== undefined ? (
                  <span className="num text-xs text-muted-foreground">{pct(weight)} of grade</span>
                ) : null}
                {grade ? <span className="num text-xs text-foreground/90">{grade}</span> : null}
                {assignment.status !== 'pending' ? (
                  <Badge
                    variant="outline"
                    className={cn('h-5 px-1.5 font-normal text-xs', ASSIGNMENT_STATUS_TONE[assignment.status])}
                  >
                    {ASSIGNMENT_STATUS_LABEL[assignment.status]}
                  </Badge>
                ) : null}
              </div>
            ) : null}
          </div>
        </button>

        {/* Fixed gutter so the row doesn't reflow; a sibling of the expander so the keyboard reaches both. */}
        <div className="flex w-7 shrink-0 items-center justify-center py-2">
          {next ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`${next.label} ${assignment.title}`}
                  disabled={update.isPending}
                  onClick={advance}
                  className="opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-visible:opacity-100"
                >
                  <Check />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{next.label}</TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      </div>

      {open ? (
        <div className={cn('flex flex-col gap-2.5 border-t border-border bg-muted/20 px-3 py-2.5', EXPAND)}>
          <div className="flex flex-wrap items-center gap-2">
            <AssignmentStatusSelect assignment={assignment} />
            {assignment.url ? (
              <Button asChild variant="outline" size="sm">
                <a
                  href={assignment.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  onClick={(event) => { event.stopPropagation() }}
                >
                  <ArrowSquareOut data-icon="inline-start" />
                  Open item
                </a>
              </Button>
            ) : null}
            <Button asChild variant="ghost" size="sm" className="ml-auto text-muted-foreground">
              <Link
                to={`/courses/${String(assignment.course_id)}?assignment=${String(assignment.id)}`}
                onClick={(event) => { event.stopPropagation() }}
              >
                Open in <span className="num">{assignment.course_code}</span>
              </Link>
            </Button>
          </div>

          {assignment.brief_md ? (
            <Markdown className="max-w-[70ch]">{assignment.brief_md}</Markdown>
          ) : (
            <p className="text-[13px] text-muted-foreground">No brief has been written for this item yet.</p>
          )}
        </div>
      ) : null}
    </li>
  )
}
