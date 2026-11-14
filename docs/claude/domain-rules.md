# Core Business Logic (Design Doc Essentials)

> Moved out of the root `CLAUDE.md` so it isn't loaded on every request. Binding: read it before changing this area. The design doc stays the authoritative source.


**Read the full design-doc before implementing.** These are the non-negotiable rules:

### TaskTemplate vs. TaskInstance
- A **TaskTemplate** defines recurrence rules and defaults (one-time, daily, weekly, etc.), including a **`recurrence.anchor`** of `calendar` (next occurrence lands where the rule says, regardless of the predecessor) or `completion` (`completed_at` + cadence; **flexible templates only**, rejected at save on fixed ones)
- A **TaskInstance** is the schedulable unit - generated from the template, has a deadline + scheduled_time + status
- Editing is **two-scoped** (design-doc 3.10):
  - **"This occurrence"** → edits just that TaskInstance, sets `detached=true` (design-doc 3.3); later series edits skip it unless the user opts in
  - **"This and future"** → the edited occurrence plus every open occurrence dated after it (by `nominal_date`) and the template, in one transaction (architecture-plan 4.1). Later `detached` occurrences are skipped unless the user ticks the dialog's "include these" checkbox (`include_detached`); earlier and terminal occurrences are never touched (design-doc 3.10, Rev 10)
- **Every occurrence has its own `nominal_date`** (design-doc 9.1), never edited; a template's first one comes from the user-supplied `start_date`, and no flexible occurrence is placed before its date

### The Scheduling Algorithm (design-doc Section 6.2)
This is the high-risk piece. It's a greedy two-pass algorithm:
- **Pass 1:** respect the daily time budget cap (soft-cap setting in user preferences)
- **Pass 2:** if Pass 1 fails and budget_enforcement is "soft", ignore the budget and find the day with least overage
- Accounts for: active-hours windows, blackout dates, task dependencies, fixed tasks, external calendar events (filtered per design-doc Section 7), and daily budget per day-of-week
- **Incremental fit, not a reflow:** existing placements are never moved by a later pass. Greedy corner-painting (`unschedulable` where a global rearrangement would have fitted) is accepted behaviour, not a bug
- **Obstacles = every instance in `scheduled` or `in_progress`, both types**, plus intra-pass placements, plus filtered external events
- **A scheduled flexible task gives way to a fixed one** (design-doc 6.5, Rev 10): it is not a creation conflict; the fixed task is saved and the flexible task is placed again or flagged `unschedulable`. There is no manual move for flexible tasks
- **"Optimize Schedule" is explicit, user-triggered, and runs in the background** (design-doc 6.11, Rev 14): it re-runs 6.2's placement over every `scheduled`/`pending` flexible task. While it runs the schedule is read-only - the UI disables edits **and the server refuses schedule-changing writes** (`SCHEDULE_UNLOCKED`, `409 optimization_in_progress`); a plan waiting for approval locks nothing. It applies at once only if no scheduled task would lose its place or go newly over budget, otherwise the whole plan is held for one collective approval (recomputed on approval); it always shows a summary; Undo (10 minutes, latest run only) is offered only while safe and simply disappears otherwise. Never run it automatically, and never offer a plan that places fewer tasks than today. The button is always visible but says whether it is worth pressing (`GET /schedule-optimizations/opportunity`, read-only, no write lock): a gain hint and rainbow border when more tasks could be scheduled, grayed out when not - moves and swaps are not value. Applying and undoing go through the shared placement-change helpers (`place_instance_at`, `return_to_pending`) so jobs and notifications follow
- **Active hours are a list of windows per day, and a window may run overnight** (design-doc 3.7, Rev 13): `{day: [{start, end}, ...] | null}`, `end` before `start` = ends next morning. The engine places against merged *eligible intervals* of absolute time; a blackout cuts at midnight and budgets count the calendar date. Never treat "the day's window" as a single `[start, end]` pair
- **Start times land on a 15-minute grid** aligned to the hour in local wall-clock. **Durations are never quantised**
- **Stricter rules repair, never block** (design-doc 6.10, Rev 11): narrowing active hours, adding blackout dates or tightening a strict budget re-places every scheduled flexible occurrence that no longer fits, in a background job with visible progress. Valid placements are still never moved
- **No topological sort.** The `blocked` gate already guarantees every candidate's dependencies are `completed`. Do not build one
- All dates/times computed in the user's IANA timezone, never UTC offsets (design-doc 14.1)

### Task Statuses (design-doc Section 4)
`pending` → `scheduled` → `in_progress` → `completed` (terminal). Also: `blocked` (has incomplete dependencies), `missed` (flexible task's deadline elapsed before scheduling, design-doc 6.7), and `dismissed` (terminal - "skip this occurrence", design-doc 3.8). **Neither `missed` nor `dismissed` satisfies a dependency** - a downstream task stays `blocked`. A `blocked` **fixed** task keeps its time and holds its slot, goes overdue normally if the time passes, and becomes `scheduled` (never `pending`) when unblocked (design-doc 6.5, 6.6, 6.9).

### Notifications (design-doc Sections 3.4, 5)
- `reminder`, `creation_conflict`, `sync_conflict`, `unschedulable`, `dependency_at_risk`, `overdue`, `budget_exceeded`, `deadline_missed` - all distinct from task status
- **Auto-resolution** (design-doc 3.9): when the underlying condition clears, set `resolved_at` - except `budget_exceeded` (informational only, dismissed like a notice)

### Binding Design Decisions (design-doc Section 14)
- **14.1 Timezone & DST:** All persisted timestamps in UTC; user timezone as IANA name; use timezone-aware library (Python `zoneinfo` or `pytz`). **A timezone change moves nothing** (Rev 11): existing occurrences keep their instants, later ones are generated in the new zone, and the UI flags a device/setting timezone mismatch. DST edge cases handled by the library, not custom code.
- **14.2 Authentication:** Mandatory for all deployments (no anon mode), even LAN-local single-user. First-run account creation is a **setup wizard** (`POST /auth/setup`), not an env var. `RESET_ADMIN_PASSWORD` is **recovery only**, one-time, and its marker lives in the **database** (not a file, which a container recreate would erase). Sessions: 30-day absolute TTL, rotate on login, all revoked on password change. The auth guard is **middleware with an explicit public allowlist** - see design-doc 14.2 for the enumerated public routes.
