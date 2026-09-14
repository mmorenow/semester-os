---
name: Semester OS
description: A calm, dense operator cockpit for one student's semester, dark by default.
colors:
  background: "oklch(0.1712 0.006 264)"
  foreground: "oklch(0.9491 0.004 264)"
  card: "oklch(0.2016 0.007 264)"
  popover: "oklch(0.2278 0.008 264)"
  primary: "oklch(0.649 0.137 251.4)"
  primary-foreground: "oklch(0.1712 0.02 251.4)"
  secondary: "oklch(0.2506 0.008 264)"
  muted: "oklch(0.2278 0.008 264)"
  muted-foreground: "oklch(0.7118 0.014 264)"
  border: "oklch(0.29 0.009 264)"
  input: "oklch(0.33 0.009 264)"
  destructive: "oklch(0.6837 0.1571 24.8)"
  scrim: "oklch(0.1 0.006 264 / 0.62)"
  signal-green: "oklch(0.7211 0.1257 156.2)"
  signal-amber: "oklch(0.7873 0.1263 76.4)"
  signal-red: "oklch(0.6837 0.1571 24.8)"
  signal-neutral: "oklch(0.6 0.014 264)"
  course-1: "oklch(0.6 0.088 62)"
  course-2: "oklch(0.7 0.121 220)"
  course-3: "oklch(0.72 0.021 255)"
  course-4: "oklch(0.7 0.156 285)"
  course-5: "oklch(0.7 0.17 145)"
  course-6: "oklch(0.7 0.17 350)"
typography:
  page-title:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  panel-title:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.375
  section-title:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.45
  meta:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.333
  micro:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: "1rem"
  metric:
    fontFamily: "Geist Mono Variable, ui-monospace, SFMono-Regular, monospace"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.01em"
    fontFeature: "tabular-nums"
  data:
    fontFamily: "Geist Mono Variable, ui-monospace, SFMono-Regular, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.333
    letterSpacing: "-0.01em"
    fontFeature: "tabular-nums"
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "14px"
  full: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "6": "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    height: "32px"
    padding: "0 10px"
  button-outline:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    height: "32px"
    padding: "0 10px"
  badge-outline:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    rounded: "{rounded.sm}"
    height: "20px"
    padding: "0 8px"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "12px 16px"
  table-cell:
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    padding: "6px 8px"
  sidebar-item-active:
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "0 10px"
  class-block:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.sm}"
    padding: "4px 8px"
---

# Design System: Semester OS

## Overview

**"The Quiet Cockpit."** Screens are read mid-task, hundreds of times. Scanability, density and consistency beat expression.

`app/web/src/index.css` is the source of truth. The frontmatter mirrors its dark theme. New tokens go there, in both themes.

- Dark first. No pure `#000` or `#fff`.
- 4/8px grid, `px-2 py-1.5` table cells, `h-8` controls, 13px body.
- Mono and tabular for every number, time, code and ID.
- Semantic shadcn tokens only. No raw Tailwind palette colors, no manual `dark:` overrides.
- Flat: 1px borders and tonal steps instead of shadows.
- Motion only on state change.

## Colors

Neutrals share hue 264. Each chromatic family has exactly one job.

| Family | Tokens | Job |
| --- | --- | --- |
| Accent | `primary` (hue 251.4) | Interaction only: primary buttons, focus ring, active nav (`bg-primary/12` + `text-primary`), selected row (`bg-primary/8`, hover `/12`), now-line |
| Signal | `signal-green`, `-amber`, `-red`, `-neutral` | Real-world state: due urgency, grade standing, run status, staleness. `-solid` siblings for dots and fills (3:1; text pairs 4.5:1) |
| Course | `course-1` to `course-6` | Course identity, assigned once per semester |
| Neutral | `background`, `card`, `popover`, `border`, `muted-foreground`, `scrim` | Three tonal depth steps, hairlines, secondary text, palette-tinted modal scrim |

### Course palette

| Slot | Color | Light | Dark |
| --- | --- | --- | --- |
| `course-1` | brown | `oklch(0.44 0.085 62)` `#73471A` | `oklch(0.6 0.088 62)` `#A67447` |
| `course-2` | sky | `oklch(0.55 0.096 220)` `#127E98` | `oklch(0.7 0.121 220)` `#22AFD2` |
| `course-3` | slate | `oklch(0.47 0.021 255)` `#535C67` | `oklch(0.72 0.021 255)` `#9CA6B2` |
| `course-4` | violet | `oklch(0.55 0.17 285)` `#6B5DCF` | `oklch(0.7 0.156 285)` `#968EFA` |
| `course-5` | green | `oklch(0.55 0.164 145)` `#16892A` | `oklch(0.7 0.17 145)` `#4DB956` |
| `course-6` | fuchsia | `oklch(0.55 0.17 350)` `#B53C7F` | `oklch(0.7 0.17 350)` `#E96CAD` |

- Sky, violet, green, fuchsia: chroma is 95% of the in-gamut max, capped at 0.17.
- Brown and slate are deliberately subdued, with their own lightness (brown L 0.44 / 0.60, slate L 0.47 / 0.72). Slate stops at 0.72: at 0.74, `text-foreground/75` on a 42% block fails AA.
- A slot is stored on the course (`color: "course-3"`); id order is only the fallback.

### Rules

**One Accent.** Hue 251.4 means "actionable or selected". Data never uses it.

**One Meaning Per Color.** Signals own state, course colors own the course mark, graded weight is a number and an area. Never two on one element.

**Course Mark.** A course is its code in mono, `text-foreground`, in a `rounded-sm` chip of `bg-course-N/28`. Same chip everywhere. Chip padding: `px-1.5` around 11-13px codes, `px-2` around 14px, `px-2.5 rounded-md` around the 28px code on a course page.

A course color takes these forms and no others:

| Form | Alpha (rest / hover) |
| --- | --- |
| Code chip | 28 |
| Week-grid block | 32 / 42 |
| Courses-list card (whole card) | 32 / 42 |
| Grade composition segment | 28 / 38 |
| Room wash, header of a single-course route | 16 |
| Watermark glyph on a courses card (decorative) | 16 |

Ceiling: **24%** under `text-muted-foreground`, **42%** where the darkest ink is `text-foreground/75`. To go above 24, promote the muted line to `text-foreground/75`.

A course color is never a text color, never a semantic icon fill, and never an edge bar.

**No Edge Bars.** No colored stripe on any side of any card, row, block or panel.

**Reserved Hues.** New hues stay out of 231-271 (accent), 55-85 (warning), 10-40 (danger). A course hue inside a band is allowed only if its chroma is far below that family's and it never takes that family's form. Current exceptions:

- `course-1` brown at 62: 23% (light) / 30% (dark) less chroma than `signal-amber`, lower lightness, and only ever a fill (amber is only ink and a 45% border).
- `course-3` slate at 255: 16% of the accent's chroma, never a button, ring or selected state.
- `course-2` sky is at 220 to stay clear of 231.

## Typography

**Sans:** Geist Variable. **Mono:** Geist Mono Variable. No third family, no serif, no fluid type.

| Role | Spec | Use |
| --- | --- | --- |
| Page title | 600, 20px (`text-xl`), `tracking-tight` | The one `h1` per route |
| Section title | 600, 17px (`.section-title`) | Every `h2` zone ("Grade center", "Due") |
| Panel title | 600, 16px, `leading-snug` | Sheet and dialog titles |
| Lede | 400, 16px (`.lede`) | Page lede |
| Body | 400/500, 13px | Table primaries, form values. 500 for the identifying line |
| Meta | 400, 12px, muted | Second lines, helper text |
| Micro | 500, 11px (`text-2xs`) | Column headers, counters, timestamps |
| Display number | mono 650, 34px (`.display-num`) | The largest figure on a screen |
| Code display | mono 600, 28px, `+0.01em` (`.code-display`) | Course code on a course page |
| Figure | mono 600, 22px (`.figure-num`) | Secondary figures |
| Metric | mono 600, 24px | Stat tiles |
| Data | mono 400, 12px | Inline numbers, times, CRNs, percentages |

The largest type on a screen is always a mono number or course code. Prose never exceeds 18px. Long prose renders through the markdown component at 65-75ch.

**Mono Data.** Every number, time, code, ID, CRN, duration or percentage uses `.num` (Geist Mono, `tabular-nums`, `-0.01em`). Numeric columns right-align. No exceptions.

**12-Hour Clock.** `9:30a`, `2:20p`, `11:59p`. Ranges share the meridiem when equal (`9:30-10:20a`), else keep both (`11:30a-1:20p`). Machine timestamps (runs, logs) stay 24-hour: `Aug 1, 07:30`.

**Due Dates.** Under 7 days: `Today 11:59p`, `Tomorrow 11:59p`, `Wed 11:59p`. Beyond: `Sep 4, 11:59p`. Past due: `2d overdue` in `signal-red`. History: `3d ago`, `5w ago`.

**Plain Hyphen.** No em or en dash in any visible string. Ranges use `-`.

## Layout

**Shell.** Left rail, 56px icons-only under 1024px, 220px with labels above. Brand block `h-14` with a muted school and term line from `config.yaml` when set. Nav `p-2 gap-0.5`; connection status and theme toggle pinned at the bottom behind a hairline. Content `max-w-[1400px]`, `px-4 py-5`, `lg:px-6`.

Rail items, in order: Today `T`, Week `W`, Assignments `A`, Courses `C`, Notes `N`, Connect (no hotkey). **Set up** appears at the top only while there are no courses or while it is the open route.

**Grid.** 4, 8, 12, 16, 24. Never 5, 7, 9, 10. Cells `px-2 py-1.5`, headers `h-8`, toolbars `gap-2`, cards `px-4 py-3`, sections 24px apart.

**Density.** Separate with hairlines and spacing. Cards only for stat tiles, overlays and discrete blocks.

**Responsive.** Desktop-first at 1280px. At 1024px the rail collapses, stat rows go 5 to 2 columns, and the week grid becomes a day list. Type never scales.

**Week grid.**

- 1 hour = 48px, min block 24px. Hour gutter 44px, right-aligned mono labels.
- Equal day columns split by 1px hairlines; hour lines only, none at the half hour.
- Blocks inset 1px, `rounded-sm`, `p-1`, text `px-2`: code in mono, one-line title, room in micro.
- Window: earliest start -1h to latest end +1h, clamped to 7:00a-10:00p. Weekends only when used.
- Now-line: 1px `primary` rule with a 4px dot at the gutter.

**Five-Second Rule.** At 1280x800, Today answers without scrolling: what is now or next, what else is today, what is due.

**Hairline Rule.** Need more emphasis? Use a `divide-y` list, never a shadow or thicker border.

## Elevation

Depth is `background` > `card` > `popover`, each with a 1px border. No shadows, glows, gradients or glass, except shadcn's own on floating layers (dialog, sheet, popover, dropdown, tooltip, toast).

## Shapes

`--radius: 0.625rem`. `lg` 10px: cards, popovers, sheets, dialogs. `md` 8px: buttons, inputs, selects. `sm` 6px: badges, chips, pills, small tracks. Full round: status dots and the scrollbar thumb only.

Borders are always 1px `border-border`, or a state color at 35-45% (`border-signal-amber/45`, `border-primary/45`).

Bars and tracks are 1-5px, `rounded-sm`, `bg-muted` track, solid semantic fill. Exception: the 28px grade composition bar. No pies, donuts, rings, radar, treemaps, 3D, or vertical bars for time series.

## Components

Every interactive component has default, hover, focus-visible, active, disabled, and where relevant loading and error states. shadcn via the CLI, composed not restyled: `className` is layout only. Use `Empty`, `Alert`, `Badge`, `Skeleton`, `Separator`, `gap-*` (not `space-y-*`), `size-*`, `cn()`, and no manual overlay `z-index`.

### Buttons

- 8px radius, `h-8`; `h-7` (`sm`) and `h-6` (`xs`) in rows and toolbars.
- Primary: accent fill, `hover:bg-primary/90`, one per region. Outline for standalone actions, ghost for row and toolbar actions.
- `active:scale-[0.98]` on all. Focus-visible: 3px `ring-ring/50` plus `border-ring`.
- Icons use `data-icon="inline-start"`, no size classes.

### Badges and chips

- `h-5`, `rounded-sm`, 12px, `font-normal` for data badges.
- State badges: outline, semantic text, same hue at 45% border (`text-signal-amber border-signal-amber/45`). Never filled.
- Filter chips: outline with a removable `x`.

### Tables

- `px-2 py-1.5` cells, 13px, `h-8` headers with 11px muted labels.
- Whole row is the target: `role="button"`, `tabIndex={0}`, Enter and Space.
- Hover under 100ms. Selected `bg-primary/8` (hover `/12`). Deprioritized rows (submitted) `opacity-55`, full on hover.
- Sort: header is a button; caret only on the active column, 10px bold.
- Loading: skeleton with the real columns and widths. Never a spinner.

### Forms

- 8px radius, `border-input`, label above, error below. Placeholder is never the label.
- `FieldGroup` / `Field`, `data-invalid` on the field, `aria-invalid` on the control.
- Explicit section Save with dirty state; notes textareas autosave after 800ms and say "Saved".

### Navigation

Rail items `h-9`, `rounded-md`, 18px Phosphor glyph and label (tooltip under 1024px). Active `bg-primary/12 text-primary font-medium`; idle `text-muted-foreground hover:bg-muted`.

### Empty states

Only `EmptyState`: 40px bordered `rounded-lg` tile with a 20px glyph, 13px medium title, muted 12px description (max 46ch), at most one action that fills it. No "Oops", illustrations or jokes.

### Overlays

Detail: right `Sheet`, `sm:max-w-[720px]`. Dialog for one decision, `AlertDialog` if destructive, sonner toasts for transient outcomes.

### Priority

**No Second Score.** Assignments have no invented 0-100 score. Priority is sort order plus the graded weight in mono (`18%`) and the due date in its urgency color.

### Grade center

The only chart. Summary to detail:

- **Standing track** (4px, `rounded-sm`): secured / lost / remaining in `signal-green-solid`, `signal-red-solid`, `bg-muted`.
- **Composition bar** (28px, hairline-separated): one segment per category, width = `weight_pct`, course tint 28 / 38, `text-foreground` labels only. Selected: `bg-primary/12`, `text-primary`, `border-primary/45`. `unallocated_pct` is a trailing `bg-muted` "Unmapped" segment.
- **Category table:** every number, one row per segment, clickable in sync. No percentage exists only as a width.

Unpublished splits read "split not published". What-if targets come from the server; unreachable ones say so in words.

### Staleness

Harvested data shows its age in the same block, muted mono: `Synced 2h ago`.

| State | Badge | Tooltip |
| --- | --- | --- |
| Older than 24h | amber outline `Stale 3d` | "Last synced Aug 21, 07:30 from Brightspace." |
| Never harvested | neutral outline `Never synced` | The source that would fill it |
| Last run failed | red outline `Sync failed` | First line of the error |
| Age unknown | `Unknown` | |

### Motion

Motion conveys state only. No entrance staggers, scroll reveals or load choreography. `prefers-reduced-motion` collapses all of it.

Curves: `--ease-enter` `cubic-bezier(0.215, 0.61, 0.355, 1)` for arriving, leaving, decaying. `--ease-shift` `cubic-bezier(0.645, 0.045, 0.355, 1)` for something on screen moving. Never override Tailwind's `--ease-out`.

| Moment | Duration | Easing |
| --- | --- | --- |
| Row hover, sort | under 100ms | |
| Color transitions on blocks, segments, brand marks | 120ms | |
| State transitions (general) | 150-250ms | |
| Activity bar fade in/out | 150ms | opacity |
| Grade value settle | 260ms | `ease-shift` |
| Grade ink firm (0.72 to 1) | 160ms | `ease-enter` |
| Grade row wash (12% green or red, decays) | 600ms | `ease-enter` |
| External calendar layer toggled on (scale 0.97, fade) | 220ms | `ease-enter` |
| Week now-line glide | 400ms | `ease-shift` |
| Activity bar sweep | 1.4s loop | `ease` |

**One Loop.** The only looping animation is the global activity bar:

- 2px indeterminate hairline fixed at the top of the shell, above everything. A `bg-primary` segment at 25% width sweeps a `bg-muted` track, transform only, never in layout flow.
- Lit by anything in flight: pending mutations, agent runs, calendar syncs.
- Appears only after 300ms, so fast local writes never flash it.
- Nothing else spins. Busy controls say so in words and stay disabled; live runs show ticking mono elapsed time. No percentages or ETAs.
- Reduced motion: a static `bg-primary/40` hairline while work runs (`use-reduced-motion.ts`, backstopped in `index.css`).
- The one exception is the `Skeleton` shimmer for query loading.

**Activity Chip.** Rail bottom, hidden when idle. One `h-8` row: kind glyph, label and elapsed of the oldest operation; opens a full list. Kinds: `run`, `sync`, `build`, `write`.

**Completion.** Agent runs and syncs toast their outcome once, with the server's figures or error. Short work never toasts success.

## Checklist

- Every surface has loading (shaped skeleton), empty, error, populated and stale states. Check both themes.
- Never: raw palette colors or `dark:` overrides; accent for data or signals for interaction; course color outside the [listed forms](#rules); edge bars; shadows for importance or borders over 1px; a second radius, icon family or font; em dashes, en dashes or emoji in UI text; animating what did not change; invented scores, fake courses, placeholder CRNs or sample grades.
