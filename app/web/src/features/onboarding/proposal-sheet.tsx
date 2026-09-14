import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Info, WarningCircle } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Markdown } from '@/components/markdown'
import { relativeTime } from '@/lib/format'
import { useCourses } from '@/lib/school-queries'
import { CourseMark } from '@/features/school/course-mark'
import { courseSlot } from '@/features/school/course-color'
import { AssignmentsEditor } from './assignments-editor'
import { MeetingsEditor } from './meetings-editor'
import { useApplySource, useDiscardSource, useSaveProposal } from './onboarding-queries'
import type { AppliedChanges, FieldMessage, Proposal, SyllabusSource } from './onboarding-types'
import {
  PLATFORM_LABEL,
  clearUncertainty,
  messageFor,
  parseNumber,
  setField,
  textOrNull,
  uncertaintyFor,
} from './proposal-model'
import { FLAG_BORDER, ReviewField, ReviewSection, describedBy } from './review-parts'
import { WeightsEditor } from './weights-editor'
import { cn } from '@/lib/utils'

/** The autosave debounce the product uses for every notes-style edit. */
const AUTOSAVE_MS = 800

type SaveState = { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved' } | { kind: 'error'; message: string }

function CourseFields({
  draft,
  problems,
  onChange,
}: {
  draft: Proposal
  problems: FieldMessage[]
  onChange: (next: Proposal) => void
}) {
  // The instructor list is typed as one line; the list is what is saved.
  const [instructors, setInstructors] = useState(draft.instructors.join(', '))

  const text = (key: 'course_code' | 'course_title' | 'term', label: string, className?: string, maxLength = 200) => {
    const id = `review-${key}`
    const reason = uncertaintyFor(draft, key)
    const problem = messageFor(problems, key)
    return (
      <ReviewField
        label={label}
        htmlFor={id}
        reason={reason}
        problem={problem}
        onDismiss={() => onChange(clearUncertainty(draft, key))}
        className={className}
      >
        <Input
          id={id}
          value={draft[key] ?? ''}
          onChange={(event) => onChange(setField(draft, key, textOrNull(event.target.value)))}
          aria-invalid={problem ? true : undefined}
          aria-describedby={describedBy(id, reason, problem)}
          className={cn(key === 'course_code' && 'num', reason && FLAG_BORDER)}
          maxLength={maxLength}
          autoComplete="off"
          spellCheck={key === 'course_code' ? false : undefined}
        />
      </ReviewField>
    )
  }

  const creditsReason = uncertaintyFor(draft, 'credit_hours')
  const instructorsReason = uncertaintyFor(draft, 'instructors')

  return (
    <ReviewSection id="review-course" title="Course">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
        {text('course_code', 'Code', undefined, 40)}
        {text('course_title', 'Title')}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[6rem_9rem_minmax(0,1fr)]">
        <ReviewField
          label="Credits"
          htmlFor="review-credits"
          reason={creditsReason}
          onDismiss={() => onChange(clearUncertainty(draft, 'credit_hours'))}
        >
          <Input
            id="review-credits"
            type="number"
            inputMode="decimal"
            min={0}
            max={20}
            step={0.5}
            value={draft.credit_hours ?? ''}
            onChange={(event) => onChange(setField(draft, 'credit_hours', parseNumber(event.target.value)))}
            aria-describedby={describedBy('review-credits', creditsReason)}
            className={cn('num text-right', creditsReason && FLAG_BORDER)}
          />
        </ReviewField>
        {text('term', 'Term', undefined, 60)}
        <ReviewField
          label="Instructors"
          htmlFor="review-instructors"
          reason={instructorsReason}
          onDismiss={() => onChange(clearUncertainty(draft, 'instructors'))}
        >
          <Input
            id="review-instructors"
            value={instructors}
            onChange={(event) => {
              setInstructors(event.target.value)
              const names = event.target.value
                .split(',')
                .map((name) => name.trim())
                .filter(Boolean)
              onChange(setField(draft, 'instructors', names))
            }}
            placeholder="Separate names with commas"
            aria-describedby={describedBy('review-instructors', instructorsReason)}
            className={cn(instructorsReason && FLAG_BORDER)}
            autoComplete="off"
          />
        </ReviewField>
      </div>
    </ReviewSection>
  )
}

const POLICY_ROWS: { key: keyof Proposal; label: string }[] = [
  { key: 'drop_rules', label: 'Dropped scores' },
  { key: 'late_policy', label: 'Late work' },
  { key: 'grading_scale', label: 'Grade scale' },
  { key: 'ai_policy', label: 'AI policy' },
  { key: 'attendance_policy', label: 'Attendance' },
  { key: 'regrade_policy', label: 'Regrades' },
]

/** Syllabus policies as the agent summarized them. Read-only; saved with the course as shown. */
function PoliciesSection({ draft }: { draft: Proposal }) {
  const rows = POLICY_ROWS.filter(({ key }) => typeof draft[key] === 'string' && draft[key])
  if (rows.length === 0 && draft.platforms.length === 0) return null
  return (
    <ReviewSection id="review-policies" title="Policies and platforms">
      {draft.platforms.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Course platforms">
          {draft.platforms.map((platform, index) => (
            <li
              key={index}
              className="rounded-sm border border-border px-2 py-0.5 text-[13px] text-foreground"
              title={platform.notes ?? undefined}
            >
              {platform.name ?? PLATFORM_LABEL[platform.platform] ?? platform.platform}
              {platform.notes ? <span className="text-muted-foreground">{`: ${platform.notes}`}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {rows.length > 0 ? (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-[8rem_minmax(0,1fr)]">
          {rows.map(({ key, label }) => (
            <div key={key} className="contents">
              <dt className="text-[13px] text-muted-foreground">{label}</dt>
              <dd className="max-w-[70ch] text-[13px] leading-relaxed text-foreground">{String(draft[key])}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </ReviewSection>
  )
}

function appliedSummary(changes: AppliedChanges | null): string {
  if (!changes) return 'The course was written.'
  const parts: string[] = []
  const work = changes.assignments
  if (work.created) parts.push(`${String(work.created)} new ${work.created === 1 ? 'item' : 'items'}`)
  if (work.updated) parts.push(`${String(work.updated)} updated`)
  const meetings = changes.meetings.created
  if (meetings) parts.push(`${String(meetings)} ${meetings === 1 ? 'meeting' : 'meetings'}`)
  let text = parts.length > 0 ? `${parts.join(', ')}.` : 'Nothing needed changing.'
  if (changes.kept.length > 0) {
    text += ` Kept ${String(changes.kept.length)} ${changes.kept.length === 1 ? 'value' : 'values'} you changed by hand.`
  }
  return text
}

function ReviewBody({ source, onClose }: { source: SyllabusSource; onClose: () => void }) {
  const navigate = useNavigate()
  const courses = useCourses()
  const save = useSaveProposal()
  const apply = useApplySource()
  const discard = useDiscardSource()

  const [draft, setDraft] = useState<Proposal>(() => source.proposal as Proposal)
  const [saveState, setSaveState] = useState<SaveState>({ kind: 'idle' })
  const dirty = useRef(false)
  const latest = useRef(draft)
  latest.current = draft

  // Debounced autosave; the server's response carries the current problems.
  useEffect(() => {
    if (!dirty.current) return
    const timer = window.setTimeout(() => {
      dirty.current = false
      setSaveState({ kind: 'saving' })
      save.mutate(
        { id: source.id, proposal: latest.current },
        {
          onSuccess: () => setSaveState({ kind: 'saved' }),
          onError: (error: unknown) =>
            setSaveState({ kind: 'error', message: error instanceof Error ? error.message : 'Not saved.' }),
        },
      )
    }, AUTOSAVE_MS)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, source.id])

  // An edit made in the last 800ms is not lost by closing the sheet.
  useEffect(() => {
    return () => {
      if (dirty.current) save.mutate({ id: source.id, proposal: latest.current })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function change(next: Proposal) {
    dirty.current = true
    setSaveState({ kind: 'idle' })
    setDraft(next)
  }

  const existing = source.existing_course
  const manual = source.kind === 'manual'
  const courseIndex = courses.data ? courses.data.length : 0
  const slot = existing ? courseSlot(existing.color) : courseIndex % 6
  const problems = source.problems
  const busy = apply.isPending || discard.isPending
  const code = draft.course_code ?? existing?.code ?? null

  function confirm() {
    dirty.current = false
    apply.mutate(
      { id: source.id, proposal: draft },
      {
        onSuccess: (applied) => {
          const courseId = applied.applied_course_id
          toast.success(`${code ?? 'Course'} ${existing ? 'updated' : 'added to your semester'}`, {
            description: appliedSummary(applied.applied_changes),
            action: courseId ? { label: 'Open course', onClick: () => navigate(`/courses/${String(courseId)}`) } : undefined,
          })
          onClose()
        },
        onError: (error: unknown) => {
          toast.error('Could not add the course', {
            description: error instanceof Error ? error.message : 'The server refused the proposal.',
          })
        },
      },
    )
  }

  function decline() {
    dirty.current = false
    discard.mutate(source.id, {
      onSuccess: () => {
        toast.info('Proposal discarded', { description: 'Nothing was added. You can read the syllabus again later.' })
        onClose()
      },
      onError: (error: unknown) => {
        toast.error('Could not discard', { description: error instanceof Error ? error.message : undefined })
      },
    })
  }

  const readFrom = source.kind === 'manual' ? 'Typed in by hand' : `Read from ${source.name}`
  const when = relativeTime(source.resolved_at)

  return (
    <>
      <SheetHeader className="gap-2 border-b border-border px-5 pb-4 pt-5">
        <div className="flex min-w-0 items-center gap-2.5 pr-8">
          {code ? <CourseMark code={code} slot={slot} size="md" /> : null}
          <SheetTitle className="min-w-0 truncate text-lg font-semibold leading-snug">
            {draft.course_title ?? existing?.title ?? 'New course'}
          </SheetTitle>
        </div>
        <SheetDescription className="text-[13px] text-muted-foreground">
          <span className="break-all">{readFrom}</span>
          {when ? ` · ${when}` : ''}
        </SheetDescription>
      </SheetHeader>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain">
        {existing || draft.uncertain.length > 0 ? (
          <div className="flex flex-col gap-2 border-b border-border px-5 py-3">
            {existing ? (
              <Alert>
                <Info />
                <AlertDescription className="text-[13px] leading-relaxed text-foreground">
                  <span className="num">{existing.code}</span> is already in your semester. Confirming updates it
                  instead of adding a second copy, and anything you changed by hand since is kept.
                </AlertDescription>
              </Alert>
            ) : null}
            {draft.uncertain.length > 0 ? (
              <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                <WarningCircle size={14} aria-hidden className="shrink-0 text-signal-amber" />
                <span>
                  <span className="num text-foreground">{String(draft.uncertain.length)}</span>{' '}
                  {draft.uncertain.length === 1 ? 'value' : 'values'} the syllabus did not state clearly. They are marked
                  below; fix them or mark them as right.
                </span>
              </p>
            ) : null}
          </div>
        ) : null}

        <CourseFields draft={draft} problems={problems} onChange={change} />
        <MeetingsEditor draft={draft} problems={problems} slot={slot} manual={manual} onChange={change} />
        <AssignmentsEditor draft={draft} problems={problems} manual={manual} onChange={change} />
        <WeightsEditor draft={draft} manual={manual} onChange={change} />
        <PoliciesSection draft={draft} />
        {source.commentary ? (
          <section className="border-b border-border bg-muted/40 px-5 py-4 last:border-b-0" aria-labelledby="review-commentary">
            <h3 id="review-commentary" className="mb-2 text-[13px] font-medium text-foreground">
              What the agent read
            </h3>
            <div className="max-w-[70ch]">
              <Markdown>{source.commentary}</Markdown>
            </div>
          </section>
        ) : null}
      </div>

      <div className="flex flex-col gap-2 border-t border-border bg-card px-5 py-3">
        {problems.length > 0 ? (
          <div className="flex items-start gap-1.5 text-[13px] text-signal-red" role="status">
            <WarningCircle size={14} aria-hidden className="mt-0.5 shrink-0" />
            <span>
              Before confirming: {problems.map((problem) => problem.message).join(' ')}
            </span>
          </div>
        ) : null}
        <div className="flex items-center gap-2">
          <Button onClick={confirm} disabled={busy || problems.length > 0} aria-busy={apply.isPending || undefined}>
            {apply.isPending ? 'Adding' : existing ? `Confirm & update ${existing.code}` : 'Confirm & add course'}
          </Button>
          <Button variant="ghost" onClick={decline} disabled={busy} aria-busy={discard.isPending || undefined}>
            {discard.isPending ? 'Discarding' : 'Discard'}
          </Button>
          <span className="ml-auto text-[13px] text-muted-foreground" role="status" aria-live="polite">
            {saveState.kind === 'saving'
              ? 'Saving'
              : saveState.kind === 'saved'
                ? 'Saved'
                : saveState.kind === 'error'
                  ? `Not saved: ${saveState.message}`
                  : ''}
          </span>
        </div>
      </div>
    </>
  )
}

/** Review sheet for one proposal. Autosaves; Confirm stays disabled while the server reports a problem, and says which. */
export function ProposalSheet({ source, onClose }: { source: SyllabusSource | null; onClose: () => void }) {
  const open = source !== null && source.status === 'proposed' && source.proposal !== null
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0 ease-enter data-open:duration-[240ms] data-closed:duration-[200ms] data-[side=right]:sm:max-w-[760px]"
        overlayClassName="ease-enter data-open:duration-[240ms] data-closed:duration-[200ms]"
      >
        {open ? <ReviewBody key={source.id} source={source} onClose={onClose} /> : null}
      </SheetContent>
    </Sheet>
  )
}
