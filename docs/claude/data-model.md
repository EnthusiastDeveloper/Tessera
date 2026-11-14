# Data Model Essentials

> Moved out of the root `CLAUDE.md` so it isn't loaded on every request. Binding: read it before changing this area. The design doc stays the authoritative source.


**TaskTemplate** (design-doc 3.2):
- `name`, `description`, `location` (informational)
- `start_date`: local date, required at creation - the first occurrence is derived from it
- `type`: "fixed" | "flexible"
- `recurrence`: pattern + interval (one_time, daily, weekly, monthly - `custom` was dropped in Rev 12; a monthly `day_of_month` clamps to a short month's last day) + **`anchor`** (`calendar` | `completion`)
- `fixed_time_of_day`: wall-clock local time (e.g. "18:00"), **re-projected per timezone change** unless instance is `detached`
- `deadline_offset_minutes`: integer minutes (e.g. 4320 = 3 days) for flexible tasks
- `priority`: low | medium | high | critical on the wire for templates **and** instances (Rev 12); numeric 1-4 is internal only
- `estimated_duration_minutes`: integer minutes, validated at save against the **merged** active-hours window, measured from the first grid point (design-doc 6.8)
- `reminder_offsets_minutes`: integer minutes before `scheduled_time` (e.g. [60, 15, 0])
- `active_hours_override`: optional per-day-of-week **list of windows** that **merges** over user settings per day (a named day replaces that day's whole list); per-day `null` always means "day excluded" (never "unrestricted" - use an explicit `00:00`-`23:59` window for that)
- `archived`: boolean (soft-delete; templates with history are archived, not hard-deleted)

**TaskInstance** (design-doc 3.3):
- `template_id`: always set (even for one-time tasks)
- `name`, `description`, `location`, `type`, `priority` (copied from template at generation)
- `estimated_duration_minutes`: integer minutes
- `detached`: boolean (true = this instance was edited on its own; series edits skip it unless the user opts in)
- `nominal_date`: DateTime - this occurrence's own date, set at generation, never edited; the series advances from it
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
- `active_hours`: {day_name: [{start, end}, ...] | null} - per-day-of-week global windows (a list, Rev 13)
- `blackout_dates`: [{start, end, label?}] - full-day exclusions
- `daily_time_budget_minutes`: {day_name: number | null} - max flexible work per day in minutes, soft cap by default
- `budget_enforcement`: "soft" | "strict" - whether to allow budget override as last resort
- `first_day_of_week`: day name, default `sunday` (display-only, doesn't affect algorithm; orders the Timeline week and every day-of-week list, via `daysOfWeekFrom` in `frontend/src/lib/days.ts`)
- `onboarding_completed`: boolean, default false - the first-run setup guide (`/welcome`, design-doc 8.1 screen 0a, Rev 16) opens on sign-in until it is finished or skipped
- `date_format`: `DD/MM/YYYY` (default) | `MM/DD/YYYY` | `YYYY-MM-DD`; `time_format`: `24h` (default) | `12h` (both display-only, Rev 15) - the frontend writes every date and time through `frontend/src/lib/dates.ts`, never `toLocaleString()`
