# Configuration

Tessera has two layers of configuration: **environment variables**, set once at deploy time, and **in-app Settings**, which shape day-to-day scheduling behavior and can change anytime.

## Environment variables

Set these in `.env` before bringing the container up (see `.env.example` in the repo root for the canonical, up-to-date list).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | - | Session signing and Fernet encryption of stored OAuth tokens. Generate with `openssl rand -hex 32`; keep it stable, rotating it invalidates every session. |
| `DATABASE_PATH` | No | `./data/tessera.db` | SQLite file location. Point this at a mounted volume - it must survive container recreates. |
| `APP_BASE_URL` | Only if using calendar sync | - | Base URL used to construct OAuth redirect URIs (e.g. `https://tessera.example.com`). |
| `TZ` | No | (system default) | Default IANA timezone (e.g. `America/New_York`), used to seed the timezone in Settings on first run. Overridable per-user in Settings afterward. |
| `RESET_ADMIN_PASSWORD` | No | (empty) | One-time password recovery - see [Getting Started](installation.md#password-recovery). Not a standing login mechanism. |
| `SESSION_COOKIE_SECURE` | No | `auto` | `auto` derives the cookie's `Secure` flag from `APP_BASE_URL`'s scheme. **Never hardcode `true`** - it silently breaks login on a plain-HTTP LAN deployment, which is a supported setup. |
| `ENABLE_API_DOCS` | No | `false` | Whether the interactive `/api/v1/docs`, `/api/v1/redoc` and `/api/v1/openapi.json` routes exist at all. Leave off in production - even though they're already auth-guarded, this is defense-in-depth against exposing the full API surface. Turn on locally if you want to browse the OpenAPI schema. |
| `PORT` | No | `8000` | Port the app listens on inside the container. |
| `LOG_LEVEL` | No | `info` | Application log verbosity. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Only for Google Calendar sync | - | OAuth credentials for Google Calendar. |
| `OUTLOOK_CLIENT_ID` / `OUTLOOK_CLIENT_SECRET` | Only for Outlook sync | - | OAuth credentials for Outlook/Microsoft 365 Calendar. |

## In-app Settings

Everything below lives in **Settings** in the app itself, not in environment variables - these are things you'll plausibly change after initial setup.

### Timezone

An IANA timezone name (e.g. `America/New_York`), not a raw UTC offset. Every scheduling computation - active-hours windows, deadlines, the 15-minute placement grid, day boundaries for budget accounting - runs in this timezone, and DST transitions are handled by the timezone library rather than any custom offset math.

Changing your timezone re-projects fixed tasks' wall-clock times against the new zone, unless a given instance has been individually edited (`detached` - see [Tasks & Events](tasks-and-events.md#detach-and-edit-scope)), in which case it keeps its own value.

### Active hours

A per-day-of-week window (`start`/`end`) that bounds where **flexible** tasks may be auto-placed. This is the global default; individual task templates can layer an override on top (see below). It has no effect on fixed tasks - those sit at whatever time you set manually.

A day can be:

- **A window**, e.g. `18:00`–`21:00`
- **`null`**, meaning that day is fully excluded from flexible placement

There is deliberately no "unrestricted" value. If you want a day fully open, set it explicitly to `00:00`–`23:59`.

### Per-task active-hours override

A task template can define its own `active_hours_override`, which **merges** over the global map rather than replacing it wholesale:

- A day named in the override uses the override's value for that day.
- A day *not* named in the override inherits the global setting for that day.
- A day explicitly set to `null` in the override is excluded, exactly like the global map's `null`.

This lets you say "this one chore can run later on Tuesdays" without accidentally opening every other day of the week to unrestricted scheduling.

### Blackout dates

A list of full-day exclusions (`start`, `end`, optional `label`) - manual holidays, vacations, or any span you want flexible tasks kept off entirely. This is a hard constraint the scheduler never crosses, same as active hours.

### Daily time budget

An optional per-day-of-week cap, in minutes, on how much *flexible*-task time gets placed in a day. It's a **soft cap by default**: fixed tasks and external calendar events still count against a day's budget (so a day already full of meetings doesn't also get chores piled on top), but the algorithm is allowed to exceed the budget as a last resort rather than miss a task's deadline.

Two enforcement modes:

- **`soft`** (default) - if a task can't be placed within budget anywhere before its deadline, the algorithm retries ignoring the budget and picks the day that overflows the least (see [Scheduling Algorithm](scheduling-algorithm.md)). You get a `budget_exceeded` notification when this happens.
- **`strict`** - the budget is a hard wall. A task that can't fit within budget becomes `unschedulable` instead of overflowing.

### First day of week

Display-only - controls calendar layout and the ordering of day-of-week rows elsewhere in Settings. It has no effect on scheduling: every day-keyed setting above is keyed by day name, not position in the week, so there's nothing for the algorithm to reorder.

### External calendar connections

Per-provider OAuth connection (Google, Outlook, etc.), plus a configurable poll interval (`refresh_interval_minutes`). See [Capabilities](capabilities.md#external-calendar-sync) for how synced events are treated.
