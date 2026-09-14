import {
  ChalkboardTeacher,
  ChartBar,
  ChatsCircle,
  ClipboardText,
  CursorClick,
  GithubLogo,
  Globe,
  GraduationCap,
  LinkSimple,
  Question,
  UsersThree,
  VideoCamera,
} from '@phosphor-icons/react'
import type { Icon } from '@phosphor-icons/react'
import { humanize } from '@/lib/format'
import type { CoursePlatform } from '@/lib/school-types'

/**
 * Platform name and glyph for a course link. Most interesting platforms arrive as `other`, so the
 * name is recovered from the harvester note ("Name: what it is for").
 */

export interface PlatformIdentity {
  name: string
  icon: Icon
  /** The rest of the note, once the name has been taken off the front. */
  detail: string | null
}

const KNOWN: Record<string, { name: string; icon: Icon }> = {
  brightspace: { name: 'Brightspace', icon: GraduationCap },
  blackboard: { name: 'Blackboard', icon: GraduationCap },
  canvas: { name: 'Canvas', icon: GraduationCap },
  gradescope: { name: 'Gradescope', icon: ClipboardText },
  ed: { name: 'Ed Discussion', icon: ChatsCircle },
  edstem: { name: 'Ed Discussion', icon: ChatsCircle },
  piazza: { name: 'Piazza', icon: ChatsCircle },
  campuswire: { name: 'Campuswire', icon: ChatsCircle },
  website: { name: 'Course site', icon: Globe },
  github: { name: 'GitHub', icon: GithubLogo },
  zoom: { name: 'Zoom', icon: VideoCamera },
  kaltura: { name: 'Lecture recordings', icon: VideoCamera },
  boilercast: { name: 'BoilerCast', icon: VideoCamera },
}

/** Keyword to glyph, for the platforms that only have a name and a note. */
const BY_KEYWORD: { match: RegExp; icon: Icon }[] = [
  { match: /quiz|exam|poll/i, icon: Question },
  { match: /grade|score|mark/i, icon: ChartBar },
  { match: /peer|team|eval/i, icon: UsersThree },
  { match: /clicker|attendance|participation/i, icon: CursorClick },
  { match: /lecture|slide|class/i, icon: ChalkboardTeacher },
]

/** "SimpleQuiz: In-lecture quizzes." splits into name and detail. A sentence stays whole as the detail. */
function splitNote(notes: string | null | undefined): { name: string | null; detail: string | null } {
  const trimmed = notes?.trim()
  if (!trimmed) return { name: null, detail: null }

  const colon = trimmed.indexOf(':')
  if (colon > 1 && colon <= 44) {
    const head = trimmed.slice(0, colon).trim()
    const tail = trimmed.slice(colon + 1).trim()
    // A label, not a clause: no sentence punctuation and not a run of words.
    if (!/[.;!?]/.test(head) && head.split(/\s+/).length <= 4) {
      return { name: head, detail: tail || null }
    }
  }
  return { name: null, detail: trimmed }
}

/** `https://cs.example.edu/~cs180quiz` becomes `cs180quiz`. */
function nameFromUrl(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    const segments = parsed.pathname.split('/').filter(Boolean)
    const last = segments.at(-1)
    if (last) return humanize(last.replace(/^~/, '').replace(/\.\w{2,4}$/, ''))
    return parsed.hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

function iconFor(text: string): Icon {
  for (const entry of BY_KEYWORD) {
    if (entry.match.test(text)) return entry.icon
  }
  return LinkSimple
}

export function platformIdentity(platform: CoursePlatform): PlatformIdentity {
  const key = platform.platform.trim().toLowerCase()
  const { name: noteName, detail } = splitNote(platform.notes)

  const known = KNOWN[key]
  if (known) return { name: known.name, icon: known.icon, detail }

  const name = noteName ?? nameFromUrl(platform.url) ?? humanize(platform.platform)
  return { name, icon: iconFor(`${name} ${platform.notes ?? ''}`), detail }
}

/**
 * Real logos from `/brand` (sources and usage in `/brand/manifest.json`), layered on top of
 * `platformIdentity`. `mono` is a single-path glyph painted via CSS mask; `raster` is desaturated
 * at rest and shows its colors on hover.
 *
 * Hexes measured against `--card`, present only where they clear 3:1:
 *
 *   Brightspace #E87511   6.00 dark   3.01 light   both
 *   Ed          #6347B7   2.68 dark   6.74 light   light only
 *   Gradescope  #3F96F7   5.94 dark   3.04 light   both
 *   iClicker    #04B1A6   6.74 dark   2.68 light   dark only
 *   GCal        #4285F4   5.06 dark   3.56 light   both
 *   Outlook     #0078D4   3.98 dark   4.53 light   both
 */
export interface PlatformMark {
  src: string
  kind: 'mono' | 'raster'
  /** The brand hex for the light theme, or null where it does not clear 3:1. */
  hexLight: string | null
  hexDark: string | null
}

const BRIGHTSPACE: PlatformMark = {
  src: '/brand/brightspace.png',
  kind: 'raster',
  hexLight: '#E87511',
  hexDark: '#E87511',
}

const ED: PlatformMark = {
  src: '/brand/ed.png',
  kind: 'raster',
  hexLight: '#6347B7',
  hexDark: null,
}

const GRADESCOPE: PlatformMark = {
  src: '/brand/gradescope-icon.png',
  kind: 'raster',
  hexLight: '#3F96F7',
  hexDark: '#3F96F7',
}

const ICLICKER: PlatformMark = {
  src: '/brand/iclicker.svg',
  kind: 'raster',
  hexLight: null,
  hexDark: '#04B1A6',
}

const GOOGLE_CALENDAR: PlatformMark = {
  src: '/brand/google-calendar-mono.svg',
  kind: 'mono',
  hexLight: '#4285F4',
  hexDark: '#4285F4',
}

const OUTLOOK: PlatformMark = {
  src: '/brand/outlook-mono.svg',
  kind: 'mono',
  hexLight: '#0078D4',
  hexDark: '#0078D4',
}

/** Matched on the resolved name, since most arrive as `other` ("iClicker Cloud: ..." is iClicker). */
export function platformMark(name: string): PlatformMark | null {
  const key = name.trim().toLowerCase()
  if (key.startsWith('brightspace')) return BRIGHTSPACE
  if (key === 'ed' || key.startsWith('ed ')) return ED
  if (key.startsWith('gradescope')) return GRADESCOPE
  if (key.startsWith('iclicker')) return ICLICKER
  // The external layer labels its feed "Google", so the bare word resolves here. Exact match:
  // Drive, Docs and Forms fall through to the Phosphor fallback.
  if (key === 'google' || key.startsWith('google calendar')) return GOOGLE_CALENDAR
  if (key.startsWith('outlook') || key.startsWith('microsoft outlook')) return OUTLOOK
  return null
}

/** Course site first, then the graded surfaces, then everything else. */
const ORDER = ['website', 'brightspace', 'gradescope', 'ed', 'edstem', 'piazza']

export function orderPlatforms(platforms: CoursePlatform[]): CoursePlatform[] {
  return [...platforms].sort((a, b) => {
    const rankA = ORDER.indexOf(a.platform.toLowerCase())
    const rankB = ORDER.indexOf(b.platform.toLowerCase())
    return (rankA === -1 ? ORDER.length : rankA) - (rankB === -1 ? ORDER.length : rankB) || a.id - b.id
  })
}
