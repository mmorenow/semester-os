import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChartBar } from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { EmptyState } from '@/components/empty-state'
import { useProjection } from '@/lib/school-queries'
import type { GradeCategory, GradeSummary } from '@/lib/school-types'
import { useReducedMotion } from '@/lib/use-reduced-motion'
import { cn } from '@/lib/utils'
import { segmentClass, segmentHoverClass } from './course-color'
import {
  GRADE_TARGETS,
  buildComposition,
  gradedLabel,
  num,
  pct,
  safe,
} from './grade-model'
import { Panel, PanelHeader } from './school-parts'

/** Banked, lost and open in one 4px track, with the same numbers in words so color isn't the only cue. */
function StandingTrack({ overall }: { overall: GradeSummary['overall'] }) {
  const secured = safe(overall.secured_pct)
  const lost = safe(overall.lost_pct)
  const remaining = safe(overall.remaining_pct)
  const unmapped = safe(overall.unallocated_pct)
  const total = secured + lost + remaining + unmapped

  if (total <= 0) return null

  const segments = [
    { key: 'secured', value: secured, fill: 'bg-signal-green-solid' },
    { key: 'lost', value: lost, fill: 'bg-signal-red-solid' },
    { key: 'remaining', value: remaining, fill: 'bg-muted' },
    { key: 'unmapped', value: unmapped, fill: 'bg-border' },
  ].filter((segment) => segment.value > 0)

  return (
    <div
      className="flex h-1 w-full overflow-hidden rounded-sm bg-muted"
      role="img"
      aria-label={`Secured ${pct(secured)}, lost ${pct(lost)}, still open ${pct(remaining)}.`}
    >
      {segments.map((segment) => (
        <span
          key={segment.key}
          className={segment.fill}
          style={{ width: `${String((segment.value / total) * 100)}%` }}
        />
      ))}
    </div>
  )
}

function StandingFigure({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn('num text-sm', tone)}>{value}</span>
    </div>
  )
}

const SETTLE_MS = 260
/** A change smaller than this is a rounding artifact, and animating it looks broken. */
const SETTLE_FLOOR = 0.5

/** in-out-cubic, same curve as `--ease-shift`. */
function easeShift(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

/** The final value's own precision, held for every frame of the tween. */
function places(value: number): number {
  return Number.isInteger(Math.round(value * 10) / 10) ? 0 : 1
}

/**
 * The current average. Animates only when the value changes while on screen (never on mount or
 * same-value refetch): 260ms for the value, 160ms for the ink. Duration doesn't scale with the delta.
 */
function SettlingFigure({ value }: { value: number }) {
  const reducedMotion = useReducedMotion()
  const node = useRef<HTMLSpanElement>(null)
  const previous = useRef(value)
  const [settling, setSettling] = useState(false)

  useLayoutEffect(() => {
    const from = previous.current
    previous.current = value
    const target = node.current
    if (!target) return
    if (from === value) return

    const digits = places(value)
    if (reducedMotion || Math.abs(value - from) < SETTLE_FLOOR) {
      target.textContent = value.toFixed(digits)
      return
    }

    // React already committed the final figure; write the old one back before paint to avoid a flash.
    target.textContent = from.toFixed(digits)
    setSettling(true)

    let frame = 0
    const started = performance.now()
    const step = (stamp: number) => {
      const progress = Math.min(1, (stamp - started) / SETTLE_MS)
      target.textContent = (from + (value - from) * easeShift(progress)).toFixed(digits)
      if (progress < 1) frame = requestAnimationFrame(step)
      else setSettling(false)
    }
    frame = requestAnimationFrame(step)

    return () => {
      cancelAnimationFrame(frame)
      target.textContent = value.toFixed(digits)
      setSettling(false)
    }
  }, [value, reducedMotion])

  return (
    <span ref={node} className={cn(settling && 'settle-ink')}>
      {value.toFixed(places(value))}
    </span>
  )
}

function Standing({ overall }: { overall: GradeSummary['overall'] }) {
  const average = overall.current_avg_pct

  return (
    <div className="flex flex-col gap-2.5 px-3 py-3">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Current average</span>
          {average === null || average === undefined ? (
            // `.lede` at the 34px figure's slot so an empty panel doesn't read as broken. Only here.
            <span className="lede text-muted-foreground">Nothing graded yet</span>
          ) : (
            // The route's one display figure.
            <span className="display-num text-foreground">
              <SettlingFigure value={average} />
              <span className="display-unit">%</span>
            </span>
          )}
        </div>

        <div className="flex items-end gap-5">
          <StandingFigure label="Secured" value={pct(overall.secured_pct)} tone="text-signal-green" />
          <StandingFigure label="Lost" value={pct(overall.lost_pct)} tone="text-signal-red" />
          <StandingFigure label="Still open" value={pct(overall.remaining_pct)} tone="text-foreground" />
          {safe(overall.unallocated_pct) > 0 ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <StandingFigure
                    label="Unmapped"
                    value={pct(overall.unallocated_pct)}
                    tone="text-muted-foreground"
                  />
                </div>
              </TooltipTrigger>
              <TooltipContent>
                This much of the final grade is not attached to any category the syllabus named.
              </TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      </div>

      <StandingTrack overall={overall} />
    </div>
  )
}

interface SelectionProps {
  selected: string | null
  onSelect: (category: string | null) => void
}

/**
 * Stacked bar: segment width is category weight, fill is the course tint at 28/38% (labels are
 * `text-foreground`, 7.4:1 at the top). The selected segment goes solid accent: a tint deep enough
 * to outrank neighbors fails `text-primary` at 4.34:1 in dark.
 */
function CompositionBar({
  summary,
  slot,
  selected,
  onSelect,
}: { summary: GradeSummary; slot: number | undefined } & SelectionProps) {
  const composition = buildComposition(summary)
  if (composition.slices.length === 0 && composition.unallocatedShare === 0) return null

  return (
    <div
      className="flex h-7 w-full overflow-hidden rounded-sm border border-border"
      role="group"
      aria-label="Grade weight by category"
    >
      {composition.slices.map(({ category, share }, index) => {
        const active = selected === category.name
        return (
          <button
            key={category.name}
            type="button"
            aria-pressed={active}
            aria-label={`${category.name}, ${pct(category.weight_pct)} of the final grade`}
            onClick={() => { onSelect(active ? null : category.name) }}
            style={{ width: `${String(share)}%`, minWidth: '3px' }}
            className={cn(
              'focus-ring-inset flex min-w-0 items-center gap-1.5 px-1.5 text-xs transition-colors duration-[120ms]',
              index > 0 && 'border-l border-border',
              active
                ? 'bg-primary font-medium text-primary-foreground'
                : cn('text-foreground', segmentClass(slot), segmentHoverClass(slot)),
            )}
          >
            {share >= 11 ? <span className="truncate">{category.name}</span> : null}
            {share >= 5 ? <span className="num ml-auto shrink-0">{pct(category.weight_pct)}</span> : null}
          </button>
        )
      })}

      {composition.unallocatedShare > 0 ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              role="img"
              aria-label={`Unmapped, ${pct(composition.unallocatedPct)} of the final grade`}
              style={{ width: `${String(composition.unallocatedShare)}%`, minWidth: '3px' }}
              className="flex min-w-0 items-center gap-1.5 border-l border-border bg-muted px-1.5 text-xs text-muted-foreground"
            >
              {composition.unallocatedShare >= 11 ? <span className="truncate">Unmapped</span> : null}
              {composition.unallocatedShare >= 5 ? (
                <span className="num ml-auto shrink-0">{pct(composition.unallocatedPct)}</span>
              ) : null}
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <span className="num">{pct(composition.unallocatedPct)}</span> of the grade has no category
            in the syllabus Semester OS has read.
          </TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  )
}

type WashTone = 'up' | 'down'

const WASH_MS = 600

function categoryMarks(summary: GradeSummary | null | undefined): Map<string, number> {
  const marks = new Map<string, number>()
  for (const category of summary?.categories ?? []) {
    marks.set(category.name, safe(category.secured_pct) - safe(category.lost_pct))
  }
  return marks
}

/** Rows whose numbers changed get a 600ms wash in the direction the average moved. Never on mount. */
function useGradeWashes(
  summary: GradeSummary | null | undefined,
  reducedMotion: boolean,
): Map<string, WashTone> {
  const previous = useRef<{ marks: Map<string, number>; average: number | null } | null>(null)
  const [washes, setWashes] = useState<Map<string, WashTone>>(new Map())

  useEffect(() => {
    const marks = categoryMarks(summary)
    const average = summary?.overall.current_avg_pct ?? null
    const before = previous.current
    previous.current = { marks, average }

    // Nothing to compare yet, or reduced motion.
    if (!before || reducedMotion) return

    const tone: WashTone =
      average !== null && before.average !== null && average < before.average ? 'down' : 'up'

    const moved = new Map<string, WashTone>()
    for (const [name, value] of marks) {
      const was = before.marks.get(name)
      if (was !== undefined && was !== value) moved.set(name, tone)
    }
    if (moved.size === 0) return
    setWashes(moved)
  }, [summary, reducedMotion])

  // Cleared in its own pass so a summary arriving mid-decay restarts the clock.
  useEffect(() => {
    if (washes.size === 0) return
    const timer = setTimeout(() => { setWashes(new Map()) }, WASH_MS)
    return () => { clearTimeout(timer) }
  }, [washes])

  return washes
}

function CategoryRow({
  category,
  selected,
  onSelect,
  wash,
}: { category: GradeCategory; wash: WashTone | null } & SelectionProps) {
  const active = selected === category.name
  const points =
    category.earned_max === null || category.earned_max === undefined
      ? null
      : `${num(category.earned_points)}/${num(category.earned_max)}`

  return (
    <tr
      role="button"
      tabIndex={0}
      aria-pressed={active}
      onClick={() => { onSelect(active ? null : category.name) }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect(active ? null : category.name)
        }
      }}
      className={cn(
        'focus-ring-inset cursor-pointer border-b border-border transition-colors duration-[80ms] last:border-b-0',
        active ? 'bg-primary/8 hover:bg-primary/12' : 'hover:bg-muted/50',
        // One-shot 600ms wash on a row whose number just moved.
        wash === 'up' && 'grade-wash-up',
        wash === 'down' && 'grade-wash-down',
      )}
    >
      <td className="px-3 py-2">
        <div className="flex items-center gap-1.5">
          <span className={cn('truncate text-sm', active ? 'text-primary' : 'text-foreground')}>
            {category.name}
          </span>
          {category.split_known ? null : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="h-5 shrink-0 px-1.5 font-normal text-xs text-muted-foreground">
                  split not published
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                The syllabus states this category's total but not how it divides across items, so the
                per-item weights below are unknown rather than estimated.
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </td>
      <td className="num px-3 py-2 text-right text-[13px] text-foreground">{pct(category.weight_pct)}</td>
      <td className="num px-3 py-2 text-right text-[13px] text-muted-foreground">{gradedLabel(category)}</td>
      <td className="num px-3 py-2 text-right text-[13px] text-muted-foreground">{points ?? '--'}</td>
      <td className="num px-3 py-2 text-right text-[13px] text-signal-green">{pct(category.secured_pct)}</td>
      <td className="num px-3 py-2 text-right text-[13px] text-signal-red">{pct(category.lost_pct)}</td>
      <td className="num px-3 py-2 text-right text-[13px] text-foreground/90">{pct(category.remaining_pct)}</td>
    </tr>
  )
}

// Heads at 13px, the same step as the cells.
const HEAD_CELL = 'px-3 py-2 text-[13px] font-medium text-muted-foreground'

function CategoryTable({
  categories,
  selected,
  onSelect,
  washes,
}: { categories: GradeCategory[]; washes: Map<string, WashTone> } & SelectionProps) {
  if (categories.length === 0) return null
  return (
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border">
            <th className={cn(HEAD_CELL, 'text-left')}>Category</th>
            <th className={cn(HEAD_CELL, 'text-right')}>Weight</th>
            <th className={cn(HEAD_CELL, 'text-right')}>Graded</th>
            <th className={cn(HEAD_CELL, 'text-right')}>Points</th>
            <th className={cn(HEAD_CELL, 'text-right')}>Secured</th>
            <th className={cn(HEAD_CELL, 'text-right')}>Lost</th>
            <th className={cn(HEAD_CELL, 'text-right')}>Open</th>
          </tr>
        </thead>
        <tbody>
          {categories.map((category) => (
            <CategoryRow
              key={category.name}
              category={category}
              selected={selected}
              onSelect={onSelect}
              wash={washes.get(category.name) ?? null}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

const CUSTOM = 'custom'
/** Start with A- rather than a blank field. */
const DEFAULT_TARGET = 90

function ProjectionLine({ courseId, target }: { courseId: number; target: number | null }) {
  const projection = useProjection(courseId, target)

  if (target === null) {
    return <span className="text-[13px] text-muted-foreground">Enter a target percentage.</span>
  }
  if (projection.isPending) {
    return <Skeleton className="h-3.5 w-56" />
  }
  if (projection.isError || !projection.data) {
    return (
      <span className="text-[13px] text-muted-foreground">
        The projection endpoint did not answer, so nothing is claimed here.
      </span>
    )
  }

  const { needed_avg_pct: needed, remaining_pct: remaining, secured_pct: secured, feasible } = projection.data

  if (!feasible || needed === null) {
    const ceiling = secured + remaining
    return (
      <span className="text-[13px] text-foreground/90">
        <span className="text-signal-red">Not reachable.</span> Full marks on the remaining{' '}
        <span className="num">{pct(remaining)}</span> lands at <span className="num">{pct(ceiling)}</span>.
      </span>
    )
  }

  // Above 95 is possible but leaves no room for a bad week.
  const tone = needed > 95 ? 'text-signal-amber' : 'text-foreground'

  return (
    <span className="text-[13px] text-foreground/90">
      You need an average of <span className={cn('num font-medium', tone)}>{pct(needed)}</span> across the
      remaining <span className="num">{pct(remaining)}</span>.
    </span>
  )
}

function WhatIfRow({ courseId }: { courseId: number }) {
  const [choice, setChoice] = useState<string>(String(DEFAULT_TARGET))
  const [customDraft, setCustomDraft] = useState('')
  const [custom, setCustom] = useState<number | null>(null)

  // Debounced so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      const parsed = Number(customDraft)
      setCustom(customDraft.trim() !== '' && Number.isFinite(parsed) && parsed > 0 && parsed <= 100 ? parsed : null)
    }, 300)
    return () => { clearTimeout(timer) }
  }, [customDraft])

  const target = choice === CUSTOM ? custom : Number(choice)

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border bg-muted/40 px-3 py-2.5">
      <label htmlFor="grade-target" className="text-xs text-muted-foreground">
        Target
      </label>
      <Select value={choice} onValueChange={setChoice}>
        <SelectTrigger id="grade-target" className="w-[116px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {GRADE_TARGETS.map((entry) => (
            <SelectItem key={entry.label} value={String(entry.pct)}>
              {entry.label} <span className="num text-muted-foreground">{String(entry.pct)}%</span>
            </SelectItem>
          ))}
          <SelectItem value={CUSTOM}>Custom</SelectItem>
        </SelectContent>
      </Select>

      {choice === CUSTOM ? (
        <>
          <label htmlFor="grade-target-custom" className="sr-only">
            Custom target percentage
          </label>
          <Input
            id="grade-target-custom"
            value={customDraft}
            onChange={(event) => { setCustomDraft(event.target.value) }}
            inputMode="decimal"
            placeholder="88"
            autoComplete="off"
            className="num w-16 caret-primary"
          />
        </>
      ) : null}

      <ProjectionLine courseId={courseId} target={target} />
    </div>
  )
}

export function GradeCenterSkeleton() {
  return (
    <Panel>
      <PanelHeader title="Grade center" icon={ChartBar} />
      <div className="flex flex-col gap-3 px-3 py-3">
        <div className="flex items-end justify-between gap-6">
          {/* Shaped like the real standing block. */}
          <Skeleton className="h-[56px] w-28" />
          <div className="flex gap-5">
            {Array.from({ length: 3 }, (_, index) => (
              <Skeleton key={index} className="h-10 w-16" />
            ))}
          </div>
        </div>
        <Skeleton className="h-1 w-full rounded-sm" />
        <Skeleton className="h-7 w-full rounded-sm" />
      </div>
      <div className="border-t border-border">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="flex items-center gap-3 border-b border-border px-3 py-2.5 last:border-b-0">
            <Skeleton className="h-3.5 flex-1" />
            <Skeleton className="h-3.5 w-12" />
            <Skeleton className="h-3.5 w-12" />
            <Skeleton className="h-3.5 w-12" />
          </div>
        ))}
      </div>
    </Panel>
  )
}

interface GradeCenterProps extends SelectionProps {
  courseId: number
  summary: GradeSummary | null | undefined
  slot: number | undefined
  /** Grading insights the syllabus extractor wrote, shown under the table. */
  insights?: string[]
}

/** Course page centerpiece: standing, composition, category table, and what-if. */
export function GradeCenter({ courseId, summary, slot, selected, onSelect, insights = [] }: GradeCenterProps) {
  const reducedMotion = useReducedMotion()
  const washes = useGradeWashes(summary, reducedMotion)
  const categories = summary?.categories ?? []
  const hasWeights = buildComposition(summary).total > 0

  if (!summary || (!hasWeights && categories.length === 0)) {
    return (
      <Panel>
        <PanelHeader title="Grade center" icon={ChartBar} />
        <EmptyState
          size="inline"
          icon={ChartBar}
          title="No grading weights yet"
          description="This course has no syllabus weights on file, so nothing here can be computed. Import the syllabus to fill it."
        />
      </Panel>
    )
  }

  return (
    <Panel>
      <PanelHeader
        title="Grade center"
        icon={ChartBar}
        meta={
          categories.length > 0 ? (
            <>
              <span className="num">{String(categories.length)}</span>{' '}
              {categories.length === 1 ? 'category' : 'categories'}
            </>
          ) : undefined
        }
        action={
          selected ? (
            <button
              type="button"
              onClick={() => { onSelect(null) }}
              className="focus-ring rounded-sm text-xs text-muted-foreground transition-colors duration-[120ms] hover:text-foreground active:scale-[0.98]"
            >
              Clear filter
            </button>
          ) : null
        }
      />

      <Standing overall={summary.overall} />

      <div className="px-3 pb-3">
        <CompositionBar summary={summary} slot={slot} selected={selected} onSelect={onSelect} />
      </div>

      <CategoryTable
        categories={categories}
        selected={selected}
        onSelect={onSelect}
        washes={washes}
      />

      {/* A washed subordinate strip; one per panel, never next to a course wash. */}
      {insights.length > 0 ? (
        <ul className="flex flex-col gap-1 border-t border-border bg-muted/40 px-3 py-2.5">
          {insights.slice(0, 2).map((insight) => (
            <li
              key={insight}
              className="relative pl-3 text-[13px] leading-relaxed text-muted-foreground before:absolute before:left-0 before:content-['-']"
            >
              {insight}
            </li>
          ))}
        </ul>
      ) : null}

      <WhatIfRow courseId={courseId} />
    </Panel>
  )
}
