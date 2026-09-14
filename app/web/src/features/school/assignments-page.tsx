import { useEffect, useMemo, useState } from 'react'
import { FileText, MagnifyingGlass, WarningCircle, X } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { EmptyState } from '@/components/empty-state'
import { humanize } from '@/lib/format'
import { ASSIGNMENT_STATUSES, ASSIGNMENT_STATUS_LABEL } from '@/lib/school-labels'
import { useAssignments, useCourses, useUpdateAssignment } from '@/lib/school-queries'
import type { AssignmentStatus } from '@/lib/school-types'
import { AssignmentSheet } from './assignment-sheet'
import { AssignmentsTable, AssignmentsTableSkeleton } from './assignments-table'
import { buildCourseColors } from './course-color'
import { Panel } from './school-parts'
import { applyAssignmentFilters, useAssignmentFilters } from './use-assignment-filters'
import { useNow } from './use-now'

const ANY = '__any__'
const ALL_STATUSES = '__all__'

function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="flex h-6 items-center gap-1 rounded-sm border border-border bg-muted/50 pl-2 pr-1 text-xs text-foreground">
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove filter ${label}`}
        className="flex size-4 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-ring active:scale-[0.98]"
      >
        <X size={12} />
      </button>
    </span>
  )
}

function BulkBar({
  count,
  ids,
  onDone,
  onClear,
}: {
  count: number
  ids: number[]
  onDone: () => void
  onClear: () => void
}) {
  const update = useUpdateAssignment()
  const [status, setStatus] = useState<AssignmentStatus>('submitted')
  const [running, setRunning] = useState(false)

  async function apply() {
    setRunning(true)
    const results = await Promise.allSettled(
      ids.map((id) => update.mutateAsync({ id, patch: { status } })),
    )
    setRunning(false)

    const failed = results.filter((result) => result.status === 'rejected').length
    if (failed === 0) {
      toast.success(`Moved ${String(ids.length)} to ${ASSIGNMENT_STATUS_LABEL[status]}`)
      onDone()
    } else {
      toast.error(`${String(failed)} of ${String(ids.length)} were not updated`, {
        description: 'The rows that failed are still on their previous status.',
      })
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/45 bg-primary/8 px-3 py-2">
      <span className="text-[13px] text-primary">
        <span className="num font-medium">{String(count)}</span> selected
      </span>

      <div className="ml-auto flex items-center gap-2">
        <label htmlFor="bulk-status" className="text-xs text-muted-foreground">
          Set status
        </label>
        <Select value={status} onValueChange={(value) => { setStatus(value as AssignmentStatus) }}>
          <SelectTrigger id="bulk-status" className="w-[144px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ASSIGNMENT_STATUSES.map((entry) => (
              <SelectItem key={entry} value={entry}>
                {ASSIGNMENT_STATUS_LABEL[entry]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button size="sm" disabled={running} onClick={() => void apply()}>
          {running ? 'Applying' : 'Apply'}
        </Button>
        <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={onClear}>
          Clear
        </Button>
      </div>
    </div>
  )
}

/** Every assignment in one table, filters in the URL, a drawer for the selected item. */
export function SchoolAssignmentsPage() {
  const now = useNow()
  const { filters, setFilters, clearFilters, hasActiveFilters } = useAssignmentFilters()
  const courses = useCourses()
  const assignments = useAssignments()

  const [searchDraft, setSearchDraft] = useState(filters.q)
  const [checked, setChecked] = useState<Set<number>>(() => new Set())

  useEffect(() => { setSearchDraft(filters.q) }, [filters.q])
  useEffect(() => {
    if (searchDraft === filters.q) return
    const timer = setTimeout(() => { setFilters({ q: searchDraft }) }, 300)
    return () => { clearTimeout(timer) }
  }, [searchDraft, filters.q, setFilters])

  const colors = useMemo(() => buildCourseColors(courses.data), [courses.data])
  const rows = useMemo(() => applyAssignmentFilters(assignments.data, filters), [assignments.data, filters])
  const kinds = useMemo(() => {
    const seen = new Set<string>()
    for (const row of assignments.data ?? []) {
      if (row.kind) seen.add(row.kind)
    }
    return [...seen].sort((a, b) => a.localeCompare(b))
  }, [assignments.data])

  const selected = rows.find((row) => row.id === filters.assignmentId)
  const selectedCourse = courses.data?.find((course) => course.id === selected?.course_id)
  const checkedVisible = rows.filter((row) => checked.has(row.id)).map((row) => row.id)

  const chips: { key: string; label: string; clear: () => void }[] = []
  if (filters.courseId !== null) {
    const course = courses.data?.find((entry) => entry.id === filters.courseId)
    chips.push({
      key: 'course',
      label: course ? course.code : `Course ${String(filters.courseId)}`,
      clear: () => { setFilters({ courseId: null }) },
    })
  }
  if (filters.status !== 'open') {
    chips.push({
      key: 'status',
      label: filters.status === '' ? 'Every status' : ASSIGNMENT_STATUS_LABEL[filters.status],
      clear: () => { setFilters({ status: 'open' }) },
    })
  }
  if (filters.kind) {
    chips.push({ key: 'kind', label: humanize(filters.kind), clear: () => { setFilters({ kind: '' }) } })
  }
  if (filters.q) {
    chips.push({ key: 'q', label: `Search: ${filters.q}`, clear: () => { setFilters({ q: '' }) } })
  }

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Assignments</h1>
        <p className="lede text-muted-foreground">
          Everything the semester is asking for, in one list.
        </p>
      </header>

      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 items-end gap-3 border-y border-border py-3 md:grid-cols-4">
          <div className="col-span-2 flex flex-col gap-1.5 md:col-span-1">
            <Label htmlFor="assignments-search" className="text-xs text-muted-foreground">
              Search
            </Label>
            <div className="relative">
              <MagnifyingGlass
                size={16}
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                id="assignments-search"
                value={searchDraft}
                onChange={(event) => { setSearchDraft(event.target.value) }}
                placeholder="Title or course"
                autoComplete="off"
                className="pl-9"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="assignments-course" className="text-xs text-muted-foreground">
              Course
            </Label>
            <Select
              value={filters.courseId === null ? ANY : String(filters.courseId)}
              onValueChange={(value) => {
                setFilters({ courseId: value === ANY ? null : Number(value) })
              }}
            >
              <SelectTrigger id="assignments-course" className="w-full">
                <SelectValue placeholder="Every course" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Every course</SelectItem>
                {(courses.data ?? []).map((course) => (
                  <SelectItem key={course.id} value={String(course.id)}>
                    <span className="num">{course.code}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="assignments-status" className="text-xs text-muted-foreground">
              Status
            </Label>
            <Select
              value={filters.status === '' ? ALL_STATUSES : filters.status}
              onValueChange={(value) => {
                setFilters({ status: value === ALL_STATUSES ? '' : (value as AssignmentStatus | 'open') })
              }}
            >
              <SelectTrigger id="assignments-status" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="open">Open</SelectItem>
                <SelectItem value={ALL_STATUSES}>Every status</SelectItem>
                {ASSIGNMENT_STATUSES.map((status) => (
                  <SelectItem key={status} value={status}>
                    {ASSIGNMENT_STATUS_LABEL[status]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="assignments-kind" className="text-xs text-muted-foreground">
              Kind
            </Label>
            <Select
              value={filters.kind || ANY}
              onValueChange={(value) => { setFilters({ kind: value === ANY ? '' : value }) }}
            >
              <SelectTrigger id="assignments-kind" className="w-full">
                <SelectValue placeholder="Every kind" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Every kind</SelectItem>
                {kinds.map((kind) => (
                  <SelectItem key={kind} value={kind}>
                    {humanize(kind)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {chips.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {chips.map((chip) => (
              <FilterChip key={chip.key} label={chip.label} onRemove={chip.clear} />
            ))}
            {hasActiveFilters ? (
              <Button variant="ghost" size="xs" className="text-muted-foreground" onClick={clearFilters}>
                Clear filters
              </Button>
            ) : null}
            <span className="num ml-auto text-[13px] text-muted-foreground">
              {String(rows.length)} {rows.length === 1 ? 'item' : 'items'}
            </span>
          </div>
        ) : (
          <p className="num text-[13px] text-muted-foreground">
            {assignments.isPending ? '' : `${String(rows.length)} ${rows.length === 1 ? 'item' : 'items'}`}
          </p>
        )}

        {checkedVisible.length > 0 ? (
          <BulkBar
            count={checkedVisible.length}
            ids={checkedVisible}
            onDone={() => { setChecked(new Set()) }}
            onClear={() => { setChecked(new Set()) }}
          />
        ) : null}
      </div>

      <Panel>
        {assignments.isPending ? (
          <AssignmentsTableSkeleton />
        ) : assignments.isError ? (
          <EmptyState
            icon={WarningCircle}
            title="Could not load assignments"
            description="The assignments endpoint did not respond. Check that the Semester OS server is still running."
            action={
              <Button size="sm" variant="outline" onClick={() => void assignments.refetch()}>
                Try again
              </Button>
            }
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={FileText}
            title={hasActiveFilters ? 'Nothing matches those filters' : 'No assignments yet'}
            description={
              hasActiveFilters
                ? 'Widen the status or clear the course filter to see the rest of the semester.'
                : 'They arrive when the harvest runs against Brightspace and Gradescope, or when you add one by hand.'
            }
            action={
              hasActiveFilters ? (
                <Button size="sm" variant="outline" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <AssignmentsTable
            assignments={rows}
            colors={colors}
            now={now}
            sort={filters.sort}
            dir={filters.dir}
            onSortChange={(sort, dir) => { setFilters({ sort, dir }) }}
            onRowClick={(assignmentId) => { setFilters({ assignmentId }) }}
            selectedId={filters.assignmentId}
            checked={checked}
            onToggle={(id, next) => {
              setChecked((current) => {
                const updated = new Set(current)
                if (next) updated.add(id)
                else updated.delete(id)
                return updated
              })
            }}
            onToggleAll={(next) => {
              setChecked(next ? new Set(rows.map((row) => row.id)) : new Set())
            }}
          />
        )}
      </Panel>

      <AssignmentSheet
        assignmentId={filters.assignmentId}
        fallback={selected}
        platforms={selectedCourse?.platforms ?? []}
        slot={selected ? colors.get(selected.course_id) : undefined}
        now={now}
        onClose={() => { setFilters({ assignmentId: null }) }}
      />
    </div>
  )
}
