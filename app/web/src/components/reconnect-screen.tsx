import { PlugsConnected } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'

/** Shown when /api/health is unreachable. The query retries every 3s; the button retries now. */
export function ReconnectScreen({ onRetry, isRetrying }: { onRetry: () => void; isRetrying: boolean }) {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-background px-6">
      <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 text-center">
        <span className="mx-auto mb-4 flex size-10 items-center justify-center rounded-lg border border-border bg-muted/40 text-signal-red">
          <PlugsConnected size={20} />
        </span>
        <h1 className="text-sm font-semibold text-foreground">Server offline</h1>
        <p className="mx-auto mt-1.5 max-w-[42ch] text-xs leading-relaxed text-muted-foreground">
          Semester OS cannot reach its local server. Start it from the repository root with{' '}
          <code className="rounded-sm bg-muted px-1 py-0.5 font-mono text-[11px] text-foreground">app/server/.venv/bin/python app/server/app.py</code>{' '}
          and this screen will clear on its own.
        </p>

        <div className="mt-5 flex items-center justify-center gap-2">
          {/* No spinner: the activity bar is the app's only loop. */}
          <span className="text-xs text-muted-foreground">Trying to reconnect…</span>
        </div>

        <Button className="mt-4" size="sm" onClick={onRetry} disabled={isRetrying}>
          Retry now
        </Button>
      </div>
    </div>
  )
}
