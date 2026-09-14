import { useEffect, useState } from 'react'
import { ArrowsClockwise, FloppyDisk, Hammer, Lightning } from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Elapsed } from '@/components/elapsed'
import { useReducedMotion } from '@/lib/use-reduced-motion'
import type { Activity, ActivityKind } from '@/lib/activity'
import { cn } from '@/lib/utils'

const KIND_ICON: Record<ActivityKind, Icon> = {
  run: Lightning,
  sync: ArrowsClockwise,
  build: Hammer,
  write: FloppyDisk,
}

/** Always decorative: a label or an `aria-label` sits beside every one of these. */
function KindGlyph({ kind, size, className }: { kind: ActivityKind; size: number; className?: string }) {
  const Glyph = KIND_ICON[kind]
  return <Glyph size={size} className={className} aria-hidden />
}

/** Matches `duration-150` below. Opacity, not height: a 2px bar growing from nothing reads as a layout bug. */
const FADE_MS = 150

/**
 * 2px indeterminate bar across the top of the shell, the app's only loop.
 * Reduced motion shows a still bar at `bg-primary/40` (backstopped in index.css).
 * `aria-hidden`: the chip carries the accessible status.
 */
export function ActivityBar({ activity }: { activity: Activity }) {
  const reduced = useReducedMotion()
  const active = activity.active

  // The container stays mounted so opacity transitions both ways; the looping child unmounts when idle.
  const [lingering, setLingering] = useState(false)
  useEffect(() => {
    if (active) {
      setLingering(true)
      return
    }
    if (!lingering) return
    const timer = window.setTimeout(() => { setLingering(false) }, FADE_MS + 30)
    return () => { window.clearTimeout(timer) }
  }, [active, lingering])

  return (
    <div
      aria-hidden
      className={cn(
        // z-[60]: above sheets and dialogs (z-50) so their scrim never dims it.
        'pointer-events-none fixed inset-x-0 top-0 z-[60] h-0.5 transition-opacity duration-150 ease-enter',
        active ? 'opacity-100' : 'opacity-0',
      )}
    >
      {active || lingering ? (
        reduced ? (
          <div className="h-full w-full bg-primary/40" />
        ) : (
          <div className="relative h-full w-full overflow-hidden bg-muted">
            <div className="activity-sweep absolute inset-y-0 left-0 w-1/4 bg-primary" />
          </div>
        )
      ) : null}
    </div>
  )
}

function summarise(activity: Activity): string {
  if (activity.count === 1 && activity.oldest) return activity.oldest.label
  return `${String(activity.count)} running`
}

function announce(activity: Activity): string {
  if (!activity.active) return ''
  if (activity.count === 1 && activity.oldest) return `${activity.oldest.label} is running`
  return `${String(activity.count)} operations running`
}

/** Rail chip: run count, oldest run's kind and elapsed time. No percentages, runs publish no progress. */
export function ActivityChip({ activity }: { activity: Activity }) {
  const oldest = activity.oldest
  const summary = summarise(activity)

  return (
    <>
      {/* Announces count changes only; the ticking elapsed is outside this region. */}
      <p role="status" aria-live="polite" className="sr-only">
        {announce(activity)}
      </p>

      {activity.active && oldest ? (
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={`Activity: ${announce(activity)}`}
              className="flex h-8 items-center justify-center gap-2.5 rounded-md px-2.5 text-xs text-foreground transition-colors hover:bg-muted active:scale-[0.98] lg:justify-start"
            >
              {/* 18px, the rail's glyph size, to align with the nav items. */}
              <KindGlyph kind={oldest.kind} size={18} className="shrink-0 text-primary" />
              <span className="hidden min-w-0 truncate lg:inline">{summary}</span>
              <Elapsed
                since={oldest.startedAt}
                className="ml-auto hidden text-2xs text-muted-foreground lg:inline"
              />
              {activity.count > 1 ? (
                <span className="num text-2xs text-muted-foreground lg:hidden" aria-hidden>
                  {activity.count}
                </span>
              ) : null}
            </button>
          </PopoverTrigger>

          <PopoverContent side="right" align="end" className="gap-2">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-2xs font-medium text-muted-foreground">Running now</span>
              <span className="num text-2xs text-muted-foreground">{activity.count}</span>
            </div>

            <ul className="flex flex-col gap-2">
              {activity.operations.map((operation) => (
                <li key={operation.id} className="flex items-start gap-2">
                  <KindGlyph kind={operation.kind} size={14} className="mt-px shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs text-foreground">{operation.label}</span>
                    {operation.detail ? (
                      <span className="block truncate text-2xs text-muted-foreground">{operation.detail}</span>
                    ) : null}
                  </span>
                  <Elapsed since={operation.startedAt} className="shrink-0 text-2xs text-muted-foreground" />
                </li>
              ))}
            </ul>

            <p className="border-t border-border pt-2 text-2xs leading-relaxed text-muted-foreground">
              Elapsed time only. None of these runs reports progress.
            </p>
          </PopoverContent>
        </Popover>
      ) : null}
    </>
  )
}
