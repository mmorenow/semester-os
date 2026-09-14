import { ArrowSquareOut, ArrowsClockwise, Warning } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { BrandMark } from '@/features/school/course-platforms'
import { gcalEverConnected, gcalHealth, useGcalReconnect } from '@/features/school/gcal-connection'
import { platformMark } from '@/features/school/platform-identity'
import { Panel, PanelHeader, SyncAge } from '@/features/school/school-parts'
import { gcalFailureText, useGcalSync } from '@/lib/school-queries'
import type { GcalStatus, SyncStatus } from '@/lib/school-types'
import { Code, CopyField, MenuPath, StateBadge, Step, Steps } from './connect-parts'

/**
 * Google Calendar OAuth writer: reaches a phone live without exposing anything, at the cost
 * of more setup and a sign-in Google expires every 7 days in Testing mode.
 */

const GOOGLE_MARK = platformMark('Google Calendar')

const BusyClasses = 'aria-disabled:pointer-events-none aria-disabled:opacity-50'

function ConnectButton({ label, primary }: { label: 'Connect' | 'Reconnect'; primary: boolean }) {
  const { reconnect, pending } = useGcalReconnect()
  return (
    <Button
      type="button"
      size="sm"
      variant={primary ? 'default' : 'outline'}
      onClick={reconnect}
      aria-disabled={pending || undefined}
      aria-busy={pending || undefined}
      className={BusyClasses}
    >
      {pending ? 'Opening Google' : label}
      <ArrowSquareOut data-icon="inline-end" aria-hidden />
    </Button>
  )
}

function SyncGoogleButton() {
  const sync = useGcalSync()
  const busy = sync.isPending
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      className={BusyClasses}
      onClick={() => {
        if (busy) return
        sync.mutate(undefined, {
          onSuccess: (summary) => {
            if (summary.failures.length > 0) {
              toast.error('Google Calendar sync had problems', { description: gcalFailureText(summary.failures) })
              return
            }
            toast.success('Google Calendar synced', {
              description: summary.detail.length > 0 ? summary.detail.join(' · ') : 'Already up to date.',
            })
          },
          onError: (error: unknown) => {
            toast.error('Google Calendar sync did not run', {
              description: error instanceof Error && error.message ? error.message : 'The server did not answer.',
            })
          },
        })
      }}
    >
      <ArrowsClockwise data-icon="inline-start" />
      {busy ? 'Syncing' : 'Sync now'}
    </Button>
  )
}

function SetupSteps({ gcal }: { gcal: GcalStatus }) {
  return (
    <Steps>
      <Step>
        In the Google Cloud console, create a project and enable the <MenuPath>Google Calendar API</MenuPath>.
      </Step>
      <Step>
        Create an OAuth client of type <MenuPath>Web application</MenuPath> with this redirect URI:
        <div className="pt-1.5">
          <CopyField id="gcal-redirect-uri" label="Redirect URI" value={gcal.redirect_uri ?? ''} />
        </div>
      </Step>
      <Step>
        Download its JSON and save it as <Code>data/.google_oauth_client.json</Code>. This panel then offers
        Connect.
      </Step>
    </Steps>
  )
}

function GoogleBody({ gcal }: { gcal: GcalStatus }) {
  if (gcal.configured !== true) {
    return (
      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] text-foreground/90">No OAuth client on this computer.</span>
          <span className="ml-auto">
            <StateBadge tone="neutral">Not set up</StateBadge>
          </span>
        </div>
        <SetupSteps gcal={gcal} />
        {gcal.error ? <p className="text-xs text-signal-red">{gcal.error}</p> : null}
      </div>
    )
  }

  const health = gcalHealth(gcal)
  const connected = gcal.connected === true
  const everConnected = gcalEverConnected(gcal)

  if (!connected && !everConnected) {
    return (
      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] text-foreground/90">The OAuth client is ready. Sign in to start writing.</span>
          <span className="ml-auto">
            <ConnectButton label="Connect" primary />
          </span>
        </div>
        {gcal.error ? (
          <p className="text-xs leading-relaxed text-signal-red">The last attempt failed: {gcal.error}</p>
        ) : null}
        <p className="text-xs leading-relaxed text-muted-foreground">
          The first sync after connecting writes to your primary calendar. If you also subscribe to the feed, you
          will see each event twice; use one or the other.
        </p>
      </div>
    )
  }

  const legacy = (gcal.legacy_calendars ?? []).map((calendar) => calendar.summary).filter(Boolean)

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      {health ? (
        <Alert variant="warning" role="status">
          <Warning aria-hidden />
          <AlertTitle className="text-[13px]">{health.title}</AlertTitle>
          <AlertDescription className="text-xs leading-relaxed text-foreground/90">{health.reason}</AlertDescription>
        </Alert>
      ) : null}

      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-xs text-muted-foreground">Account</span>
          <span className="truncate text-sm text-foreground">{gcal.account_email ?? 'Unknown account'}</span>
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <span className="text-xs text-muted-foreground">Primary calendar</span>
          <SyncAge at={gcal.last_sync_at} source="Google Calendar" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {connected ? <SyncGoogleButton /> : null}
        <span className="ml-auto">
          <ConnectButton label={health?.action ?? 'Reconnect'} primary={Boolean(health)} />
        </span>
      </div>

      {legacy.length > 0 ? (
        <p className="text-xs text-muted-foreground">Old calendars you can remove in Google: {legacy.join(', ')}</p>
      ) : null}
    </div>
  )
}

export function GooglePanel({
  status,
  isPending,
  isError,
}: {
  status: SyncStatus | undefined
  isPending: boolean
  isError: boolean
}) {
  return (
    <Panel>
      <PanelHeader
        title="Google Calendar"
        meta="Advanced"
        action={GOOGLE_MARK ? <BrandMark mark={GOOGLE_MARK} size="chip" /> : null}
      />
      <p className="border-b border-border px-4 py-3 text-[13px] leading-relaxed text-foreground/90">
        Writes classes, deadlines and events straight into your Google primary calendar: live on your phone, with
        nothing on the internet. It needs your own Google Cloud OAuth client, and while that client is in Testing
        mode Google ends the sign-in every seven days.
      </p>
      {isPending ? (
        <div className="flex flex-col gap-2 px-4 py-3" aria-busy>
          <Skeleton className="h-3.5 w-40" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : isError || !status?.gcal ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">
          The server did not report the Google connection. Reload to try again.
        </p>
      ) : (
        <GoogleBody gcal={status.gcal} />
      )}
    </Panel>
  )
}
