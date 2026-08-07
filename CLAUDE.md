# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

**Tessera** is a self-hosted task scheduling application that auto-places flexible tasks into your calendar while respecting fixed commitments, deadlines, and priorities. It's a Python FastAPI backend + React frontend, single-user, containerized.

### Key References
- **Product specification:** `docs/design-doc.md` (Revision 9) - this is the authoritative source for what the system *does*
- **Implementation plan:** `docs/architecture-plan.md` (Revision 3) - defines how it's structured and built
- **Findings register / decision log:** `docs/implementation-readiness-review-2.md` (IRR-2) - why Revisions 9 and 3 say what they say, plus the findings still open (H2 onward, gating Stage 5+)
- **Architecture enforcement:** `backend/pyproject.toml` has an `import-linter` configuration that blocks layering violations at CI

### Common Commands

- `lint-imports` - check layering violations (also runs in CI, blocking); see `backend/pyproject.toml` and `frontend/package.json` for the rest of the standard install/test/build/lint commands.

---

Backend layering rules and module map: see `backend/CLAUDE.md`.

## Core Business Logic (Design Doc Essentials)

**Read the full design-doc before implementing.** These are the non-negotiable rules:

### TaskTemplate vs. TaskInstance
- A **TaskTemplate** defines recurrence rules and defaults (one-time, daily, weekly, etc.), including a **`recurrence.anchor`** of `calendar` (next occurrence lands where the rule says, regardless of the predecessor) or `completion` (`completed_at` + cadence; **flexible templates only**, rejected at save on fixed ones)
- A **TaskInstance** is the schedulable unit - generated from the template, has a deadline + scheduled_time + status
- Editing is **two-scoped** (design-doc 3.10):
  - **"This occurrence"** → edits just the live TaskInstance, sets `detached=true` (design-doc 3.3), skips template propagation forever
  - **"This and future"** → edits the template; if the live instance isn't `detached`, updates its fields immediately in the same transaction (architecture-plan 4.1)

### The Scheduling Algorithm (design-doc Section 6.2)
This is the high-risk piece. It's a greedy two-pass algorithm:
- **Pass 1:** respect the daily time budget cap (soft-cap setting in user preferences)
- **Pass 2:** if Pass 1 fails and budget_enforcement is "soft", ignore the budget and find the day with least overage
- Accounts for: active-hours windows, blackout dates, task dependencies, fixed tasks, external calendar events (filtered per design-doc Section 7), and daily budget per day-of-week
- **Incremental fit, not a reflow:** existing placements are never moved by a later pass. Greedy corner-painting (`unschedulable` where a global rearrangement would have fitted) is accepted behaviour, not a bug
- **Obstacles = every instance in `scheduled` or `in_progress`, both types**, plus intra-pass placements, plus filtered external events
- **Start times land on a 15-minute grid** aligned to the hour in local wall-clock. **Durations are never quantised**
- **No topological sort.** The `blocked` gate already guarantees every candidate's dependencies are `completed`. Do not build one
- All dates/times computed in the user's IANA timezone, never UTC offsets (design-doc 14.1)

### Task Statuses (design-doc Section 4)
`pending` → `scheduled` → `in_progress` → `completed` (terminal). Also: `blocked` (has incomplete dependencies), `missed` (flexible task's deadline elapsed before scheduling, design-doc 6.7), and `dismissed` (terminal - "skip this occurrence", design-doc 3.8). **Neither `missed` nor `dismissed` satisfies a dependency** - a downstream task stays `blocked`.

### Notifications (design-doc Sections 3.4, 5)
- `reminder`, `creation_conflict`, `sync_conflict`, `unschedulable`, `dependency_at_risk`, `overdue`, `budget_exceeded`, `deadline_missed` - all distinct from task status
- **Auto-resolution** (design-doc 3.9): when the underlying condition clears, set `resolved_at` - except `budget_exceeded` (informational only, dismissed like a notice)

### Binding Design Decisions (design-doc Section 14)
- **14.1 Timezone & DST:** All persisted timestamps in UTC; user timezone as IANA name; use timezone-aware library (Python `zoneinfo` or `pytz`). Fixed tasks re-project on timezone change unless `detached`. DST edge cases handled by the library, not custom code.
- **14.2 Authentication:** Mandatory for all deployments (no anon mode), even LAN-local single-user. First-run account creation is a **setup wizard** (`POST /auth/setup`), not an env var. `RESET_ADMIN_PASSWORD` is **recovery only**, one-time, and its marker lives in the **database** (not a file, which a container recreate would erase). Sessions: 30-day absolute TTL, rotate on login, all revoked on password change. The auth guard is **middleware with an explicit public allowlist** - see design-doc 14.2 for the enumerated public routes.

---

Background job wiring and reconciliation rules: see `backend/CLAUDE.md`.

## Testing Strategy (architecture-plan Section 8)

**Build order:** Scheduling engine first, tested in isolation, before wiring anything else. Then service layer, then API.

**Required test categories:**
1. **Unit tests** on scheduling engine (~90%+ coverage on this module specifically) - place tasks against various constraint combinations
2. **Scheduling algorithm acceptance tests** - design-doc Section 10's Worked Examples A–K are concrete input/output scenarios; implement these as test fixtures
3. **Edit-scope/detach tests** - Worked Examples L–M (design-doc 3.10); verifies "this occurrence" vs. "this and future" scoping and the detach flag
4. **Job-wiring integration tests** - assert that every mutation creates/cancels the right job(s) at the right time; don't just test the business logic, test the job plumbing too (architecture-plan 4.1)
5. **Reconciliation tests** - simulate a killed process, verify startup 4.2 reconciliation restores consistency
6. **Architecture tests** - `import-linter` run on every push; also a pytest test that walks the AST and fails if `scheduling_engine/` imports forbidden modules

---

## API Contract (architecture-plan Section 3)

**REST, versioned (`/api/v1/...`), session-cookie auth (`HttpOnly`, `SameSite=Lax`, `Secure` derived from `APP_BASE_URL`'s scheme via `SESSION_COOKIE_SECURE=auto`).**

### Key Endpoints
- `GET /api/v1/task-instances` - list with filtering
- `POST /api/v1/task-instances` - create (auto-enters `pending` if flexible, `scheduled` if fixed)
- `PATCH /api/v1/task-instances/{id}` - "this occurrence" edit (sets `detached=true`)
- `POST /api/v1/task-instances/{id}/reschedule` - reschedule a fixed task (also a "this occurrence" edit per design-doc 6.6, sets `detached=true`)
- `POST /api/v1/task-instances/{id}/complete` - mark complete
- `POST /api/v1/task-instances/{id}/extend-deadline` - extend deadline on a `missed` instance (also a "this occurrence" edit per design-doc 6.7)
- `PATCH /api/v1/task-templates/{id}?scope=this_and_future` - "this and future" edit (touches template + conditionally live instance)
- `DELETE /api/v1/task-instances/{id}` - delete (dependency unlink, not cascade)
- `POST /api/v1/auth/login`, `/logout` - session-based auth
- `POST /api/v1/task-instances/{id}/dismiss` - "skip this occurrence"; terminal, preserves the row, and for a completion-anchored template **must generate the successor** or the series silently ends
- `POST /api/v1/auth/setup` - first-run account creation; requires the setup token logged at startup; `410 Gone` once a user exists
- `DELETE /api/v1/task-instances/{id}?scope=this_occurrence|this_and_future` - deletion scope mirrors edit scope (design-doc 3.8); required for recurring templates
- `GET /api/v1/task-instances?view=backlog` - the Backlog view is a filter, not its own resource

### Error Envelope
Consistent across all endpoints: HTTP status + machine-readable code + human message. Distinct error codes:
- `cycle_detected` - dependency creates a cycle
- `creation_conflict` - fixed task collides with existing event
- `infeasible_duration` - flexible task can't fit any single day's active-hours window (design-doc 6.8)
- `invalid_recurrence_anchor` - `anchor: "completion"` on a fixed template
- `session_expired` - distinct from a generic 401 so the client redirects to login
- `409 Conflict` - optimistic lock collision; see architecture-plan 5.1. The client sends an `expected` map of the values it read for the fields it is changing; the server compares only those and merges onto the current row. **PATCH must be genuinely partial** - sending the whole object defeats the mechanism

---

## Data Model Essentials

**TaskTemplate** (design-doc 3.2):
- `name`, `description`, `location` (informational)
- `type`: "fixed" | "flexible"
- `recurrence`: pattern + interval (one_time, daily, weekly, monthly, custom) + **`anchor`** (`calendar` | `completion`)
- `fixed_time_of_day`: wall-clock local time (e.g. "18:00"), **re-projected per timezone change** unless instance is `detached`
- `deadline_offset_minutes`: integer minutes (e.g. 4320 = 3 days) for flexible tasks
- `priority`: low | medium | high | critical (numeric internally: 1-4)
- `estimated_duration_minutes`: integer minutes, validated at save against the **merged** active-hours window, measured from the first grid point (design-doc 6.8)
- `reminder_offsets_minutes`: integer minutes before `scheduled_time` (e.g. [60, 15, 0])
- `active_hours_override`: optional per-day-of-week window that **merges** over user settings per day; per-day `null` always means "day excluded" (never "unrestricted" - use an explicit `00:00`-`23:59` window for that)
- `archived`: boolean (soft-delete; templates with history are archived, not hard-deleted)

**TaskInstance** (design-doc 3.3):
- `template_id`: always set (even for one-time tasks)
- `name`, `description`, `location`, `type`, `priority` (copied from template at generation)
- `estimated_duration_minutes`: integer minutes
- `detached`: boolean (true = this instance no longer receives template propagation)
- `scheduled_time`: DateTime (set once placed on timeline)
- `deadline`: DateTime (set at generation for flexible tasks)
- `status`: pending | scheduled | in_progress | completed | blocked | missed
- `status_history`: [{status, at}] - immutable trail
- `dependencies`: TaskInstance id[] (can't start until all are completed) - **persisted as a join table**, not an array column, because the Backlog view navigates it in both directions
- `created_at`, `updated_at`, `version` - `version` is the optimistic-locking token, incremented at the ORM layer; `updated_at` is display/audit only
- `completed_at`: DateTime (set when transitioned to completed, from any status)
- `generated_at`: DateTime

**UserSettings** (design-doc 3.7):
- `timezone`: IANA name (e.g. "America/New_York")
- `active_hours`: {day_name: {start, end} | null} - per-day-of-week global window
- `blackout_dates`: [{start, end, label?}] - full-day exclusions
- `daily_time_budget_minutes`: {day_name: number | null} - max flexible work per day in minutes, soft cap by default
- `budget_enforcement`: "soft" | "strict" - whether to allow budget override as last resort
- `first_day_of_week`: day name (display-only, doesn't affect algorithm)

---

## Scope: What's In vs. Out for POC

**In POC (locked, design-doc Section 2):**
- Single user, password login, read-only external calendar sync (polling)
- WebUI only (no IM bot)
- One fixed greedy scheduling algorithm
- Global active-hours + per-task override + manual blackout dates + soft daily time-budget
- Fixed-task hard-block on conflicts (no soft override)
- In-app notifications only (no email/IM push)

**Explicitly out of POC (Backlog sections 12 & 13, will not be built "while you're in there"):**
- Multi-user / shared timeline
- Location-aware scheduling or commute time
- Automatic task splitting (design-doc 12.20) - hard-block at creation instead (design-doc 6.8)
- Multiple selectable algorithms (design-doc 12.9)
- Holiday calendars (design-doc 12.15 has open questions)
- Email/IM notification channels
- Write access to external calendars (read-only polling only)

**Critical discipline rule (design-doc Section 0):** Do not build backlog items "while you're in there" under the guise of prep work. The scope boundaries are deliberate.

---

## Common Pitfalls

1. **Don't edit the design doc casually.** Sections 3 (Data Model) and 6 (Algorithm) are load-bearing; Section 14 (Design Decisions) has binding constraints. Section 11 is locked - all `[UNCONFIRMED]` items were resolved in Rev 8. Changes need to go through a revision process with stakeholder sign-off.

2. **Don't skip the layering.** Import-linter will catch it in CI, but a violation caught in code review is cheaper than a failed CI run. Specifically: `scheduling_engine/` must not import FastAPI, SQLAlchemy, or anything under `app/`.

3. **Don't periodic-scan when you should event-drive.** Background jobs are event-driven (architecture-plan 4). If you find yourself adding a new job, ask: "Can this fire off an event (a task state change, a dependency completion) or a precise timestamp?" If the answer is yes, schedule a one-off job. If not, reconcile why.

4. **Don't half-implement job wiring.** A mutation writes to the DB *and* updates jobs in the same method, or it's wrong. The orphaned-job failure mode has no error to surface - it's a silent miss.

5. **Don't assume `schedule_time` means the task actually happened.** A flexible task can be marked `completed` without ever being `scheduled` (design-doc 3.3, Section 4) - user already did the task. The timestamp is `completed_at`, not `scheduled_time`.

6. **Don't forget detach.** "This occurrence" edits and manual fixed-task reschedules set `detached=true` (design-doc 3.10, 6.6). A detached instance stops receiving template propagation. The UI should indicate this visibly so users understand why a later template edit didn't land on an instance.

7. **Don't store raw UTC offsets for timezone.** Use IANA timezone names (design-doc 14.1). `pytz` or `zoneinfo` (Python 3.9+) handle DST automatically; custom UTC offset math will silently drift by an hour at DST boundaries.

8. **Don't build search/filtering as a separate layer.** The API layer already filters `GET /task-instances?status=scheduled&priority=high` through the service layer; the service layer calls the data layer with constraints. Keep the direction one-way: API → Service → Data.

---

## Deployment & Configuration (architecture-plan Section 7)

**Single container, single process.** React builds to static assets; FastAPI serves them directly (no separate nginx container for same-origin simplicity).

**Required env vars** (see `.env.example`):
- `SECRET_KEY` - for session signing + Fernet encryption of OAuth tokens (required)
- `DATABASE_PATH` - path to SQLite file, should point into a mounted volume (default: `./data/tessera.db`)
- `APP_BASE_URL` - base URL for OAuth redirect construction (required if using calendar sync)
- `TZ` - default timezone, overridable in Settings (optional, sensible default)
- `RESET_ADMIN_PASSWORD` - one-time password recovery (optional, requires container restart)
- `SESSION_COOKIE_SECURE` - `auto` (default) | `true` | `false`; `auto` derives the cookie's `Secure` flag from `APP_BASE_URL`. Never hardcode it to `true` - it silently breaks login on plain-HTTP LAN, which is a supported deployment
- Calendar provider credentials if using sync (`GOOGLE_CLIENT_ID`, etc.)

**Data persistence:** SQLite file must live on a mounted Docker volume, never in the container's writable layer. Otherwise all tasks, history, and credentials evaporate on container recreate.

**Health check included** in the container - standard practice under orchestration.

---

Debugging playbook (scheduling bugs, missed jobs, stuck dependencies, unexpected 409s, calendar filtering): use the `debug-tessera` skill.

---

Code review checklist: use the `tessera-code-review` skill.

Frontend notes: see `frontend/CLAUDE.md`.

---

## References

- **Product spec:** `/docs/design-doc.md` - authoritative source for what to build
- **Architecture & implementation:** `/docs/architecture-plan.md` - how to structure the code
- **Build order & testing:** architecture-plan Section 8 - scheduling engine first
- **Worked examples:** design-doc Section 10 (A–M) - concrete scenarios to test against
- **Backlog & non-goals:** design-doc Sections 12–13 - explicitly out of scope for POC
