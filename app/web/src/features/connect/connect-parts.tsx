import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, Copy } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SCHOOL_BADGE } from '@/features/school/school-parts'
import { cn } from '@/lib/utils'

const COPIED_MS = 2000

/** Copy and confirm on the control for 2s. Failures toast; successes don't. */
export function useCopy() {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )

  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => {
        setCopied(false)
      }, COPIED_MS)
    } catch {
      toast.error('Could not copy the link', {
        description: 'The browser refused clipboard access. Select the text and copy it by hand.',
      })
    }
  }, [])

  return { copied, copy }
}

/** Read-only mono value, selected whole on focus, with a Copy button. */
export function CopyField({
  id,
  label,
  value,
  primary = false,
  description,
}: {
  id: string
  label: string
  value: string
  /** The one primary action of its region. */
  primary?: boolean
  description?: ReactNode
}) {
  const { copied, copy } = useCopy()
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      <div className="flex min-w-0 items-center gap-2">
        <input
          id={id}
          readOnly
          translate="no"
          value={value}
          spellCheck={false}
          autoComplete="off"
          onFocus={(event) => {
            event.currentTarget.select()
          }}
          className="num h-8 w-full min-w-0 truncate rounded-md border border-input bg-muted/40 px-2.5 text-xs text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <Button
          type="button"
          size="default"
          variant={primary ? 'default' : 'outline'}
          onClick={() => void copy(value)}
          className="w-[84px] shrink-0"
          aria-label={copied ? `Copied ${label.toLowerCase()}` : `Copy ${label.toLowerCase()}`}
        >
          {copied ? <Check data-icon="inline-start" /> : <Copy data-icon="inline-start" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      {description ? <p className="text-xs leading-relaxed text-muted-foreground">{description}</p> : null}
      <span className="sr-only" aria-live="polite">
        {copied ? 'Copied to the clipboard.' : ''}
      </span>
    </div>
  )
}

export function Steps({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <ol
      className={cn(
        'flex list-none flex-col gap-2 text-[13px] leading-relaxed text-foreground/90 [counter-reset:step]',
        className,
      )}
    >
      {children}
    </ol>
  )
}

export function Step({ children }: { children: ReactNode }) {
  return (
    <li className="relative pl-6 [counter-increment:step] before:absolute before:top-0 before:left-0 before:w-4 before:text-right before:font-mono before:text-xs before:leading-[1.3rem] before:text-muted-foreground before:tabular-nums before:content-[counter(step)]">
      {children}
    </li>
  )
}

/** A menu path or a literal a person types, in mono ink. */
export function MenuPath({ children }: { children: ReactNode }) {
  return <span className="font-medium text-foreground">{children}</span>
}

export function Code({ children }: { children: ReactNode }) {
  return <code translate="no" className="num rounded-sm bg-muted px-1 py-px text-xs text-foreground">{children}</code>
}

export type StateTone = 'ok' | 'warn' | 'bad' | 'neutral'

const TONE_CLASS: Record<StateTone, string> = {
  ok: 'border-signal-green/45 text-signal-green',
  warn: 'border-signal-amber/45 text-signal-amber',
  bad: 'border-signal-red/45 text-signal-red',
  neutral: 'text-muted-foreground',
}

/** Outline badge: semantic ink, same hue at 45% for the border. */
export function StateBadge({ tone, children }: { tone: StateTone; children: ReactNode }) {
  return (
    <Badge variant="outline" className={cn(SCHOOL_BADGE, 'shrink-0', TONE_CLASS[tone])}>
      {children}
    </Badge>
  )
}

/** Native <details>: keyboard and screen reader support for free; the caret turns in CSS. */
export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group/disclosure">
      <summary className="focus-ring flex w-fit cursor-pointer list-none items-center gap-1.5 rounded-sm text-xs font-medium text-muted-foreground transition-colors duration-[80ms] select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
        <span
          aria-hidden
          className="inline-block size-0 border-y-[4px] border-l-[5px] border-y-transparent border-l-current transition-transform duration-150 group-open/disclosure:rotate-90 motion-reduce:transition-none"
        />
        {summary}
      </summary>
      <div className="pt-2 pl-3">{children}</div>
    </details>
  )
}
