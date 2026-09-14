import type { AssignmentStatus, ExternalSource, MeetingKind, NoteOpKind, NoteStatus } from './school-types'

export const MEETING_KIND_LABEL: Record<MeetingKind, string> = {
  lecture: 'Lecture',
  lab: 'Lab',
  pso: 'PSO',
}

/** External calendar labels, also the keys `platformMark` matches. Google is just "Google"; the mark says which. */
export const EXTERNAL_SOURCE_LABEL: Record<ExternalSource, string> = {
  outlook: 'Outlook',
  brightspace: 'Brightspace',
  gcal: 'Google',
  // Named for where they came from; "Events" would read as a fourth product.
  notes: 'Notes',
}

/** Feeds a sync reads. `notes` is absent: this app writes those events, so nothing goes stale. */
export const EXTERNAL_SOURCES: ExternalSource[] = ['outlook', 'brightspace', 'gcal']

/** Names in a sentence: `Outlook`, `Outlook and Brightspace`, `Outlook, Brightspace and Google`. */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** Every status, in the order the work moves through them. */
export const ASSIGNMENT_STATUSES: AssignmentStatus[] = [
  'pending',
  'in_progress',
  'submitted',
  'graded',
  'dropped',
]

export const ASSIGNMENT_STATUS_LABEL: Record<AssignmentStatus, string> = {
  pending: 'Pending',
  in_progress: 'In progress',
  submitted: 'Submitted',
  graded: 'Graded',
  dropped: 'Dropped',
}

/** Status is colorless: the signal ramp is reserved for due-date urgency, so done items just dim. */
export const ASSIGNMENT_STATUS_TONE: Record<AssignmentStatus, string> = {
  pending: 'text-muted-foreground border-border',
  in_progress: 'text-foreground border-input',
  submitted: 'text-muted-foreground border-border',
  graded: 'text-muted-foreground border-border',
  dropped: 'text-muted-foreground border-border',
}

/** Statuses that take a row out of the queue: shown, dimmed, never hidden. */
export function isSettled(status: AssignmentStatus): boolean {
  return status === 'submitted' || status === 'graded' || status === 'dropped'
}

/** The one status change the panel offers. `label` reads as an action before a title: "Start Homework 3". */
export const NEXT_STATUS: Partial<Record<AssignmentStatus, { to: AssignmentStatus; label: string }>> = {
  pending: { to: 'in_progress', label: 'Start' },
  in_progress: { to: 'submitted', label: 'Mark submitted' },
}

export const NOTE_STATUS_LABEL: Record<NoteStatus, string> = {
  running: 'Reading',
  proposed: 'Needs review',
  applied: 'Applied',
  discarded: 'Discarded',
  failed: 'Failed',
}

/**
 * Notes use run-status tones, unlike the colorless assignment ramp. A proposal awaiting the user
 * stays colorless; the primary button under it already says an action is available.
 */
export const NOTE_STATUS_TONE: Record<NoteStatus, string> = {
  running: 'text-primary border-primary/45',
  proposed: 'text-foreground border-input',
  applied: 'text-signal-green border-signal-green/45',
  discarded: 'text-muted-foreground border-border',
  failed: 'text-signal-red border-signal-red/45',
}

/** Screen reader prefix for each op, so "Cancel event: Office hours, Thu 3p" isn't a bare sentence. */
export const NOTE_OP_LABEL: Record<NoteOpKind, string> = {
  create_assignment: 'New assignment',
  update_assignment: 'Assignment change',
  create_todo: 'New todo',
  update_todo: 'Todo change',
  create_event: 'New event',
  update_event: 'Event change',
  cancel_event: 'Cancel event',
  comment: 'Agent comment',
}

/**
 * Google's error in plain words. `invalid_grant` means the Testing-mode refresh token expired
 * (every 7 days); anything else passes through, trimmed to one sentence.
 */
export function describeGcalError(error: string | null | undefined): string | null {
  const raw = error?.trim()
  if (!raw) return null
  const lower = raw.toLowerCase()
  if (lower.includes('invalid_grant') || lower.includes('expired or revoked')) {
    return 'Google’s weekly sign-in expired.'
  }
  if (lower.includes('access_denied')) return 'Access was declined on the Google consent screen.'
  return raw.length > 220 ? `${raw.slice(0, 218)}…` : raw
}

/** A server target name as a label: `deadlines` reads as `Deadlines`. */
export function gcalTargetLabel(target: string): string {
  const words = target.replace(/[_-]+/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : target
}

/** A `comment` op writes nothing. Everything else is a real write. */
export function opWrites(op: NoteOpKind): boolean {
  return op !== 'comment'
}
