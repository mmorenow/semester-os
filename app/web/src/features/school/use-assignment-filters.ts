import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { isSettled } from '@/lib/school-labels'
import type { Assignment, AssignmentStatus } from '@/lib/school-types'

/** Explorer state lives in the URL: views are links, Back walks filters, reload restores. */

export type AssignmentSortKey = 'due' | 'weight' | 'course' | 'title' | 'grade'
export type SortDir = 'asc' | 'desc'

export interface AssignmentFilters {
  courseId: number | null
  status: AssignmentStatus | 'open' | ''
  kind: string
  q: string
  sort: AssignmentSortKey
  dir: SortDir
  /** The row the drawer is showing, deep-linked so a task can be sent to itself. */
  assignmentId: number | null
}

const SORT_KEYS: AssignmentSortKey[] = ['due', 'weight', 'course', 'title', 'grade']

const DEFAULTS: AssignmentFilters = {
  courseId: null,
  status: 'open',
  kind: '',
  q: '',
  sort: 'due',
  dir: 'asc',
  assignmentId: null,
}

function readNumber(value: string | null): number | null {
  const parsed = Number(value)
  return value !== null && Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function useAssignmentFilters() {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters = useMemo<AssignmentFilters>(() => {
    const rawSort = searchParams.get('sort')
    return {
      courseId: readNumber(searchParams.get('course')),
      status: (searchParams.get('status') ?? DEFAULTS.status) as AssignmentFilters['status'],
      kind: searchParams.get('kind') ?? DEFAULTS.kind,
      q: searchParams.get('q') ?? DEFAULTS.q,
      sort: SORT_KEYS.includes(rawSort as AssignmentSortKey) ? (rawSort as AssignmentSortKey) : DEFAULTS.sort,
      dir: searchParams.get('dir') === 'desc' ? 'desc' : DEFAULTS.dir,
      assignmentId: readNumber(searchParams.get('assignment')),
    }
  }, [searchParams])

  const setFilters = useCallback(
    (patch: Partial<AssignmentFilters>) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          const merged = { ...filters, ...patch }

          const write = (key: string, value: string, fallback: string) => {
            if (value === fallback) next.delete(key)
            else next.set(key, value)
          }

          write('course', merged.courseId === null ? '' : String(merged.courseId), '')
          write('status', merged.status, DEFAULTS.status)
          write('kind', merged.kind, DEFAULTS.kind)
          write('q', merged.q, DEFAULTS.q)
          write('sort', merged.sort, DEFAULTS.sort)
          write('dir', merged.dir, DEFAULTS.dir)
          write('assignment', merged.assignmentId === null ? '' : String(merged.assignmentId), '')

          return next
        },
        { replace: true },
      )
    },
    [filters, setSearchParams],
  )

  const clearFilters = useCallback(() => {
    setFilters({ courseId: null, status: 'open', kind: '', q: '' })
  }, [setFilters])

  const hasActiveFilters =
    filters.courseId !== null || filters.status !== 'open' || filters.kind !== '' || filters.q !== ''

  return { filters, setFilters, clearFilters, hasActiveFilters }
}

const DUE_LAST = Number.POSITIVE_INFINITY

function dueTime(assignment: Assignment): number {
  if (!assignment.due_at) return DUE_LAST
  const at = new Date(assignment.due_at).getTime()
  return Number.isNaN(at) ? DUE_LAST : at
}

function ratio(assignment: Assignment): number {
  const points = assignment.grade_points
  const max = assignment.grade_max ?? assignment.points
  if (points === null || points === undefined) return -1
  if (max === null || max === undefined || max <= 0) return points
  return (points / max) * 100
}

/** Filter and sort in one place so toolbar counts and table rows always match. */
export function applyAssignmentFilters(
  assignments: Assignment[] | undefined,
  filters: AssignmentFilters,
): Assignment[] {
  const query = filters.q.trim().toLowerCase()

  const rows = (assignments ?? []).filter((row) => {
    if (filters.courseId !== null && row.course_id !== filters.courseId) return false
    if (filters.status === 'open' && isSettled(row.status)) return false
    if (filters.status !== '' && filters.status !== 'open' && row.status !== filters.status) return false
    if (filters.kind !== '' && (row.kind ?? '') !== filters.kind) return false
    if (query && !`${row.title} ${row.course_code}`.toLowerCase().includes(query)) return false
    return true
  })

  const direction = filters.dir === 'desc' ? -1 : 1

  return rows.sort((a, b) => {
    switch (filters.sort) {
      case 'weight':
        return ((a.weight_pct ?? -1) - (b.weight_pct ?? -1)) * direction
      case 'course':
        return a.course_code.localeCompare(b.course_code) * direction || dueTime(a) - dueTime(b)
      case 'title':
        return a.title.localeCompare(b.title) * direction
      case 'grade':
        return (ratio(a) - ratio(b)) * direction
      case 'due':
      default: {
        // Undated items sort last in both directions: they are not "the oldest".
        const timeA = dueTime(a)
        const timeB = dueTime(b)
        if (timeA === DUE_LAST && timeB === DUE_LAST) return 0
        if (timeA === DUE_LAST) return 1
        if (timeB === DUE_LAST) return -1
        return (timeA - timeB) * direction
      }
    }
  })
}
