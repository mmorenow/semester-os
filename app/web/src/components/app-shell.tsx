import { useEffect, useState } from 'react'
import { NavLink, Outlet, useMatch } from 'react-router-dom'
import {
  Books,
  CalendarCheck,
  CalendarDots,
  ClipboardText,
  GraduationCap,
  Moon,
  NotePencil,
  PlugsConnected,
  Tray,
  Sun,
} from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTheme } from '@/components/theme-provider'
import { useAppConfig, useHealth } from '@/lib/queries'
import { useCourses } from '@/lib/school-queries'
import { useActivity, useActivityWatcher } from '@/lib/use-activity'
import { cn } from '@/lib/utils'
import { ActivityBar, ActivityChip } from '@/components/activity'
import { ReconnectScreen } from '@/components/reconnect-screen'

interface NavEntry {
  to: string
  label: string
  icon: Icon
  end: boolean
  /** Surfaced in the rail and handled inside the section that owns it. */
  hotkey?: string
}

const NAV_ITEMS: NavEntry[] = [
  { to: '/', label: 'Today', icon: CalendarCheck, end: true, hotkey: 'T' },
  { to: '/week', label: 'Week', icon: CalendarDots, end: false, hotkey: 'W' },
  { to: '/assignments', label: 'Assignments', icon: ClipboardText, end: false, hotkey: 'A' },
  { to: '/courses', label: 'Courses', icon: Books, end: false, hotkey: 'C' },
  { to: '/notes', label: 'Notes', icon: NotePencil, end: false, hotkey: 'N' },
  { to: '/connect', label: 'Connect', icon: PlugsConnected, end: false },
]

/** In the rail only while the semester is empty or /setup is open, so confirming a course doesn't yank it away. */
const SETUP_ITEM: NavEntry = { to: '/setup', label: 'Set up', icon: Tray, end: false }

function NavItem({ to, label, icon: Glyph, end, hotkey }: NavEntry) {
  // Resolved here, not via NavLink's className function: Radix `asChild` would stringify it.
  const isActive = useMatch({ path: to, end }) !== null

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <NavLink
          to={to}
          end={end}
          aria-keyshortcuts={hotkey}
          className={cn(
            'flex h-9 items-center justify-center gap-2.5 rounded-md px-2.5 text-sm transition-colors active:scale-[0.98] lg:justify-start',
            isActive
              ? 'bg-primary/12 font-medium text-primary'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground',
          )}
        >
          <Glyph size={18} className="shrink-0" />
          <span className="hidden lg:inline">{label}</span>
          {hotkey ? (
            <span className="num ml-auto hidden text-2xs text-muted-foreground lg:inline" aria-hidden>
              {hotkey}
            </span>
          ) : null}
        </NavLink>
      </TooltipTrigger>
      <TooltipContent side="right" className="lg:hidden">
        {label}
        {hotkey ? <span className="num text-muted-foreground"> {hotkey}</span> : null}
      </TooltipContent>
    </Tooltip>
  )
}

function ConnectionStatus({ connected, isPending }: { connected: boolean; isPending: boolean }) {
  const label = isPending ? 'Connecting' : connected ? 'Connected' : 'Server offline'
  const dotTone = isPending ? 'bg-signal-neutral' : connected ? 'bg-signal-green-solid' : 'bg-signal-red-solid'

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex h-8 items-center gap-2 rounded-md px-2.5 justify-center lg:justify-start">
          <span className={cn('size-2 shrink-0 rounded-full', dotTone)} aria-hidden />
          <span className="hidden text-xs text-muted-foreground lg:inline">{label}</span>
          <span className="sr-only">{label}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="right">
        {connected ? 'The Semester OS server is responding.' : 'No response from the Semester OS server.'}
      </TooltipContent>
    </Tooltip>
  )
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={`Switch to ${next} theme`}
          className="flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-[0.98] justify-center lg:justify-start"
        >
          {theme === 'dark' ? <Sun size={18} className="shrink-0" /> : <Moon size={18} className="shrink-0" />}
          <span className="hidden lg:inline text-xs">{theme === 'dark' ? 'Light theme' : 'Dark theme'}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="right" className="lg:hidden">
        Switch to {next} theme
      </TooltipContent>
    </Tooltip>
  )
}

/** Consecutive failed health polls; the query's `failureCount` resets on every refetch. */
function useConsecutiveMisses(isError: boolean, errorUpdatedAt: number, dataUpdatedAt: number): number {
  const [misses, setMisses] = useState(0)
  useEffect(() => {
    setMisses((current) => (isError ? current + 1 : 0))
  }, [isError, errorUpdatedAt, dataUpdatedAt])
  return misses
}

/** Wordmark plus the school and term from config.yaml, when set. */
function Brand() {
  const config = useAppConfig()
  const context = [config.data?.school_name, config.data?.term].filter(Boolean).join(' · ')
  return (
    <div className="hidden min-w-0 flex-col lg:flex">
      <span className="text-sm font-semibold tracking-tight">Semester OS</span>
      {context ? <span className="truncate text-2xs text-muted-foreground">{context}</span> : null}
    </div>
  )
}

export function AppShell() {
  const health = useHealth()
  const connected = health.isSuccess && health.data.ok
  const misses = useConsecutiveMisses(health.isError, health.errorUpdatedAt, health.dataUpdatedAt)

  // Mounted once here; consumers get it as a prop.
  const activity = useActivity()
  useActivityWatcher()

  const courses = useCourses()
  const onSetup = useMatch({ path: '/setup', end: false }) !== null
  const navItems = (courses.data && courses.data.length === 0) || onSetup ? [SETUP_ITEM, ...NAV_ITEMS] : NAV_ITEMS

  // Wait for a second consecutive miss so one dropped request doesn't blank the screen.
  if (health.isError && (misses >= 2 || !health.data)) {
    return <ReconnectScreen onRetry={() => void health.refetch()} isRetrying={health.isFetching} />
  }

  return (
    <div className="min-h-[100dvh] bg-background">
      <ActivityBar activity={activity} />
      <aside className="fixed inset-y-0 left-0 z-30 flex w-14 flex-col border-r border-border bg-card lg:w-[220px]">
        <div className="flex h-14 items-center gap-2.5 border-b border-border px-2.5 lg:px-4">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <GraduationCap size={16} />
          </span>
          <Brand />
        </div>

        <nav className="flex flex-1 flex-col gap-0.5 p-2" aria-label="Primary">
          {navItems.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>

        <div className="flex flex-col gap-0.5 border-t border-border p-2">
          <ActivityChip activity={activity} />
          <ConnectionStatus connected={connected} isPending={health.isPending} />
          <ThemeToggle />
        </div>
      </aside>

      <div className="pl-14 lg:pl-[220px]">
        <main className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
