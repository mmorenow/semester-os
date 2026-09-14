import { ArrowSquareIn } from '@phosphor-icons/react'
import { Skeleton } from '@/components/ui/skeleton'
import { BrandMark } from '@/features/school/course-platforms'
import { SyncNowButton } from '@/features/school/external-parts'
import { platformMark } from '@/features/school/platform-identity'
import { Panel, PanelHeader, SyncAge } from '@/features/school/school-parts'
import type { IcsSourceStatus, SyncStatus } from '@/lib/school-types'
import { Code, Disclosure, MenuPath, StateBadge, Step, Steps } from './connect-parts'

/**
 * Import feeds: the school's Outlook and Brightspace calendars, read every 30 minutes.
 * The URLs are credentials and never leave the server, so this panel only shows whether each is set.
 */

type FeedName = 'outlook' | 'brightspace'

const FEEDS: { source: FeedName; name: string; what: string }[] = [
  { source: 'brightspace', name: 'Brightspace', what: 'Course calendar: due dates, quizzes and course events' },
  { source: 'outlook', name: 'Outlook', what: 'Your school mailbox calendar: meetings and invitations' },
]

function FeedState({ entry, name }: { entry: IcsSourceStatus | undefined; name: string }) {
  if (!entry?.configured) return <StateBadge tone="neutral">Not set up</StateBadge>
  if (entry.ok === false) return <StateBadge tone="bad">Sync failed</StateBadge>
  return <SyncAge at={entry.last_sync_at} source={name} />
}

function BrightspaceHowTo() {
  return (
    <Steps>
      <Step>
        In Brightspace, open <MenuPath>Calendar</MenuPath>, from a course&rsquo;s tools or the calendar widget on
        the home page.
      </Step>
      <Step>
        Choose <MenuPath>Subscribe</MenuPath> (it may sit behind the settings or <MenuPath>More</MenuPath> menu),
        select <MenuPath>All Courses</MenuPath>, and copy the address. It ends in <Code>.ics</Code> and carries a
        token.
      </Step>
      <Step>
        Paste it into <Code>config.yaml</Code> under <Code>calendar_feeds.brightspace</Code>. The next sync reads
        it, no restart needed.
      </Step>
    </Steps>
  )
}

function OutlookHowTo() {
  return (
    <Steps>
      <Step>
        In Outlook on the web, open <MenuPath>Settings &gt; Calendar &gt; Shared calendars</MenuPath>.
      </Step>
      <Step>
        Under <MenuPath>Publish a calendar</MenuPath>, pick your calendar and <MenuPath>Can view all details</MenuPath>,
        press <MenuPath>Publish</MenuPath>, and copy the ICS link, not the HTML one. Some schools turn publishing off.
      </Step>
      <Step>
        Paste it into <Code>config.yaml</Code> under <Code>calendar_feeds.outlook</Code>.
      </Step>
    </Steps>
  )
}

export function ImportFeedsPanel({
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
        title="Import feeds"
        icon={ArrowSquareIn}
        meta="Read into Today and Week"
        action={status ? <SyncNowButton status={status} /> : null}
      />
      {isPending ? (
        <div className="flex flex-col divide-y divide-border" aria-busy>
          {FEEDS.map((feed) => (
            <div key={feed.source} className="flex items-center gap-3 px-4 py-3">
              <Skeleton className="size-4 rounded-sm" />
              <div className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="h-3 w-56" />
              </div>
              <Skeleton className="h-6 w-24" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">
          The server did not report the feeds. They keep syncing in the background; reload to try again.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {FEEDS.map((feed) => {
            const entry = status?.ics?.[feed.source]
            const mark = platformMark(feed.name)
            return (
              <li key={feed.source} className="flex flex-col gap-2 px-4 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  {mark ? <BrandMark mark={mark} /> : null}
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="text-sm font-medium text-foreground">{feed.name}</span>
                    <span className="truncate text-xs text-muted-foreground">{feed.what}</span>
                  </div>
                  {entry?.configured && entry.ok !== false && entry.last_sync_at ? (
                    <span className="num shrink-0 text-xs text-muted-foreground">
                      {String(entry.event_count ?? 0)} events
                    </span>
                  ) : null}
                  <FeedState entry={entry} name={feed.name} />
                </div>
                {entry?.configured && entry.ok === false && entry.error ? (
                  <p className="line-clamp-2 text-xs leading-relaxed text-signal-red">{entry.error}</p>
                ) : null}
                <Disclosure summary={entry?.configured ? 'Replace the URL' : 'Where to find the URL'}>
                  {feed.source === 'brightspace' ? <BrightspaceHowTo /> : <OutlookHowTo />}
                </Disclosure>
              </li>
            )
          })}
        </ul>
      )}
      <p className="mt-auto border-t border-border px-4 py-2 text-xs leading-relaxed text-muted-foreground">
        These URLs work like passwords: anyone with one can read that calendar. They stay in{' '}
        <Code>config.yaml</Code> on this computer and are never shown here.
      </p>
    </Panel>
  )
}
