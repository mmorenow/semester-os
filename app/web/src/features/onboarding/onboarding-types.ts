import type { MeetingKind } from '@/lib/school-types'

/** Shapes of /api/onboarding/*. The server owns these vocabularies; unknown values still render. */

export type SourceKind = 'file' | 'url' | 'manual'
export type SourceStatus = 'queued' | 'reading' | 'proposed' | 'failed' | 'applied' | 'discarded'
export type ProposalDay = 'M' | 'T' | 'W' | 'R' | 'F' | 'S' | 'U'
export type ProposalAssignmentKind = 'hw' | 'quiz' | 'exam' | 'project' | 'reading' | 'other'
export type ProposalPlatform = 'brightspace' | 'gradescope' | 'ed' | 'website' | 'other'

export interface ProposalMeeting {
  kind: MeetingKind | null
  days: ProposalDay[]
  start_time: string | null
  duration_min: number | null
  location: string | null
  start_date: string | null
  end_date: string | null
  crn: string | null
}

export interface ProposalPlatformEntry {
  platform: ProposalPlatform
  name: string | null
  url: string | null
  notes: string | null
}

export interface ProposalAssignment {
  title: string | null
  kind: ProposalAssignmentKind | null
  category: string | null
  due_date: string | null
  due_time: string | null
  /** When a block (an exam) ends, 24 hour `HH:MM` on the due date. */
  end_time: string | null
  /** Where a block happens: the exam room. */
  location: string | null
  points: number | null
  weight_pct: number | null
  notes: string | null
}

export interface Uncertainty {
  /** A key path: `course_title`, `meetings[0].location`, `assignments[3].due_date`. */
  field: string
  reason: string
}

/** The course-notes document, exactly the keys the server accepts. */
export interface Proposal {
  course_code: string | null
  course_title: string | null
  credit_hours: number | null
  term: string | null
  instructors: string[]
  meetings: ProposalMeeting[]
  platforms: ProposalPlatformEntry[]
  grading_weights_pct: Record<string, number>
  total_points: number | null
  grading_scale: string | null
  drop_rules: string | null
  late_policy: string | null
  ai_policy: string | null
  attendance_policy: string | null
  regrade_policy: string | null
  assignments: ProposalAssignment[]
  uncertain: Uncertainty[]
}

/** Something that blocks Confirm (a problem) or only deserves a look (a warning). */
export interface FieldMessage {
  field: string
  message: string
}

export interface VerdictCounts {
  created: number
  updated: number
  unchanged: number
  kept: number
}

export interface AppliedChanges {
  courses: VerdictCounts
  meetings: VerdictCounts
  platforms: VerdictCounts
  grading_scheme: VerdictCounts
  assignments: VerdictCounts
  /** One sentence per value left alone because the student changed it by hand. */
  kept: string[]
  course_ids: number[]
}

export interface SyllabusSource {
  id: number
  kind: SourceKind
  origin: string
  name: string
  path: string | null
  url: string | null
  size_bytes: number | null
  missing: boolean
  status: SourceStatus
  action_id: number | null
  action: {
    id: number
    status: string
    error: string | null
    created_at: string | null
    started_at: string | null
    finished_at: string | null
  } | null
  proposal: Proposal | null
  commentary: string | null
  problems: FieldMessage[]
  warnings: FieldMessage[]
  existing_course: { id: number; code: string; title: string; color: string | null } | null
  applied_course_id: number | null
  applied_changes: AppliedChanges | null
  error: string | null
  created_at: string | null
  updated_at: string | null
  read_started_at: string | null
  resolved_at: string | null
  edited_at: string | null
  applied_at: string | null
}

export interface SourcesResponse {
  sources: SyllabusSource[]
  /** What the folder holds that cannot be read, and why. */
  skipped: { name: string; reason: string }[]
  folder: string
  course_count: number
  supported_extensions: string[]
  max_upload_bytes: number
}

export function isReading(source: Pick<SyllabusSource, 'status'>): boolean {
  return source.status === 'reading'
}
