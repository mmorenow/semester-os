import { ArrowsClockwise, CalendarBlank, NotePencil } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { EXTERNAL_SOURCES, EXTERNAL_SOURCE_LABEL, listNames } from '@/lib/school-labels'
import { useSyncNow, type SyncFailure } from '@/lib/school-queries'
import { startGcalConnect } from '@/lib/gcal-connect'
import { formatClock, formatClockRange } from '@/lib/school-time'
import type { ExternalEvent, ExternalSource, SyncStatus } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { CourseMark } from './course-mark'
import { BrandMark } from './course-platforms'
import type { TimedExternal } from './event-time'
import { gcalHealth } from './gcal-connection'
import { platformMark } from './platform-identity'
import { SCHOOL_BADGE, SyncAge } from './school-parts'

/**
 * External calendar layer (Outlook, Brightspace, Google, Notes). No course color: a feed names its
 * course in free text, so matching would be a guess. Externals get a `bg-foreground/10` wash, a
 * dashed hairline and a 14px monochrome logo. A Notes event with a resolved course takes its chip.
 */

/** Course slot for a Notes event with a known course; otherwise undefined. */
export function externalSlot(external: ExternalEvent, colors: Map<number, number>): number | undefined {
  if (external.source !== 'notes' || external.course_id === null || external.course_id === undefined) {
    return undefined
  }
  return colors.get(external.course_id)
}

/** The course code a `notes` event names, when it names one. */
export function externalCourseCode(external: ExternalEvent): string | null {
  return external.source === 'notes' && external.course_code ? external.course_code : null
}

/** Source logo, 14px monochrome: brand hexes only clear 3:1 on untinted `--card`, not on the wash. */
export function SourceMark({ source, className }: { source: ExternalSource; className?: string }) {
  // Notes is this app's own surface, so it uses the rail's Notes glyph.
  const mark = source === 'notes' ? null : platformMark(EXTERNAL_SOURCE_LABEL[source])
  if (!mark) {
    const Glyph = source === 'notes' ? NotePencil : CalendarBlank
    return (
      <span
        className={cn('flex size-4 shrink-0 items-center justify-center text-muted-foreground', className)}
        aria-hidden
      >
        <Glyph size={14} />
      </span>
    )
  }
  return <BrandMark mark={mark} tone="neutral" className={className} />
}

/** `9-10p`, or the single clock time for a deadline the feed states as a point. */
export function externalTimeLabel(item: TimedExternal): string {
  if (item.allDay) return 'All day'
  if (item.instant) return formatClock(item.startMin)
  return formatClockRange(item.startMin, item.endMin)
}

/** The screen-reader sentence for one external event, wherever it renders. */
export function externalLabel(item: TimedExternal): string {
  const code = externalCourseCode(item.external)
  const source = EXTERNAL_SOURCE_LABEL[item.external.source]
  return `${code ? `${source}, ${code}` : source}: ${item.external.title}, ${externalTimeLabel(item)}`
}

/** External event row on `ScheduleRow`'s geometry, with the source logo instead of a course chip and no link. */
export function ExternalRow({
  item,
  slot,
  past = false,
}: {
  item: TimedExternal
  /** The course slot, for a Notes event that names a course. */
  slot?: number
  past?: boolean
}) {
  const code = externalCourseCode(item.external)
  return (
    <li className="border-b border-border last:border-b-0">
      <div
        className={cn(
          'flex items-stretch transition-[background-color,opacity] duration-[80ms] hover:bg-muted/50',
          past && 'opacity-55 hover:opacity-100',
        )}
      >
        <span className="num flex w-[112px] shrink-0 items-center justify-end py-2 pr-2 pl-3 text-xs text-muted-foreground">
          {externalTimeLabel(item)}
        </span>
        <div className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2">
          {code ? <CourseMark code={code} slot={slot} /> : <SourceMark source={item.external.source} />}
          <span className="truncate text-sm text-foreground/90">{item.external.title}</span>
          <span className="sr-only">{`, from ${EXTERNAL_SOURCE_LABEL[item.external.source]}`}</span>
          {item.external.location ? (
            <span className="ml-auto max-w-[38%] shrink-0 truncate text-xs text-muted-foreground">
              {item.external.location}
            </span>
          ) : null}
        </div>
      </div>
    </li>
  )
}

interface SourceAge {
  source: ExternalSource
  at: string | null
  ok: boolean
  error: string | null
  /** Google's connection is what failed, not one read of it. */
  disconnected?: boolean
}

/** Only configured feeds; unconfigured ones are absent from the `ics` map and skipped. */
function configuredSources(status: SyncStatus | undefined): SourceAge[] {
  const rows: SourceAge[] = []
  for (const source of EXTERNAL_SOURCES) {
    const entry = status?.ics?.[source]
    if (!entry?.configured) continue
    rows.push({
      source,
      at: entry.last_sync_at ?? null,
      ok: entry.ok !== false,
      error: entry.error ?? null,
    })
  }

  // The connection outranks the last pull: a dead token can hide behind yesterday's successful sync.
  const health = gcalHealth(status?.gcal)
  if (health && status?.gcal?.connected !== true) {
    const google = rows.find((row) => row.source === 'gcal')
    const broken = { ok: false, error: health.reason, disconnected: true }
    if (google) Object.assign(google, broken)
    else if (status?.gcal?.account_email || status?.gcal?.error) {
      rows.push({ source: 'gcal', at: status.gcal.last_sync_at ?? null, ...broken })
    }
  }
  return rows
}

/** Feeds a sync would read. Google comes from the connection, since older servers omit it from `ics`. */
function syncTargetLabels(status: SyncStatus | undefined): string[] {
  const names = configuredSources(status).map((entry) => EXTERNAL_SOURCE_LABEL[entry.source])
  const google = EXTERNAL_SOURCE_LABEL.gcal
  if (status?.gcal?.configured === true && status.gcal.connected === true && !names.includes(google)) {
    names.push(google)
  }
  return names
}

/**
 * One staleness badge per surface: the oldest configured feed's age, each feed named in the
 * tooltip. A failure outranks any age.
 */
export function ExternalSyncBadge({
  status,
  quiet = false,
  className,
}: {
  status: SyncStatus | undefined
  /** No external events to stamp: hide the badge, unless something failed. */
  quiet?: boolean
  className?: string
}) {
  const sources = configuredSources(status)
  if (sources.length === 0) return null

  const failed = sources.filter((entry) => !entry.ok)
  if (quiet && failed.length === 0) return null
  if (failed.length > 0) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            className={cn(
              SCHOOL_BADGE,
              // A lapsed Google sign-in is a warning; a failed feed read is red.
              failed.every((entry) => entry.disconnected)
                ? 'border-signal-amber/45 text-signal-amber'
                : 'border-signal-red/45 text-signal-red',
              className,
            )}
          >
            {/* Past one failure, show the count; the tooltip names each. */}
            {failed.length === 1 && failed[0].disconnected ? (
              `${EXTERNAL_SOURCE_LABEL[failed[0].source]} disconnected`
            ) : failed.length === sources.length ? (
              'Sync failed'
            ) : failed.length === 1 ? (
              `${EXTERNAL_SOURCE_LABEL[failed[0].source]} failed`
            ) : (
              <>
                <span className="num">{String(failed.length)}</span> feeds failed
              </>
            )}
          </Badge>
        </TooltipTrigger>
        <TooltipContent className="max-w-[46ch]">
          {failed.map((entry) => (
            <span key={entry.source} className="block">
              {EXTERNAL_SOURCE_LABEL[entry.source]}: {entry.error ?? 'the last sync did not finish.'}
            </span>
          ))}
        </TooltipContent>
      </Tooltip>
    )
  }

  // The stalest feed sets the age; `null` (never run) sorts first.
  const oldest = sources.reduce<SourceAge>((worst, entry) => {
    if (worst.at === null) return worst
    if (entry.at === null) return entry
    return new Date(entry.at).getTime() < new Date(worst.at).getTime() ? entry : worst
  }, sources[0])

  const names = listNames(sources.map((entry) => EXTERNAL_SOURCE_LABEL[entry.source]))
  return <SyncAge at={oldest.at} source={names} className={className} />
}

/** The reason line under a failure toast, without repeating the headline. */
function failureDetail(failed: SyncFailure[]): string {
  if (failed.length === 1) return failed[0].error
  return failed.map((entry) => `${EXTERNAL_SOURCE_LABEL[entry.source]}: ${entry.error}`).join(' ')
}

/**
 * Read the calendar feeds now. No spinner: the label and a refused second press carry the busy state.
 * Busy is `aria-disabled`, not `disabled`, so keyboard focus isn't dropped mid-run.
 */
export function SyncNowButton({
  status,
  size = 'xs',
  className,
}: {
  /** The same status the badge beside it reads. Undefined until it answers. */
  status: SyncStatus | undefined
  /** `xs` inside a panel header, `sm` in a page toolbar beside `h-7` controls. */
  size?: 'xs' | 'sm'
  className?: string
}) {
  const sync = useSyncNow()
  const targets = syncTargetLabels(status)
  const busy = sync.isPending

  function handleClick() {
    if (busy) return
    sync.mutate(undefined, {
      onSuccess: (outcome) => {
        if (outcome.failed.length > 0) {
          const names = listNames(outcome.failed.map((entry) => EXTERNAL_SOURCE_LABEL[entry.source]))
          const disconnected = outcome.failed.some((entry) => entry.disconnected)
          toast.error(`${names} did not sync`, {
            description: failureDetail(outcome.failed),
            // Only a reconnect fixes this. The toast action is a user gesture, so the popup is allowed.
            action: disconnected
              ? {
                  label: 'Reconnect',
                  onClick: () => {
                    startGcalConnect().catch((error: unknown) => {
                      toast.error('Could not open the Google sign-in', {
                        description: error instanceof Error ? error.message : 'The server did not answer.',
                      })
                    })
                  },
                }
              : undefined,
          })
          return
        }
        if (outcome.ran.length === 0) {
          toast.info('No calendar feed is configured', {
            description: 'Add the Outlook or Brightspace feed URL to config.yaml (see the Connect page), or connect Google, and this will read them.',
          })
          return
        }
        toast.success(`Synced ${listNames(outcome.ran.map((source) => EXTERNAL_SOURCE_LABEL[source]))}`, {
          // The server's own figures, when it has any.
          description: outcome.googleDetail.length > 0 ? `Google: ${outcome.googleDetail.join(' · ')}` : undefined,
        })
      },
      onError: (error: unknown) => {
        toast.error('Sync did not run', {
          description:
            error instanceof Error
              ? error.message
              : 'The Semester OS server did not answer. Check that it is still running.',
        })
      },
    })
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size={size}
          onClick={handleClick}
          aria-disabled={busy || undefined}
          aria-busy={busy || undefined}
          className={cn('aria-disabled:pointer-events-none aria-disabled:opacity-50', className)}
        >
          <ArrowsClockwise data-icon="inline-start" />
          {busy ? 'Syncing' : 'Sync now'}
        </Button>
      </TooltipTrigger>
      <TooltipContent className="max-w-[46ch]">
        {targets.length > 0
          ? `Read ${listNames(targets)} now.`
          : 'No calendar feed is configured yet.'}
      </TooltipContent>
    </Tooltip>
  )
}
