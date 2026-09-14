import { formatElapsedMs } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useNow } from '@/features/school/use-now'

/**
 * Elapsed time, ticking each second. Runs publish no progress, so this is the only honest figure.
 * Its own component so the tick re-renders only this span.
 */
export function Elapsed({
  since,
  className,
}: {
  /** An ISO timestamp from the server, or epoch milliseconds. */
  since: string | number | null | undefined
  className?: string
}) {
  const now = useNow(1000)

  const start = typeof since === 'number' ? since : since ? Date.parse(since) : Number.NaN
  if (!Number.isFinite(start)) return null

  return <span className={cn('num', className)}>{formatElapsedMs(now.getTime() - start)}</span>
}
