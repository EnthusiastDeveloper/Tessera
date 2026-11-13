# Frontend Design Tokens & Conventions

Originally written before Stage 9a as its hard prerequisite. **Restyled in the UI overhaul
(Nov 2026) to the "Mosaic" direction**, chosen from three mockups: dark-first, near-black
surfaces, one lime accent, and the Timeline's own colours (fixed work amber, flexible
work navy) reused as the brand. A tessera is one mosaic tile, so the mark is a 3x3 grid
of tiles (`src/components/MosaicMark.tsx`).

**A light theme is deferred, not designed yet.** When it comes it overrides the same
`--color-*` variables under `:root[data-theme='light']`; it never introduces new names.

## Stack

- **Tailwind CSS v4** (`@tailwindcss/vite`), for new markup. Utilities read the tokens
  below: `bg-surface`, `text-text-muted`, `border-border`, `font-display`, `rounded-lg`.
  The default palette is switched off (`--color-*: initial`), so there is no `bg-red-500`
  to reach for - if a colour isn't a token, it isn't in the design.
- **Radix primitives** (`@radix-ui/react-*`), for anything with real interaction
  semantics - menus, dialogs, popovers, tooltips. Radix brings focus management, keyboard
  handling and ARIA; we bring the styling. Add a primitive package when a screen first
  needs it, not ahead of time. Radix content renders in a portal at the end of `<body>`,
  so style it by class (see `.menu*` in `src/index.css`), not by its trigger's context.
- **Existing component classes stay** (`.field`, `button.primary`, `.banner-*`,
  `.settings-section`, ...), restyled in `src/index.css`. Element defaults live in
  `@layer base` and component classes in `@layer components`, so a Tailwind utility on an
  element always wins over them. Rewrite a screen with utilities when it is redesigned;
  don't mix both styles inside one component.
- **Fonts are self-hosted** (`@fontsource-variable/inter`, `@fontsource/space-grotesk`,
  imported in `src/main.tsx`). A LAN-only app must not depend on, or report to, Google's
  font CDN.

## Color

Defined once, in `src/styles/tokens.css`, through Tailwind's `@theme static` - each is a
CSS variable and a utility colour at the same time.

| Token | Value | Use |
|---|---|---|
| `--color-bg` | `#0d0f13` | page background |
| `--color-surface` | `#15181e` | panels, cards, the calendar |
| `--color-surface-raised` | `#1c2028` | inputs, buttons, nested tiles, menus |
| `--color-border` | `#272c35` | dividers, panel borders |
| `--color-border-strong` | `#3a414c` | input and button borders |
| `--color-text` | `#eceef2` | primary text |
| `--color-text-muted` | `#a3abb8` | secondary text, hints (7:1 on surface) |
| `--color-accent` | `#c8f169` | primary actions, focus ring, "now", the active item |
| `--color-accent-contrast` | `#0d0f13` | text on accent, danger and success fills |
| `--color-danger` | `#ff7a7a` | destructive actions, error text |
| `--color-success` | `#7ee0a1` | completed state, confirmations |
| `--color-warning` | `#f2b544` | at-risk, overdue, over budget |
| `--color-status-blocked` | `#b79ee0` | blocked |

**Timeline kinds** (design doc 8.1 screen 2) - what a block *is*, independent of status:

| Token | Value | Use |
|---|---|---|
| `--color-fixed` / `-contrast` | `#f2b544` / `#241a03` | a fixed task: a commitment, solid amber |
| `--color-flexible` / `-text` | `#2a3a6e` / `#e2e8ff` | a flexible task Tessera placed |
| `--color-flexible-strong` | `#8fa8ff` | flexible as an accent (budget tiles, the mark) |
| `--color-external` / `-stripe` / `-text` | `#262c36` / `#1e232b` / `#c3cad5` | external calendar events, hatched |

**Task-status colours:** `pending` muted, `scheduled` accent, `in_progress` warning,
`completed` success, `blocked` `--color-status-blocked`, `missed` danger, `dismissed`
muted. Status colour is never the *only* signal (icon or label text always accompanies
it) - colour alone isn't accessible.

## Spacing

4px base unit. Tailwind's own spacing scale is also 4px-based, so `p-2` and
`var(--space-2)` are both 8px. Named scale for component CSS:

`--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`,
`--space-6: 24px`, `--space-8: 32px`, `--space-12: 48px`.

## Typography

**Inter** (variable) for body and UI; **Space Grotesk** for headings and display figures
(`font-display`). Numbers are tabular everywhere (`font-variant-numeric: tabular-nums` on
`body`), so times and counts line up in columns.

`--font-size-xs: 12px`, `--font-size-sm: 14px`, `--font-size-base: 15px`,
`--font-size-lg: 18px`, `--font-size-xl: 22px`, `--font-size-2xl: 30px`.
Line-height `1.5` for body text, `1.2` for headings.

## Shape & elevation

Mosaic is sharp-edged: `--radius-sm: 4px` for tiles and calendar events, `--radius-md:
8px` (alias `--radius`) for buttons and inputs, `--radius-lg: 12px` for panels.
`--shadow-card` for floating things (menus, dialogs, the auth card); `--shadow-glow`, an
accent glow, only for "this is happening now" (the now-indicator, an in-progress task).

## Component conventions

- **Buttons:** one primary (`--color-accent` fill), one secondary (bordered, transparent
  fill), one danger (`--color-danger` fill, for destructive confirmations per design-doc
  §8.2). No third "tertiary" variant until a screen needs one.
- **Forms:** label above input, always visible (no placeholder-as-label). Validation
  error text in `--color-danger` directly under the field, not a toast - errors need to
  stay visible while the user fixes them. Duration fields follow §8.1a's "number + unit
  control" pattern from 9b onward - not relevant to 9a's forms (setup/login have none).
- **Layout:** a single top app bar (mark and wordmark, primary nav, New task, the account
  menu with Log out) once authenticated; pinned on wide screens, scrolling on phones. No
  sidebar for the POC's screen count (six top-level destinations, a top bar scales fine,
  a sidebar would be premature structure). Unauthenticated screens (setup, login)
  render standalone, centered, no app bar.
- **Feedback:** inline field errors as above; page-level errors (e.g. a failed API call
  unrelated to a specific field) as a dismissible banner in `--color-danger` at the top
  of the content area. No toast library for the POC - two feedback mechanisms is enough
  surface area. **(Added 9f)** a page-level positive confirmation (e.g. "password
  changed", a settings save) uses the same banner shape in `--color-success` instead
  (`.banner-success`, `src/index.css`) - not a new mechanism, the existing one with the
  other status color already reserved for this in the color table above.

## Dates

Every date and time shown goes through `src/lib/dates.ts` with the user's `date_format`
and `time_format` (design doc 3.7, Rev 15; read them with `useDisplayPreferences()`),
never `toLocaleString()` - the browser's locale would otherwise pick the day/month order
and the clock. Day first and a 24-hour clock are the defaults. Drop the year where it goes
without saying (`formatWeekdayDayMonth`: "Fri 13/11"). FullCalendar's own labels take the
clock through `slotLabelFormat`/`eventTimeFormat` (TimelinePage). Native date pickers
can't be formatted and follow the browser's language - they get replaced in the task-form
redesign.

## Accessibility baseline

Every interactive element reachable by keyboard and has a visible focus ring
(`--color-accent`, via `:focus-visible`, not a browser default outline removal). Form
inputs always have an associated `<label>`. Status is never color-only (see above).
