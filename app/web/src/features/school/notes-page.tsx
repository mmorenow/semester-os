import { useState } from 'react'
import { NotePencil, TerminalWindow, WarningCircle } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { EmptyState } from '@/components/empty-state'
import { useHealth } from '@/lib/queries'
import { useCreateSchoolNote, useSchoolNotes, useSyncStatus } from '@/lib/school-queries'
import { isNoteRunning } from '@/lib/school-types'
import { GcalStatusLine } from './gcal-connection'
import { NoteCard, NotesSkeleton } from './note-card'
import { Panel } from './school-parts'

/** Composer. Cmd/Ctrl+Enter submits. The field clears when the server has the note, so a failed submit keeps the text. */
function NoteComposer({ agentAvailable }: { agentAvailable: boolean }) {
  const createNote = useCreateSchoolNote()
  const [text, setText] = useState('')

  const trimmed = text.trim()
  const canSubmit = agentAvailable && trimmed !== '' && !createNote.isPending

  function submit() {
    if (!canSubmit) return
    createNote.mutate(
      { text: trimmed },
      {
        onSuccess: () => {
          // No success toast: the running card appears in the same frame.
          setText('')
        },
        onError: (error: unknown) => {
          toast.error('Could not send the note', {
            description: error instanceof Error ? error.message : 'The server rejected the request.',
          })
        },
      },
    )
  }

  return (
    <Panel>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <div className="p-3">
          <label htmlFor="school-note" className="sr-only">
            New note
          </label>
          <Textarea
            id="school-note"
            value={text}
            onChange={(event) => { setText(event.target.value) }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault()
                submit()
              }
            }}
            placeholder="The crypto hw2 moved to Friday"
            className="min-h-20 resize-none text-sm"
          />
        </div>

        <div className="flex items-center gap-3 border-t border-border bg-muted/40 px-3 py-2">
          <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-muted-foreground">
            Describe a change in plain words - the agent turns it into assignments, exams, todos and
            calendar events for your review.
          </p>
          <span className="num hidden shrink-0 text-xs text-muted-foreground sm:inline" aria-hidden>
            Cmd + Enter
          </span>
          <Button
            type="submit"
            size="sm"
            disabled={!canSubmit}
            title={agentAvailable ? undefined : 'Install the Claude Code CLI to send notes'}
            aria-busy={createNote.isPending || undefined}
            aria-keyshortcuts="Meta+Enter Control+Enter"
          >
            {createNote.isPending ? 'Sending' : 'Apply'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}

/**
 * Shown when this machine lacks the Claude Code CLI, which only Notes needs. The composer stays
 * visible but disabled; the server refuses the POST with the same instructions.
 */
function AgentMissingNotice() {
  return (
    <Alert variant="warning">
      <TerminalWindow />
      <AlertTitle>Notes need the Claude Code CLI</AlertTitle>
      <AlertDescription className="text-[13px] leading-relaxed text-muted-foreground">
        The agent that reads a note runs through the <code className="font-mono text-foreground">claude</code>{' '}
        command, and it is not installed on this machine. Install Claude Code, run{' '}
        <code className="font-mono text-foreground">claude</code> once to sign in, then restart Semester OS.
        Courses, the week, assignments, grades and todos all work without it.
      </AlertDescription>
    </Alert>
  )
}

/** Composer plus the full history. Nothing is ever deleted; discarded notes stay, dimmed. */
export function SchoolNotesPage() {
  const notes = useSchoolNotes()
  const syncStatus = useSyncStatus()
  const health = useHealth()
  // Unknown while health loads counts as available, so the notice never flashes.
  const agentAvailable = health.data?.claude_cli !== false
  const rows = notes.data ?? []
  const running = rows.filter(isNoteRunning).length

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">Notes</h1>
          <p className="lede text-muted-foreground">
            What changed, in your own words. The agent proposes, you decide what gets written.
          </p>
        </div>
        {/* Notes writes to the calendar, so it names the account. */}
        <GcalStatusLine status={syncStatus.data} align="end" />
      </header>

      {agentAvailable ? null : <AgentMissingNotice />}

      <NoteComposer agentAvailable={agentAvailable} />

      <section className="flex flex-col gap-2">
        <div className="flex h-6 items-center gap-2">
          <h2 className="section-title text-foreground">History</h2>
          {rows.length > 0 ? (
            <span className="text-[13px] text-muted-foreground">
              <span className="num">{String(rows.length)}</span>
              {rows.length === 1 ? ' note' : ' notes'}
              {running > 0 ? (
                <>
                  {', '}
                  <span className="num">{String(running)}</span> running
                </>
              ) : null}
            </span>
          ) : null}
        </div>

        {notes.isPending ? (
          <NotesSkeleton />
        ) : notes.isError ? (
          <Panel>
            <EmptyState
              size="inline"
              icon={WarningCircle}
              title="Could not load notes"
              description="The notes endpoint did not respond. Check that the Semester OS server is still running."
              action={
                <Button size="sm" variant="outline" onClick={() => void notes.refetch()}>
                  Try again
                </Button>
              }
            />
          </Panel>
        ) : rows.length === 0 ? (
          <Panel>
            <EmptyState
              size="inline"
              icon={NotePencil}
              title="No notes yet"
              description="Write what changed above. The agent reads it and proposes the assignments, exams, todos and events it would create."
            />
          </Panel>
        ) : (
          <div className="flex flex-col gap-3">
            {rows.map((note) => (
              <NoteCard key={note.id} note={note} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
