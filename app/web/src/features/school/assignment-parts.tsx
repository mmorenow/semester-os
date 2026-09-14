import { useEffect, useRef, useState } from 'react'
import { ArrowSquareOut } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Markdown } from '@/components/markdown'
import { humanize } from '@/lib/format'
import { ASSIGNMENT_STATUSES, ASSIGNMENT_STATUS_LABEL } from '@/lib/school-labels'
import { useUpdateAssignment } from '@/lib/school-queries'
import type { Assignment, AssignmentStatus, CoursePlatform } from '@/lib/school-types'
import { DUE_TONE_TEXT, dueLabel } from '@/lib/school-time'
import { cn } from '@/lib/utils'
import { gradeLabel, num, pct } from './grade-model'
import { platformIdentity } from './platform-identity'

/** Inline status change, optimistic, rolled back with a toast on rejection. */
export function AssignmentStatusSelect({
  assignment,
  className,
}: {
  assignment: Assignment
  className?: string
}) {
  const update = useUpdateAssignment()

  function handleChange(next: string) {
    const status = next as AssignmentStatus
    if (status === assignment.status) return
    update.mutate(
      { id: assignment.id, patch: { status } },
      {
        onError: (error: unknown) => {
          toast.error('Status change failed', {
            description: error instanceof Error ? error.message : 'The server rejected the update.',
          })
        },
      },
    )
  }

  return (
    <Select value={assignment.status} onValueChange={handleChange}>
      <SelectTrigger
        className={cn('w-[116px]', className)}
        aria-label={`Status for ${assignment.title}`}
        onClick={(event) => { event.stopPropagation() }}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent onClick={(event) => { event.stopPropagation() }}>
        {ASSIGNMENT_STATUSES.map((status) => (
          <SelectItem key={status} value={status}>
            {ASSIGNMENT_STATUS_LABEL[status]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function toDraft(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : num(value)
}

/**
 * Manual grade entry, committed on blur or Enter so a half-typed value never reaches the server.
 * Clearing both boxes sends an explicit null.
 */
export function GradeEntry({ assignment, className }: { assignment: Assignment; className?: string }) {
  const update = useUpdateAssignment()
  const [points, setPoints] = useState(() => toDraft(assignment.grade_points))
  const [max, setMax] = useState(() => toDraft(assignment.grade_max ?? assignment.points))

  // Someone else's write (a harvest, another surface) wins over a stale draft.
  const serverPoints = toDraft(assignment.grade_points)
  const serverMax = toDraft(assignment.grade_max ?? assignment.points)
  useEffect(() => { setPoints(serverPoints) }, [serverPoints])
  useEffect(() => { setMax(serverMax) }, [serverMax])

  function parse(value: string): number | null | undefined {
    const trimmed = value.trim()
    if (trimmed === '') return null
    const parsed = Number(trimmed)
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined
  }

  function commit() {
    const nextPoints = parse(points)
    const nextMax = parse(max)

    if (nextPoints === undefined || nextMax === undefined) {
      toast.error('Grade not saved', { description: 'Enter a number, or leave the box empty.' })
      setPoints(serverPoints)
      setMax(serverMax)
      return
    }
    if (points === serverPoints && max === serverMax) return

    update.mutate(
      { id: assignment.id, patch: { grade_points: nextPoints, grade_max: nextMax } },
      {
        onError: (error: unknown) => {
          setPoints(serverPoints)
          setMax(serverMax)
          toast.error('Grade not saved', {
            description: error instanceof Error ? error.message : 'The server rejected the update.',
          })
        },
      },
    )
  }

  const pointsId = `grade-points-${String(assignment.id)}`
  const maxId = `grade-max-${String(assignment.id)}`

  return (
    <div
      className={cn('flex items-center gap-1.5', className)}
      onClick={(event) => { event.stopPropagation() }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault()
          ;(event.target as HTMLElement).blur()
        }
      }}
      role="presentation"
    >
      <label htmlFor={pointsId} className="sr-only">
        Points earned on {assignment.title}
      </label>
      <Input
        id={pointsId}
        value={points}
        onChange={(event) => { setPoints(event.target.value) }}
        onBlur={commit}
        inputMode="decimal"
        placeholder="--"
        autoComplete="off"
        className="num w-16 px-2 text-center"
      />
      <span className="text-sm text-muted-foreground" aria-hidden>
        /
      </span>
      <label htmlFor={maxId} className="sr-only">
        Points possible on {assignment.title}
      </label>
      <Input
        id={maxId}
        value={max}
        onChange={(event) => { setMax(event.target.value) }}
        onBlur={commit}
        inputMode="decimal"
        placeholder="--"
        autoComplete="off"
        className="num w-16 px-2 text-center"
      />
    </div>
  )
}

/** Autosaved on an 800ms debounce, and it says so once it has landed. */
export function AssignmentNotes({ assignment }: { assignment: Assignment }) {
  const update = useUpdateAssignment()
  const [draft, setDraft] = useState(assignment.notes ?? '')
  const [saved, setSaved] = useState(false)
  const serverNotes = assignment.notes ?? ''
  const dirty = useRef(false)

  useEffect(() => {
    if (!dirty.current) setDraft(serverNotes)
  }, [serverNotes])

  useEffect(() => {
    if (!dirty.current || draft === serverNotes) return
    const timer = setTimeout(() => {
      update.mutate(
        { id: assignment.id, patch: { notes: draft } },
        {
          onSuccess: () => {
            dirty.current = false
            setSaved(true)
          },
          onError: (error: unknown) => {
            toast.error('Note not saved', {
              description: error instanceof Error ? error.message : 'The server rejected the update.',
            })
          },
        },
      )
    }, 800)
    return () => { clearTimeout(timer) }
    // `update` is a stable mutation handle for the life of this component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, serverNotes, assignment.id])

  const noteId = `assignment-notes-${String(assignment.id)}`

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={noteId} className="text-xs font-medium text-muted-foreground">
          Notes
        </label>
        {saved && draft === serverNotes ? (
          <span className="text-xs text-muted-foreground">Saved</span>
        ) : null}
      </div>
      <Textarea
        id={noteId}
        value={draft}
        onChange={(event) => {
          dirty.current = true
          setSaved(false)
          setDraft(event.target.value)
        }}
        onClick={(event) => { event.stopPropagation() }}
        rows={2}
        placeholder="What is left to do on this one"
        className="min-h-0 resize-y"
      />
    </div>
  )
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-[13px] text-foreground/90">{children}</span>
    </div>
  )
}

/** Where the work goes back, named the way the course names that surface. */
function SubmitTo({ source, platforms }: { source: string; platforms: CoursePlatform[] }) {
  const match = platforms.find((platform) => platform.platform.toLowerCase() === source.toLowerCase())
  const name = match ? platformIdentity(match).name : humanize(source)

  if (match?.url) {
    return (
      <a
        href={match.url}
        target="_blank"
        rel="noreferrer noopener"
        onClick={(event) => { event.stopPropagation() }}
        className="text-primary underline underline-offset-2 hover:no-underline"
      >
        {name}
      </a>
    )
  }
  return <>{name}</>
}

interface AssignmentBodyProps {
  assignment: Assignment
  now: Date
  /** The course's platforms, so "submit on" can resolve to a real link. */
  platforms?: CoursePlatform[]
  className?: string
}

/** Expanded assignment body, shared by the course page row and the explorer drawer. */
export function AssignmentBody({ assignment, now, platforms = [], className }: AssignmentBodyProps) {
  const due = dueLabel(assignment.due_at, now, assignment.ends_at)
  // Items with an end are sittings (exams): show when it happens, not when it's due.
  const sitting = Boolean(assignment.ends_at)
  const grade = gradeLabel(assignment)

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
        {assignment.weight_pct !== null && assignment.weight_pct !== undefined ? (
          <Fact label="Weight">
            <span className="num">{pct(assignment.weight_pct)}</span> of the final grade
          </Fact>
        ) : null}
        {due ? (
          <Fact label={sitting ? 'When' : 'Due'}>
            <span className={cn('num', DUE_TONE_TEXT[due.tone])}>{due.label}</span>
          </Fact>
        ) : null}
        {assignment.location ? (
          <Fact label="Where">
            <span className="num">{assignment.location}</span>
          </Fact>
        ) : null}
        {assignment.kind ? <Fact label="Kind">{humanize(assignment.kind)}</Fact> : null}
        {assignment.source ? (
          <Fact label="Submit on">
            <SubmitTo source={assignment.source} platforms={platforms} />
          </Fact>
        ) : null}
        {grade ? (
          <Fact label="Grade">
            <span className="num">{grade}</span>
          </Fact>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Status</span>
          <AssignmentStatusSelect assignment={assignment} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Grade</span>
          <GradeEntry assignment={assignment} />
        </div>
        {assignment.url ? (
          <Button asChild variant="outline" size="sm" className="ml-auto">
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
      </div>

      {assignment.brief_md ? (
        <div className="border-t border-border pt-3">
          <Markdown className="max-w-[75ch]">{assignment.brief_md}</Markdown>
        </div>
      ) : (
        <p className="border-t border-border pt-3 text-[13px] text-muted-foreground">
          No brief has been written for this item yet.
        </p>
      )}

      <AssignmentNotes assignment={assignment} />
    </div>
  )
}

/** Due date cell. An exam's room goes in the title and accessible name; the 112px column can't fit it. */
export function DueCell({ assignment, now }: { assignment: Assignment; now: Date }) {
  const due = dueLabel(assignment.due_at, now, assignment.ends_at)
  if (!due) return <span className="num text-[13px] text-muted-foreground">No date</span>
  const room = assignment.location?.trim()
  return (
    <span className={cn('num text-[13px]', DUE_TONE_TEXT[due.tone])} title={room ? `${due.label} · ${room}` : undefined}>
      {due.label}
      {room ? <span className="sr-only">{`, ${room}`}</span> : null}
    </span>
  )
}

export function WeightCell({ assignment }: { assignment: Assignment }) {
  const weight = assignment.weight_pct
  if (weight === null || weight === undefined) {
    return <span className="num block text-right text-[13px] text-muted-foreground">--</span>
  }
  return <span className="num block text-right text-[13px] text-foreground">{pct(weight)}</span>
}

export function GradeCell({ assignment }: { assignment: Assignment }) {
  const grade = gradeLabel(assignment)
  return (
    <span
      className={cn('num block text-right text-[13px]', grade ? 'text-foreground' : 'text-muted-foreground')}
    >
      {grade ?? '--'}
    </span>
  )
}

export function KindBadge({ kind }: { kind: string | null | undefined }) {
  if (!kind) return null
  return (
    <Badge variant="outline" className="h-5 px-1.5 font-normal text-xs text-muted-foreground">
      {humanize(kind)}
    </Badge>
  )
}
