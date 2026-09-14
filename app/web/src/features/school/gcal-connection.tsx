import { useCallback, useEffect, useRef, useState } from 'react'
import { useMatch } from 'react-router-dom'
import { ArrowSquareOut } from '@phosphor-icons/react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  clearAwaitingGcalReturn,
  GCAL_MESSAGE_TYPE,
  handOffGcalReturn,
  isAwaitingGcalReturn,
  isGcalMessage,
  openGcalChannel,
  readGcalReturn,
  startGcalConnect,
  stripGcalReturn,
  type GcalReturnMessage,
  type GcalReturnResult,
} from '@/lib/gcal-connect'
import { describeGcalError } from '@/lib/school-labels'
import { gcalFailureText, refreshSyncStatus, schoolKeys, useGcalSync, useSyncStatus } from '@/lib/school-queries'
import type { GcalStatus, SyncStatus } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { BrandMark } from './course-platforms'
import { platformMark } from './platform-identity'
import { SyncAge } from './school-parts'

/**
 * Google Calendar connection state for the School section. Testing-mode OAuth expires every
 * 7 days and background sync failures are invisible, so a broken connection is shown above every route.
 */

export interface GcalHealth {
  title: string
  reason: string
  action: 'Connect' | 'Reconnect'
}

const CONSEQUENCE = 'Until then, new classes, deadlines and events from Notes stay off your calendar.'

/** Whether the connection needs the user, and in what words. Null when Google isn't set up or all is well. */
export function gcalHealth(gcal: GcalStatus | undefined): GcalHealth | null {
  if (!gcal || gcal.configured !== true) return null
  const described = describeGcalError(gcal.error)

  if (gcal.connected !== true) {
    const neverConnected = !gcal.account_email && !gcal.error && !gcal.last_sync_at
    if (neverConnected) {
      return {
        title: 'Google Calendar is not connected',
        reason: 'Connect it to put your classes, deadlines and events from Notes on your primary calendar.',
        action: 'Connect',
      }
    }
    return {
      title: 'Google Calendar disconnected',
      reason: `${described ?? 'Semester OS can no longer write to your calendar.'} ${CONSEQUENCE}`,
      action: 'Reconnect',
    }
  }

  if (described) {
    return { title: 'Google Calendar reported a problem', reason: described, action: 'Reconnect' }
  }
  return null
}

/** True if an account was ever signed in or a sync ran. An unused client file isn't worth announcing. */
export function gcalEverConnected(gcal: GcalStatus | undefined): boolean {
  return Boolean(gcal?.connected === true || gcal?.account_email || gcal?.last_sync_at)
}

const GOOGLE_MARK = platformMark('Google')

/** Open Google's consent screen. Busy only while fetching the URL; once the popup shows Google, it is the feedback. */
export function useGcalReconnect() {
  const [pending, setPending] = useState(false)
  const pendingRef = useRef(false)

  const reconnect = useCallback(() => {
    if (pendingRef.current) return
    pendingRef.current = true
    setPending(true)
    startGcalConnect()
      .catch((error: unknown) => {
        toast.error('Could not open the Google sign-in', {
          description:
            error instanceof Error && error.message
              ? error.message
              : 'The Semester OS server did not answer. Check that it is still running.',
        })
      })
      .finally(() => {
        pendingRef.current = false
        setPending(false)
      })
  }, [])

  return { reconnect, pending }
}

/**
 * Warning callout with the fix beside it. `role="status"`, not `alert`: it renders on every
 * School route, and an assertive announcement per navigation trains screen reader users to tune out.
 */
export function GcalConnectionAlert({ status, className }: { status: SyncStatus | undefined; className?: string }) {
  const health = gcalHealth(status?.gcal)
  const { reconnect, pending } = useGcalReconnect()
  if (!health) return null

  return (
    <Alert
      variant="warning"
      role="status"
      className={cn('flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2', className)}
    >
      {GOOGLE_MARK ? <BrandMark mark={GOOGLE_MARK} size="chip" /> : null}
      <div className="flex min-w-[240px] flex-1 flex-col gap-0.5">
        <AlertTitle className="text-sm leading-snug">{health.title}</AlertTitle>
        <AlertDescription className="text-[13px] leading-relaxed text-pretty">
          {health.reason}
          {status?.gcal?.account_email ? (
            <>
              {' '}
              <span className="text-muted-foreground">Account: </span>
              <span className="break-all">{status.gcal.account_email}</span>
            </>
          ) : null}
        </AlertDescription>
      </div>
      <Button
        type="button"
        size="sm"
        onClick={reconnect}
        aria-disabled={pending || undefined}
        aria-busy={pending || undefined}
        className="shrink-0 aria-disabled:pointer-events-none aria-disabled:opacity-50"
      >
        {pending ? 'Opening Google' : health.action}
        <ArrowSquareOut data-icon="inline-end" aria-hidden />
      </Button>
    </Alert>
  )
}

/** Section-wide callout, only for a connection that worked and stopped. Hidden on Connect, whose Google panel says the same. */
export function SchoolGcalAlert() {
  const status = useSyncStatus()
  const onConnect = useMatch('/connect') !== null
  if (onConnect || !gcalEverConnected(status.data?.gcal)) return null
  return <GcalConnectionAlert status={status.data} />
}

/** Connected account and last write, plus a hint about calendars older versions created. Silent about breakage (the callout covers it). */
export function GcalStatusLine({
  status,
  align = 'start',
  className,
}: {
  status: SyncStatus | undefined
  /** `end` right-aligns both lines from `sm` up. */
  align?: 'start' | 'end'
  className?: string
}) {
  const gcal = status?.gcal
  if (!gcal || gcal.configured !== true) return null

  const healthy = gcal.connected === true && gcalHealth(gcal) === null
  const legacy = (gcal.legacy_calendars ?? []).map((calendar) => calendar.summary).filter(Boolean)
  if (!healthy && legacy.length === 0) return null

  return (
    <div
      className={cn(
        'flex min-w-0 flex-col gap-1 text-[13px] text-muted-foreground',
        align === 'end' && 'sm:items-end sm:text-right',
        className,
      )}
    >
      {healthy ? (
        <div className={cn('flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1', align === 'end' && 'sm:justify-end')}>
          {GOOGLE_MARK ? <BrandMark mark={GOOGLE_MARK} /> : null}
          <span className="text-foreground/90">Google Calendar</span>
          {gcal.account_email ? <span className="min-w-0 truncate">{gcal.account_email}</span> : null}
          <SyncAge at={gcal.last_sync_at} source="Google Calendar" />
        </div>
      ) : null}
      {legacy.length > 0 ? <p>Old calendars you can remove in Google: {legacy.join(', ')}</p> : null}
    </div>
  )
}

/** Module-level, so StrictMode's second effect run cannot announce twice. */
let landingHandled = false
let lastHandledId: string | null = null
const TOAST_ID = 'gcal-connect'

/**
 * Mounted once at the app root. When the page loads with `?gcal=`, hand the result to the opener
 * (the popup then closes) or announce it here in the same-tab fallback, and strip the param.
 * In the starting tab, listen for that handoff, refetch the connection, toast once, and after
 * a reconnect run the Google sync so the dead-token days catch up now.
 */
export function GcalConnectReturn() {
  const client = useQueryClient()
  const gcalSync = useGcalSync()
  const syncRef = useRef(gcalSync.mutate)
  syncRef.current = gcalSync.mutate

  const announce = useCallback(
    async (result: GcalReturnResult) => {
      clearAwaitingGcalReturn()
      const status = await refreshSyncStatus(client)

      if (result === 'denied') {
        toast.info('Google Calendar was not connected', {
          id: TOAST_ID,
          description: 'The Google consent screen was closed or declined. Nothing changed.',
        })
        return
      }

      if (result === 'error' || status?.gcal?.connected === false) {
        toast.error('Google Calendar did not reconnect', {
          id: TOAST_ID,
          description:
            describeGcalError(status?.gcal?.error) ?? 'Google did not say why. Press Reconnect to try again.',
        })
        return
      }

      const email = status?.gcal?.account_email
      toast.success('Google Calendar reconnected', {
        id: TOAST_ID,
        description: `${email ? `Signed in as ${email}. ` : ''}Syncing your calendar now.`,
      })
      syncRef.current(undefined, {
        onSuccess: (summary) => {
          if (summary.failures.length > 0) {
            toast.error('Google Calendar reconnected, but the sync had problems', {
              id: TOAST_ID,
              description: gcalFailureText(summary.failures),
            })
            return
          }
          toast.success('Google Calendar reconnected', {
            id: TOAST_ID,
            description:
              summary.detail.length > 0
                ? `Synced. ${summary.detail.join(' · ')}`
                : 'Synced. Your calendar was already up to date.',
          })
        },
        onError: (error: unknown) => {
          toast.error('Google Calendar reconnected, but the sync did not run', {
            id: TOAST_ID,
            description:
              error instanceof Error && error.message ? error.message : 'The Semester OS server did not answer.',
          })
        },
      })
    },
    [client],
  )

  // Starting tab: opener message and BroadcastChannel.
  useEffect(() => {
    function accept(message: GcalReturnMessage) {
      if (message.id === lastHandledId) return
      lastHandledId = message.id
      void announce(message.result)
    }

    function onWindowMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return
      const data: unknown = event.data
      if (!isGcalMessage(data) || data.kind !== 'return') return
      accept(data)
    }
    window.addEventListener('message', onWindowMessage)

    const channel = openGcalChannel()
    if (channel) {
      channel.onmessage = (event: MessageEvent) => {
        const data: unknown = event.data
        if (!isGcalMessage(data) || data.kind !== 'return') return
        if (isAwaitingGcalReturn()) {
          const ack: GcalReturnMessage = { type: GCAL_MESSAGE_TYPE, kind: 'ack', id: data.id, result: data.result }
          channel.postMessage(ack)
          accept(data)
        } else {
          // Another tab reconnected; refresh so this tab's callout doesn't describe a fixed problem.
          void client.invalidateQueries({ queryKey: schoolKeys.syncStatus })
        }
      }
    }

    return () => {
      window.removeEventListener('message', onWindowMessage)
      channel?.close()
    }
  }, [announce, client])

  // Where the callback landed.
  useEffect(() => {
    if (landingHandled) return
    landingHandled = true
    const result = readGcalReturn()
    if (!result) return
    stripGcalReturn()

    void handOffGcalReturn(result).then((where) => {
      if (where === 'here') {
        void announce(result)
        return
      }
      // A popup the browser would not let close itself is still on screen.
      window.setTimeout(() => {
        if (window.closed) return
        toast.info('You can close this window', {
          id: TOAST_ID,
          description: 'The Semester OS tab that started the sign-in has the result.',
        })
      }, 300)
    })
  }, [announce])

  return null
}
