// Activity vocabulary for the activity bar and rail chip. Imports nothing, so both
// `school-queries.ts` and `use-activity.ts` can depend on it.

/**
 * What kind of work this is:
 *   run    an agent executing something
 *   sync   reading an outside source (calendar feeds)
 *   build  producing an artifact (reserved)
 *   write  saving something typed
 */
export type ActivityKind = 'run' | 'sync' | 'build' | 'write'

/** What a mutation declares about itself through `meta`. */
export interface ActivityMeta {
  label: string
  kind: ActivityKind
}

/** One thing in flight, as the bar and the chip see it. */
export interface ActivityOperation {
  /** Stable for the life of the operation, so React keys do not churn. */
  id: string
  label: string
  /** The second line in the popover: which note, which course. Optional. */
  detail?: string | null
  kind: ActivityKind
  /** Epoch milliseconds. Elapsed time is derived, never stored. */
  startedAt: number
}

export interface Activity {
  /** True once something has been in flight longer than `ACTIVITY_APPEAR_MS`. */
  active: boolean
  /** Oldest first. Empty when idle. */
  operations: ActivityOperation[]
  count: number
  /** The operation whose elapsed time the collapsed chip shows. */
  oldest: ActivityOperation | null
}

export const IDLE_ACTIVITY: Activity = { active: false, operations: [], count: 0, oldest: null }

/**
 * Delay before the bar shows, so fast autosaves don't strobe it; under the ~400ms where a wait is felt.
 * Elapsed time still counts from the real start.
 */
export const ACTIVITY_APPEAR_MS = 300

/**
 * Tag a mutation so it names itself in the activity popover; untagged ones get a generic label.
 * `useMutation({ mutationFn, meta: activityMeta('Calendar sync', 'sync') })`
 */
export function activityMeta(label: string, kind: ActivityKind): { activity: ActivityMeta } {
  return { activity: { label, kind } }
}

/** Label for untagged mutations. */
export const UNLABELLED_ACTIVITY: ActivityMeta = { label: 'Saving', kind: 'write' }

/** Reads back what `activityMeta` wrote, defensively: `meta` is `unknown`. */
export function readActivityMeta(meta: unknown): ActivityMeta {
  if (!meta || typeof meta !== 'object') return UNLABELLED_ACTIVITY
  const candidate = (meta as { activity?: unknown }).activity
  if (!candidate || typeof candidate !== 'object') return UNLABELLED_ACTIVITY
  const { label, kind } = candidate as { label?: unknown; kind?: unknown }
  if (typeof label !== 'string' || typeof kind !== 'string') return UNLABELLED_ACTIVITY
  if (kind !== 'run' && kind !== 'sync' && kind !== 'build' && kind !== 'write') {
    return UNLABELLED_ACTIVITY
  }
  return { label, kind }
}
