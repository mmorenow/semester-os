import type { Assignment, GradeCategory, GradeSummary } from '@/lib/school-types'

/**
 * Grade Center formatting. Numbers print at the precision they carry (`25%`, `12.5%`), and a
 * missing number is `--`, never zero: "no grade" and "scored zero" are different facts.
 */

const NO_VALUE = '--'

/** `25` renders `25%`, `12.5` renders `12.5%`, null renders `--`. */
export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_VALUE
  const rounded = Math.round(value * 10) / 10
  return `${Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)}%`
}

export function num(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_VALUE
  const rounded = Math.round(value * 100) / 100
  return Number.isInteger(rounded) ? String(rounded) : String(rounded)
}

/** `18/20` once a grade exists, and nothing at all before that. */
export function gradeLabel(assignment: Pick<Assignment, 'grade_points' | 'grade_max' | 'points'>): string | null {
  const { grade_points: points } = assignment
  if (points === null || points === undefined) return null
  const max = assignment.grade_max ?? assignment.points
  return max === null || max === undefined ? num(points) : `${num(points)}/${num(max)}`
}

/** The share of the category's own points that were earned, for a row's tone. */
export function gradeRatio(
  assignment: Pick<Assignment, 'grade_points' | 'grade_max' | 'points'>,
): number | null {
  const points = assignment.grade_points
  const max = assignment.grade_max ?? assignment.points
  if (points === null || points === undefined) return null
  if (max === null || max === undefined || max <= 0) return null
  return (points / max) * 100
}

export function safe(value: number | null | undefined): number {
  return value === null || value === undefined || !Number.isFinite(value) ? 0 : value
}

export interface CategorySlice {
  category: GradeCategory
  /** Percent of the bar, already normalized so the row sums to exactly 100. */
  share: number
}

export interface Composition {
  slices: CategorySlice[]
  /** Weight the server could not attach to a category. Rendered, never folded. */
  unallocatedShare: number
  unallocatedPct: number
  total: number
}

/** Composition bar geometry. Widths normalize `weight_pct` against the whole, unmapped weight included. */
export function buildComposition(summary: GradeSummary | null | undefined): Composition {
  const categories = summary?.categories ?? []
  const unallocated = safe(summary?.overall.unallocated_pct)
  const weighted = categories.reduce((sum, category) => sum + safe(category.weight_pct), 0)
  const total = weighted + unallocated

  if (total <= 0) {
    return { slices: [], unallocatedShare: 0, unallocatedPct: unallocated, total: 0 }
  }

  return {
    slices: categories
      .filter((category) => safe(category.weight_pct) > 0)
      .map((category) => ({ category, share: (safe(category.weight_pct) / total) * 100 })),
    unallocatedShare: (unallocated / total) * 100,
    unallocatedPct: unallocated,
    total,
  }
}

/** How many items of a category have a grade, out of how many the server knows. */
export function gradedLabel(category: GradeCategory): string {
  const total = category.graded_count + category.pending_count
  return total === 0 ? NO_VALUE : `${String(category.graded_count)}/${String(total)}`
}

/**
 * Categories aren't stamped on assignments, so a segment matches by name: the category's meaningful
 * words against the assignment's kind and title. Loose on purpose (`midterm_1` finds `Midterm 1`).
 */

const NOISE = new Set(['total', 'pct', 'and', 'or', 'the', 'of', 'each', 'per', 'points', 'grade', 'all'])

function tokenize(value: string): string[] {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .split(' ')
    .map((token) => token.replace(/s$/, ''))
    .filter((token) => token.length > 0 && !NOISE.has(token))
}

function tokensTouch(a: string, b: string): boolean {
  const width = Math.min(4, a.length, b.length)
  if (width < 2) return a === b
  return a.slice(0, width) === b.slice(0, width)
}

export function matchesCategory(assignment: Assignment, categoryName: string): boolean {
  const wanted = tokenize(categoryName)
  if (wanted.length === 0) return false
  const haystack = tokenize(`${assignment.kind ?? ''} ${assignment.title}`)
  return wanted.some((token) => haystack.some((candidate) => tokensTouch(token, candidate)))
}

/** Letter targets at common US cutoffs, shown with the number visible (a syllabus may differ). */
export const GRADE_TARGETS: { label: string; pct: number }[] = [
  { label: 'A', pct: 93 },
  { label: 'A-', pct: 90 },
  { label: 'B+', pct: 87 },
  { label: 'B', pct: 83 },
]
