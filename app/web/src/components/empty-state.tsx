import type { Icon } from '@phosphor-icons/react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon: Icon
  title: string
  description: string
  action?: React.ReactNode
  className?: string
  /** `inline` sits inside a detail section, `page` fills a whole view. */
  size?: 'inline' | 'page'
  /** Glyph color for an empty state that is good news. Muted by default. */
  iconTone?: string
}

export function EmptyState({
  icon: IconGlyph,
  title,
  description,
  action,
  className,
  size = 'page',
  iconTone,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        size === 'page' ? 'gap-3 px-6 py-20' : 'gap-2 px-4 py-8',
        className,
      )}
    >
      <span
        className={cn(
          'flex items-center justify-center rounded-lg border border-border bg-muted/40',
          size === 'page' ? 'size-10' : 'size-8',
          iconTone ?? 'text-muted-foreground',
        )}
      >
        <IconGlyph size={size === 'page' ? 20 : 16} />
      </span>
      <div className="space-y-1">
        <p className={cn('font-medium text-foreground', size === 'page' ? 'text-sm' : 'text-[13px]')}>{title}</p>
        <p className="max-w-[46ch] text-xs leading-relaxed text-muted-foreground">{description}</p>
      </div>
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  )
}
