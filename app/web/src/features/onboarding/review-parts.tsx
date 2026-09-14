import type { ReactNode } from 'react'
import { WarningCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/**
 * Review marks. To check (amber): uncertain, never blocks; border and glyph only, text stays in ink.
 * To fix (red): the server won't confirm until it's filled; rides on `aria-invalid`.
 */
export const FLAG_BORDER = 'border-signal-amber/45'

/** A section of the review sheet: a 17px title, a meta count, an action on the right. */
export function ReviewSection({
  title,
  meta,
  action,
  children,
  id,
}: {
  title: string
  meta?: ReactNode
  action?: ReactNode
  children: ReactNode
  id?: string
}) {
  return (
    <section className="flex flex-col gap-3 border-b border-border px-5 py-4 last:border-b-0" aria-labelledby={id}>
      <div className="flex min-h-7 items-center gap-2">
        <h3 id={id} className="section-title text-foreground">
          {title}
        </h3>
        {meta ? <span className="truncate text-[13px] text-muted-foreground">{meta}</span> : null}
        {action ? <div className="ml-auto flex items-center gap-1">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}

/** The reason a value is flagged, with the one-click way to say it is right. */
export function FlagNote({ id, reason, onDismiss }: { id?: string; reason: string; onDismiss: () => void }) {
  return (
    <div className="flex items-start gap-1.5" id={id}>
      <WarningCircle size={14} aria-hidden className="mt-0.5 shrink-0 text-signal-amber" />
      <p className="min-w-0 flex-1 text-[13px] leading-snug text-muted-foreground">
        <span className="sr-only">To check: </span>
        {reason}
      </p>
      <Button type="button" size="xs" variant="ghost" onClick={onDismiss} className="-my-0.5 shrink-0">
        Looks right
      </Button>
    </div>
  )
}

export function ProblemNote({ id, message }: { id?: string; message: string }) {
  return (
    <p id={id} className="text-[13px] leading-snug text-signal-red">
      {message}
    </p>
  )
}

/** Labelled control with its flag and problem. The caller wires the note ids via `describedBy`. */
export function ReviewField({
  label,
  htmlFor,
  reason,
  problem,
  onDismiss,
  className,
  children,
}: {
  label: string
  htmlFor: string
  reason?: string
  problem?: string
  onDismiss: () => void
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <label htmlFor={htmlFor} className="text-[13px] font-medium text-foreground">
        {label}
      </label>
      {children}
      {problem ? <ProblemNote id={`${htmlFor}-problem`} message={problem} /> : null}
      {reason ? <FlagNote id={`${htmlFor}-flag`} reason={reason} onDismiss={onDismiss} /> : null}
    </div>
  )
}

export function describedBy(htmlFor: string, reason?: string, problem?: string): string | undefined {
  const ids = [problem ? `${htmlFor}-problem` : null, reason ? `${htmlFor}-flag` : null].filter(Boolean)
  return ids.length > 0 ? ids.join(' ') : undefined
}

/** Flag for dense table cells: a button whose tooltip and label carry the reason; pressing it marks the value checked. */
export function CellFlag({ reason, onDismiss }: { reason: string; onDismiss: () => void }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={`To check: ${reason} Press to mark it as right.`}
          className="flex size-6 shrink-0 items-center justify-center rounded-sm text-signal-amber transition-colors hover:bg-muted focus-ring"
        >
          <WarningCircle size={16} />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-[36ch] flex-col items-start gap-0.5">
        <span>{reason}</span>
        <span className="text-background/75">Click to mark it as right.</span>
      </TooltipContent>
    </Tooltip>
  )
}
