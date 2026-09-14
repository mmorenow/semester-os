import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatClockRange, formatHourTick, isSameDay, minutesOfDay, shortWeekday } from '@/lib/school-time'
import { EXTERNAL_SOURCE_LABEL, MEETING_KIND_LABEL } from '@/lib/school-labels'
import { useReducedMotion } from '@/lib/use-reduced-motion'
import { cn } from '@/lib/utils'
import { blockClass, blockHoverClass, segmentClass, segmentHoverClass } from './course-color'
import {
  asClassItems,
  asExternalItems,
  asSittingItems,
  externalKey,
  itemKey,
  type GridItem,
  type TimedEvent,
  type TimedExternal,
  type TimedSitting,
} from './event-time'
import { externalCourseCode, externalLabel, externalSlot, externalTimeLabel, SourceMark } from './external-parts'

/** Week-grid metrics (DESIGN.md). */
export const HOUR_PX = 48
const GUTTER_PX = 44
const MIN_BLOCK_PX = 24
/** The visible window never opens before 7:00a or past 10:00p on its own. */
const CLAMP_START = 7 * 60
const CLAMP_END = 22 * 60
/** Pinned chips per day before the rest collapse into a counter. */
const PINNED_SHOWN = 2

function floorHour(minutes: number): number {
  return Math.floor(minutes / 60) * 60
}

function ceilHour(minutes: number): number {
  return Math.ceil(minutes / 60) * 60
}

export interface GridWindow {
  start: number
  end: number
  height: number
}

/** Anything the grid positions: it only ever needs the two minute figures. */
interface Span {
  startMin: number
  endMin: number
}

/** Schedule span plus an hour of padding, clamped to 7a-10p. The clamp only trims padding; a 6:30a class still shows. */
export function computeWindow(items: Span[]): GridWindow {
  if (items.length === 0) {
    const start = 8 * 60
    const end = 18 * 60
    return { start, end, height: ((end - start) / 60) * HOUR_PX }
  }

  const earliest = Math.min(...items.map((item) => item.startMin))
  const latest = Math.max(...items.map((item) => item.endMin))

  let start = floorHour(earliest - 60)
  if (start < CLAMP_START) start = Math.min(CLAMP_START, floorHour(earliest))
  let end = ceilHour(latest + 60)
  if (end > CLAMP_END) end = Math.max(CLAMP_END, ceilHour(latest))

  return { start, end, height: ((end - start) / 60) * HOUR_PX }
}

interface PlacedEvent<T extends Span> {
  item: T
  lane: number
  lanes: number
}

/** Side-by-side lanes for overlaps. Classes and externals share one pass, so collisions split the column instead of hiding. */
export function placeDay<T extends Span>(items: T[]): PlacedEvent<T>[] {
  const sorted = [...items].sort((a, b) => a.startMin - b.startMin || a.endMin - b.endMin)
  const placed: PlacedEvent<T>[] = []
  let cluster: PlacedEvent<T>[] = []
  let laneEnds: number[] = []

  function flush() {
    for (const entry of cluster) entry.lanes = laneEnds.length
    placed.push(...cluster)
    cluster = []
    laneEnds = []
  }

  for (const item of sorted) {
    const clusterEnd = laneEnds.length > 0 ? Math.max(...laneEnds) : -1
    if (laneEnds.length > 0 && item.startMin >= clusterEnd) flush()

    let lane = laneEnds.findIndex((end) => end <= item.startMin)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(item.endMin)
    } else {
      laneEnds[lane] = item.endMin
    }
    cluster.push({ item, lane, lanes: 1 })
  }
  flush()

  return placed
}

/** Only externals with a duration become blocks. Point deadlines (Brightspace's 11:59p-11:59p) go to the pinned row. */
function isBlockable(item: TimedExternal): boolean {
  return !item.allDay && !item.instant
}

/** Absolute box for one item in a day column, lane-split with its neighbours. */
function blockStyle<T extends Span>(placed: PlacedEvent<T>, gridWindow: GridWindow): CSSProperties {
  const { item, lane, lanes } = placed
  return {
    top: `${String(((item.startMin - gridWindow.start) / 60) * HOUR_PX)}px`,
    height: `${String(Math.max(MIN_BLOCK_PX, ((item.endMin - item.startMin) / 60) * HOUR_PX))}px`,
    left: `${String((lane / lanes) * 100)}%`,
    width: `${String(100 / lanes)}%`,
  }
}

function blockHeight<T extends Span>(placed: PlacedEvent<T>): number {
  return Math.max(MIN_BLOCK_PX, ((placed.item.endMin - placed.item.startMin) / 60) * HOUR_PX)
}

function ClassBlock({
  placed,
  window: gridWindow,
  slot,
}: {
  placed: PlacedEvent<{ kind: 'class' } & TimedEvent>
  window: GridWindow
  slot: number | undefined
}) {
  const { item } = placed
  // Two 12px lines (30px) + `gap-px` + `p-1` = 39px; a 50-minute class is 40px and must keep its title.
  const showTitle = blockHeight(placed) >= 40

  return (
    <div className="absolute px-px" style={blockStyle(placed, gridWindow)}>
      {/* 32/42% tint, since the block's area is data. The room line uses `text-foreground/75`
          because muted ink caps a tint at 24%. */}
      <Link
        to={`/courses/${String(item.event.course_id)}`}
        aria-label={`Open ${item.event.course_code}`}
        className={cn(
          'focus-ring relative block h-full overflow-hidden rounded-sm p-1 transition-colors duration-[120ms]',
          blockClass(slot),
          blockHoverClass(slot),
        )}
      >
        <div className="flex h-full min-w-0 flex-col gap-px px-1">
          {/* For anything that can't see the geometry. */}
          <span className="sr-only">{formatClockRange(item.startMin, item.endMin)}</span>
          <div className="flex min-w-0 items-baseline gap-1">
            <span className="min-w-0 truncate text-xs leading-tight text-foreground">
              <span className="num font-medium">{item.event.course_code}</span>
              {item.event.kind === 'lecture' ? '' : ` ${MEETING_KIND_LABEL[item.event.kind]}`}
            </span>
            {item.event.location ? (
              <span className="num ml-auto shrink-0 text-xs leading-tight text-foreground/75">
                {item.event.location}
              </span>
            ) : null}
          </div>
          {showTitle ? (
            <span className="truncate text-xs leading-tight text-foreground/90">{item.event.course_title}</span>
          ) : null}
        </div>
      </Link>
    </div>
  )
}

/** Exam block: course tint like a class, plus the work's title and a `border-foreground/40` edge. */
function SittingBlock({
  placed,
  window: gridWindow,
  slot,
}: {
  placed: PlacedEvent<{ kind: 'sitting' } & TimedSitting>
  window: GridWindow
  slot: number | undefined
}) {
  const { item } = placed
  const { assignment } = item
  const showLocation = blockHeight(placed) >= 40 && Boolean(assignment.location)

  return (
    <div className="absolute px-px" style={blockStyle(placed, gridWindow)}>
      <Link
        to={`/courses/${String(assignment.course_id)}?assignment=${String(assignment.id)}`}
        aria-label={`Open ${assignment.title}, ${assignment.course_code}`}
        className={cn(
          'focus-ring relative block h-full overflow-hidden rounded-sm border border-foreground/40 p-1 transition-colors duration-[120ms]',
          blockClass(slot),
          blockHoverClass(slot),
        )}
      >
        <div className="flex h-full min-w-0 flex-col gap-px px-1">
          <span className="sr-only">{formatClockRange(item.startMin, item.endMin)}</span>
          <div className="flex min-w-0 items-baseline gap-1">
            <span className="num shrink-0 text-xs font-medium leading-tight text-foreground">
              {assignment.course_code}
            </span>
            <span className="min-w-0 truncate text-xs font-medium leading-tight text-foreground">
              {assignment.title}
            </span>
          </div>
          {showLocation ? (
            <span className="num truncate text-xs leading-tight text-foreground/75">{assignment.location}</span>
          ) : null}
        </div>
      </Link>
    </div>
  )
}

/**
 * External event block: `bg-foreground/10` fill, dashed border, monochrome logo, no course tint.
 * `bg-muted/60` would clear the card by only 1.04:1 in dark; the foreground wash works in both themes.
 */
function ExternalBlock({
  placed,
  window: gridWindow,
  slot,
  animate,
}: {
  placed: PlacedEvent<{ kind: 'external' } & TimedExternal>
  window: GridWindow
  /** Only for a Notes event naming a known course: takes its tint and drops the dashed edge. */
  slot: number | undefined
  animate: boolean
}) {
  const { item } = placed
  const code = externalCourseCode(item.external)
  const tinted = slot !== undefined
  // 44, not 40: the first line is a 16px mark, so a 50-minute event would clip the location.
  const showLocation = blockHeight(placed) >= 44 && Boolean(item.external.location)

  return (
    <div className="absolute px-px" style={blockStyle(placed, gridWindow)}>
      <div
        className={cn(
          'relative h-full overflow-hidden rounded-sm p-1 transition-colors duration-[120ms]',
          tinted
            ? cn(blockClass(slot), blockHoverClass(slot))
            : 'border border-dashed border-border bg-foreground/10 hover:bg-foreground/16',
          animate && 'external-enter',
        )}
      >
        <div className={cn('flex h-full min-w-0 flex-col gap-px', tinted ? 'px-1' : 'px-0.5')}>
          <span className="sr-only">{externalLabel(item)}</span>
          <div className="flex min-w-0 items-center gap-1" aria-hidden>
            {tinted && code ? (
              <span className="num shrink-0 text-xs font-medium leading-tight text-foreground">{code}</span>
            ) : (
              <SourceMark source={item.external.source} />
            )}
            <span className="min-w-0 truncate text-xs leading-tight text-foreground/90">
              {item.external.title}
            </span>
          </div>
          {showLocation ? (
            <span className="truncate text-xs leading-tight text-foreground/75" aria-hidden>
              {item.external.location}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/**
 * Pinned chip for an all-day event or a point deadline. Deadlines keep their clock; a Notes event
 * naming a course takes its chip tint (28/38) and code.
 */
function PinnedChip({ item, slot, animate }: { item: TimedExternal; slot: number | undefined; animate: boolean }) {
  const code = externalCourseCode(item.external)
  const tinted = slot !== undefined
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'flex min-w-0 items-center gap-1 rounded-sm px-1 py-px transition-colors duration-[120ms]',
            tinted
              ? cn(segmentClass(slot), segmentHoverClass(slot))
              : 'border border-dashed border-border bg-foreground/10 hover:bg-foreground/16',
            animate && 'external-enter',
          )}
        >
          {tinted && code ? (
            <span className="num shrink-0 text-xs font-medium leading-4 text-foreground">{code}</span>
          ) : (
            <SourceMark source={item.external.source} />
          )}
          {item.allDay ? null : (
            <span className="num shrink-0 text-xs leading-4 text-foreground/75">
              {externalTimeLabel(item)}
            </span>
          )}
          <span className="min-w-0 truncate text-xs leading-4 text-foreground/90">
            {item.external.title}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-[46ch]">
        <span className="block">{item.external.title}</span>
        <span className="num block text-muted-foreground">
          {code ? `${code} · ` : ''}
          {EXTERNAL_SOURCE_LABEL[item.external.source]} · {externalTimeLabel(item)}
          {item.external.location ? ` · ${item.external.location}` : ''}
        </span>
      </TooltipContent>
    </Tooltip>
  )
}

/** The rest of a crowded day, as one counter with the whole list behind it. */
function PinnedOverflow({ items }: { items: TimedExternal[] }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="num px-1 text-left text-xs leading-4 text-muted-foreground">
          +{String(items.length)} more
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-[46ch]">
        {items.map((item) => (
          <span key={externalKey(item.external)} className="block">
            <span className="num">{externalTimeLabel(item)}</span> {item.external.title}
          </span>
        ))}
      </TooltipContent>
    </Tooltip>
  )
}

interface WeekGridProps {
  days: Date[]
  /** Class meetings for the visible days, resolved and sorted. */
  items: TimedEvent[]
  /** External events for the same days. Empty when the layer is switched off. */
  externals: TimedExternal[]
  /** Graded work with a time block (exams) for the same days. */
  sittings?: TimedSitting[]
  colors: Map<number, number>
  now: Date
  /** True only on the render where the External toggle was switched on; blocks never animate on load. */
  animateExternal?: boolean
}

/** The week as geometry: 48px per hour, hour hairlines, equal day columns, a now-line across today. */
export function WeekGrid({ days, items, externals, sittings = [], colors, now, animateExternal = false }: WeekGridProps) {
  const reducedMotion = useReducedMotion()

  const blockable = externals.filter(isBlockable)
  const pinned = externals.filter((item) => !isBlockable(item))
  const gridItems: GridItem[] = [...asClassItems(items), ...asSittingItems(sittings), ...asExternalItems(blockable)]

  // The window covers every boxed item, externals included.
  const gridWindow = computeWindow(gridItems)
  // The window end is the grid's bottom edge; a tick there would clip and double the border.
  const hours: number[] = []
  for (let minute = gridWindow.start; minute < gridWindow.end; minute += 60) hours.push(minute)

  // One pinned band shared by all columns, omitted when nothing is pinned.
  const pinnedByDay = days.map((day) => pinned.filter((item) => isSameDay(item.start, day)))
  const hasPinned = pinnedByDay.some((list) => list.length > 0)

  const nowMinutes = minutesOfDay(now)
  // No now marker on a week paged away from.
  const nowVisible =
    nowMinutes >= gridWindow.start &&
    nowMinutes <= gridWindow.end &&
    days.some((day) => isSameDay(day, now))
  const nowTop = ((nowMinutes - gridWindow.start) / 60) * HOUR_PX

  /** Anchored at the column top and moved with a transform, so the 30s updates glide. No pulse. */
  const nowStyle: CSSProperties = {
    transform: `translateY(${String(nowTop)}px)`,
    transition: reducedMotion ? undefined : 'transform 400ms var(--ease-shift)',
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex border-b border-border">
        <div className="shrink-0" style={{ width: `${String(GUTTER_PX)}px` }} />
        {days.map((day) => {
          const isToday = isSameDay(day, now)
          return (
            <div
              key={day.toDateString()}
              className="flex h-9 flex-1 items-center justify-center gap-1.5 border-l border-border"
            >
              <span className={cn('text-xs font-medium', isToday ? 'text-primary' : 'text-muted-foreground')}>
                {shortWeekday(day)}
              </span>
              <span className={cn('num text-xs', isToday ? 'text-primary' : 'text-muted-foreground')}>
                {String(day.getDate())}
              </span>
            </div>
          )
        })}
      </div>

      {hasPinned ? (
        <div className="flex border-b border-border">
          <div className="shrink-0" style={{ width: `${String(GUTTER_PX)}px` }} />
          {days.map((day, index) => {
            const list = pinnedByDay[index]
            const shown = list.length > PINNED_SHOWN ? list.slice(0, PINNED_SHOWN) : list
            const rest = list.slice(shown.length)
            return (
              <div
                key={day.toDateString()}
                className="flex min-w-0 flex-1 flex-col gap-px border-l border-border p-1"
              >
                {shown.map((item) => (
                  <PinnedChip
                    key={externalKey(item.external)}
                    item={item}
                    slot={externalSlot(item.external, colors)}
                    animate={animateExternal}
                  />
                ))}
                {rest.length > 0 ? <PinnedOverflow items={rest} /> : null}
              </div>
            )
          })}
        </div>
      ) : null}

      <div className="flex" style={{ height: `${String(gridWindow.height)}px` }}>
        <div className="relative shrink-0" style={{ width: `${String(GUTTER_PX)}px` }}>
          {hours.map((minute, index) => (
            <span
              key={minute}
              className={cn(
                'num absolute right-2 text-xs text-muted-foreground',
                index === 0 ? 'translate-y-0' : '-translate-y-1/2',
              )}
              style={{ top: `${String(((minute - gridWindow.start) / 60) * HOUR_PX)}px` }}
            >
              {formatHourTick(minute)}
            </span>
          ))}
          {nowVisible ? (
            <span className="absolute top-0 right-0" style={nowStyle} aria-hidden>
              <span className="block size-1 -translate-y-1/2 translate-x-1/2 rounded-full bg-primary" />
            </span>
          ) : null}
        </div>

        {days.map((day) => {
          const dayItems = gridItems.filter((item) => isSameDay(item.start, day))
          const isToday = isSameDay(day, now)
          return (
            <div key={day.toDateString()} className="relative min-w-0 flex-1 border-l border-border">
              {hours.slice(1).map((minute) => (
                <span
                  key={minute}
                  className="absolute inset-x-0 h-px bg-border"
                  style={{ top: `${String(((minute - gridWindow.start) / 60) * HOUR_PX)}px` }}
                  aria-hidden
                />
              ))}

              {placeDay(dayItems).map(({ item, lane, lanes }) =>
                item.kind === 'class' ? (
                  <ClassBlock
                    key={itemKey(item)}
                    placed={{ item, lane, lanes }}
                    window={gridWindow}
                    slot={colors.get(item.event.course_id)}
                  />
                ) : item.kind === 'sitting' ? (
                  <SittingBlock
                    key={itemKey(item)}
                    placed={{ item, lane, lanes }}
                    window={gridWindow}
                    slot={colors.get(item.assignment.course_id)}
                  />
                ) : (
                  <ExternalBlock
                    key={itemKey(item)}
                    placed={{ item, lane, lanes }}
                    window={gridWindow}
                    slot={externalSlot(item.external, colors)}
                    animate={animateExternal}
                  />
                ),
              )}

              {isToday && nowVisible ? (
                <span className="absolute inset-x-0 top-0 h-px bg-primary" style={nowStyle} aria-hidden />
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
