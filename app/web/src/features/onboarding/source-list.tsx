import { Link } from 'react-router-dom'
import { FilePdf, FileText, Globe, PencilSimpleLine, Tray, WarningCircle } from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Elapsed } from '@/components/elapsed'
import { EmptyState } from '@/components/empty-state'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Panel, PanelHeader, SCHOOL_BADGE } from '@/features/school/school-parts'
import { useCancelRead, useReadAllSources, useReadSource } from './onboarding-queries'
import type { SourcesResponse, SyllabusSource } from './onboarding-types'
import { SOURCE_STATUS_LABEL, SOURCE_STATUS_TONE } from './proposal-model'

function glyphFor(source: SyllabusSource): Icon {
  if (source.kind === 'url') return Globe
  if (source.kind === 'manual') return PencilSimpleLine
  return source.name.toLowerCase().endsWith('.pdf') ? FilePdf : FileText
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

/** The one line under a source's name: what happened, or what to do. */
function SourceDetail({ source }: { source: SyllabusSource }) {
  if (source.missing && source.status !== 'applied') {
    return <span>No longer in the syllabi folder.</span>
  }
  switch (source.status) {
    case 'reading':
      return (
        <span>
          {source.action?.status === 'pending' ? 'Waiting for a free agent' : 'The agent is reading it'}
          {' · '}
          <Elapsed since={source.read_started_at} />
        </span>
      )
    case 'proposed': {
      const code = source.proposal?.course_code
      const checks = source.proposal?.uncertain.length ?? 0
      return (
        <span>
          {code ? <span className="num text-foreground">{code}</span> : 'A course'}
          {checks > 0 ? `, ${String(checks)} ${checks === 1 ? 'value' : 'values'} to check` : ''}
          {source.problems.length > 0 ? `, ${String(source.problems.length)} to fix` : ''}
        </span>
      )
    }
    case 'failed':
      return <span className="line-clamp-2 text-signal-red">{source.error ?? 'The read failed.'}</span>
    case 'applied':
      return (
        <span>
          Added {relativeTime(source.applied_at) ?? ''}
          {source.applied_changes?.kept.length
            ? `, kept ${String(source.applied_changes.kept.length)} of your edits`
            : ''}
        </span>
      )
    case 'discarded':
      return <span>Discarded. Nothing was added.</span>
    default:
      return <span>{source.kind === 'url' ? 'A course website' : 'Not read yet'}</span>
  }
}

function SourceAction({
  source,
  agentAvailable,
  onReview,
}: {
  source: SyllabusSource
  agentAvailable: boolean
  onReview: (id: number) => void
}) {
  const read = useReadSource()
  const cancel = useCancelRead()
  const label = source.status === 'queued' ? 'Read' : 'Read again'

  function start() {
    read.mutate(source.id, {
      onError: (error) => toast.error(`Could not read ${source.name}`, { description: errorMessage(error, 'The server refused.') }),
    })
  }

  if (source.status === 'proposed') {
    return (
      <Button size="sm" onClick={() => onReview(source.id)}>
        Review
      </Button>
    )
  }
  if (source.status === 'reading') {
    return (
      <Button
        size="sm"
        variant="ghost"
        disabled={source.action_id === null || cancel.isPending}
        onClick={() => {
          if (source.action_id !== null) cancel.mutate(source.action_id)
        }}
      >
        {cancel.isPending ? 'Stopping' : 'Stop'}
      </Button>
    )
  }
  if (source.kind === 'manual' || source.missing) {
    return source.applied_course_id ? (
      <Button size="sm" variant="ghost" asChild>
        <Link to={`/courses/${String(source.applied_course_id)}`}>Open course</Link>
      </Button>
    ) : null
  }
  return (
    <div className="flex items-center gap-1">
      {source.status === 'applied' && source.applied_course_id ? (
        <Button size="sm" variant="ghost" asChild>
          <Link to={`/courses/${String(source.applied_course_id)}`}>Open course</Link>
        </Button>
      ) : null}
      <Button
        size="sm"
        variant={source.status === 'queued' ? 'outline' : 'ghost'}
        onClick={start}
        disabled={!agentAvailable || read.isPending}
        title={agentAvailable ? undefined : 'Install the Claude Code CLI to read syllabi'}
      >
        {read.isPending ? 'Starting' : label}
      </Button>
    </div>
  )
}

function SourceRow({
  source,
  agentAvailable,
  onReview,
}: {
  source: SyllabusSource
  agentAvailable: boolean
  onReview: (id: number) => void
}) {
  const Glyph = glyphFor(source)
  const settled = source.status === 'discarded' || (source.missing && source.status !== 'applied')
  return (
    <li className={cn('flex items-center gap-3 px-3 py-2.5', settled && 'opacity-55 hover:opacity-100')}>
      <Glyph size={20} aria-hidden className="shrink-0 text-muted-foreground" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm text-foreground" title={source.url ?? source.name}>
          {source.name}
        </span>
        <span className="min-w-0 text-[13px] text-muted-foreground">
          <SourceDetail source={source} />
        </span>
      </div>
      <Badge variant="outline" className={cn(SCHOOL_BADGE, 'hidden shrink-0 sm:inline-flex', SOURCE_STATUS_TONE[source.status])}>
        {SOURCE_STATUS_LABEL[source.status] ?? source.status}
      </Badge>
      <div className="flex shrink-0 justify-end sm:min-w-24">
        <SourceAction source={source} agentAvailable={agentAvailable} onReview={onReview} />
      </div>
    </li>
  )
}

function SourcesSkeleton() {
  return (
    <ul className="divide-y divide-border" aria-hidden>
      {[62, 48, 70].map((width) => (
        <li key={width} className="flex items-center gap-3 px-3 py-2.5">
          <Skeleton className="size-5 rounded-sm" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-3.5" style={{ width: `${String(width)}%` }} />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <Skeleton className="h-6 w-20" />
        </li>
      ))}
    </ul>
  )
}

/** Every syllabus, newest first, with its next action. */
export function SourceList({
  query,
  agentAvailable,
  onReview,
}: {
  query: { data?: SourcesResponse; isPending: boolean; isError: boolean; refetch: () => unknown }
  agentAvailable: boolean
  onReview: (id: number) => void
}) {
  const readAll = useReadAllSources()
  const sources = query.data?.sources ?? []
  const queued = sources.filter((source) => source.status === 'queued' && !source.missing && source.kind !== 'manual')
  const reading = sources.filter((source) => source.status === 'reading').length
  const review = sources.filter((source) => source.status === 'proposed').length
  const skipped = query.data?.skipped ?? []

  const meta = [
    sources.length > 0 ? `${String(sources.length)} ${sources.length === 1 ? 'source' : 'sources'}` : null,
    reading > 0 ? `${String(reading)} reading` : null,
    review > 0 ? `${String(review)} to review` : null,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <Panel>
      <PanelHeader
        title="Syllabi"
        icon={Tray}
        meta={meta || undefined}
        action={
          queued.length > 0 && agentAvailable ? (
            <Button
              size="sm"
              onClick={() =>
                readAll.mutate(undefined, {
                  onError: (error) => toast.error('Could not start reading', { description: errorMessage(error, '') }),
                })
              }
              disabled={readAll.isPending}
            >
              {readAll.isPending ? 'Starting' : `Read ${String(queued.length)} new`}
            </Button>
          ) : null
        }
      />
      {query.isPending ? (
        <SourcesSkeleton />
      ) : query.isError ? (
        <EmptyState
          size="inline"
          icon={WarningCircle}
          title="Could not load your syllabi"
          description="The setup endpoint did not respond. Check that the Semester OS server is still running."
          action={
            <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
              Try again
            </Button>
          }
        />
      ) : sources.length === 0 ? (
        <EmptyState
          size="inline"
          icon={Tray}
          title="No syllabi yet"
          description="Drop a syllabus into the box, paste a course website, or put files in the syllabi folder. Each one becomes a course for you to review."
        />
      ) : (
        <ul className="divide-y divide-border">
          {sources.map((source) => (
            <SourceRow key={source.id} source={source} agentAvailable={agentAvailable} onReview={onReview} />
          ))}
        </ul>
      )}
      {skipped.length > 0 ? (
        <div className="border-t border-border bg-muted/40 px-3 py-2.5">
          <p className="text-[13px] font-medium text-foreground">Skipped in the syllabi folder</p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {skipped.map((item) => (
              <li key={item.name} className="text-[13px] text-muted-foreground">
                <span className="text-foreground">{item.name}</span>: {item.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  )
}
