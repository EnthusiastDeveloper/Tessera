# Frontend Design Tokens & Conventions

Hard prerequisite for Stage 9 (implementation-plan.md, "Before writing any Stage 9 UI
code"). Written once, before 9a, and extended only when a later sub-stage needs a token
that genuinely doesn't exist yet - not restyled per screen.

No external design system is pulled in for the POC (single user, no brand requirements).
Tokens live as CSS custom properties in `src/styles/tokens.css`, imported once from
`index.css`. Components consume `var(--token-name)`, never a hardcoded hex/px value.

## Color

Semantic names, not raw colors, so light/dark mode is a value swap, not a rule rewrite.
Defined for `:root` (light) and overridden under `@media (prefers-color-scheme: dark)` -
no manual toggle for the POC (Backlog-adjacent; revisit only if requested).

| Token | Light | Dark | Use |
|---|---|---|---|
| `--color-bg` | `#ffffff` | `#1a1a1a` | page background |
| `--color-surface` | `#f6f7f9` | `#242424` | cards, panels, inputs |
| `--color-border` | `#d9dce1` | `#3a3a3a` | dividers, input borders |
| `--color-text` | `#1b1e24` | `#ececec` | primary text |
| `--color-text-muted` | `#5b6270` | `#a3a3a3` | secondary text, hints |
| `--color-accent` | `#4a55c7` | `#8791f2` | primary actions, links, focus ring |
| `--color-accent-contrast` | `#ffffff` | `#1a1a1a` | text/icons on `--color-accent` |
| `--color-danger` | `#c1352b` | `#e8756a` | destructive actions, error text |
| `--color-success` | `#1f8a4c` | `#59c785` | completed state, success text |
| `--color-warning` | `#b2790a` | `#e0a83f` | at-risk / overdue state |

**Task-status colors** (used from 9c/9d onward, defined now so they're not improvised
per-screen later): `pending`→muted, `scheduled`→accent, `in_progress`→warning,
`completed`→success, `blocked`→a distinct neutral-purple (`--color-status-blocked`,
`#7a5ea8` / `#b79ee0`), `missed`/`dismissed`→danger/muted respectively. Status color is
never the *only* signal (icon or label text always accompanies it) - color alone isn't
accessible.

## Spacing

4px base unit. Named scale, used for padding/margin/gap everywhere - no ad hoc pixel
values in component styles.

`--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`,
`--space-6: 24px`, `--space-8: 32px`, `--space-12: 48px`.

## Typography

System font stack (already in `index.css`); no webfont load for a self-hosted POC.

`--font-size-xs: 12px`, `--font-size-sm: 14px`, `--font-size-base: 16px`,
`--font-size-lg: 20px`, `--font-size-xl: 24px`, `--font-size-2xl: 32px`.
Line-height `1.5` for body text, `1.2` for headings (`--line-height-body` /
`--line-height-heading`).

## Shape & elevation

`--radius: 8px` for buttons/inputs/cards (matches the Vite starter's existing button
radius - kept rather than picked arbitrarily). `--shadow-card` for the one elevation
level the POC needs (modals/dropdowns in later sub-stages); no elevation scale beyond
that until a screen actually needs one.

## Component conventions

- **Buttons:** one primary (`--color-accent` fill), one secondary (bordered, transparent
  fill), one danger (`--color-danger` fill, for destructive confirmations per design-doc
  §8.2). No third "tertiary" variant until a screen needs one.
- **Forms:** label above input, always visible (no placeholder-as-label). Validation
  error text in `--color-danger` directly under the field, not a toast - errors need to
  stay visible while the user fixes them. Duration fields follow §8.1a's "number + unit
  control" pattern from 9b onward - not relevant to 9a's forms (setup/login have none).
- **Layout:** a single top app bar (app name, primary nav, logout) once authenticated;
  no sidebar for the POC's screen count (six top-level destinations, a top bar scales
  fine, a sidebar would be premature structure). Unauthenticated screens (setup, login)
  render standalone, centered, no app bar.
- **Feedback:** inline field errors as above; page-level errors (e.g. a failed API call
  unrelated to a specific field) as a dismissible banner in `--color-danger` at the top
  of the content area. No toast library for the POC - two feedback mechanisms is enough
  surface area. **(Added 9f)** a page-level positive confirmation (e.g. "password
  changed", a settings save) uses the same banner shape in `--color-success` instead
  (`.banner-success`, `src/index.css`) - not a new mechanism, the existing one with the
  other status color already reserved for this in the color table above.

## Accessibility baseline

Every interactive element reachable by keyboard and has a visible focus ring
(`--color-accent`, via `:focus-visible`, not a browser default outline removal). Form
inputs always have an associated `<label>`. Status is never color-only (see above).
