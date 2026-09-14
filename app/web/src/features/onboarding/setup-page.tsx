import { useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowClockwise, FileArrowUp, TerminalWindow, UploadSimple } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useHealth } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Panel, PanelHeader } from '@/features/school/school-parts'
import {
  useAddCourseLink,
  useCreateManualCourse,
  useReadSource,
  useSyllabusSources,
  useUploadSyllabus,
} from './onboarding-queries'
import type { SyllabusSource } from './onboarding-types'
import { ProposalSheet } from './proposal-sheet'
import { SourceList } from './source-list'

const INSTALL_URL = 'https://code.claude.com/docs/en/overview'
const ACCEPT = '.pdf,.docx,.md,.txt,.html,.htm'
const MAX_BYTES = 15 * 1024 * 1024

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The server refused the request.'
}

/** Shown when this machine can't run the agent. */
function AgentMissingNotice() {
  return (
    <Alert variant="warning">
      <TerminalWindow />
      <AlertTitle>Reading syllabi needs Claude Code</AlertTitle>
      <AlertDescription className="text-[13px] leading-relaxed text-muted-foreground">
        Semester OS reads each syllabus through the <code className="font-mono text-foreground">claude</code> command,
        which is not installed here.{' '}
        <a
          href={INSTALL_URL}
          target="_blank"
          rel="noreferrer noopener"
          className="text-primary underline underline-offset-2 hover:no-underline"
        >
          Install Claude Code
        </a>
        , run <code className="font-mono text-foreground">claude</code> once to sign in and restart Semester OS, or add your
        courses by hand below.
      </AlertDescription>
    </Alert>
  )
}

/**
 * Syllabus intake. Dropped files are read immediately; files added in Finder wait for Read,
 * since finding a file isn't a request to spend an agent run.
 */
function IntakePanel({
  agentAvailable,
  folder,
  onRescan,
  rescanning,
  onReview,
}: {
  agentAvailable: boolean
  folder: string | null
  onRescan: () => void
  rescanning: boolean
  onReview: (id: number) => void
}) {
  const upload = useUploadSyllabus()
  const read = useReadSource()
  const addLink = useAddCourseLink()
  const manual = useCreateManualCourse()
  const fileInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [url, setUrl] = useState('')
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')

  function startReading(source: SyllabusSource) {
    if (!agentAvailable || source.status !== 'queued') return
    read.mutate(source.id, {
      onError: (error) => toast.error(`Could not read ${source.name}`, { description: errorMessage(error) }),
    })
  }

  function takeFiles(files: FileList | File[]) {
    for (const file of Array.from(files)) {
      if (file.size > MAX_BYTES) {
        toast.error(`${file.name} is larger than 15 MB`, { description: 'A syllabus is not. Nothing was saved.' })
        continue
      }
      upload.mutate(file, {
        onSuccess: startReading,
        onError: (error) => toast.error(`Could not add ${file.name}`, { description: errorMessage(error) }),
      })
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    if (event.dataTransfer.files.length > 0) takeFiles(event.dataTransfer.files)
  }

  function submitLink(event: FormEvent) {
    event.preventDefault()
    const value = url.trim()
    if (!value) return
    addLink.mutate(value, {
      onSuccess: (source) => {
        setUrl('')
        startReading(source)
      },
      onError: (error) => toast.error('Could not add that link', { description: errorMessage(error) }),
    })
  }

  function submitManual(event: FormEvent) {
    event.preventDefault()
    if (!code.trim()) return
    manual.mutate(
      { course_code: code.trim(), course_title: title.trim() || null },
      {
        onSuccess: (source) => {
          setCode('')
          setTitle('')
          onReview(source.id)
        },
        onError: (error) => toast.error('Could not start that course', { description: errorMessage(error) }),
      },
    )
  }

  return (
    <Panel>
      <PanelHeader title="Add syllabi" icon={UploadSimple} />

      <div className="flex flex-col gap-4 p-3">
        <div
          onDragEnter={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
          }}
          onDrop={onDrop}
          className={cn(
            'flex flex-col items-center gap-2 rounded-md border border-dashed px-4 py-6 text-center transition-colors duration-100',
            dragging ? 'border-primary/45 bg-primary/8' : 'border-border bg-muted/40',
          )}
        >
          <FileArrowUp size={24} aria-hidden className={dragging ? 'text-primary' : 'text-muted-foreground'} />
          <p className="text-sm font-medium text-foreground">Drop syllabi here</p>
          <p className="max-w-[40ch] text-[13px] text-muted-foreground">
            PDF, Word, Markdown, text or a saved web page, up to 15 MB each.
            {agentAvailable ? ' Each one is read as soon as it lands.' : ''}
          </p>
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            multiple
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              if (event.target.files) takeFiles(event.target.files)
              event.target.value = ''
            }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => fileInput.current?.click()}
            disabled={upload.isPending}
            aria-busy={upload.isPending || undefined}
          >
            {upload.isPending ? 'Saving' : 'Choose files'}
          </Button>
        </div>

        <form onSubmit={submitLink} className="flex flex-col gap-1.5">
          <label htmlFor="setup-link" className="text-[13px] font-medium text-foreground">
            Course website
          </label>
          <div className="flex gap-2">
            <Input
              id="setup-link"
              type="url"
              inputMode="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://"
              autoComplete="off"
              spellCheck={false}
              maxLength={2000}
            />
            <Button type="submit" variant="outline" disabled={!url.trim() || addLink.isPending}>
              {addLink.isPending ? 'Adding' : 'Add link'}
            </Button>
          </div>
          <p className="text-[13px] text-muted-foreground">A public https page. Pages behind a login cannot be read.</p>
        </form>

        <form onSubmit={submitManual} className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium text-foreground" id="setup-manual-label">
            No syllabus? Type the course in
          </span>
          <div className="grid grid-cols-[7rem_minmax(0,1fr)_auto] gap-2" role="group" aria-labelledby="setup-manual-label">
            <Input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="Code"
              aria-label="Course code"
              className="num"
              maxLength={40}
              autoComplete="off"
              spellCheck={false}
            />
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Course title"
              aria-label="Course title"
              maxLength={200}
              autoComplete="off"
            />
            <Button type="submit" variant={agentAvailable ? 'outline' : 'default'} disabled={!code.trim() || manual.isPending}>
              {manual.isPending ? 'Starting' : 'Start'}
            </Button>
          </div>
        </form>
      </div>

      <div className="flex items-center gap-3 border-t border-border bg-muted/40 px-3 py-2">
        <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-muted-foreground">
          Or put files in the{' '}
          <code className="font-mono text-foreground" title={folder ?? undefined}>
            syllabi/
          </code>{' '}
          folder of Semester OS, and course links one per line in{' '}
          <code className="font-mono text-foreground">syllabi/links.txt</code>.
        </p>
        <Button type="button" size="sm" variant="ghost" onClick={onRescan} disabled={rescanning}>
          <ArrowClockwise data-icon="inline-start" />
          Rescan
        </Button>
      </div>
    </Panel>
  )
}

/** Set up: syllabi in, courses out. The reviewed source is in the URL (`?review=12`) so toasts and reloads land on it. */
export function SetupPage() {
  const sources = useSyllabusSources()
  const health = useHealth()
  const [params, setParams] = useSearchParams()
  // Unknown while health loads counts as available, so the notice never flashes.
  const agentAvailable = health.data?.claude_cli !== false

  const reviewId = Number(params.get('review'))
  const reviewing = sources.data?.sources.find((source) => source.id === reviewId) ?? null

  function openReview(id: number) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('review', String(id))
      return next
    })
  }

  function closeReview() {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.delete('review')
      return next
    })
  }

  const courseCount = sources.data?.course_count ?? 0

  return (
    <div className="flex flex-col gap-4">
      <header className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Set up your semester</h1>
        <p className="lede max-w-[72ch] text-muted-foreground">
          Add each course's syllabus. Semester OS reads it and proposes the course, its weekly schedule, its assignments
          and its grade weights. Nothing is added until you confirm.
          {courseCount > 0 ? (
            <>
              {' '}
              <span className="num text-foreground">{String(courseCount)}</span>{' '}
              {courseCount === 1 ? 'course is' : 'courses are'} already in your semester.
            </>
          ) : null}
        </p>
      </header>

      {agentAvailable ? null : <AgentMissingNotice />}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <IntakePanel
          agentAvailable={agentAvailable}
          folder={sources.data?.folder ?? null}
          onRescan={() => void sources.refetch()}
          rescanning={sources.isFetching}
          onReview={openReview}
        />
        <SourceList query={sources} agentAvailable={agentAvailable} onReview={openReview} />
      </div>

      <ProposalSheet source={reviewing} onClose={closeReview} />
    </div>
  )
}
