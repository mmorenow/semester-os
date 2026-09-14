import {
  CalendarDots,
  CalendarPlus,
  CalendarX,
  CheckCircle,
  FilePlus,
  Info,
  ListChecks,
  ListPlus,
  PencilSimple,
  WarningCircle,
} from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Elapsed } from '@/components/elapsed'
import { Markdown } from '@/components/markdown'
import { formatDateTime, relativeTime } from '@/lib/format'
import {
  EXTERNAL_SOURCE_LABEL,
  NOTE_OP_LABEL,
  NOTE_STATUS_LABEL,
  NOTE_STATUS_TONE,
  opWrites,
} from '@/lib/school-labels'
import { useApplySchoolNote, useDiscardSchoolNote } from '@/lib/school-queries'
import type { NoteOp, NoteOpKind, SchoolNote } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { Panel, SCHOOL_BADGE } from './school-parts'

/** One glyph per write kind. `comment` is the agent talking, so it gets `Info` in muted ink. */
const OP_GLYPH: Record<NoteOpKind, Icon> = {
  create_assignment: FilePlus,
  update_assignment: PencilSimple,
  create_todo: ListPlus,
  update_todo: ListChecks,
  create_event: CalendarPlus,
  update_event: CalendarDots,
  cancel_event: CalendarX,
  comment: Info,
}

/** One proposed operation, rendered exactly as the server phrased it; never re-derived here. */
function OpRow({ op }: { op: NoteOp }) {
  // A newer server may send an unknown op; render its sentence behind a neutral glyph.
  const Glyph = OP_GLYPH[op.op] ?? Info
  const writes = opWrites(op.op)
  // `cancel_event` is the only removal: red glyph and a 6% wash, text stays in ink.
  const cancels = op.op === 'cancel_event'

  return (
    <li className={cn('flex items-start gap-2', cancels && '-mx-1.5 rounded-sm bg-signal-red/6 px-1.5 py-0.5')}>
      <Glyph
        size={16}
        aria-hidden
        className={cn(
          'mt-0.5 shrink-0',
          cancels ? 'text-signal-red' : writes ? 'text-muted-foreground' : 'text-muted-foreground/75',
        )}
      />
      <span className={cn('text-sm leading-relaxed', writes ? 'text-foreground' : 'text-muted-foreground')}>
        <span className="sr-only">{`${NOTE_OP_LABEL[op.op] ?? 'Change'}: `}</span>
        {op.summary}
      </span>
    </li>
  )
}

/**
 * Placeholder for a running agent: three skeleton rows on `OpRow`'s geometry so the card doesn't
 * jump, swapped instantly (a cross-fade makes a skeleton look like content). The elapsed figure shows it's live.
 */
function RunningBody({ note }: { note: SchoolNote }) {
  return (
    <div className="flex flex-col gap-3 border-t border-border px-3 py-3">
      <div className="flex items-center gap-2">
        {/* The live region is the sentence, not the row, so the ticking figure isn't announced every second. */}
        <p className="text-[13px] text-muted-foreground" role="status">
          Agent is reading your note
        </p>
        <Elapsed since={note.created_at} className="ml-auto text-[13px] text-muted-foreground" />
      </div>
      {/* Decorative; the status line already says what's happening. */}
      <ul className="flex flex-col gap-2" aria-hidden>
        <li className="flex items-center gap-2">
          <Skeleton className="size-4 shrink-0 rounded-sm" />
          <Skeleton className="h-3.5 w-[62%]" />
        </li>
        <li className="flex items-center gap-2">
          <Skeleton className="size-4 shrink-0 rounded-sm" />
          <Skeleton className="h-3.5 w-[78%]" />
        </li>
        <li className="flex items-center gap-2">
          <Skeleton className="size-4 shrink-0 rounded-sm" />
          <Skeleton className="h-3.5 w-[45%]" />
        </li>
      </ul>
    </div>
  )
}

/** A changeset awaiting the user: Confirm (primary) and Discard. Busy controls say so in words, no spinner. */
function ProposedBody({ note }: { note: SchoolNote }) {
  const applyNote = useApplySchoolNote()
  const discardNote = useDiscardSchoolNote()
  const busy = applyNote.isPending || discardNote.isPending

  const ops = note.proposal ?? []
  const writes = ops.filter((op) => opWrites(op.op)).length

  function handleApply() {
    applyNote.mutate(note.id, {
      onSuccess: (applied) => {
        // Announce the outcome once with the server's figures; the changed rows live on other routes.
        const changes = applied.applied_changes?.length ?? 0
        toast.success('Note applied', {
          description:
            changes > 0
              ? `${String(changes)} change${changes === 1 ? '' : 's'} written.`
              : 'The server reported no changes.',
        })
      },
      onError: (error: unknown) => {
        toast.error('Could not apply the note', {
          description: error instanceof Error ? error.message : 'The server rejected the request.',
        })
      },
    })
  }

  function handleDismiss() {
    discardNote.mutate(note.id, {
      onError: (error: unknown) => {
        toast.error('Could not dismiss the note', {
          description: error instanceof Error ? error.message : 'The server rejected the request.',
        })
      },
    })
  }

  function handleDiscard() {
    discardNote.mutate(note.id, {
      onSuccess: () => {
        toast.info('Note discarded', { description: 'Nothing was written.' })
      },
      onError: (error: unknown) => {
        toast.error('Could not discard the note', {
          description: error instanceof Error ? error.message : 'The server rejected the request.',
        })
      },
    })
  }

  return (
    <>
      <div className="flex flex-col gap-2 border-t border-border px-3 py-3">
        {ops.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {ops.map((op, index) => (
              <OpRow key={`${op.op}-${String(index)}`} op={op} />
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted-foreground">
            The agent proposed no changes for this note.
          </p>
        )}
      </div>

      {note.agent_md ? (
        <div className="border-t border-border bg-muted/40 px-3 py-2.5">
          <Markdown>{note.agent_md}</Markdown>
        </div>
      ) : null}

      {writes > 0 ? (
        <div className="flex items-center gap-2 border-t border-border px-3 py-2">
          <Button size="sm" onClick={handleApply} disabled={busy} aria-busy={applyNote.isPending || undefined}>
            {applyNote.isPending ? 'Applying' : 'Confirm & apply'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleDiscard}
            disabled={busy}
            aria-busy={discardNote.isPending || undefined}
          >
            {discardNote.isPending ? 'Discarding' : 'Discard'}
          </Button>
          <span className="ml-auto text-[13px] text-muted-foreground">
            <span className="num">{String(writes)}</span> {writes === 1 ? 'write' : 'writes'}
          </span>
        </div>
      ) : (
        // Only comments, nothing to confirm: the way forward is a clearer note.
        <div className="flex items-center gap-3 border-t border-border px-3 py-2">
          <p className="min-w-0 flex-1 text-[13px] text-muted-foreground">
            Nothing to apply. Send a new note with the missing detail.
          </p>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleDismiss}
            disabled={busy}
            aria-busy={discardNote.isPending || undefined}
          >
            {discardNote.isPending ? 'Dismissing' : 'Dismiss'}
          </Button>
        </div>
      )}
    </>
  )
}

/** The Google Calendar push: sent, failed, or never attempted. Each is a fact worth stating. */
function GcalLine({ note }: { note: SchoolNote }) {
  const gcal = note.gcal
  if (!gcal) return null

  if (!gcal.attempted) {
    return (
      <p className="text-[13px] text-muted-foreground">
        Not pushed to {EXTERNAL_SOURCE_LABEL.gcal} Calendar
        {gcal.detail ? `. ${gcal.detail}` : '.'}
      </p>
    )
  }

  if (gcal.ok) {
    return (
      <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
        <CheckCircle size={14} aria-hidden className="shrink-0 text-signal-green" />
        Pushed to {EXTERNAL_SOURCE_LABEL.gcal} Calendar
      </p>
    )
  }

  return (
    <p className="flex items-start gap-1.5 text-[13px] text-signal-amber">
      <WarningCircle size={14} aria-hidden className="mt-px shrink-0" />
      <span>
        {EXTERNAL_SOURCE_LABEL.gcal} Calendar push failed
        {gcal.detail ? `. ${gcal.detail}` : '.'}
      </span>
    </p>
  )
}

/** What the confirm actually wrote, in the server's own lines. */
function AppliedBody({ note }: { note: SchoolNote }) {
  const changes = note.applied_changes ?? []
  const stamped = formatDateTime(note.applied_at ?? note.resolved_at)

  return (
    <div className="flex flex-col gap-2.5 border-t border-border px-3 py-3">
      {changes.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {changes.map((change, index) => (
            <li key={`${String(index)}-${change}`} className="flex items-start gap-2">
              <CheckCircle size={16} aria-hidden className="mt-0.5 shrink-0 text-signal-green" />
              <span className="text-sm leading-relaxed text-foreground">{change}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">The server reported no changes.</p>
      )}

      <div className="flex flex-col gap-1">
        <GcalLine note={note} />
        {stamped ? <p className="num text-[13px] text-muted-foreground">Applied {stamped}</p> : null}
      </div>
    </div>
  )
}

/** The agent could not answer, in its own words. */
function FailedBody({ note }: { note: SchoolNote }) {
  return (
    <div className="border-t border-border px-3 py-3">
      <div className="flex items-start gap-2 rounded-md border border-signal-red/35 bg-signal-red/8 p-2.5">
        <WarningCircle size={15} aria-hidden className="mt-px shrink-0 text-signal-red" />
        <p className="text-[13px] leading-relaxed text-foreground/90">
          {note.error ?? 'The agent failed without saying why.'}
        </p>
      </div>
    </div>
  )
}

function NoteHeader({ note }: { note: SchoolNote }) {
  const written = relativeTime(note.created_at)

  return (
    <div className="flex items-start gap-3 px-3 py-2.5">
      {/* The user's own sentence, kept as they typed it, line breaks included. */}
      <p className="min-w-0 flex-1 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
        {note.text}
      </p>
      <div className="flex shrink-0 items-center gap-2">
        {written ? <span className="num text-[13px] text-muted-foreground">{written}</span> : null}
        <Badge variant="outline" className={cn(SCHOOL_BADGE, NOTE_STATUS_TONE[note.status])}>
          {NOTE_STATUS_LABEL[note.status]}
        </Badge>
      </div>
    </div>
  )
}

/** One note in any of its five states. Discarded notes collapse and dim to `opacity-55`; notes are never deleted. */
export function NoteCard({ note }: { note: SchoolNote }) {
  const discarded = note.status === 'discarded'

  return (
    <Panel
      className={cn(
        'transition-opacity duration-150',
        discarded && 'opacity-55 hover:opacity-100',
      )}
    >
      <NoteHeader note={note} />
      {note.status === 'running' ? <RunningBody note={note} /> : null}
      {note.status === 'proposed' ? <ProposedBody note={note} /> : null}
      {note.status === 'applied' ? <AppliedBody note={note} /> : null}
      {note.status === 'failed' ? <FailedBody note={note} /> : null}
    </Panel>
  )
}

/** The list's loading state: the same cards, at the same geometry, unfilled. */
export function NotesSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: 3 }, (_, index) => (
        <Panel key={index}>
          <div className="flex items-start gap-3 px-3 py-2.5">
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-5 w-20 shrink-0 rounded-sm" />
          </div>
          <div className="flex flex-col gap-2 border-t border-border px-3 py-3">
            <Skeleton className="h-3.5 w-[70%]" />
            <Skeleton className="h-3.5 w-[52%]" />
          </div>
        </Panel>
      ))}
    </div>
  )
}
