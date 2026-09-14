import type { Course } from '@/lib/school-types'

/**
 * Course identity: a mono code inside a chip of one of six course colors, assigned by slot.
 *
 *   chip    28%                course code ground, everywhere
 *   block   32%  hover 42%     week-grid block
 *   card    32%  hover 42%     courses list card
 *   segment 28%  hover 38%     grade-bar segment (foreground labels only)
 *   room    16%                header block of a single-course route
 *   glyph   16%                decorative watermark on a courses card
 *
 * Contrast caps: 24% under `text-muted-foreground` (26% fails in dark at 4.43), 42% under
 * `text-foreground/75`. Surfaces tinted above 24% promote muted ink to `text-foreground/75`.
 * A course color is never a text color or a semantic icon fill.
 *
 * A slot stored by the server (`course-3`) wins; otherwise id order decides, so it's stable.
 * Class strings are spelled out because Tailwind scans source text.
 */

export const COURSE_SLOTS = 6

const CHIP = [
  'bg-course-1/28',
  'bg-course-2/28',
  'bg-course-3/28',
  'bg-course-4/28',
  'bg-course-5/28',
  'bg-course-6/28',
]

const BLOCK = [
  'bg-course-1/32',
  'bg-course-2/32',
  'bg-course-3/32',
  'bg-course-4/32',
  'bg-course-5/32',
  'bg-course-6/32',
]

const BLOCK_HOVER = [
  'hover:bg-course-1/42',
  'hover:bg-course-2/42',
  'hover:bg-course-3/42',
  'hover:bg-course-4/42',
  'hover:bg-course-5/42',
  'hover:bg-course-6/42',
]

const SEGMENT = [
  'bg-course-1/28',
  'bg-course-2/28',
  'bg-course-3/28',
  'bg-course-4/28',
  'bg-course-5/28',
  'bg-course-6/28',
]

const SEGMENT_HOVER = [
  'hover:bg-course-1/38',
  'hover:bg-course-2/38',
  'hover:bg-course-3/38',
  'hover:bg-course-4/38',
  'hover:bg-course-5/38',
  'hover:bg-course-6/38',
]

const CARD = [
  'bg-course-1/32',
  'bg-course-2/32',
  'bg-course-3/32',
  'bg-course-4/32',
  'bg-course-5/32',
  'bg-course-6/32',
]

const CARD_HOVER = [
  'group-hover:bg-course-1/42',
  'group-hover:bg-course-2/42',
  'group-hover:bg-course-3/42',
  'group-hover:bg-course-4/42',
  'group-hover:bg-course-5/42',
  'group-hover:bg-course-6/42',
]

const GLYPH = [
  'text-course-1/16',
  'text-course-2/16',
  'text-course-3/16',
  'text-course-4/16',
  'text-course-5/16',
  'text-course-6/16',
]

const ROOM = [
  'bg-course-1/16',
  'bg-course-2/16',
  'bg-course-3/16',
  'bg-course-4/16',
  'bg-course-5/16',
  'bg-course-6/16',
]

const STORED = /^course-([1-6])$/

/** Course id to slot index (0-5). Courses the list does not carry map to null. */
export function buildCourseColors(courses: Course[] | undefined): Map<number, number> {
  const map = new Map<number, number>()
  if (!courses) return map
  const ordered = [...courses].sort((a, b) => a.id - b.id)
  ordered.forEach((course, index) => {
    const stored = course.color ? STORED.exec(course.color) : null
    map.set(course.id, stored ? Number(stored[1]) - 1 : index % COURSE_SLOTS)
  })
  return map
}

/** The slot a single course occupies, when the whole list is not on hand. */
export function courseSlot(color: string | null | undefined): number | undefined {
  const stored = color ? STORED.exec(color) : null
  return stored ? Number(stored[1]) - 1 : undefined
}

/**
 * Set by the tightest stack: the code on a hovered courses card measures 4.72:1 at 28%
 * (30% would be 4.61).
 */
export function chipClass(slot: number | undefined): string {
  return slot === undefined ? 'bg-muted' : CHIP[slot % COURSE_SLOTS]
}

export function blockClass(slot: number | undefined): string {
  return slot === undefined ? 'bg-muted/60' : BLOCK[slot % COURSE_SLOTS]
}

/** +10 points; the block's room line caps it at 42. */
export function blockHoverClass(slot: number | undefined): string {
  return slot === undefined ? 'hover:bg-muted/80' : BLOCK_HOVER[slot % COURSE_SLOTS]
}

/** Grade-bar segment: foreground labels only, so 28% at rest and 38% on hover. */
export function segmentClass(slot: number | undefined): string {
  return slot === undefined ? 'bg-muted/60' : SEGMENT[slot % COURSE_SLOTS]
}

export function segmentHoverClass(slot: number | undefined): string {
  return slot === undefined ? 'hover:bg-muted/80' : SEGMENT_HOVER[slot % COURSE_SLOTS]
}

/**
 * Whole-card tint at 32/42, the deepest `text-foreground/75` survives (46% fails in dark at 4.29).
 * Muted ink on the card is promoted to `text-foreground/75`.
 */
export function cardClass(slot: number | undefined): string {
  return slot === undefined ? 'bg-muted/60' : CARD[slot % COURSE_SLOTS]
}

/** +10 points, driven by the card's `group` so the 1px edge counts. */
export function cardHoverClass(slot: number | undefined): string {
  return slot === undefined ? 'group-hover:bg-muted/80' : CARD_HOVER[slot % COURSE_SLOTS]
}

/**
 * Decorative 64px watermark at 16%, `aria-hidden`. It must not sit under text: on a hovered card
 * it drops `text-foreground/75` to 3.89:1, so the footer reserves its right end.
 */
export function watermarkClass(slot: number | undefined): string {
  return slot === undefined ? 'text-foreground/8' : GLYPH[slot % COURSE_SLOTS]
}

/** Header block tint for a single-course route, 16%. */
export function roomClass(slot: number | undefined): string {
  return slot === undefined ? '' : ROOM[slot % COURSE_SLOTS]
}
