import { Plus, Trash } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatClock, parseHhMm } from '@/lib/school-time'
import { cn } from '@/lib/utils'
import type { FieldMessage, Proposal, ProposalAssignment, ProposalAssignmentKind } from './onboarding-types'
import {
  ASSIGNMENT_KIND_LABEL,
  addItem,
  clearUncertainty,
  messageFor,
  parseNumber,
  removeItem,
  setItemField,
  textOrNull,
  uncertaintyFor,
} from './proposal-model'
import { CellFlag, FLAG_BORDER, ProblemNote, ReviewSection } from './review-parts'

const KINDS = Object.keys(ASSIGNMENT_KIND_LABEL) as ProposalAssignmentKind[]

/** The fields a row edits inline, in column order. The rest ride on the second line. */
const EDITED = ['title', 'kind', 'due_date', 'due_time', 'points'] as const

function AssignmentRow({
  draft,
  index,
  problems,
  onChange,
}: {
  draft: Proposal
  index: number
  problems: FieldMessage[]
  onChange: (next: Proposal) => void
}) {
  const item = draft.assignments[index]
  const base = `assignments[${String(index)}]`
  const label = item.title ?? `Assignment ${String(index + 1)}`
  const flag = (field: string) => uncertaintyFor(draft, `${base}.${field}`)
  const problem = (field: string) => messageFor(problems, `${base}.${field}`)
  const set = <F extends keyof ProposalAssignment>(field: F, value: ProposalAssignment[F]) =>
    onChange(setItemField(draft, 'assignments', index, field, value))

  const flags = (
    ['title', 'kind', 'category', 'due_date', 'due_time', 'end_time', 'location', 'points', 'weight_pct', 'notes'] as const
  )
    .map((field) => ({ field, reason: flag(field) }))
    .filter((entry): entry is { field: (typeof entry)['field']; reason: string } => Boolean(entry.reason))
  const rowProblems = EDITED.map((field) => problem(field)).filter((message): message is string => Boolean(message))
  const categoryAddsSomething =
    item.category !== null && item.category.toLowerCase() !== (ASSIGNMENT_KIND_LABEL[item.kind ?? ''] ?? '').toLowerCase()
  const endMinutes = parseHhMm(item.end_time)
  const context = [
    endMinutes !== null ? `Ends ${formatClock(endMinutes)}` : null,
    item.location,
    categoryAddsSomething ? item.category : null,
    item.weight_pct !== null ? `${String(item.weight_pct)}% of the grade` : null,
    item.notes,
  ].filter(Boolean)

  return (
    <li className="col-span-full grid grid-cols-subgrid gap-y-1.5 py-2.5 first:pt-0 last:pb-0">
      <div className="col-span-full grid grid-cols-subgrid items-center">
        <Input
          value={item.title ?? ''}
          onChange={(event) => set('title', textOrNull(event.target.value))}
          placeholder="Title"
          aria-label={`Assignment ${String(index + 1)} title`}
          aria-invalid={problem('title') ? true : undefined}
          className={cn('h-7', flag('title') && FLAG_BORDER)}
          maxLength={300}
          autoComplete="off"
        />
        <Select value={item.kind ?? undefined} onValueChange={(value) => set('kind', value as ProposalAssignmentKind)}>
          <SelectTrigger
            size="sm"
            className={cn('w-full', flag('kind') && FLAG_BORDER)}
            aria-label={`${label} kind`}
            aria-invalid={problem('kind') ? true : undefined}
          >
            <SelectValue placeholder="Kind" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {KINDS.map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {ASSIGNMENT_KIND_LABEL[kind]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Input
          type="date"
          value={item.due_date ?? ''}
          onChange={(event) => set('due_date', textOrNull(event.target.value))}
          aria-label={`${label} due date`}
          aria-invalid={problem('due_date') ? true : undefined}
          className={cn('num h-7 w-auto', flag('due_date') && FLAG_BORDER)}
        />
        <Input
          type="time"
          value={item.due_time ?? ''}
          onChange={(event) => set('due_time', textOrNull(event.target.value))}
          aria-label={`${label} due time`}
          className={cn('num h-7 w-auto', flag('due_time') && FLAG_BORDER)}
        />
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          value={item.points ?? ''}
          onChange={(event) => set('points', parseNumber(event.target.value))}
          placeholder="pts"
          aria-label={`${label} points`}
          className={cn('num h-7 text-right', flag('points') && FLAG_BORDER)}
        />
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          onClick={() => onChange(removeItem(draft, 'assignments', index))}
          aria-label={`Remove ${label}`}
        >
          <Trash />
        </Button>
      </div>

      {context.length > 0 || rowProblems.length > 0 || flags.length > 0 ? (
        <div className="col-span-full flex min-w-0 flex-col gap-1.5">
          {context.length > 0 ? (
            <p className="truncate text-xs text-muted-foreground" title={context.join(' · ')}>
              {context.join(' · ')}
            </p>
          ) : null}
          {rowProblems.map((message) => (
            <ProblemNote key={message} message={message} />
          ))}
          {flags.map(({ field, reason }) => (
            <div key={field} className="flex items-center gap-1.5">
              <CellFlag reason={reason} onDismiss={() => onChange(clearUncertainty(draft, `${base}.${field}`))} />
              <span className="min-w-0 text-[13px] leading-snug text-muted-foreground">{reason}</span>
            </div>
          ))}
        </div>
      ) : null}
    </li>
  )
}

/** One editable row per item; exam end, room, category, weight and note sit read-only on a second line. */
export function AssignmentsEditor({
  draft,
  problems,
  manual = false,
  onChange,
}: {
  draft: Proposal
  problems: FieldMessage[]
  manual?: boolean
  onChange: (next: Proposal) => void
}) {
  const count = draft.assignments.length
  const undated = draft.assignments.filter((item) => !item.due_date).length
  return (
    <ReviewSection
      id="review-work"
      title="Assignments and exams"
      meta={
        count === 0 ? (
          'None listed'
        ) : (
          <>
            <span className="num">{String(count)}</span> {count === 1 ? 'item' : 'items'}
            {undated > 0 ? (
              <>
                {', '}
                <span className="num">{String(undated)}</span> without a date
              </>
            ) : null}
          </>
        )
      }
      action={
        <Button type="button" size="sm" variant="ghost" onClick={() => onChange(addItem(draft, 'assignments'))}>
          <Plus data-icon="inline-start" />
          Add item
        </Button>
      }
    >
      {count > 0 ? (
        <div className="overflow-x-auto">
          {/* One subgrid for header and rows so date/time columns fit the locale's native inputs, not a fixed width. */}
          <div className="grid min-w-[36rem] grid-cols-[minmax(0,1fr)_7rem_max-content_max-content_4.5rem_1.75rem] gap-x-2">
            <div
              className="col-span-full grid grid-cols-subgrid pb-1.5 text-2xs font-medium text-muted-foreground"
              aria-hidden
            >
              <span>Title</span>
              <span>Kind</span>
              <span>Due date</span>
              <span>Time</span>
              <span className="text-right">Points</span>
              <span />
            </div>
            <ul className="col-span-full grid grid-cols-subgrid divide-y divide-border">
              {draft.assignments.map((_, index) => (
                <AssignmentRow key={index} draft={draft} index={index} problems={problems} onChange={onChange} />
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {manual ? 'Add homework, quizzes, exams and projects with Add item.' : 'No graded work was found. Add items here.'}
        </p>
      )}
    </ReviewSection>
  )
}
