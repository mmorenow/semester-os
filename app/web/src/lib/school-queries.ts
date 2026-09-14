import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, buildQuery } from './api'
import { activityMeta } from './activity'
import { EXTERNAL_SOURCES, describeGcalError, gcalTargetLabel } from './school-labels'
import type {
  Announcement,
  Course,
  AnnouncementsResponse,
  Assignment,
  AssignmentPatch,
  AssignmentStatus,
  AssignmentsResponse,
  CourseDetail,
  CoursesResponse,
  CreateNoteBody,
  CreateTodoBody,
  ExternalEventsResponse,
  ExternalSource,
  GcalSyncResponse,
  GcalTargetResult,
  IcsSyncResponse,
  Projection,
  ScheduleResponse,
  SchoolNote,
  SchoolNotesResponse,
  SyncStatus,
  Todo,
  TodoPatch,
  TodosResponse,
} from './school-types'
import { gcalTargetResults, isNoteRunning } from './school-types'

export const schoolKeys = {
  courses: ['school', 'courses'] as const,
  course: (id: number) => ['school', 'course', id] as const,
  projection: (courseId: number, target: number) => ['school', 'projection', courseId, target] as const,
  schedule: (start: string, end: string) => ['school', 'schedule', start, end] as const,
  externalEvents: (start: string, end: string) => ['school', 'external-events', start, end] as const,
  syncStatus: ['school', 'sync-status'] as const,
  assignments: (params: AssignmentsQuery) => ['school', 'assignments', params] as const,
  announcements: (courseId: number | undefined) => ['school', 'announcements', courseId ?? null] as const,
  todos: ['school', 'todos'] as const,
  notes: ['school', 'notes'] as const,
}

export interface AssignmentsQuery {
  course_id?: number
  status?: AssignmentStatus
}

/** All queries are `retry: false`: a server without School endpoints 404s, and panels should show that immediately. */

export function useCourses() {
  return useQuery({
    queryKey: schoolKeys.courses,
    queryFn: async () => (await apiRequest<CoursesResponse>('/api/school/courses')).courses,
    retry: false,
    // The semester's shape barely changes inside a session.
    staleTime: 5 * 60_000,
  })
}

/** One course with `grade_summary`, which only this endpoint computes. */
export function useCourse(id: number | null) {
  return useQuery({
    queryKey: schoolKeys.course(id ?? 0),
    queryFn: () => apiRequest<CourseDetail>(`/api/school/courses/${String(id)}`),
    enabled: id !== null,
    retry: false,
    staleTime: 60_000,
  })
}

/**
 * Grade summaries for several courses, keyed by id, so the index shows the server's `current_avg_pct`
 * instead of a local average. Shares a cache key with `useCourse`.
 */
export function useCourseSummaries(courses: Course[] | undefined) {
  return useQueries({
    queries: (courses ?? []).map((course) => ({
      queryKey: schoolKeys.course(course.id),
      queryFn: () => apiRequest<CourseDetail>(`/api/school/courses/${String(course.id)}`),
      retry: false,
      staleTime: 60_000,
    })),
    combine: (results) => {
      const byId = new Map<number, CourseDetail>()
      for (const result of results) {
        if (result.data) byId.set(result.data.id, result.data)
      }
      return { byId, isPending: results.some((result) => result.isPending) }
    },
  })
}

/** What a target grade still requires. Computed server-side so there's one formula, aware of unmapped categories. */
export function useProjection(courseId: number | null, targetPct: number | null) {
  return useQuery({
    queryKey: schoolKeys.projection(courseId ?? 0, targetPct ?? 0),
    queryFn: () =>
      apiRequest<Projection>(
        `/api/school/projection${buildQuery({ course_id: courseId, target_pct: targetPct })}`,
      ),
    enabled: courseId !== null && targetPct !== null,
    retry: false,
    staleTime: 60_000,
  })
}

/** Events for one visible range, inclusive of both ends. */
export function useSchedule(start: string, end: string, enabled = true) {
  return useQuery({
    queryKey: schoolKeys.schedule(start, end),
    queryFn: async () =>
      (await apiRequest<ScheduleResponse>(`/api/school/schedule${buildQuery({ start, end })}`)).events,
    enabled,
    retry: false,
    staleTime: 60_000,
    // Keep the previous week while paging so the grid doesn't blank.
    placeholderData: (previous) => previous,
  })
}

/**
 * External feed events for a range, cached like `useSchedule` so paging doesn't blank half the grid.
 * `enabled` is how the External toggle turns the layer off.
 */
export function useExternalEvents(start: string, end: string, enabled = true) {
  return useQuery({
    queryKey: schoolKeys.externalEvents(start, end),
    queryFn: async () =>
      (
        await apiRequest<ExternalEventsResponse>(
          `/api/school/external-events${buildQuery({ start, end })}`,
        )
      ).events,
    enabled,
    retry: false,
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  })
}

/** When each external feed last ran and whether it succeeded; backs the sync badge. */
export function useSyncStatus(enabled = true) {
  return useQuery({
    queryKey: schoolKeys.syncStatus,
    queryFn: () => apiRequest<SyncStatus>('/api/school/sync/status'),
    enabled,
    retry: false,
    staleTime: 60_000,
    // The one School read that refetches on focus: Google's weekly sign-in expires in background tabs.
    refetchOnWindowFocus: true,
  })
}

/** One feed that came back with a problem, in the server's own words. */
export interface SyncFailure {
  source: ExternalSource
  error: string
  /** The Google connection itself failed. The toast offers Reconnect, since pressing Sync again won't help. */
  disconnected?: boolean
}

/** What one press of Sync now actually did, feed by feed. */
export interface SyncOutcome {
  /** The feeds that ran, in the order they ran. Unconfigured feeds are absent. */
  ran: ExternalSource[]
  /** The ones that reported a failure. Always a subset of `ran`, or Google. */
  failed: SyncFailure[]
  /** The Google run's own figures, one line per target that changed anything. */
  googleDetail: string[]
}

const UNSTATED = 'The server did not say why.'

function reason(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

/** `3 created, 1 updated`, from whichever counts the server published. */
function countsPhrase(result: GcalTargetResult): string | null {
  const parts: string[] = []
  for (const key of ['created', 'updated', 'removed'] as const) {
    const value = result[key]
    if (typeof value === 'number' && value > 0) parts.push(`${String(value)} ${key}`)
  }
  return parts.length > 0 ? parts.join(', ') : null
}

/** One Google run, read generically: failures by target name, successes by their counts. `skipped` targets say nothing. */
export interface GcalRunSummary {
  failures: { target: string; error: string }[]
  detail: string[]
}

export function summarizeGcalRun(response: GcalSyncResponse): GcalRunSummary {
  const failures: GcalRunSummary['failures'] = []
  const detail: string[] = []
  for (const [target, result] of gcalTargetResults(response)) {
    if (result.ok === false) {
      failures.push({ target, error: result.error ?? UNSTATED })
      continue
    }
    if (result.skipped) continue
    const phrase = countsPhrase(result)
    if (phrase) detail.push(`${gcalTargetLabel(target)}: ${phrase}`)
  }
  return { failures, detail }
}

/** Several target failures as one reason line: `Deadlines: ... Events: ...`. */
export function gcalFailureText(failures: GcalRunSummary['failures']): string {
  if (failures.length === 1) return describeGcalError(failures[0].error) ?? failures[0].error
  return failures
    .map((entry) => `${gcalTargetLabel(entry.target)}: ${describeGcalError(entry.error) ?? entry.error}`)
    .join(' ')
}

/**
 * Read every configured calendar feed now. Sequential: the Google leg depends on the connection
 * status, and its pull reconciles against the `external_events` the ICS run wrote.
 *
 * Google is called with no body so the server's default targets apply. Per-feed failures are
 * returned, not thrown; only an unreachable server throws. The Google leg is caught separately so it
 * can't swallow a successful ICS run. A set-up but disconnected account counts as a failure, not a skip.
 */
async function runSync(): Promise<SyncOutcome> {
  const ran: ExternalSource[] = []
  const failed: SyncFailure[] = []
  let googleDetail: string[] = []

  const ics = await apiRequest<IcsSyncResponse>('/api/school/sync/ics', { method: 'POST' })
  for (const source of EXTERNAL_SOURCES) {
    // Google's row here is its pull state, owned by the Google leg below.
    if (source === 'gcal') continue
    const entry = ics[source]
    // Not owned by this endpoint, or no URL configured: nothing to report.
    if (!entry || entry.configured === false) continue
    ran.push(source)
    if (entry.ok === false) failed.push({ source, error: entry.error ?? UNSTATED })
  }

  let google = false
  try {
    const status = await apiRequest<SyncStatus>('/api/school/sync/status')
    google = status.gcal?.configured === true && status.gcal.connected === true
    if (status.gcal?.configured === true && status.gcal.connected !== true) {
      failed.push({
        source: 'gcal',
        error: describeGcalError(status.gcal.error) ?? 'Google Calendar is not connected.',
        disconnected: true,
      })
    }
  } catch (error: unknown) {
    // Can't tell whether Google should have run; report that rather than a clean sync.
    failed.push({
      source: 'gcal',
      error: reason(error, 'The server did not say whether Google is connected.'),
    })
  }

  if (google) {
    ran.push('gcal')
    try {
      const answer = await apiRequest<GcalSyncResponse>('/api/school/gcal/sync', { method: 'POST' })
      const summary = summarizeGcalRun(answer)
      googleDetail = summary.detail
      if (summary.failures.length > 0) {
        failed.push({
          source: 'gcal',
          error: gcalFailureText(summary.failures),
          disconnected: summary.failures.some((entry) => /invalid_grant/i.test(entry.error)),
        })
      }
    } catch (error: unknown) {
      failed.push({ source: 'gcal', error: reason(error, UNSTATED) })
    }
  }

  return { ran, failed, googleDetail }
}

function invalidateCalendar(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({ queryKey: ['school', 'external-events'] })
  void client.invalidateQueries({ queryKey: ['school', 'schedule'] })
  void client.invalidateQueries({ queryKey: schoolKeys.syncStatus })
}

/** Manual sync. Invalidates `onSettled`, not `onSuccess`: a partial failure still moved data and the badge must turn red. */
export function useSyncNow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: runSync,
    // Shows in the activity bar; the button still owns the outcome toast, which has per-feed detail.
    meta: activityMeta('Calendar sync', 'sync'),
    onSettled: () => {
      // The schedule is re-read too because the grid draws both from one window.
      invalidateCalendar(client)
    },
  })
}

/** Google alone, default targets. Run after a reconnect so the dead-token days catch up now. */
export function useGcalSync() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      summarizeGcalRun(await apiRequest<GcalSyncResponse>('/api/school/gcal/sync', { method: 'POST' })),
    meta: activityMeta('Google Calendar sync', 'sync'),
    onSettled: () => {
      invalidateCalendar(client)
    },
  })
}

/** Re-read the connection and return the fresh status, so a consent return can quote Google's current reason. */
export async function refreshSyncStatus(client: ReturnType<typeof useQueryClient>): Promise<SyncStatus | null> {
  await client.invalidateQueries({ queryKey: schoolKeys.syncStatus })
  try {
    return await client.fetchQuery({
      queryKey: schoolKeys.syncStatus,
      queryFn: () => apiRequest<SyncStatus>('/api/school/sync/status'),
      staleTime: 0,
      retry: false,
    })
  } catch {
    return null
  }
}

export function useAssignments(params: AssignmentsQuery = {}) {
  return useQuery({
    queryKey: schoolKeys.assignments(params),
    queryFn: async () =>
      (await apiRequest<AssignmentsResponse>(`/api/school/assignments${buildQuery({ ...params })}`))
        .assignments,
    retry: false,
    staleTime: 60_000,
  })
}

/** One assignment. The drawer needs this because only the detail carries `notes`. */
export function useAssignment(id: number | null) {
  return useQuery({
    queryKey: ['school', 'assignment', id ?? 0] as const,
    queryFn: () => apiRequest<Assignment>(`/api/school/assignments/${String(id)}`),
    enabled: id !== null,
    retry: false,
    staleTime: 30_000,
  })
}

/**
 * Update an assignment's status, grade or note. Optimistic, rolled back on failure. A grade change
 * also invalidates the course, since `grade_summary` is computed server-side.
 */
export function useUpdateAssignment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: AssignmentPatch }) =>
      apiRequest<Assignment>(`/api/school/assignments/${String(id)}`, { method: 'PATCH', body: patch }),
    onMutate: async ({ id, patch }) => {
      await client.cancelQueries({ queryKey: ['school', 'assignments'] })
      const previous = client.getQueriesData<Assignment[]>({ queryKey: ['school', 'assignments'] })
      client.setQueriesData<Assignment[]>({ queryKey: ['school', 'assignments'] }, (old) =>
        old?.map((assignment) => (assignment.id === id ? { ...assignment, ...patch } : assignment)),
      )
      return { previous }
    },
    onError: (_error, _variables, context) => {
      for (const [key, data] of context?.previous ?? []) {
        client.setQueryData(key, data)
      }
    },
    onSettled: (_data, _error, variables) => {
      void client.invalidateQueries({ queryKey: ['school', 'assignments'] })
      void client.invalidateQueries({ queryKey: ['school', 'assignment', variables.id] })
      if ('grade_points' in variables.patch || 'grade_max' in variables.patch) {
        void client.invalidateQueries({ queryKey: ['school', 'course'] })
        void client.invalidateQueries({ queryKey: ['school', 'projection'] })
      }
    },
  })
}

/** Course announcements, newest first. Idle without a course id. */
export function useAnnouncements(courseId: number | undefined) {
  return useQuery({
    queryKey: schoolKeys.announcements(courseId),
    queryFn: async () =>
      (
        await apiRequest<AnnouncementsResponse>(
          `/api/school/announcements${buildQuery({ course_id: courseId })}`,
        )
      ).announcements,
    enabled: courseId !== undefined,
    retry: false,
    staleTime: 60_000,
  })
}

/** Optimistic, so marking read feels instant. */
export function useMarkAnnouncementSeen(courseId: number | undefined) {
  const client = useQueryClient()
  const key = schoolKeys.announcements(courseId)
  return useMutation({
    mutationFn: ({ id, seen }: { id: number; seen: boolean }) =>
      apiRequest<Announcement>(`/api/school/announcements/${String(id)}`, {
        method: 'PATCH',
        body: { seen },
      }),
    onMutate: async ({ id, seen }) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<Announcement[]>(key)
      client.setQueryData<Announcement[]>(key, (old) =>
        old?.map((item) => (item.id === id ? { ...item, seen: seen ? 1 : 0 } : item)),
      )
      return { previous }
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key })
    },
  })
}

export function useTodos() {
  return useQuery({
    queryKey: schoolKeys.todos,
    queryFn: async () => (await apiRequest<TodosResponse>('/api/school/todos')).todos,
    retry: false,
    staleTime: 30_000,
  })
}

/** Pessimistic: the server assigns the id, so the input clears on success. */
export function useCreateTodo() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateTodoBody) =>
      apiRequest<Todo>('/api/school/todos', { method: 'POST', body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: schoolKeys.todos })
    },
  })
}

/** Optimistic, so the checkbox responds instantly. */
export function useUpdateTodo() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: TodoPatch }) =>
      apiRequest<Todo>(`/api/school/todos/${String(id)}`, { method: 'PATCH', body: patch }),
    onMutate: async ({ id, patch }) => {
      await client.cancelQueries({ queryKey: schoolKeys.todos })
      const previous = client.getQueryData<Todo[]>(schoolKeys.todos)
      client.setQueryData<Todo[]>(schoolKeys.todos, (old) =>
        old?.map((todo) => (todo.id === id ? { ...todo, ...patch } : todo)),
      )
      return { previous }
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) client.setQueryData(schoolKeys.todos, context.previous)
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: schoolKeys.todos })
    },
  })
}

/** The interval the list polls at while an agent is still reading a note. */
const NOTE_POLL_MS = 2000

/**
 * Every note, newest first. The agent answers into the row, so this list is how a proposal shows up:
 * it polls every 2s while a note is `running`, stops otherwise, and never polls in a background tab.
 */
export function useSchoolNotes() {
  return useQuery({
    queryKey: schoolKeys.notes,
    queryFn: async () => (await apiRequest<SchoolNotesResponse>('/api/school/notes')).notes,
    retry: false,
    refetchInterval: (query) => (query.state.data?.some(isNoteRunning) ? NOTE_POLL_MS : false),
    refetchIntervalInBackground: false,
    // Re-read on focus; a settled list costs one local request.
    staleTime: 0,
  })
}

/**
 * Write a note and start the agent. Pessimistic (the server assigns id and status); the returned row
 * is seeded into the list so the running card appears immediately. Tagged as a run.
 */
export function useCreateSchoolNote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateNoteBody) =>
      apiRequest<SchoolNote>('/api/school/notes', { method: 'POST', body }),
    meta: activityMeta('Note agent', 'run'),
    onSuccess: (note) => {
      client.setQueryData<SchoolNote[]>(schoolKeys.notes, (old) => (old ? [note, ...old] : [note]))
      void client.invalidateQueries({ queryKey: schoolKeys.notes })
      // The started run is what the activity bar and completion toast watch.
      void client.invalidateQueries({ queryKey: ['actions'] })
    },
  })
}

/**
 * Confirm a proposal; the server does the writing. Re-reads everything it can touch (assignments,
 * todos, events, standings, Google). `onSettled` because a partial apply still moved rows.
 */
export function useApplySchoolNote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiRequest<SchoolNote>(`/api/school/notes/${String(id)}/apply`, { method: 'POST' }),
    meta: activityMeta('Applying note', 'write'),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: schoolKeys.notes })
      void client.invalidateQueries({ queryKey: ['school', 'assignments'] })
      void client.invalidateQueries({ queryKey: schoolKeys.todos })
      // `grade_summary` is server-computed, so new graded items change standings.
      void client.invalidateQueries({ queryKey: ['school', 'course'] })
      // Applied notes may create, move or cancel events and push them to Google.
      void client.invalidateQueries({ queryKey: ['school', 'external-events'] })
      void client.invalidateQueries({ queryKey: schoolKeys.syncStatus })
    },
  })
}

/** Discard a proposal. Nothing is written or deleted; the note stays in the history, dimmed. */
export function useDiscardSchoolNote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiRequest<SchoolNote>(`/api/school/notes/${String(id)}/discard`, { method: 'POST' }),
    meta: activityMeta('Discarding note', 'write'),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: schoolKeys.notes })
    },
  })
}
