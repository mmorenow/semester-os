import { useMemo } from 'react'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { CaretDown, CaretUp } from '@phosphor-icons/react'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { isSettled } from '@/lib/school-labels'
import type { Assignment } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import {
  AssignmentStatusSelect,
  DueCell,
  GradeCell,
  KindBadge,
  WeightCell,
} from './assignment-parts'
import { CourseMark } from './course-mark'
import type { AssignmentSortKey, SortDir } from './use-assignment-filters'

const columnHelper = createColumnHelper<Assignment>()

const SORTABLE: Partial<Record<string, AssignmentSortKey>> = {
  course: 'course',
  title: 'title',
  due: 'due',
  weight: 'weight',
  grade: 'grade',
}

function SortHeader({
  label,
  columnId,
  sort,
  dir,
  align = 'left',
  onSort,
}: {
  label: string
  columnId: string
  sort: AssignmentSortKey
  dir: SortDir
  align?: 'left' | 'right'
  onSort: (key: AssignmentSortKey) => void
}) {
  const key = SORTABLE[columnId]
  if (!key) {
    return (
      <span
        className={cn('text-[13px] font-medium text-muted-foreground', align === 'right' && 'block text-right')}
      >
        {label}
      </span>
    )
  }

  const active = sort === key
  return (
    <button
      type="button"
      onClick={() => { onSort(key) }}
      aria-label={`Sort by ${label}`}
      className={cn(
        'flex items-center gap-1 rounded-sm text-[13px] font-medium transition-colors active:scale-[0.98] focus-ring',
        align === 'right' && 'ml-auto',
        active ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {label}
      {active ? (
        dir === 'desc' ? <CaretDown size={12} weight="bold" /> : <CaretUp size={12} weight="bold" />
      ) : null}
    </button>
  )
}

interface AssignmentsTableProps {
  assignments: Assignment[]
  colors: Map<number, number>
  now: Date
  sort: AssignmentSortKey
  dir: SortDir
  onSortChange: (sort: AssignmentSortKey, dir: SortDir) => void
  onRowClick: (assignmentId: number) => void
  selectedId: number | null
  /** Ids ticked for a bulk change, owned by the page above. */
  checked: Set<number>
  onToggle: (id: number, next: boolean) => void
  onToggleAll: (next: boolean) => void
}

/** Every assignment in one table. Status and checkbox are live in the row; the rest opens the drawer. */
export function AssignmentsTable({
  assignments,
  colors,
  now,
  sort,
  dir,
  onSortChange,
  onRowClick,
  selectedId,
  checked,
  onToggle,
  onToggleAll,
}: AssignmentsTableProps) {
  function handleSort(key: AssignmentSortKey) {
    if (sort === key) onSortChange(key, dir === 'desc' ? 'asc' : 'desc')
    else onSortChange(key, key === 'weight' || key === 'grade' ? 'desc' : 'asc')
  }

  const allChecked = assignments.length > 0 && assignments.every((row) => checked.has(row.id))
  const someChecked = assignments.some((row) => checked.has(row.id))

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'select',
        header: () => (
          <Checkbox
            checked={allChecked ? true : someChecked ? 'indeterminate' : false}
            onCheckedChange={(value) => { onToggleAll(value === true) }}
            aria-label="Select every visible assignment"
          />
        ),
        cell: (info) => (
          <span
            className="flex"
            onClick={(event) => { event.stopPropagation() }}
            role="presentation"
          >
            <Checkbox
              checked={checked.has(info.row.original.id)}
              onCheckedChange={(value) => { onToggle(info.row.original.id, value === true) }}
              aria-label={`Select ${info.row.original.title}`}
            />
          </span>
        ),
      }),
      columnHelper.accessor((row) => row.course_code, {
        id: 'course',
        header: () => <SortHeader label="Course" columnId="course" sort={sort} dir={dir} onSort={handleSort} />,
        cell: (info) => (
          <CourseMark
            code={info.row.original.course_code}
            slot={colors.get(info.row.original.course_id)}
            size="xs"
          />
        ),
      }),
      columnHelper.accessor((row) => row.title, {
        id: 'title',
        header: () => <SortHeader label="Item" columnId="title" sort={sort} dir={dir} onSort={handleSort} />,
        cell: (info) => (
          <span className="block truncate text-sm text-foreground">{info.row.original.title}</span>
        ),
      }),
      columnHelper.accessor((row) => row.kind ?? '', {
        id: 'kind',
        header: () => <SortHeader label="Kind" columnId="kind" sort={sort} dir={dir} onSort={handleSort} />,
        cell: (info) => <KindBadge kind={info.row.original.kind} />,
      }),
      columnHelper.accessor((row) => row.due_at ?? '', {
        id: 'due',
        header: () => <SortHeader label="Due" columnId="due" sort={sort} dir={dir} onSort={handleSort} />,
        cell: (info) => <DueCell assignment={info.row.original} now={now} />,
      }),
      columnHelper.accessor((row) => row.weight_pct ?? 0, {
        id: 'weight',
        header: () => (
          <SortHeader label="Weight" columnId="weight" sort={sort} dir={dir} align="right" onSort={handleSort} />
        ),
        cell: (info) => <WeightCell assignment={info.row.original} />,
      }),
      columnHelper.accessor((row) => row.grade_points ?? -1, {
        id: 'grade',
        header: () => (
          <SortHeader label="Grade" columnId="grade" sort={sort} dir={dir} align="right" onSort={handleSort} />
        ),
        cell: (info) => <GradeCell assignment={info.row.original} />,
      }),
      columnHelper.accessor((row) => row.status, {
        id: 'status',
        header: () => <SortHeader label="Status" columnId="status" sort={sort} dir={dir} onSort={handleSort} />,
        cell: (info) => <AssignmentStatusSelect assignment={info.row.original} />,
      }),
    ],
    // handleSort is stable for a given sort/dir pair.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sort, dir, colors, now, checked, allChecked, someChecked],
  )

  const table = useReactTable({
    data: assignments,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
  })

  return (
    <Table className="text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {table.getHeaderGroups()[0].headers.map((header) => (
            <TableHead
              key={header.id}
              className={cn(
                'h-10 px-2 py-0',
                header.id === 'select' && 'w-[36px]',
                header.id === 'course' && 'w-[104px]',
                header.id === 'kind' && 'w-[88px]',
                // `px-2` padding plus measured content: `Sep 16, 11:58p` is 108px of 13px mono,
                // a sortable head is its label plus a 12px caret, the status select needs 116px.
                header.id === 'due' && 'w-[128px]',
                header.id === 'weight' && 'w-[80px]',
                header.id === 'grade' && 'w-[80px]',
                header.id === 'status' && 'w-[136px]',
              )}
            >
              {flexRender(header.column.columnDef.header, header.getContext())}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map((row) => {
          const assignment = row.original
          const selected = selectedId === assignment.id
          return (
            <TableRow
              key={row.id}
              tabIndex={0}
              role="button"
              aria-label={`Open ${assignment.title} for ${assignment.course_code}`}
              onClick={() => { onRowClick(assignment.id) }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onRowClick(assignment.id)
                }
              }}
              className={cn(
                'cursor-pointer transition-colors duration-[80ms]',
                isSettled(assignment.status) && 'opacity-55 hover:opacity-100',
                selected && 'bg-primary/8 hover:bg-primary/12',
              )}
            >
              {row.getVisibleCells().map((cell) => (
                <TableCell
                  key={cell.id}
                  // Only the elastic column gets `max-w-0`, so `truncate` works in an auto-layout table.
                  className={cn('px-2 py-2', cell.column.id === 'title' && 'max-w-0')}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

/** Loading state shaped like the real table: same columns, same widths. */
export function AssignmentsTableSkeleton() {
  const widths = ['w-4', 'w-[72px]', 'w-full', 'w-14', 'w-24', 'w-10', 'w-12', 'w-[116px]']
  const labels = ['', 'Course', 'Item', 'Kind', 'Due', 'Weight', 'Grade', 'Status']

  return (
    <Table className="text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {labels.map((label, index) => (
            <TableHead key={index} className="h-10 px-2 py-0 text-[13px] font-medium text-muted-foreground">
              {label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 8 }, (_, rowIndex) => (
          <TableRow key={rowIndex} className="hover:bg-transparent">
            {widths.map((width, cellIndex) => (
              <TableCell key={cellIndex} className="px-2 py-2.5">
                <Skeleton className={cn('h-3.5', width)} />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
