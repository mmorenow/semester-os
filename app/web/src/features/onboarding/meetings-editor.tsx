import { Plus, Trash } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Toggle } from '@/components/ui/toggle'
import { MEETING_KIND_LABEL } from '@/lib/school-labels'
import { formatClockRange, parseHhMm } from '@/lib/school-time'
import type { MeetingKind } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { chipClass } from '@/features/school/course-color'
import type { FieldMessage, Proposal, ProposalDay, ProposalMeeting } from './onboarding-types'
import {
  DAYS,
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

const KINDS: MeetingKind[] = ['lecture', 'lab', 'pso']

function meetingRange(meeting: ProposalMeeting): string | null {
  const start = parseHhMm(meeting.start_time)
  if (start === null) return null
  if (meeting.duration_min === null) return formatClockRange(start, start).split('-')[0]
  return formatClockRange(start, start + meeting.duration_min)
}

/**
 * Week preview of the proposal's meetings as course-tinted chips (28%). Untimed meetings
 * still show, so a day never looks empty by mistake.
 */
export function WeekStrip({ meetings, slot }: { meetings: ProposalMeeting[]; slot: number | undefined }) {
  const weekend = meetings.some((meeting) => meeting.days.includes('S') || meeting.days.includes('U'))
  const days = weekend ? DAYS : DAYS.slice(0, 5)
  const sorted = meetings
    .map((meeting, index) => ({ meeting, index }))
    .sort((a, b) => (parseHhMm(a.meeting.start_time) ?? 9999) - (parseHhMm(b.meeting.start_time) ?? 9999))

  return (
    <div
      className={cn('grid gap-px overflow-hidden rounded-md border border-border bg-border', weekend ? 'grid-cols-7' : 'grid-cols-5')}
      role="list"
      aria-label="Weekly schedule preview"
    >
      {days.map((day) => {
        const today = sorted.filter(({ meeting }) => meeting.days.includes(day.code))
        return (
          <div key={day.code} className="flex min-h-20 min-w-0 flex-col gap-1 bg-card p-1.5" role="listitem">
            <span className="text-xs font-medium text-muted-foreground">{day.short}</span>
            {today.length === 0 ? (
              <span className="sr-only">No meetings</span>
            ) : (
              today.map(({ meeting, index }) => (
                <span
                  key={index}
                  className={cn('flex min-w-0 flex-col rounded-sm px-1.5 py-0.5 text-foreground', chipClass(slot))}
                >
                  <span className="num truncate text-xs">{meetingRange(meeting) ?? '-'}</span>
                  <span className="truncate text-xs">{meeting.kind ? MEETING_KIND_LABEL[meeting.kind] : 'Meeting'}</span>
                </span>
              ))
            )}
          </div>
        )
      })}
    </div>
  )
}

function MeetingRow({
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
  const meeting = draft.meetings[index]
  const base = `meetings[${String(index)}]`
  const id = `meeting-${String(index)}`
  const flag = (field: string) => uncertaintyFor(draft, `${base}.${field}`)
  const problem = (field: string) => messageFor(problems, `${base}.${field}`)
  const set = <F extends keyof ProposalMeeting>(field: F, value: ProposalMeeting[F]) =>
    onChange(setItemField(draft, 'meetings', index, field, value))
  const dismiss = (field: string) => onChange(clearUncertainty(draft, `${base}.${field}`))

  const rowProblems = (['kind', 'days', 'start_time', 'duration_min', 'end_date'] as const)
    .map((field) => problem(field))
    .filter((message): message is string => Boolean(message))
  const flags = (['kind', 'days', 'start_time', 'duration_min', 'location', 'crn', 'start_date', 'end_date'] as const)
    .map((field) => ({ field, reason: flag(field) }))
    .filter((entry): entry is { field: (typeof entry)['field']; reason: string } => Boolean(entry.reason))

  function toggleDay(code: ProposalDay, pressed: boolean) {
    const next = pressed ? [...meeting.days, code] : meeting.days.filter((day) => day !== code)
    set('days', DAYS.map((day) => day.code).filter((day) => next.includes(day)))
  }

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={meeting.kind ?? undefined} onValueChange={(value) => set('kind', value as MeetingKind)}>
          <SelectTrigger
            size="sm"
            className={cn('w-24', flag('kind') && FLAG_BORDER)}
            aria-label={`Meeting ${String(index + 1)} kind`}
            aria-invalid={problem('kind') ? true : undefined}
          >
            <SelectValue placeholder="Kind" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {KINDS.map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {MEETING_KIND_LABEL[kind]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>

        <div
          className={cn('flex rounded-md border border-transparent', (flag('days') || problem('days')) && FLAG_BORDER)}
          role="group"
          aria-label={`Meeting ${String(index + 1)} days`}
        >
          {DAYS.map((day) => (
            <Toggle
              key={day.code}
              size="sm"
              variant="outline"
              pressed={meeting.days.includes(day.code)}
              onPressedChange={(pressed) => toggleDay(day.code, pressed)}
              aria-label={day.long}
              className="num w-7 min-w-7 rounded-none border-l-0 px-0 first:rounded-l-md first:border-l last:rounded-r-md data-[state=on]:bg-primary/12 data-[state=on]:text-primary"
            >
              {day.code}
            </Toggle>
          ))}
        </div>

        <Input
          id={`${id}-start`}
          type="time"
          value={meeting.start_time ?? ''}
          onChange={(event) => set('start_time', textOrNull(event.target.value))}
          aria-label={`Meeting ${String(index + 1)} start time`}
          aria-invalid={problem('start_time') ? true : undefined}
          className={cn('num h-7 w-auto', flag('start_time') && FLAG_BORDER)}
        />
        <div className="flex items-center gap-1">
          <Input
            type="number"
            inputMode="numeric"
            min={5}
            max={600}
            step={5}
            value={meeting.duration_min ?? ''}
            onChange={(event) => {
              const value = parseNumber(event.target.value)
              set('duration_min', value === null ? null : Math.round(value))
            }}
            aria-label={`Meeting ${String(index + 1)} length in minutes`}
            aria-invalid={problem('duration_min') ? true : undefined}
            className={cn('num h-7 w-16 text-right', flag('duration_min') && FLAG_BORDER)}
          />
          <span className="text-[13px] text-muted-foreground" aria-hidden>
            min
          </span>
        </div>

        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          className="ml-auto"
          onClick={() => onChange(removeItem(draft, 'meetings', index))}
          aria-label={`Remove meeting ${String(index + 1)}`}
        >
          <Trash />
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={meeting.location ?? ''}
          onChange={(event) => set('location', textOrNull(event.target.value))}
          placeholder="Room"
          aria-label={`Meeting ${String(index + 1)} room`}
          className={cn('h-7 min-w-40 flex-1', flag('location') && FLAG_BORDER)}
          maxLength={300}
          autoComplete="off"
        />
        <Input
          value={meeting.crn ?? ''}
          onChange={(event) => set('crn', textOrNull(event.target.value))}
          placeholder="CRN"
          aria-label={`Meeting ${String(index + 1)} CRN`}
          className={cn('num h-7 w-24', flag('crn') && FLAG_BORDER)}
          maxLength={20}
          autoComplete="off"
          spellCheck={false}
        />
        {meeting.start_date || meeting.end_date ? (
          <span className="num text-xs text-muted-foreground">
            {meeting.start_date ?? '...'} to {meeting.end_date ?? '...'}
          </span>
        ) : null}
      </div>

      {rowProblems.map((message) => (
        <ProblemNote key={message} message={message} />
      ))}
      {flags.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {flags.map(({ field, reason }) => (
            <li key={field} className="flex items-center gap-1.5">
              <CellFlag reason={reason} onDismiss={() => dismiss(field)} />
              <span className="min-w-0 text-[13px] leading-snug text-muted-foreground">{reason}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function MeetingsEditor({
  draft,
  problems,
  slot,
  manual = false,
  onChange,
}: {
  draft: Proposal
  problems: FieldMessage[]
  slot: number | undefined
  /** A course typed in by hand has no syllabus to have said anything. */
  manual?: boolean
  onChange: (next: Proposal) => void
}) {
  const count = draft.meetings.length
  return (
    <ReviewSection
      id="review-meetings"
      title="Weekly schedule"
      meta={count === 0 ? 'No meetings' : `${String(count)} ${count === 1 ? 'meeting' : 'meetings'}`}
      action={
        <Button type="button" size="sm" variant="ghost" onClick={() => onChange(addItem(draft, 'meetings'))}>
          <Plus data-icon="inline-start" />
          Add meeting
        </Button>
      }
    >
      <WeekStrip meetings={draft.meetings} slot={slot} />
      {count > 0 ? (
        <ul className="flex flex-col divide-y divide-border">
          {draft.meetings.map((_, index) => (
            <MeetingRow key={index} draft={draft} index={index} problems={problems} onChange={onChange} />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {manual
            ? 'Add each weekly lecture, lab or PSO with Add meeting.'
            : 'The syllabus lists no weekly meetings. Add them here if the course has any.'}
        </p>
      )}
    </ReviewSection>
  )
}
