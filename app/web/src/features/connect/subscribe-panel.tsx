import { useEffect, useId, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AppleLogo, ArrowsCounterClockwise, CalendarPlus, DownloadSimple, Globe } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { BrandMark } from '@/features/school/course-platforms'
import { platformMark } from '@/features/school/platform-identity'
import { Panel, PanelHeader } from '@/features/school/school-parts'
import { formatDate, relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useRotateFeed, useSetPublicAddress, type CalendarFeed } from './connect-api'
import { Code, CopyField, Disclosure, MenuPath, StateBadge, Step, Steps, useCopy } from './connect-parts'

/**
 * `127.0.0.1` is this computer: the link works for apps that fetch locally (Apple Calendar,
 * classic Outlook) but not for server-side fetchers (Google Calendar, Outlook web, phones).
 * The public address section is the opt-in way around that.
 */

const GOOGLE_MARK = platformMark('Google Calendar')
const OUTLOOK_MARK = platformMark('Outlook')

/** "7 weekly classes, 12 deadlines, 2 exams", skipping kinds with none; figures in mono. */
function Coverage({ feed }: { feed: CalendarFeed }) {
  const parts: [number, string, string][] = [
    [feed.counts.classes, 'weekly class', 'weekly classes'],
    [feed.counts.deadlines, 'deadline', 'deadlines'],
    [feed.counts.exams, 'exam', 'exams'],
    [feed.counts.events, 'event', 'events'],
  ]
  const shown = parts.filter(([count]) => count > 0)
  return (
    <>
      {shown.map(([count, one, many], index) => (
        <span key={one} className="text-foreground/90">
          {index > 0 ? ', ' : null}
          <span className="num">{String(count)}</span> {count === 1 ? one : many}
        </span>
      ))}
    </>
  )
}

function isMac(): boolean {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)
}

/**
 * The built app is served by the API, so the relative path is same-origin and `download` applies.
 * Under the Vite dev server it points at the API origin to skip the SPA fallback.
 */
function downloadHref(feed: CalendarFeed): string {
  try {
    return new URL(feed.local_url).origin === window.location.origin ? feed.path : feed.local_url
  } catch {
    return feed.local_url
  }
}

/** Rotating breaks every subscription, so it asks inline with a focused destructive confirm. */
function RotateControl({ onRotated }: { onRotated: () => void }) {
  const rotate = useRotateFeed()
  const [confirming, setConfirming] = useState(false)
  const triggerId = useId()
  const busy = rotate.isPending

  function cancel() {
    setConfirming(false)
    window.requestAnimationFrame(() => document.getElementById(triggerId)?.focus())
  }

  function confirm() {
    if (busy) return
    rotate.mutate(undefined, {
      onSuccess: () => {
        setConfirming(false)
        onRotated()
      },
      onError: (error: unknown) => {
        toast.error('The link was not rotated', {
          description:
            error instanceof Error && error.message
              ? error.message
              : 'The Semester OS server did not answer. The current link still works.',
        })
      },
    })
  }

  if (!confirming) {
    return (
      <Button id={triggerId} type="button" variant="ghost" size="sm" onClick={() => setConfirming(true)}>
        <ArrowsCounterClockwise data-icon="inline-start" />
        Rotate link
      </Button>
    )
  }

  return (
    <div
      role="group"
      aria-label="Confirm rotating the calendar link"
      className="flex flex-wrap items-center gap-2"
      onKeyDown={(event: KeyboardEvent) => {
        if (event.key === 'Escape') cancel()
      }}
    >
      <span className="text-xs text-muted-foreground">Every app subscribed to this link stops updating.</span>
      <Button
        type="button"
        // Mounted by the press that asked for it, so focus follows the question.
        autoFocus
        variant="destructive"
        size="sm"
        onClick={confirm}
        aria-disabled={busy || undefined}
        aria-busy={busy || undefined}
        className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
      >
        {busy ? 'Rotating' : 'Rotate link'}
      </Button>
      <Button type="button" variant="ghost" size="sm" onClick={cancel}>
        Keep link
      </Button>
    </div>
  )
}

/** Which kinds of app fetched the link since the last rotation. Browser downloads prove nothing, so they're excluded. */
function ReadersLine({ feed }: { feed: CalendarFeed }) {
  const readers = feed.readers.filter((reader) => reader.client !== 'browser')
  if (readers.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No calendar app has read this link yet. Once one subscribes, it shows up here.
      </p>
    )
  }
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Recent readers">
      {readers.map((reader) => (
        <li key={reader.client} className="flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-signal-green-solid" aria-hidden />
          <span className="text-foreground/90">{reader.label}</span>
          <span className="num">{relativeTime(reader.last_fetch_at) ?? 'at an unknown time'}</span>
          {reader.via === 'public' ? <span>through the public address</span> : null}
        </li>
      ))}
    </ul>
  )
}

function AppColumn({
  title,
  mark,
  state,
  children,
}: {
  title: string
  mark: ReactNode
  state: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        {mark}
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <span className="ml-auto">{state}</span>
      </div>
      {children}
    </section>
  )
}

function AppleGuide({ feed }: { feed: CalendarFeed }) {
  return (
    <AppColumn
      title="Apple Calendar"
      mark={
        <span className="flex size-4 items-center justify-center text-muted-foreground" aria-hidden>
          <AppleLogo size={16} weight="fill" />
        </span>
      }
      state={<StateBadge tone="ok">Works on this Mac</StateBadge>}
    >
      <Steps>
        <Step>
          {isMac() ? (
            <>
              Press <MenuPath>Open in Apple Calendar</MenuPath>, or choose{' '}
            </>
          ) : (
            <>Choose </>
          )}
          <MenuPath>File &gt; New Calendar Subscription</MenuPath> and paste the link.
        </Step>
        <Step>
          Set <MenuPath>Location</MenuPath> to <MenuPath>On My Mac</MenuPath>. iCloud fetches from Apple&rsquo;s
          servers, which cannot reach this computer.
        </Step>
        <Step>
          Set <MenuPath>Auto-refresh</MenuPath> to <MenuPath>Every hour</MenuPath>.
        </Step>
      </Steps>
      {feed.public_url ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          For iPhone and iPad, subscribe with the public link and choose iCloud instead.
        </p>
      ) : null}
    </AppColumn>
  )
}

function GoogleGuide({ feed }: { feed: CalendarFeed }) {
  const live = Boolean(feed.public_url)
  return (
    <AppColumn
      title="Google Calendar"
      mark={GOOGLE_MARK ? <BrandMark mark={GOOGLE_MARK} /> : null}
      state={
        live ? (
          <StateBadge tone="ok">Public link</StateBadge>
        ) : (
          <StateBadge tone="warn">Needs a public address</StateBadge>
        )
      }
    >
      {live ? (
        <Steps>
          <Step>Copy the public link below.</Step>
          <Step>
            In Google Calendar, next to <MenuPath>Other calendars</MenuPath>, choose{' '}
            <MenuPath>+ &gt; From URL</MenuPath>, paste it and press <MenuPath>Add calendar</MenuPath>.
          </Step>
          <Step>Google refreshes on its own schedule, every 8 to 24 hours. Changes are not instant.</Step>
        </Steps>
      ) : (
        <>
          <p className="text-[13px] leading-relaxed text-foreground/90">
            Google fetches subscriptions from its own servers, which cannot reach this computer.
          </p>
          <Steps>
            <Step>
              For a one-time copy, press <MenuPath>Download .ics</MenuPath>, then in Google Calendar{' '}
              <MenuPath>Settings &gt; Import &amp; export</MenuPath>. It will not update.
            </Step>
            <Step>For a live copy, add a public address below, or use Google Calendar (advanced).</Step>
          </Steps>
        </>
      )}
    </AppColumn>
  )
}

function OutlookGuide({ feed }: { feed: CalendarFeed }) {
  const live = Boolean(feed.public_url)
  return (
    <AppColumn
      title="Outlook"
      mark={OUTLOOK_MARK ? <BrandMark mark={OUTLOOK_MARK} /> : null}
      state={
        live ? (
          <StateBadge tone="ok">Public link</StateBadge>
        ) : (
          <StateBadge tone="warn">Desktop on this PC only</StateBadge>
        )
      }
    >
      <Steps>
        <Step>
          Classic Outlook for Windows, on this computer: <MenuPath>File &gt; Account Settings &gt; Internet
          Calendars &gt; New</MenuPath>, paste the link.
        </Step>
        <Step>
          Outlook on the web and the new Outlook fetch from Microsoft&rsquo;s servers:{' '}
          <MenuPath>Add calendar &gt; Subscribe from web</MenuPath>
          {live ? ' with the public link.' : ' needs a public link. Upload from file works once, without updates.'}
        </Step>
      </Steps>
    </AppColumn>
  )
}

function TunnelCommand({ feed }: { feed: CalendarFeed }) {
  const origin = (() => {
    try {
      return new URL(feed.local_url).origin
    } catch {
      return 'http://127.0.0.1:8790'
    }
  })()
  const command = `tailscale funnel --bg --https=443 --set-path=/calendar ${origin}/calendar`
  const { copied, copy } = useCopy()
  return (
    <div className="flex min-w-0 items-start gap-2">
      <pre translate="no" className="num min-w-0 flex-1 overflow-x-auto rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-foreground">
        {command}
      </pre>
      <Button type="button" variant="outline" size="sm" onClick={() => void copy(command)} className="w-[76px]" aria-label={copied ? 'Copied the Tailscale command' : 'Copy the Tailscale command'}>
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  )
}

function PublicAddress({ feed }: { feed: CalendarFeed }) {
  const inputId = useId()
  const errorId = useId()
  const save = useSetPublicAddress()
  const [draft, setDraft] = useState(feed.public_base_url ?? '')
  const [error, setError] = useState<string | null>(null)
  const busy = save.isPending

  useEffect(() => {
    setDraft(feed.public_base_url ?? '')
  }, [feed.public_base_url])

  function submit(value: string | null) {
    if (busy) return
    setError(null)
    save.mutate(value, {
      onError: (failure: unknown) => {
        setError(
          failure instanceof Error && failure.message
            ? failure.message
            : 'The Semester OS server did not answer. Nothing was saved.',
        )
        document.getElementById(inputId)?.focus()
      },
    })
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const value = draft.trim()
    if (!value) {
      setError('Enter the https address your tunnel gives you.')
      document.getElementById(inputId)?.focus()
      return
    }
    submit(value)
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Globe size={16} aria-hidden className="text-muted-foreground" />
        <h3 className="text-sm font-semibold text-foreground">Public address</h3>
        <span className="text-xs text-muted-foreground">Optional, for Google Calendar, Outlook on the web and phones</span>
      </div>

      <p className="max-w-[80ch] text-[13px] leading-relaxed text-foreground/90">
        Run a tunnel on this computer that forwards only <Code>/calendar</Code>, then save the https address it
        gives you. From that address Semester OS serves the feed and nothing else. Anyone who has the public link
        can read your schedule, so rotate it if it leaks.
      </p>

      <Disclosure summary="Set up Tailscale Funnel">
        <Steps>
          <Step>Install Tailscale on this computer and sign in. Funnel must be allowed for your tailnet.</Step>
          <Step>
            Run this in a terminal. It publishes only the calendar path, and keeps running in the background:
            <div className="pt-1.5">
              <TunnelCommand feed={feed} />
            </div>
          </Step>
          <Step>
            Save the address it prints, like <Code>https://my-mac.tail1234.ts.net</Code>. Turn it off with{' '}
            <Code>tailscale funnel --https=443 off</Code>.
          </Step>
        </Steps>
        <p className="pt-2 text-xs leading-relaxed text-muted-foreground">
          The trade-offs, and other tunnels, are in <Code>docs/calendar.md</Code>. The feed only updates while this
          computer is awake.
        </p>
      </Disclosure>

      {feed.public_url ? (
        <div className="flex flex-col gap-3">
          <CopyField id="calendar-public-link" label="Public link" value={feed.public_url} />
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">
              Served from <span className="num text-foreground/90">{feed.public_base_url}</span>
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => submit(null)}
              aria-disabled={busy || undefined}
              aria-busy={busy || undefined}
              className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
            >
              {busy ? 'Removing' : 'Remove public address'}
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={onSubmit} noValidate className="flex max-w-[640px] flex-col gap-1.5">
          <label htmlFor={inputId} className="text-xs font-medium text-muted-foreground">
            Tunnel address
          </label>
          <div className="flex items-center gap-2">
            <Input
              id={inputId}
              type="url"
              inputMode="url"
              name="public-address"
              autoComplete="off"
              spellCheck={false}
              placeholder="https://my-mac.tail1234.ts.net"
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value)
                if (error) setError(null)
              }}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? errorId : undefined}
              className="num text-xs md:text-xs"
            />
            <Button
              type="submit"
              variant="outline"
              aria-disabled={busy || undefined}
              aria-busy={busy || undefined}
              className="w-[72px] shrink-0 aria-disabled:pointer-events-none aria-disabled:opacity-50"
            >
              {busy ? 'Saving' : 'Save'}
            </Button>
          </div>
          {error ? (
            <p id={errorId} role="alert" className="text-xs text-destructive">
              {error}
            </p>
          ) : null}
        </form>
      )}
    </div>
  )
}

export function SubscribePanel({ feed }: { feed: CalendarFeed }) {
  const [rotated, setRotated] = useState(false)

  return (
    <Panel>
      <PanelHeader title="Subscribe" icon={CalendarPlus} meta="Your semester as one calendar link" />

      <div className="flex flex-col gap-3 px-4 py-3">
        <CopyField
          id="calendar-local-link"
          label="Calendar link on this computer"
          value={feed.local_url}
          primary
        />

        <div className="flex flex-wrap items-center gap-2">
          {isMac() ? (
            <Button asChild variant="outline" size="sm">
              <a href={feed.local_webcal_url}>
                <AppleLogo data-icon="inline-start" weight="fill" />
                Open in Apple Calendar
              </a>
            </Button>
          ) : null}
          <Button asChild variant="outline" size="sm">
            <a href={downloadHref(feed)} download="semester-os.ics">
              <DownloadSimple data-icon="inline-start" />
              Download .ics
            </a>
          </Button>
          <div className="ml-auto">
            <RotateControl onRotated={() => setRotated(true)} />
          </div>
        </div>

        {rotated ? (
          <p role="status" className="text-xs text-signal-amber">
            New link issued. Old subscriptions have stopped updating; subscribe again with the link above.
          </p>
        ) : null}

        {feed.event_count === 0 ? (
          <Alert>
            <AlertTitle className="text-[13px]">Nothing to publish yet</AlertTitle>
            <AlertDescription className="text-xs leading-relaxed text-muted-foreground">
              The feed fills itself as you add courses, deadlines and events. Apps that already subscribed pick them
              up on their next refresh. <Link to="/courses" className="focus-ring rounded-sm text-primary underline-offset-4 hover:underline">Go to Courses</Link>
            </AlertDescription>
          </Alert>
        ) : (
          <p className="text-xs text-muted-foreground">
            <Coverage feed={feed} />
            {' from '}
            <span className="num">
              {formatDate(feed.window.start) ?? feed.window.start}
            </span>
            {' to '}
            <span className="num">{formatDate(feed.window.end) ?? feed.window.end}</span>
            {', in '}
            {feed.timezone}
          </p>
        )}

        <ReadersLine feed={feed} />
      </div>

      <div
        className={cn(
          'grid border-t border-border lg:grid-cols-3',
          'divide-y divide-border lg:divide-x lg:divide-y-0',
        )}
      >
        <AppleGuide feed={feed} />
        <GoogleGuide feed={feed} />
        <OutlookGuide feed={feed} />
      </div>

      <div className="border-t border-border">
        <PublicAddress feed={feed} />
      </div>
    </Panel>
  )
}
