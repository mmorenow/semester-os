import { useState } from 'react'
import { ArrowSquareOut, CaretRight, Megaphone, WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { Markdown } from '@/components/markdown'
import { humanize, relativeAge } from '@/lib/format'
import { useAnnouncements, useMarkAnnouncementSeen } from '@/lib/school-queries'
import { isSeen, type Announcement } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { Panel, PanelHeader } from './school-parts'

const EXPAND = 'animate-in fade-in-0 slide-in-from-top-1 duration-[220ms] ease-enter'

function Row({ announcement, courseId }: { announcement: Announcement; courseId: number }) {
  const [open, setOpen] = useState(false)
  const markSeen = useMarkAnnouncementSeen(courseId)
  const seen = isSeen(announcement)
  const age = relativeAge(announcement.posted_at)

  function toggle() {
    const next = !open
    setOpen(next)
    // Opening an announcement marks it read.
    if (next && !seen) markSeen.mutate({ id: announcement.id, seen: true })
  }

  return (
    <li className="border-b border-border last:border-b-0">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={toggle}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            toggle()
          }
        }}
        className={cn(
          'flex cursor-pointer items-center gap-2 px-3 py-2 transition-colors duration-[80ms] focus-ring',
          open ? 'bg-muted/40' : 'hover:bg-muted/50',
          seen && !open && 'opacity-70 hover:opacity-100',
        )}
      >
        <CaretRight
          size={14}
          className={cn(
            'shrink-0 text-muted-foreground transition-transform duration-[220ms] ease-enter',
            open && 'rotate-90',
          )}
          aria-hidden
        />
        <span
          className={cn('size-1.5 shrink-0 rounded-full', seen ? 'bg-transparent' : 'bg-primary')}
          aria-hidden
        />
        <span className={cn('min-w-0 flex-1 truncate text-sm', seen ? 'text-foreground/90' : 'text-foreground')}>
          {announcement.title ?? 'Untitled announcement'}
        </span>
        {announcement.source ? (
          <span className="shrink-0 text-xs text-muted-foreground">{humanize(announcement.source)}</span>
        ) : null}
        <span className="num w-[68px] shrink-0 text-right text-xs text-muted-foreground">{age ?? '--'}</span>
        <span className="sr-only">{seen ? 'Read' : 'Unread'}</span>
      </div>

      {open ? (
        <div className={cn('flex flex-col gap-2 border-t border-border bg-muted/20 px-3 py-2.5', EXPAND)}>
          {announcement.body_md ? (
            <Markdown className="max-w-[70ch]">{announcement.body_md}</Markdown>
          ) : (
            <p className="text-[13px] text-muted-foreground">
              The harvester recorded this announcement's title but not its body.
            </p>
          )}
          <div className="flex items-center gap-2">
            {announcement.url ? (
              <Button asChild variant="outline" size="sm">
                <a
                  href={announcement.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  onClick={(event) => { event.stopPropagation() }}
                >
                  <ArrowSquareOut data-icon="inline-start" />
                  Open
                </a>
              </Button>
            ) : null}
            {seen ? (
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                onClick={(event) => {
                  event.stopPropagation()
                  markSeen.mutate({ id: announcement.id, seen: false })
                }}
              >
                Mark unread
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  )
}

function AnnouncementsSkeleton() {
  return (
    <ul>
      {Array.from({ length: 3 }, (_, index) => (
        <li key={index} className="flex items-center gap-2 border-b border-border px-3 py-2.5 last:border-b-0">
          <Skeleton className="size-1.5 shrink-0 rounded-full" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-14 shrink-0" />
        </li>
      ))}
    </ul>
  )
}

/** What the course said, newest first, with unread carried by a primary dot. */
export function CourseAnnouncements({ courseId }: { courseId: number }) {
  const announcements = useAnnouncements(courseId)
  const rows = announcements.data ?? []
  const unread = rows.filter((row) => !isSeen(row)).length

  return (
    <Panel>
      <PanelHeader
        title="Announcements"
        icon={Megaphone}
        meta={
          unread > 0 ? (
            <>
              <span className="num">{String(unread)}</span> unread
            </>
          ) : undefined
        }
      />

      {announcements.isPending ? (
        <AnnouncementsSkeleton />
      ) : announcements.isError ? (
        <EmptyState
          size="inline"
          icon={WarningCircle}
          title="Could not load announcements"
          description="The announcements endpoint did not respond. Check that the Semester OS server is still running."
          action={
            <Button size="sm" variant="outline" onClick={() => void announcements.refetch()}>
              Try again
            </Button>
          }
        />
      ) : rows.length === 0 ? (
        <EmptyState
          size="inline"
          icon={Megaphone}
          title="Nothing posted yet"
          description="Announcements land here when the harvest reads this course's Ed board and Brightspace feed."
        />
      ) : (
        <ul className="max-h-[352px] overflow-y-auto">
          {rows.map((announcement) => (
            <Row key={announcement.id} announcement={announcement} courseId={courseId} />
          ))}
        </ul>
      )}
    </Panel>
  )
}
