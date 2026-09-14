import type { CSSProperties } from 'react'
import { ArrowSquareOut } from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { CoursePlatform } from '@/lib/school-types'
import { cn } from '@/lib/utils'
import { orderPlatforms, platformIdentity, platformMark, type PlatformMark } from './platform-identity'
import { SyncAge } from './school-parts'

/**
 * Brand logo in a box. `row` is 16px around 14px (week grid, timeline); `chip` is 18px around 16px.
 * Brand color at rest where the hex clears 3:1 on `--card`, monochrome otherwise.
 */
export function BrandMark({
  mark,
  tone = 'brand',
  size = 'row',
  className,
}: {
  mark: PlatformMark
  size?: 'row' | 'chip'
  /**
   * `neutral` forces monochrome. Brand hexes were measured on untinted `--card` (Brightspace
   * clears 3:1 by 0.01), so any other ground voids the gate.
   */
  tone?: 'brand' | 'neutral'
  className?: string
}) {
  const style: CSSProperties = {}
  if (tone === 'brand' && mark.hexLight) Object.assign(style, { '--brand-light': mark.hexLight })
  if (tone === 'brand' && mark.hexDark) Object.assign(style, { '--brand-dark': mark.hexDark })
  if (mark.kind === 'mono') Object.assign(style, { '--brand-src': `url("${mark.src}")` })
  const colored = tone === 'brand'

  return (
    <span
      className={cn(
        // `currentColor` only reaches mono marks that failed the gate; index.css paints the rest.
        'flex shrink-0 items-center justify-center text-muted-foreground',
        size === 'chip' ? 'size-[18px]' : 'size-4',
        mark.kind === 'mono' && colored && 'group-hover/badge:text-foreground',
        className,
      )}
      aria-hidden
    >
      <span className={cn('block', size === 'chip' ? 'size-4' : 'size-3.5')} style={style}>
        {mark.kind === 'mono' ? (
          <span className="brand-mark-mono" />
        ) : (
          <img
            src={mark.src}
            alt=""
            className="brand-mark-raster"
            {...(colored && mark.hexLight !== null ? { 'data-brand-light': '' } : {})}
            {...(colored && mark.hexDark !== null ? { 'data-brand-dark': '' } : {})}
          />
        )}
      </span>
    </span>
  )
}


/**
 * One chip per platform, with a recovered name and glyph. `mark` shows the real logo.
 * Marked chips are opaque `bg-card`, hover included: brand hexes only clear 3:1 on `--card`.
 */
export function PlatformChip({ platform, mark = false }: { platform: CoursePlatform; mark?: boolean }) {
  const identity = platformIdentity(platform)
  const Glyph = identity.icon
  const brand = mark ? platformMark(identity.name) : null

  // No drawn logo: the platform-identity glyph at the same size, no hover color.
  const leading = brand ? (
    <BrandMark mark={brand} size="chip" />
  ) : mark ? (
    <span
      className="flex size-[18px] shrink-0 items-center justify-center text-muted-foreground"
      aria-hidden
    >
      <Glyph size={16} />
    </span>
  ) : (
    <Glyph />
  )

  // Carry the ground the brand hex was measured on, so a tinted card can't void the 3:1 gate.
  const ground = mark ? 'bg-card' : undefined

  /** Sized up from `Badge` defaults so the links are easy to hit; `h-7` keeps the 16px logo unclipped. */
  const size = mark
    ? 'h-7 gap-1.5 py-1 pl-2 pr-2.5 text-[13px] [&>svg]:size-3.5!'
    : 'h-6 px-2 py-1 text-[13px]'

  const chip = platform.url ? (
    <Badge
      variant="outline"
      className={cn(
        'font-normal',
        size,
        ground,
        mark && '[a]:hover:bg-card [a]:hover:border-input [a]:hover:text-foreground',
      )}
      asChild
    >
      <a href={platform.url} target="_blank" rel="noreferrer noopener">
        {leading}
        {identity.name}
        <ArrowSquareOut />
      </a>
    </Badge>
  ) : (
    <Badge variant="outline" className={cn('font-normal text-muted-foreground', size, ground)}>
      {leading}
      {identity.name}
    </Badge>
  )

  if (!identity.detail) return chip

  return (
    <Tooltip>
      <TooltipTrigger asChild>{chip}</TooltipTrigger>
      <TooltipContent className="max-w-[46ch]">{identity.detail}</TooltipContent>
    </Tooltip>
  )
}

/**
 * Platforms with sync ages. An age renders only after a sync: nothing writes `last_synced_at`
 * yet, and "Never synced" on every chip would be noise.
 */
export function PlatformList({ platforms, className }: { platforms: CoursePlatform[]; className?: string }) {
  if (platforms.length === 0) {
    return <p className={cn('text-[13px] text-muted-foreground', className)}>No platforms mapped yet.</p>
  }

  return (
    <ul className={cn('flex flex-wrap items-center gap-x-3 gap-y-2', className)}>
      {orderPlatforms(platforms).map((platform) => (
        <li key={platform.id} className="flex items-center gap-1.5">
          <PlatformChip platform={platform} mark />
          {platform.last_synced_at ? (
            <SyncAge at={platform.last_synced_at} source={platformIdentity(platform).name} />
          ) : null}
        </li>
      ))}
    </ul>
  )
}

/** The compact form for a card, where the ages would crowd the row out. */
export function PlatformChips({
  platforms,
  limit = 4,
  className,
  mark = false,
  onTint = false,
}: {
  platforms: CoursePlatform[]
  limit?: number
  className?: string
  /** Draw the real logos rather than the Phosphor glyphs. */
  mark?: boolean
  /** The overflow counter and empty line sit on the caller's surface; on a course tint they need `text-foreground/75`. */
  onTint?: boolean
}) {
  const bare = onTint ? 'text-foreground/75' : 'text-muted-foreground'

  if (platforms.length === 0) {
    return <span className={cn('text-[13px]', bare, className)}>No platforms mapped</span>
  }

  const ordered = orderPlatforms(platforms)
  const shown = ordered.slice(0, limit)
  const rest = ordered.length - shown.length

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {shown.map((platform) => (
        <PlatformChip key={platform.id} platform={platform} mark={mark} />
      ))}
      {rest > 0 ? <span className={cn('num text-[13px]', bare)}>+{String(rest)}</span> : null}
    </div>
  )
}
