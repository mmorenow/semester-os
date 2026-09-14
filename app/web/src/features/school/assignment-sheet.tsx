import { Link } from 'react-router-dom'
import { ArrowSquareOut, WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/empty-state'
import { useAssignment } from '@/lib/school-queries'
import type { Assignment, CoursePlatform } from '@/lib/school-types'
import { AssignmentBody } from './assignment-parts'
import { CourseMark } from './course-mark'

function SheetSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-5">
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-4 w-1/3" />
      <div className="flex gap-6">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-7 w-20" />
        ))}
      </div>
      <Skeleton className="h-7 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  )
}

interface AssignmentSheetProps {
  assignmentId: number | null
  /** The row already on screen, so the drawer has a title before it loads. */
  fallback: Assignment | undefined
  platforms: CoursePlatform[]
  slot: number | undefined
  now: Date
  onClose: () => void
}

/** One assignment in the explorer drawer, with the same body as the course page. */
export function AssignmentSheet({
  assignmentId,
  fallback,
  platforms,
  slot,
  now,
  onClose,
}: AssignmentSheetProps) {
  const detail = useAssignment(assignmentId)
  const assignment = detail.data ?? fallback

  return (
    <Sheet
      open={assignmentId !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      {/* Panel and scrim share timing; the exit is faster than the entrance. */}
      <SheetContent
        side="right"
        className="w-full gap-0 overflow-y-auto p-0 ease-enter data-open:duration-[240ms] data-closed:duration-[200ms] data-[side=right]:sm:max-w-[640px]"
        overlayClassName="ease-enter data-open:duration-[240ms] data-closed:duration-[200ms]"
      >
        {!assignment ? (
          <>
            <SheetHeader className="sr-only">
              <SheetTitle>{detail.isError ? 'Assignment not available' : 'Loading assignment'}</SheetTitle>
              <SheetDescription>
                {detail.isError ? 'The assignment detail could not be loaded.' : 'Fetching the assignment.'}
              </SheetDescription>
            </SheetHeader>
            {detail.isError ? (
              <EmptyState
                icon={WarningCircle}
                title="Could not load this assignment"
                description="The server did not return a detail for this id. It may have been removed from the database."
                action={
                  <Button size="sm" variant="outline" onClick={onClose}>
                    Close
                  </Button>
                }
              />
            ) : (
              <SheetSkeleton />
            )}
          </>
        ) : (
          <>
            <SheetHeader className="gap-2 border-b border-border px-5 pb-4 pt-5">
              <div className="pr-8">
                <SheetTitle className="text-lg font-semibold leading-snug">{assignment.title}</SheetTitle>
                <SheetDescription asChild>
                  <div className="mt-1 flex items-center gap-2">
                    <CourseMark code={assignment.course_code} slot={slot} size="xs" />
                    <Link
                      to={`/courses/${String(assignment.course_id)}?assignment=${String(assignment.id)}`}
                      onClick={onClose}
                      className="text-[13px] text-primary underline underline-offset-2 hover:no-underline"
                    >
                      Open the course page
                    </Link>
                    {assignment.url ? (
                      <a
                        href={assignment.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="flex items-center gap-1 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
                      >
                        <ArrowSquareOut size={14} />
                        Source
                      </a>
                    ) : null}
                  </div>
                </SheetDescription>
              </div>
            </SheetHeader>

            <div className="px-5 py-4">
              <AssignmentBody assignment={assignment} now={now} platforms={platforms} />
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
