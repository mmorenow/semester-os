import { WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { Panel, PanelHeader } from '@/features/school/school-parts'
import { useSyncStatus } from '@/lib/school-queries'
import { useCalendarFeed } from './connect-api'
import { GooglePanel } from './google-panel'
import { ImportFeedsPanel } from './import-feeds-panel'
import { SubscribePanel } from './subscribe-panel'

/** Connect: Subscribe first (the default), then import feeds and Google OAuth. */

function SubscribeSkeleton() {
  return (
    <Panel>
      <PanelHeader title="Subscribe" meta="Your semester as one calendar link" />
      <div className="flex flex-col gap-3 px-4 py-3" aria-busy>
        <Skeleton className="h-3 w-40" />
        <div className="flex gap-2">
          <Skeleton className="h-8 flex-1" />
          <Skeleton className="h-8 w-[84px]" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-7 w-44" />
          <Skeleton className="h-7 w-32" />
        </div>
        <Skeleton className="h-3 w-80" />
      </div>
      <div className="grid gap-4 border-t border-border px-4 py-3 lg:grid-cols-3">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex flex-col gap-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ))}
      </div>
    </Panel>
  )
}

export function ConnectPage() {
  const feed = useCalendarFeed()
  const syncStatus = useSyncStatus()

  return (
    <div className="flex flex-col gap-6">
      <header className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Connect</h1>
        <p className="lede max-w-[72ch] text-muted-foreground">
          Put your semester on the calendar you already use, and bring in the calendars your school publishes.
        </p>
      </header>

      {feed.isPending ? (
        <SubscribeSkeleton />
      ) : feed.isError ? (
        <Panel>
          <PanelHeader title="Subscribe" meta="Your semester as one calendar link" />
          <EmptyState
            size="inline"
            icon={WarningCircle}
            title="The calendar link could not be loaded"
            description={
              feed.error instanceof Error && feed.error.message
                ? feed.error.message
                : 'The Semester OS server did not answer. Subscriptions that already exist keep working.'
            }
            action={
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void feed.refetch()}
                aria-disabled={feed.isFetching || undefined}
                className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
              >
                {feed.isFetching ? 'Retrying' : 'Try again'}
              </Button>
            }
          />
        </Panel>
      ) : (
        <SubscribePanel feed={feed.data} />
      )}

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <ImportFeedsPanel status={syncStatus.data} isPending={syncStatus.isPending} isError={syncStatus.isError} />
        <GooglePanel status={syncStatus.data} isPending={syncStatus.isPending} isError={syncStatus.isError} />
      </div>
    </div>
  )
}
