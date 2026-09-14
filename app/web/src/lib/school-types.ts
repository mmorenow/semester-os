/** Types for the School API. Times arrive as 24h `HH:MM` and dates as `YYYY-MM-DD`, local; `lib/school-time.ts` formats them. */

export type MeetingKind = 'lecture' | 'lab' | 'pso'

/** Registrar day letters: R is Thursday and U is Sunday, so every day stays one letter. */
export type DayCode = 'M' | 'T' | 'W' | 'R' | 'F'

export interface CourseMeeting {
  id: number
  kind: MeetingKind
  days: DayCode[]
  /** 24 hour `HH:MM`. */
  start_time: string
  duration_min: number
  location?: string | null
  start_date?: string | null
  end_date?: string | null
  crn?: string | null
}

export interface CoursePlatform {
  id: number
  platform: string
  url?: string | null
  auth_mode?: string | null
  notes?: string | null
  last_synced_at?: string | null
}

/** A course contact. Instructors arrive as objects or bare strings; read them through `readCoursePeople`. */
export interface CoursePerson {
  name: string
  email?: string | null
  role?: string | null
  office?: string | null
  phone?: string | null
  office_hours?: string | null
  note?: string | null
}

export interface Course {
  id: number
  code: string
  title: string
  credit_hours?: number | null
  instructors: (string | CoursePerson)[]
  /** TAs, coordinators, graders. Shape varies by harvester; read defensively. */
  people?: unknown
  term?: string | null
  grading_scheme?: string | Record<string, unknown> | null
  color?: string | null
  meetings: CourseMeeting[]
  platforms: CoursePlatform[]
}

export interface CoursesResponse {
  courses: Course[]
}

/** One grading category. Percentages are points of the final grade, so secured + lost + remaining = `weight_pct`. */
export interface GradeCategory {
  name: string
  weight_pct: number | null
  earned_points: number | null
  earned_max: number | null
  graded_count: number
  pending_count: number
  secured_pct: number | null
  lost_pct: number | null
  remaining_pct: number | null
  /** False when the syllabus states a total but not the per-item split. */
  split_known: boolean
}

export interface GradeOverall {
  current_avg_pct: number | null
  secured_pct: number | null
  lost_pct: number | null
  remaining_pct: number | null
  /** Weight the server could not attach to any category. Shown, never hidden. */
  unallocated_pct: number | null
}

export interface GradeSummary {
  categories: GradeCategory[]
  overall: GradeOverall
}

export interface CourseDetail extends Course {
  grade_summary?: GradeSummary | null
}

/** What the server answers when asked what a target grade would still cost. */
export interface Projection {
  target_pct: number
  secured_pct: number
  remaining_pct: number
  needed_avg_pct: number | null
  feasible: boolean
}

export interface ScheduleEvent {
  meeting_id: number
  course_id: number
  course_code: string
  course_title: string
  kind: MeetingKind
  /** `YYYY-MM-DD`. */
  date: string
  /** 24 hour `HH:MM`. */
  start: string
  /** 24 hour `HH:MM`. */
  end: string
  location?: string | null
}

export interface ScheduleResponse {
  events: ScheduleEvent[]
}

/**
 * Sources in `external_events`: Outlook and Brightspace ICS, the user's Google calendar, and `notes`
 * (one-off events created from a note, stored by the server). Feeds carry no course id; only `notes`
 * may. Maps keyed by this union are `Partial` because older servers omit `gcal`.
 */
export type ExternalSource = 'outlook' | 'brightspace' | 'gcal' | 'notes'

export interface ExternalEvent {
  id: number
  source: ExternalSource
  title: string
  location?: string | null
  /** `YYYY-MM-DD`. */
  date: string
  /** 24 hour `HH:MM`. Equal to `end` for a deadline the feed states as a point. */
  start: string
  end: string
  /** SQLite hands booleans over as 0 or 1. Read it through `isAllDay`. */
  all_day: number | boolean
  is_active?: number | boolean
  /** Only `notes` events carry these. */
  course_id?: number | null
  course_code?: string | null
  notes?: string | null
}

export interface ExternalEventsResponse {
  events: ExternalEvent[]
}

export function isAllDay(event: Pick<ExternalEvent, 'all_day'>): boolean {
  return event.all_day === true || event.all_day === 1
}

/** One ICS feed's last run, as `GET /api/school/sync/status` reports it. */
export interface IcsSourceStatus {
  source?: string
  last_sync_at?: string | null
  ok?: boolean
  error?: string | null
  event_count?: number
  /** False when no URL has been configured for this feed at all. */
  configured?: boolean
}

/** A calendar an earlier version created, which the user can now delete by hand. */
export interface GcalLegacyCalendar {
  summary: string
  id: string
}

/**
 * Google connection from `GET /api/school/gcal/status` (also under `gcal` in sync status). Everything
 * goes to the primary calendar. An expired Testing-mode token shows as `connected: false` with `invalid_grant`.
 */
export interface GcalStatus {
  configured?: boolean
  connected?: boolean
  account_email?: string | null
  last_sync_at?: string | null
  error?: string | null
  calendar_id?: string | null
  legacy_calendars?: GcalLegacyCalendar[]
  redirect_uri?: string | null
}

export interface SyncStatus {
  ics?: Partial<Record<ExternalSource, IcsSourceStatus>>
  gcal?: GcalStatus
}

/** `POST /api/school/sync/ics` response: per-feed state for the feeds this run touched. */
export type IcsSyncResponse = Partial<Record<ExternalSource, IcsSourceStatus>>

/**
 * One Google target's run. `target` is the server's vocabulary (`classes`, `deadlines`, `events`,
 * `pull`, retired `mirror`); the UI never branches on it. Any count may be absent.
 */
export interface GcalTargetResult {
  target?: string
  ok?: boolean
  error?: string | null
  created?: number
  updated?: number
  unchanged?: number
  removed?: number
  /** A retired target's reason for doing nothing. */
  skipped?: string | null
}

/** `POST /api/school/gcal/sync` response. Results are top-level keys, or under `results` on older servers; read via `gcalTargetResults`. */
export type GcalSyncResponse = Record<string, unknown> & {
  results?: Record<string, GcalTargetResult>
}

/** What `POST /api/school/gcal/connect` answers: the consent URL to open. */
export interface GcalConnectResponse {
  auth_url: string
}

function isTargetResult(value: unknown): value is GcalTargetResult {
  return typeof value === 'object' && value !== null && 'ok' in value
}

/** Every reported target as `[name, result]`, in server order. Prefers `results`, else top-level keys that look like results. */
export function gcalTargetResults(response: GcalSyncResponse | null | undefined): [string, GcalTargetResult][] {
  if (!response) return []
  const source: Record<string, unknown> =
    response.results && typeof response.results === 'object' ? response.results : response
  return Object.entries(source).filter((entry): entry is [string, GcalTargetResult] => isTargetResult(entry[1]))
}

export type AssignmentStatus = 'pending' | 'in_progress' | 'submitted' | 'graded' | 'dropped'

export interface Assignment {
  id: number
  course_id: number
  course_code: string
  title: string
  kind?: string | null
  due_at?: string | null
  /** When a timed item ends. Set for exams, where `due_at` is the start. */
  ends_at?: string | null
  /** Where a timed item happens, as the syllabus or the note named it. */
  location?: string | null
  points?: number | null
  weight_pct?: number | null
  grade_points?: number | null
  grade_max?: number | null
  status: AssignmentStatus
  brief_md?: string | null
  url?: string | null
  /** Where the harvester read it, which is also where the work goes back. */
  source?: string | null
  notes?: string | null
  updated_at?: string | null
}

export interface AssignmentsResponse {
  assignments: Assignment[]
}

/** Everything PATCH /api/school/assignments/{id} accepts, all optional. */
export interface AssignmentPatch {
  status?: AssignmentStatus
  grade_points?: number | null
  grade_max?: number | null
  notes?: string | null
}

export interface Announcement {
  id: number
  course_id?: number | null
  course_code?: string | null
  source?: string | null
  title?: string | null
  body_md?: string | null
  url?: string | null
  posted_at?: string | null
  /** SQLite hands booleans over as 0 or 1. Read it through `isSeen`. */
  seen: number | boolean
}

export interface AnnouncementsResponse {
  announcements: Announcement[]
}

export function isSeen(announcement: Pick<Announcement, 'seen'>): boolean {
  return announcement.seen === true || announcement.seen === 1
}

/** True once the server has recorded any grade at all for this item. */
export function hasGrade(assignment: Pick<Assignment, 'grade_points'>): boolean {
  return assignment.grade_points !== null && assignment.grade_points !== undefined
}

export interface Todo {
  id: number
  title: string
  course_id?: number | null
  course_code?: string | null
  assignment_id?: number | null
  due_at?: string | null
  /** SQLite hands booleans over as 0 or 1. Read it through `isDone`. */
  done: number | boolean
  origin?: string | null
  created_at?: string | null
}

export interface TodosResponse {
  todos: Todo[]
}

export function isDone(todo: Pick<Todo, 'done'>): boolean {
  return todo.done === true || todo.done === 1
}

export interface CreateTodoBody {
  title: string
  course_id?: number
  assignment_id?: number
  due_at?: string
}

export interface TodoPatch {
  done?: 0 | 1
  title?: string
  due_at?: string | null
}

// Notes: the user writes a sentence, an agent turns it into a changeset, nothing is written until confirmed.
// Notes are never deleted.

/**
 * Where a note stands.
 *
 *   running    the agent has the note and has not answered yet
 *   proposed   a changeset is waiting for the user to confirm or discard
 *   applied    the changeset was written
 *   discarded  the user threw the changeset away; nothing was written
 *   failed     the agent could not answer, and said why in `error`
 */
export type NoteStatus = 'running' | 'proposed' | 'failed' | 'applied' | 'discarded'

/** What one proposal line does. `comment` writes nothing (the agent explaining itself); `_event` ops also push to Google. */
export type NoteOpKind =
  | 'create_assignment'
  | 'update_assignment'
  | 'create_todo'
  | 'update_todo'
  | 'create_event'
  | 'update_event'
  | 'cancel_event'
  | 'comment'

/** One proposed operation. The UI renders the server's `summary` verbatim and never rephrases it. */
export interface NoteOp {
  op: NoteOpKind
  summary: string
}

/** What the Google Calendar push did, in the server's own words. */
export interface NoteGcal {
  attempted: boolean
  ok: boolean
  detail: string
}

export interface SchoolNote {
  id: number
  text: string
  status: NoteStatus
  /** The agent run behind a `running` note, which the activity system polls. */
  action_id: number | null
  /** Present from `proposed` onwards. Null while the agent is still reading. */
  proposal: NoteOp[] | null
  /** Secondary commentary from the agent, as markdown. Optional, often absent. */
  agent_md: string | null
  /** What applying actually wrote, one English line each. */
  applied_changes: string[] | null
  gcal: NoteGcal | null
  error: string | null
  created_at: string
  /** When the note left `running`, whichever way it left. */
  resolved_at: string | null
  applied_at: string | null
}

export interface SchoolNotesResponse {
  notes: SchoolNote[]
}

export interface CreateNoteBody {
  text: string
}

/** The one status that makes the list poll. */
export function isNoteRunning(note: Pick<SchoolNote, 'status'>): boolean {
  return note.status === 'running'
}
