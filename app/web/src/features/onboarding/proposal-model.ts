import type {
  FieldMessage,
  Proposal,
  ProposalAssignment,
  ProposalDay,
  ProposalMeeting,
  SourceStatus,
} from './onboarding-types'

/** Pure helpers that keep the review draft coherent between saves, e.g. flags follow removed items. */

export const DAYS: { code: ProposalDay; short: string; long: string }[] = [
  { code: 'M', short: 'Mon', long: 'Monday' },
  { code: 'T', short: 'Tue', long: 'Tuesday' },
  { code: 'W', short: 'Wed', long: 'Wednesday' },
  { code: 'R', short: 'Thu', long: 'Thursday' },
  { code: 'F', short: 'Fri', long: 'Friday' },
  { code: 'S', short: 'Sat', long: 'Saturday' },
  { code: 'U', short: 'Sun', long: 'Sunday' },
]

export const ASSIGNMENT_KIND_LABEL: Record<string, string> = {
  hw: 'Homework',
  quiz: 'Quiz',
  exam: 'Exam',
  project: 'Project',
  reading: 'Reading',
  other: 'Other',
}

export const PLATFORM_LABEL: Record<string, string> = {
  brightspace: 'Brightspace',
  gradescope: 'Gradescope',
  ed: 'Ed',
  website: 'Course website',
  other: 'Other',
}

export const SOURCE_STATUS_LABEL: Record<SourceStatus, string> = {
  queued: 'Not read yet',
  reading: 'Reading',
  proposed: 'Ready to review',
  failed: 'Failed',
  applied: 'Added',
  discarded: 'Discarded',
}

/** Same ramp as Notes: accent for a live agent, signals for outcomes, ink when waiting on the student. */
export const SOURCE_STATUS_TONE: Record<SourceStatus, string> = {
  queued: 'text-muted-foreground border-border',
  reading: 'text-primary border-primary/45',
  proposed: 'text-foreground border-input',
  failed: 'text-signal-red border-signal-red/45',
  applied: 'text-signal-green border-signal-green/45',
  discarded: 'text-muted-foreground border-border',
}

export function emptyMeeting(): ProposalMeeting {
  return {
    kind: 'lecture',
    days: [],
    start_time: null,
    duration_min: null,
    location: null,
    start_date: null,
    end_date: null,
    crn: null,
  }
}

export function emptyAssignment(): ProposalAssignment {
  return {
    title: null,
    kind: 'hw',
    category: null,
    due_date: null,
    due_time: null,
    end_time: null,
    location: null,
    points: null,
    weight_pct: null,
    notes: null,
  }
}

export function uncertaintyFor(proposal: Proposal, field: string): string | undefined {
  return proposal.uncertain.find((entry) => entry.field === field)?.reason
}

export function messageFor(messages: FieldMessage[], field: string): string | undefined {
  return messages.find((entry) => entry.field === field)?.message
}

/** The student looked at a flagged value (edited it, or said it is right). */
export function clearUncertainty(proposal: Proposal, field: string): Proposal {
  if (!proposal.uncertain.some((entry) => entry.field === field)) return proposal
  return { ...proposal, uncertain: proposal.uncertain.filter((entry) => entry.field !== field) }
}

/** Set one top-level value, clearing its flag. */
export function setField<K extends keyof Proposal>(proposal: Proposal, key: K, value: Proposal[K]): Proposal {
  return clearUncertainty({ ...proposal, [key]: value }, String(key))
}

type ListKey = 'meetings' | 'assignments'

/** Set one field of one list item, clearing that field's flag. */
export function setItemField<L extends ListKey, F extends keyof Proposal[L][number]>(
  proposal: Proposal,
  list: L,
  index: number,
  field: F,
  value: Proposal[L][number][F],
): Proposal {
  const items = proposal[list].map((item, position) => (position === index ? { ...item, [field]: value } : item))
  return clearUncertainty({ ...proposal, [list]: items } as Proposal, `${list}[${String(index)}].${String(field)}`)
}

export function addItem(proposal: Proposal, list: ListKey): Proposal {
  if (list === 'meetings') return { ...proposal, meetings: [...proposal.meetings, emptyMeeting()] }
  return { ...proposal, assignments: [...proposal.assignments, emptyAssignment()] }
}

const INDEXED = /^(meetings|assignments)\[(\d+)\](.*)$/

/** Remove an item: drop its flags and shift later items' flags down one index. */
export function removeItem(proposal: Proposal, list: ListKey, index: number): Proposal {
  const items = proposal[list].filter((_, position) => position !== index)
  const uncertain = proposal.uncertain.flatMap((entry) => {
    const match = INDEXED.exec(entry.field)
    if (!match || match[1] !== list) return [entry]
    const position = Number(match[2])
    if (position === index) return []
    if (position < index) return [entry]
    return [{ ...entry, field: `${list}[${String(position - 1)}]${match[3]}` }]
  })
  return { ...proposal, [list]: items, uncertain } as Proposal
}

/** Weights as an ordered list of rows, because an object cannot hold an empty name mid-edit. */
export interface WeightRow {
  name: string
  pct: number | null
}

export function weightRows(proposal: Proposal): WeightRow[] {
  return Object.entries(proposal.grading_weights_pct).map(([name, pct]) => ({ name, pct }))
}

/** Rows back into the object the server takes. A row with no name or no number is left out until finished. */
export function weightsFromRows(rows: WeightRow[]): Record<string, number> {
  const weights: Record<string, number> = {}
  for (const row of rows) {
    const name = row.name.trim()
    if (name && row.pct !== null && Number.isFinite(row.pct) && !(name in weights)) weights[name] = row.pct
  }
  return weights
}

export function weightsTotal(rows: WeightRow[]): number {
  return rows.reduce((total, row) => total + (row.pct !== null && Number.isFinite(row.pct) ? row.pct : 0), 0)
}

/** An input's text as a number or null. Empty is null, never zero. */
export function parseNumber(text: string): number | null {
  if (text.trim() === '') return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

/** An input's text as a string or null. */
export function textOrNull(text: string): string | null {
  return text.trim() === '' ? null : text
}

/** How many flags and blockers the draft carries, for the sheet footer. */
export function reviewCounts(proposal: Proposal, problems: FieldMessage[]): { check: number; fix: number } {
  return { check: proposal.uncertain.length, fix: problems.length }
}
