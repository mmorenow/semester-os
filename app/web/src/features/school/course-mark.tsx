import { cn } from '@/lib/utils'
import { chipClass } from './course-color'

/**
 * Course mark: the code in mono inside a chip of the course color (alpha in `chipClass`).
 *
 *   xs    12px code   px-1.5  rounded-sm   dense tables, sheet headers
 *   sm    14px code   px-2    rounded-sm   list rows
 *   md    15px code   px-2.5  rounded-sm   cards
 *   page  28px code   px-2.5  rounded-md   course detail h1 only
 */

export type MarkSize = 'xs' | 'sm' | 'md' | 'page'

/** Leading is pinned so a chip's height is a number, not whatever it inherits. */
const CHIP: Record<MarkSize, string> = {
  xs: 'rounded-sm px-1.5 py-0.5 leading-4',
  sm: 'rounded-sm px-2 py-0.5 leading-5',
  md: 'rounded-sm px-2.5 py-1 leading-6',
  page: 'rounded-md px-2.5 py-1',
}

const CODE: Record<MarkSize, string> = {
  xs: 'num font-medium text-xs',
  sm: 'num font-medium text-sm',
  md: 'num font-medium text-[15px]',
  page: 'code-display',
}

export function CourseMark({
  code,
  slot,
  className,
  size = 'sm',
}: {
  code: string
  slot: number | undefined
  className?: string
  /** `sm` is the row and cell default; `md` is a card; `page` is a course h1. */
  size?: MarkSize
}) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center whitespace-nowrap text-foreground',
        CHIP[size],
        CODE[size],
        chipClass(slot),
        className,
      )}
    >
      {code}
    </span>
  )
}
