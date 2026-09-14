import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutationState, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiRequest, buildQuery } from './api'
import { isLive, queryKeys } from './queries'
import { actionTypeLabel } from './labels'
import {
  ACTIVITY_APPEAR_MS,
  readActivityMeta,
  type Activity,
  type ActivityOperation,
} from './activity'
import type { ActionsResponse, AgentAction } from './types'

// Activity reads a short recent window of GET /api/actions rather than `status=running`, so a run
// that just finished still carries its outcome. Polls every 3s while live, 20s otherwise, never in a
// background tab; creating a note invalidates `actions` immediately.

const ACTIVITY_WINDOW = 12
const POLL_LIVE_MS = 3000
const POLL_IDLE_MS = 20_000

function pollInterval(anyLive: boolean): number {
  return anyLive ? POLL_LIVE_MS : POLL_IDLE_MS
}

function useRecentActions() {
  const status = 'pending,running,done,failed,cancelled'
  return useQuery({
    queryKey: queryKeys.actions({ status, limit: ACTIVITY_WINDOW }),
    queryFn: async () => {
      const response = await apiRequest<ActionsResponse>(
        `/api/actions${buildQuery({ status, limit: ACTIVITY_WINDOW })}`,
      )
      return Array.isArray(response) ? response : response.items
    },
    retry: false,
    refetchInterval: (query) => pollInterval(query.state.data?.some(isLive) ?? false),
    refetchIntervalInBackground: false,
    staleTime: 0,
  })
}

function startedAtOf(action: AgentAction): number {
  const stamp = Date.parse(action.started_at ?? action.created_at ?? '')
  return Number.isNaN(stamp) ? Date.now() : stamp
}

/**
 * Everything in flight: pending mutations plus running agent runs (they don't overlap, since the
 * starting POST has settled by the time the run is polled). Mount once, in the app shell.
 */
export function useActivity(): Activity {
  const actions = useRecentActions()

  // `useMutationState` deep-compares, so this array keeps identity across no-op refetches.
  const pending = useMutationState({
    filters: { status: 'pending' },
    select: (mutation) => ({
      id: `mutation-${String(mutation.mutationId)}`,
      meta: readActivityMeta(mutation.meta),
      submittedAt: mutation.state.submittedAt,
    }),
  })

  const liveActions = actions.data?.filter(isLive) ?? []

  // Serialized so the memo only recomputes when the live set actually changes.
  const actionsKey = liveActions.map((action) => `${String(action.id)}:${action.status}`).join(',')
  const pendingKey = pending.map((entry) => `${entry.id}:${String(entry.submittedAt)}`).join(',')

  const operations = useMemo<ActivityOperation[]>(() => {
    const list: ActivityOperation[] = []

    for (const entry of pending) {
      list.push({
        id: entry.id,
        label: entry.meta.label,
        kind: entry.meta.kind,
        startedAt: entry.submittedAt,
      })
    }

    for (const action of liveActions) {
      list.push({
        id: `action-${String(action.id)}`,
        label: action.status === 'pending' ? `${actionTypeLabel(action.type)} queued` : actionTypeLabel(action.type),
        kind: 'run',
        startedAt: startedAtOf(action),
      })
    }

    return list.sort((left, right) => left.startedAt - right.startedAt)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingKey, actionsKey])

  const oldest = operations.length > 0 ? operations[0] : null
  const earliest = oldest?.startedAt ?? null

  /**
   * Appearance gate: hidden until the oldest operation has run `ACTIVITY_APPEAR_MS`. It only re-hides
   * when the list empties; otherwise `earliest` jumping forward would flicker the bar mid-work.
   */
  const [shown, setShown] = useState(false)
  useEffect(() => {
    if (earliest === null) {
      setShown(false)
      return
    }
    const wait = ACTIVITY_APPEAR_MS - (Date.now() - earliest)
    if (wait <= 0) {
      setShown(true)
      return
    }
    const timer = window.setTimeout(() => { setShown(true) }, wait)
    return () => { window.clearTimeout(timer) }
  }, [earliest])

  const active = shown && operations.length > 0

  return { active, operations, count: operations.length, oldest }
}

// Completion toasts for long runs, wherever the user is. Calendar sync toasts from its own button;
// short writes never toast a success.

function openNotes(): void {
  window.history.pushState({}, '', '/notes')
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function openSetup(): void {
  window.history.pushState({}, '', '/setup')
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function announceAction(action: AgentAction) {
  const label = actionTypeLabel(action.type)
  if (action.type === 'syllabus_import') {
    // A finished syllabus run can still have been refused, so the toast names the page, not an outcome.
    if (action.status === 'done') {
      toast.success('Syllabus read', {
        description: 'Check the result on Set up before it is added to your semester.',
        action: { label: 'Open Set up', onClick: openSetup },
      })
    } else if (action.status === 'failed') {
      toast.error('Syllabus read failed', {
        description: action.error ?? 'The run ended without a result. Set up has the detail.',
        action: { label: 'Open Set up', onClick: openSetup },
      })
    } else if (action.status === 'cancelled') {
      toast.info('Syllabus read stopped')
    }
    return
  }
  if (action.status === 'done') {
    toast.success(`${label} read`, {
      description: 'The proposal is ready to review in Notes.',
      action: { label: 'Open Notes', onClick: openNotes },
    })
    return
  }
  if (action.status === 'failed') {
    toast.error(`${label} failed`, {
      description: action.error ?? 'The run ended without a result. Notes has the detail.',
      action: { label: 'Open Notes', onClick: openNotes },
    })
    return
  }
  if (action.status === 'cancelled') {
    toast.info(`${label} cancelled`)
  }
}

function invalidateAfterAction(client: QueryClient) {
  void client.invalidateQueries({ queryKey: ['actions'] })
  // A finished run changed a note's status.
  void client.invalidateQueries({ queryKey: ['school', 'notes'] })
  void client.invalidateQueries({ queryKey: ['onboarding'] })
}

/** Announces runs that settle. Only runs first seen running are announced, so page loads stay silent. Mount once. */
export function useActivityWatcher(): void {
  const client = useQueryClient()
  const actions = useRecentActions()

  const liveActionIds = useRef<Set<number>>(new Set())

  const actionItems = actions.data
  useEffect(() => {
    if (!actionItems) return
    const next = new Set<number>()
    for (const action of actionItems) {
      if (isLive(action)) {
        next.add(action.id)
      } else if (liveActionIds.current.has(action.id)) {
        announceAction(action)
        invalidateAfterAction(client)
      }
    }
    liveActionIds.current = next
  }, [actionItems, client])
}
