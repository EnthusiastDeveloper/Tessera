# Tessera - Design Document (POC)
### Revision 8

> **⚠ Open review against this revision - read before implementing.** `docs/implementation-readiness-review-2.md` (IRR-2) records unresolved findings against Revision 8, including twelve rated BLOCKER. Revision 8 declares this document "locked", and it is - no edits have been made in response to IRR-2, per Section 0's rule that changes go back to the stakeholder first. But "locked" here means "no unilateral edits", not "verified correct": several load-bearing rules below are internally contradictory or undefined (notably §6.2's obstacle set, §9.1's recurrence generation, `Duration`, and `active_hours_override`'s null semantics). Resolving IRR-2 into a Revision 9 is the intended next step.

## 0. How to use this document

This document is the authoritative specification for the Proof-of-Concept (POC) build. It was produced through a requirements-elicitation process where every field, algorithm rule, and boundary was explicitly confirmed by the product stakeholder - nothing here is a default or an assumption unless it is explicitly marked **[UNCONFIRMED - flagged during design, needs stakeholder sign-off]**.

Rules for whoever (human or LLM) implements against this doc:
- Section 3 (Data Model) and Section 6 (Scheduling Algorithm) are load-bearing. Do not deviate from them without raising the change back to the stakeholder.
- Section 12 (Backlog) is explicitly **out of scope**. Do not build it "while you're in there" - POC scope discipline is a deliberate design choice, not an oversight.
- Section 13 (Non-Goals) lists things that were considered and explicitly rejected for POC. Treat these the same as backlog items: known, deliberate, deferred.
- Section 14 (Design Decisions Log) contains binding architectural rules that don't map to a single feature but must be followed throughout implementation (e.g. timezone handling). Treat these as cross-cutting constraints, not optional style notes.

**Revision 2 changelog:** added user authentication (in scope for POC), scheduling-window constraints (global + per-task override), blackout dates, revised deletion semantics (dependency unlink instead of cascade, template archival instead of hard delete), overdue-task handling, notification self-resolution, and a binding timezone/DST rule. Holiday-calendar automation evaluated and moved to backlog with open questions recorded.

**Revision 3 changelog:** added a per-day-of-week **daily time budget** for flexible-task auto-placement, so the scheduling algorithm stops packing a day back-to-back once its configured capacity is used - measured as total scheduled duration (not task count), to avoid conflating a 5-minute chore with a 2-hour one. The budget is **soft**: it yields as a last resort when respecting it would otherwise cause a task to miss its deadline, and a new `budget_exceeded` notification surfaces whenever that happens.

**Revision 4 changelog:** made the soft-budget behavior itself configurable (`budget_enforcement: strict | soft` in Settings - `strict` disables the last-resort override entirely), and fixed a gap in the last-resort search: rather than accepting the first physically-free day it finds, it now compares every eligible day and picks the one with the smallest resulting overage.

**Revision 5 changelog:** added a `first_day_of_week` display preference. Display-only - the scheduling algorithm is unaffected, since active-hours/budget/blackout constraints are already keyed by day name, not by position in the week.

**Revision 6 changelog:** resolved a batch of edge cases surfaced during an implementation-readiness review (source list retained alongside this doc). Specifically:
- Fixed a null-reference bug in the dependency earliest-start calculation - it now keys off `dep.completed_at` instead of `dep.scheduled_time` (6.2).
- Clarified that an instance may be marked `completed` directly from `pending`/`blocked`/`scheduled`, not only from `in_progress` (3.3, Section 4).
- Confirmed (and documented why) dependency eviction does **not** need to cascade to downstream tasks (3.3, 6.2).
- Added creation-time feasibility validation for flexible tasks whose duration cannot fit any single day's active-hours window (new 6.8). Recorded task-splitting as a new backlog item (12.20) instead of building it now.
- Added a physical-buffer secondary tie-break to the Pass 2 budget-override day selection (6.2).
- Added computed, non-persisted "virtual" instance projection for Timeline display of recurring templates, without changing the real one-instance-at-a-time generation rule (new 9.2).
- Added external-event transparency/all-day filtering rules for calendar sync (Section 7).
- Clarified `fixed_time_of_day` as wall-clock local time (re-projected on timezone change), not a frozen UTC instant, and documented DST-transition handling (14.1).
- Added a new `missed` state for flexible tasks whose deadline elapses before they're ever scheduled or completed, replacing an infinite unschedulable-retry loop (Section 4, new 6.7).
- Added `14.2` (Authentication is mandatory) to resolve a dangling cross-reference from 8.1 present in earlier revisions.
- **Explicitly declined to resolve** one item - instance-level field overrides - because it contradicts the deliberate 3.1 decision. See Section 11, item 7 (reversed - see Revision 7 changelog below).

Several Revision 6 changes were marked **[UNCONFIRMED]** and collected in Section 11, per this document's own convention. Items 6 and 7 were resolved in Revision 7; **items 1–5 are resolved in Revision 8 below. As of Revision 8, Section 11 has no remaining open items - this document is fully locked for POC implementation.**

**Revision 7 changelog:** resolved Section 11 items 6 and 7 following stakeholder input.
- **Item 6 (the `missed` state) is CONFIRMED as specified in Revision 6.** No behavior change; the `[UNCONFIRMED]` markers in Section 4 and 6.7 are removed.
- **Item 7 (instance-level overrides) is RESOLVED, reversing the Revision 6 decision.** The stakeholder's reference point was Google Calendar's edit-scope prompt ("this event" vs. "this and following events"), adapted to this app's one-instance-at-a-time generation model (9.1), which collapses the usual three-way GCal choice to two. New **Section 3.10 (Edit Scope & Propagation)** is now the binding rule; `TaskInstance` gains a `detached` flag (3.3). Resolving this also closed two things that were previously informal or broken:
  - The dangling **"(3.6)"** citations in Revision 6's 3.1, 8.1, and Section 11 item 7 - which pointed to "edit-propagation rules" that were never actually written under that section number (3.6 is, and remains, the `User` schema) - now correctly point to 3.10.
  - The previously-unstated semantics of the fixed-task **"reschedule"** action (6.6, 8.1) are now formally defined as a "this occurrence" edit (3.10) of `scheduled_time`, not a template edit.
- Added Worked Examples L and M (Section 10) covering both edit-scope paths.
- Added a recurring-task-edit-scope row to the POC/Backlog scope table (Section 2).

**Revision 8 changelog:** closed the remaining five `[UNCONFIRMED]` items in Section 11. All five are **confirmed as originally specified - no behavior, schema, or algorithm changes**, so this revision is purely markup: removing `[UNCONFIRMED]` tags at 6.2, 6.8, Section 7, 9.2, and 14.1, and updating Section 11's status. One addition: Item 5's rejected alternative (a fixed-UTC-instant option for `fixed_time_of_day`) is recorded as new **Backlog 12.21**, so the idea isn't lost even though it wasn't built.

---

## 1. Product Summary

A self-hosted application that helps a single user define tasks, and automatically schedules the flexible ones onto a timeline while respecting fixed commitments, task deadlines, priorities, dependencies between tasks, the user's own active-hours preferences, and events already present on the user's external calendars (read-only, POC).

Core POC value proposition: **the user lists what needs doing and how urgent/flexible it is; the app figures out when to actually do it, without double-booking the user's real life or scheduling things at hours that don't make sense.**

---

## 2. Scope Boundary: POC vs. Backlog

| Area | POC | Backlog |
|---|---|---|
| Client | WebUI only | IM bot (V2) |
| Notification delivery | In-app banner (persisted) | Email, IM bot push |
| Users | Single user, with login (username/password) | Multi-user shared timeline; 2FA |
| Authentication | Password login; password reset via one-time container env var | Full account-recovery flows, SSO |
| External calendar | Read-only, polling | Write access, webhooks |
| Rescheduling on conflict | Fixed: manual resolution. Flexible: auto | Priority-based bumping of other tasks |
| Recurring-task edit scope *(added Rev 7)* | Two-way scope prompt on edit - "this occurrence" (instance override, 3.10) or "this and future" (template edit, propagates to the current live instance unless it's already detached) | Per-field diff/merge UI; explicit "re-sync to template" action for a detached instance |
| Scheduling algorithm | One fixed greedy algorithm | Multiple selectable algorithms |
| Scheduling window | Global active-hours (per day-of-week) + per-task override + manual blackout dates + soft daily time-budget cap (per day-of-week, yields to deadlines as last resort) | Business/location working-hours registry, task-to-business tagging; per-task budget exemption |
| Holidays | - | Multi-tradition holiday calendars (see 12.15 for open questions) |
| Location | Stored, informational only | Commute-time-aware scheduling, geofencing |
| Dependencies | On `TaskInstance` only; deleting a depended-on task unlinks, doesn't cascade | On `TaskTemplate` (recurring-to-recurring) |
| Task/duration analytics | - | Actual-vs-estimated duration tracking, prediction |
| Deployment | Single self-hosted app/container | Home Assistant add-on/integration |
| Task duration vs. window fit | Creation-time hard-block if a task can never fit any day's window (6.8) | Automatic splitting/chunking into sub-slots (12.20) |
| Recurring-task calendar preview | Non-persisted "virtual" projections rendered on Timeline (9.2) | Rolling-window pre-generation of real instances (12.13) |

---

## 3. Data Model

### 3.1 Design decision: everything is a `TaskInstance`, optionally generated from a `TaskTemplate`

Every completable, schedulable unit is a `TaskInstance`. A `TaskTemplate` always exists behind it - for a one-time task, the template has `recurrence: one_time` and generates exactly one instance immediately upon creation. For a recurring task, the template generates instances over time.

**(Amended Revision 7)** Editing a task now has two distinct scopes: **"this occurrence"** (an instance-level override touching only the live `TaskInstance` - see 3.3, 3.10) and **"this and future occurrences"** (a template edit - see 3.10 for exactly how and when it propagates to the currently-live instance). The Revision 6 framing - "edit a task always means edit its template" - is no longer accurate as a blanket statement; **3.10 is now the binding rule** and supersedes it.

This was a deliberate simplicity decision through Revision 6, not an oversight, and was reconsidered - not casually - in response to a concrete recurring case (Section 11, item 7) that the template-only model handled poorly. See 3.10 for the resolution and Section 11 item 7 for the reasoning trail.

### 3.2 `TaskTemplate`

```typescript
interface TaskTemplate {
  id: string;
  name: string;
  description?: string;
  location?: string;               // informational only in POC, see 13. Non-Goals

  type: "fixed" | "flexible";

  // --- Recurrence ---
  recurrence: {
    pattern: "one_time" | "daily" | "weekly" | "monthly" | "custom";
    interval?: number;              // e.g. every 2 weeks
    day_of_week?: number;           // for weekly
    day_of_month?: number;          // for monthly
  };

  // --- Fixed-type scheduling ---
  fixed_time_of_day?: string;       // e.g. "18:00" - a WALL-CLOCK local time, not a UTC
                                     // instant; see 14.1 for the binding rule on how this
                                     // is projected against the user's timezone.
                                     // required if type == "fixed"

  // --- Flexible-type scheduling ---
  deadline_offset?: Duration;       // e.g. "3 days after instance generation"
                                     // required if type == "flexible"

  priority: "low" | "medium" | "high" | "critical"; // enum in UI
  estimated_duration: Duration;     // e.g. minutes - see 6.8: validated at save time against
                                     // the applicable active-hours window for flexible tasks.

  reminder_offsets: Duration[];     // e.g. [ "1h", "15m", "0m" ]

  // --- Scheduling-window override (optional) ---
  active_hours_override?: {         // replaces the user's global active-hours window
    [day: string]: { start: string; end: string } | null;
  } | null;                         // null override = "no restriction", e.g. HVAC filters at 22:30

  archived: boolean;                // see 3.7 - archived instead of hard-deleted when history exists

  created_at: DateTime;
  updated_at: DateTime;
}
```

Notes:
- `dependencies` is **not** a template field (dependencies apply to `TaskInstance` only, POC). See Backlog 12.12.
- Numeric priority mapping (internal, not exposed in UI): `low=1, medium=2, high=3, critical=4`.
- `active_hours_override` exists for two conceptually different reasons that share one mechanism: (a) the user's personal flexibility about a specific chore ("filters can wait till late"), or (b) a genuine external constraint (a business's real opening hours). POC ships the mechanism; a proper business-hours registry with task tagging is Backlog item - see scope table.
- **(Added Revision 6)** `estimated_duration` is checked at save time against every day-of-week's applicable active-hours window (override if set, else global) - see 6.8. A duration that cannot physically fit any single day is rejected at creation, not silently left to fail scheduling forever.
- **(Added Revision 7)** A template edit only reaches a currently-live `TaskInstance` if that instance is not `detached` (3.3, 3.10). A `detached` instance keeps its own values until it completes; the template's new values apply starting with the *next* generated instance (9.1) regardless.

### 3.3 `TaskInstance`

```typescript
interface TaskInstance {
  id: string;
  template_id: string;              // always set, even for one-time tasks

  name: string;
  description?: string;
  location?: string;
  type: "fixed" | "flexible";
  priority: number;                 // numeric, copied from template at generation
  estimated_duration: Duration;

  detached: boolean;                // (added Revision 7, see 3.10) - true once this occurrence
                                     // has been individually edited or manually rescheduled.
                                     // A detached instance no longer receives template
                                     // propagation (3.10) of any kind - its fields are its
                                     // own until it reaches "completed". Default false.

  scheduled_time?: DateTime;        // set once placed on the timeline
  deadline?: DateTime;              // set at generation for flexible tasks

  status: "pending" | "scheduled" | "in_progress" | "completed" | "blocked" | "missed";
  status_history: { status: string; at: DateTime }[];

  dependencies: string[];           // TaskInstance ids - this instance cannot
                                     // be scheduled/started until all are "completed".
                                     // If a dependency is deleted, its id is simply
                                     // removed from this list (see 3.8) - this instance
                                     // is not deleted or altered otherwise.

  completed_at?: DateTime;

  generated_at: DateTime;
}
```

Notes:
- `completed` is a **terminal** state - an immutable historical record. Template edits never touch completed instances (3.10). *(Rev 7: this citation previously read "(3.6)" - see the Revision 7 changelog for why that was wrong.)*
- No `owner` field in POC (single-user; collaboration deferred, Backlog 12.6).
- **(Added Revision 6)** `status` gains a new value, `missed` - flexible-only, see Section 4 and new 6.7. `missed` is *not* equivalent to `completed` for dependency-graph purposes: a downstream instance depending on a `missed` instance stays `blocked` until the upstream instance is actually completed or the dependency link is removed via deletion (3.8).
- **(Added Revision 6)** An instance may be marked `completed` directly from `pending`, `blocked`, or `scheduled` - not only from `in_progress` - covering the "I already did this, don't bother scheduling/tracking it further" case. `completed_at` is always set on this transition regardless of whether `scheduled_time` was ever populated. `in_progress` remains an optional intermediate step, never mandatory.
- **(Added Revision 6)** Because a candidate only becomes eligible for scheduling (`pending`, unblocked from `blocked`) once **all** its dependencies have reached `completed` (never merely `scheduled`), a dependency's `completed_at` is always populated by the time it's read in 6.2's earliest-start calculation. This also means: if an upstream dependency is later evicted back to `pending` by an external-sync collision (6.4) or an overdue revert (6.6), that eviction has **no cascading effect** on any downstream instance that already unblocked - unblocking was gated on the upstream's (terminal, immutable) completion, not on it remaining scheduled. There is nothing to cascade.
- **(Added Revision 7)** `detached` is independent of `status` - a `pending`, `blocked`, or `scheduled` instance can be `detached`; the flag only concerns whether the instance's fields still track its template. See 3.10 for the full edit-scope and propagation rule, and for which fields it applies to (notably: not `type`, not `dependencies`, not `status`).

### 3.4 `Notification`

```typescript
interface Notification {
  id: string;
  type: "reminder"
      | "creation_conflict"        // fixed-task creation hard-blocked (see 6.5)
      | "sync_conflict"            // fixed task now collides with synced external event
      | "unschedulable"            // flexible task has no valid slot before its deadline, even ignoring the daily budget
      | "dependency_at_risk"       // deadline approaching with unfulfilled dependency (see 6.3)
      | "overdue"                  // scheduled time has passed with no completion (see 6.6)
      | "budget_exceeded"          // task was placed by overriding the daily time budget as a last resort (see 6.2)
      | "deadline_missed";         // (added Rev 6) flexible task's deadline elapsed before it was
                                    // ever scheduled/completed (see 6.7)

  related_instance_id: string;
  message: string;

  created_at: DateTime;
  dismissed_at?: DateTime;         // user explicitly closed it
  resolved_at?: DateTime;          // underlying condition cleared on its own (see 3.9)
}
```

Kept as a **separate enum from `TaskInstance.status`** - a task can be simultaneously `scheduled` and have an active `dependency_at_risk` notification.

### 3.5 `ExternalCalendarConnection`

```typescript
interface ExternalCalendarConnection {
  id: string;
  provider: "google" | "outlook" | "other";
  oauth_credentials_ref: string;    // reference to secret storage, not raw tokens in this table
  refresh_interval_minutes: number; // configurable in Settings
  last_synced_at?: DateTime;
  sync_mode: "read_only";           // POC is read-only; "read_write" is Backlog 12.4
  enabled: boolean;
}
```

Fetched external events are treated as opaque busy-blocks (start, end, title for display) - **with the filtering rules added in Section 7 (Revision 6)** for transparent/"Free" events and all-day events - never edited/written to by this app in POC.

### 3.6 `User`

```typescript
interface User {
  id: string;
  username: string;
  password_hash: string;
  two_factor_enabled: boolean;      // always false in POC; field reserved for Backlog
  created_at: DateTime;
}
```

**Password reset (confirmed mechanism):** on container startup, if a `RESET_ADMIN_PASSWORD` env var (or mounted secret file) is present and non-empty, the app resets the admin password to that value **once**. On successful reset, the app writes a local marker (e.g. a hash of the value it just consumed) so that if the same env var is still present on the next restart, the app does **not** reset again - it logs a warning instead. This prevents the env var from acting as a standing backdoor if the operator forgets to remove it from their compose file after use. A changed value is treated as a new reset request and is honored.

### 3.7 `UserSettings`

```typescript
interface UserSettings {
  id: string;
  timezone: string;                 // IANA name, e.g. "America/New_York" - see 14.1
                                     // default sourced from the container's TZ env var
  active_hours: {                   // global default scheduling window, per day of week
    [day: string]: { start: string; end: string } | null;  // null = day fully excluded
  };
  blackout_dates: { start: Date; end: Date; label?: string }[]; // manual full-day exclusions
                                     // (POC stand-in for holiday calendars, see Backlog 12.15)

  daily_time_budget: {               // max total scheduled duration per day, per day of week
    [day: string]: Duration | null;  // null = unlimited for that day. Soft cap - see 6.2:
                                      // yields as a last resort rather than causing a missed deadline
  };

  budget_enforcement: "strict" | "soft";  // "strict": daily_time_budget is a hard wall - a task that
                                           //   can't be placed within budget becomes unschedulable.
                                           // "soft" (default): the algorithm's last-resort override
                                           //   (6.2) is allowed to breach the budget to meet a deadline.

  first_day_of_week: "sunday" | "monday" | "tuesday" | "wednesday"
                    | "thursday" | "friday" | "saturday";  // display-only, see note below.
                                                            // default: "monday"
}
```

`first_day_of_week` affects **display only** - it controls the Timeline view's calendar layout (8.1) and the row order of the day-of-week settings below (`active_hours`, `daily_time_budget`, `blackout_dates`). It has no effect on scheduling algorithm behavior: those fields are already keyed by day name rather than position-in-week, so the algorithm doesn't have a concept of "week" to reorder in the first place.

`active_hours` (and any `TaskTemplate.active_hours_override`), `blackout_dates`, and `daily_time_budget` constrain **flexible-task auto-placement only** (6.2). Fixed tasks are user-chosen times and are never constrained by this window - the window governs what the algorithm may choose, not what the user is allowed to set manually. Note the distinction between "constrains" and "counts toward capacity" for `daily_time_budget` specifically: fixed tasks and external calendar events are never *blocked* by the budget, but their duration *does* count against a day's budget when the algorithm decides whether there's still room for more flexible tasks that day (see 6.2) - otherwise a day already packed with fixed commitments would still get flexible chores piled on top of it, which defeats the purpose of the setting. Unlike `allowed_hours` and `blackout_dates`, which are hard constraints the algorithm never crosses, `daily_time_budget` is a constraint whose strictness is itself configurable via `budget_enforcement` - see 6.2 for exactly when and how it's allowed to yield.

### 3.8 Deletion & archival rules

- **Deleting a `TaskInstance` that other instances depend on:** the dependency link is simply removed from the dependent instance(s)' `dependencies` array. The dependent instance(s) are otherwise untouched. If this removal leaves a `blocked` instance with zero remaining dependencies, it transitions to `pending` per the normal state machine (Section 4) and becomes eligible for the next scheduling pass. **No cascading delete.**
- **Deleting a `TaskTemplate` with incomplete instances:** the UI must show a confirmation dialog explaining the implications (which incomplete instances exist and what happens to them) before proceeding. On confirmation, the template is **archived**, not hard-deleted (`archived = true`) - this keeps `template_id` references on historical/completed instances valid rather than dangling, and preserves history availability.

### 3.9 Notification self-resolution

If the condition a `Notification` was raised for clears on its own before the user acts on it (e.g. a `dependency_at_risk` dependency completes in time, a `sync_conflict` resolves because the external event was later removed, a `deadline_missed` instance is extended back to `pending` or completed - see 6.7), the system sets `resolved_at` automatically. If the user opens/clicks a notification that has already auto-resolved, the UI shows an "already resolved" state instead of presenting stale action buttons tied to a condition that no longer exists.

`budget_exceeded` remains the one exception (5): it records something that already happened, not an ongoing condition, so it is dismissed like a normal informational notice rather than auto-resolved.

### 3.10 Edit Scope & Propagation (added Revision 7)

This section defines what "editing a task" does, resolving the Revision 6 gap where 3.1, 8.1, and Section 11 item 7 all cited a "3.6" that never actually contained this content - Section 3.6 is, and remains, the `User` schema. It also formally resolves Section 11 item 7 (reversing the Revision 6 non-decision).

**Reference model, and why it's two-way here, not three-way.** The requested behavior is deliberately modeled on Google Calendar's recurring-event edit prompt. GCal offers three scopes ("this event" / "this and following events" / "all events") because a recurring series there is a set of events that mostly already exist as persisted rows. This app's generation model (9.1) is different: only **one real instance exists at a time**, generated fresh once its predecessor reaches `completed`. There is no persisted "following" series to fan an edit out across, and Timeline previews of upcoming occurrences (9.2) are explicitly virtual and non-editable. So the three-way GCal choice collapses to two here:

| Scope | What it touches | What it does NOT touch |
|---|---|---|
| **"This occurrence"** | The live `TaskInstance` directly - any of `name`, `description`, `location`, `priority`, `estimated_duration`, `deadline` (flexible only), or `scheduled_time` (fixed only, i.e. a manual reschedule, 6.6). Sets `detached = true`. | The `TaskTemplate`. Future-generated instances (9.1) are unaffected and will reflect the template's values, not this override. |
| **"This and future occurrences"** | The `TaskTemplate` (as in Revision 6), **plus** the currently-live instance's corresponding fields, applied immediately - *unless that instance is already `detached`* (see below). | Already-`completed` instances - terminal and immutable per 3.3, unreachable by any propagation. |

There is deliberately no third "all occurrences, including past" scope: "past" means `completed`, and 3.3 already makes `completed` instances immutable. Nothing new is needed there.

**Detach is sticky and total, not per-field.** Once an instance is `detached` (via any "this occurrence" edit, or a manual fixed-task reschedule, 6.6), it is skipped **entirely** by all subsequent "this and future" template propagation - not just the field(s) originally overridden - until it reaches `completed`, at which point it's immutable history and propagation is moot anyway. This mirrors GCal's actual behavior (a customized single event keeps its customization even after later series-wide edits) and avoids a harder problem this POC doesn't need: field-by-field merge logic between an instance's overrides and a template's new values. Full detach is simpler, matches user expectation, and is an explicit tradeoff - a finer-grained per-field merge is a possible future direction, not currently backlogged since it hasn't actually been requested.

**What "applied immediately" means for the non-detached case.** If the live instance is *not* detached, a "this and future" template edit updates its copied fields to match the new template values in the same operation - it does not wait for the next generation cycle (9.1). If the field(s) changed affect scheduling validity (e.g. `estimated_duration` grew past the remaining time before `deadline`, or past the day's `active_hours_override`/budget), the instance re-enters the normal `pending` scheduling pool and is re-evaluated by 6.2 exactly as any other edit-triggered re-placement would be - this is not a new mechanism, just an added entry point into 6.2 (see 6.2's updated "runs whenever" clause).

**Interaction with 6.8 (feasibility validation).** A "this occurrence" override that changes `estimated_duration` is checked against 6.8 the same way template-level duration changes are - an override that could never fit any day's active-hours window is rejected at save time with the same `infeasible_duration` error, not silently accepted and left to fail scheduling forever.

**UI implication (see also 8.1).** The task edit form must prompt for scope ("this occurrence" vs. "this and future") whenever the task being edited is (a) recurring and (b) not a one-time (`recurrence: one_time`) template - a one-time task has no "future occurrences" to distinguish, so no prompt is needed; the edit simply applies to that instance and template alike, as in Revision 6. The task detail view should visibly indicate when an instance is `detached`, so the user understands why it didn't pick up a later template-wide edit.

---

## 4. Status Lifecycle (state machine)

```
                 ┌─────────────┐
                 │   pending   │◄────────────────────────────┐
                 └──────┬──────┘                              │
                        │ scheduling algorithm finds a slot    │ external sync invalidates, or
                        ▼                                      │ overdue flexible task auto-reschedules
                 ┌─────────────┐                               │
      ┌─────────►│  scheduled  │───────────────────────────────┘
      │          └──────┬──────┘
      │                 │ user marks "in progress" (optional step)
      │                 ▼
      │          ┌──────────────┐
      │          │ in_progress  │
      │          └──────┬───────┘
      │                 │ user marks complete
      │                 ▼
      │          ┌──────────────┐
      │          │  completed   │  ◄── terminal, immutable
      │          └──────────────┘
      │
      │  all remaining dependencies complete
      │  (including via dependency removal on deletion, 3.8)
      │
┌─────┴──────┐
│  blocked   │  ◄── instance has ≥1 incomplete dependency;
└─────┬──────┘      cannot enter scheduling pool while blocked
      │
      │  deadline elapses before scheduled/completed (flexible only, 6.7)
      ▼
┌────────────┐
│   missed   │  ◄── flexible only; excluded from scheduling candidates
└─────┬──────┘      until the user acts
      │
      ├── user extends deadline ─────────► back to pending
      ├── user marks complete ───────────► completed
      └── user deletes instance/template ─► removed (3.8)
```

Rules:
- A `TaskInstance` with unfulfilled dependencies starts life as `blocked`, not `pending`.
- Only `pending` instances are eligible for the scheduling algorithm.
- `fixed` instances go straight to `scheduled` at creation if hard-block validation (6.5) passes - they never enter the algorithm, since their time is user-specified.
- A `fixed` instance can also start `blocked` if it has unfulfilled dependencies; once unblocked it becomes `scheduled` directly.
- **(Added Revision 6)** `completed` is reachable directly from `pending`, `blocked`, or `scheduled` - not only via `in_progress` - see 3.3.
- **(Added Revision 6)** `missed` is reachable from `pending` or `blocked` (flexible instances only) when the deadline elapses before the instance is scheduled or completed. See 6.7 for the full trigger logic and resolution paths. **[CONFIRMED - Revision 7, Section 11 item 6 - no change from the Revision 6 design.]**
- **(Added Revision 7)** `detached` (3.3/3.10) is orthogonal to `status` - it does not add, remove, or gate any transition in this diagram. An instance can be `detached` in any non-terminal status.

---

## 5. Notification Types - reference

| Type | Trigger | Resolution path |
|---|---|---|
| `reminder` | Now + reminder_offset == scheduled_time | User dismisses; informational only |
| `creation_conflict` | Fixed task creation collides with existing fixed task or external event | User must change the new task's time/type before saving (hard block, 6.5) |
| `sync_conflict` | External sync introduces an event colliding with a `scheduled` fixed task | Manual: user reschedules or dismisses |
| `unschedulable` | Flexible task's placement search finds no valid slot before its deadline | User relaxes deadline/duration or intervenes manually |
| `dependency_at_risk` | Deadline within 3 days (flat, POC threshold) with ≥1 incomplete dependency | Informational; user chases dependency or adjusts deadline |
| `overdue` | `scheduled_time` has passed, instance not `completed` | Flexible: auto-reschedules, notification is informational. Fixed: action menu offers "reschedule" **and** "mark complete" (see 6.6) |
| `budget_exceeded` | A flexible task was placed by overriding its day's `daily_time_budget` because no compliant slot existed before the deadline (see 6.2) | Informational; user may relax the deadline, move another task off that day, or accept it |
| `deadline_missed` *(added Rev 6)* | A flexible instance's `deadline` elapses while status is `pending` or `blocked` (see 6.7) | User extends deadline, marks complete, or deletes the instance/template - auto-resolves when any of those happen (3.9) |

All types support auto-resolution per 3.9, **except `budget_exceeded`**: it records something that already happened (the task was placed over budget), not an ongoing condition that can clear on its own - it's dismissed like a normal informational notice, never auto-resolved.

---

## 6. Scheduling Algorithm

### 6.1 Dependency resolution & cycle detection

- Dependencies form a directed graph over `TaskInstance` ids.
- Cycle check runs at **save time** - a task cannot be saved with a dependency list that would create a direct or indirect cycle. Reject with a validation error.
- Before each scheduling pass, topologically sort all `pending` flexible instances so no instance is placed before its dependencies' scheduled/completed times.

### 6.2 Core placement algorithm

Runs whenever: a new flexible instance enters `pending`, an external sync or overdue event invalidates a scheduled flexible instance (returns it to `pending`), a dependency completes/is removed and unblocks a downstream instance, or **(added Revision 7)** a non-`detached` flexible instance's `estimated_duration`/`deadline` changes via a "this and future" template propagation (3.10) in a way that invalidates its current placement.

```
function schedule_pending_flexible_tasks():
    candidates = all TaskInstance where status == "pending" and type == "flexible"
    candidates = topological_sort(candidates, by=dependencies)
    candidates = stable_sort(candidates, key=(deadline ASC, priority DESC))

    for task in candidates:
        earliest_start = max(
            now(),
            max(dep.completed_at for dep in task.dependencies)
                if task.dependencies else now()
        )
        # (Fixed Revision 6) Uses dep.completed_at, not dep.scheduled_time + duration.
        # A candidate only reaches "pending" once ALL its dependencies are "completed"
        # (Section 4) - so completed_at is always populated here, never null, and it
        # reflects the dependency's actual real-world finish time rather than its
        # original plan, which may have diverged (e.g. the dependency was marked
        # complete directly from "pending" without ever being scheduled - 3.3).

        allowed_hours = task.template.active_hours_override
                         if task.template.active_hours_override is not None
                         else user_settings.active_hours

        # Pass 1: respect the daily time budget (preferred outcome)
        slot = find_first_free_slot(
            duration = task.estimated_duration,
            not_before = earliest_start,
            not_after = task.deadline,
            allowed_hours = allowed_hours,          # per-day-of-week window
            excluded_dates = user_settings.blackout_dates,
            daily_time_budget = user_settings.daily_time_budget,  # per-day-of-week cap, see 3.7
            obstacles = all "fixed" TaskInstances (scheduled)
                      + all already-scheduled "flexible" TaskInstances (this pass)
                      + all external calendar busy-blocks (filtered per Section 7 - Rev 6)
        )

        budget_overridden = False
        if slot is None and user_settings.budget_enforcement == "soft":
            # Pass 2: only runs in "soft" mode (3.7). Reached when respecting
            # the budget would leave the task unplaceable before its deadline.
            #
            # Rather than accepting the first physically-free day encountered,
            # evaluate every day in [earliest_start, task.deadline] that has a
            # physically free slot of sufficient duration (allowed_hours,
            # excluded_dates, and obstacles still apply - only daily_time_budget
            # is ignored).
            candidate_days = every day in [earliest_start, task.deadline]
                             with a physically free slot of sufficient duration
                             (budget ignored; all other constraints still apply)

            if candidate_days is not empty:
                best_day = day in candidate_days minimizing, in order:
                    1. overage = max(0, committed_duration(day) + task.estimated_duration
                                          - (daily_time_budget[day_of_week(day)] or +infinity))
                    2. (added Rev 6) -remaining_physical_free_capacity(day after placement)
                       # prefer the day that ends up LESS "wall-to-wall" when overage ties -
                       # i.e. maximize slack left over, not just minimize formal overage
                    3. earliest date  # final tie-break
                slot = earliest free slot within best_day
                budget_overridden = True

        if slot exists:
            task.scheduled_time = slot.start
            task.status = "scheduled"
            if budget_overridden:
                create Notification(type="budget_exceeded", related=task)
        else:
            create Notification(type="unschedulable", related=task)
            # task stays "pending"
```

`find_first_free_slot` treats `daily_time_budget` (when passed) as an additional day-level exclusion, alongside `allowed_hours` and `excluded_dates`: for each candidate day D it is considering, it sums the duration of every obstacle already occupying D (fixed instances scheduled that day + external busy-blocks that day + flexible instances already placed on D in this pass) and skips D entirely for this task if `committed_duration(D) + task.estimated_duration` would exceed `daily_time_budget[day_of_week(D)]`. The day isn't invalid in general - just full for the purposes of adding more flexible work - so the search simply continues to the next eligible day.

Notes:
- Single fixed greedy algorithm for POC (Backlog 12.9 covers alternatives). The minimum-overage comparison in Pass 2 is a bounded, deterministic tie-break rule, not a pluggable/alternate algorithm - it stays within that scope.
- "Obstacles" accumulate within a single pass, preventing self-collision among flexible tasks placed in the same run.
- `allowed_hours`, `excluded_dates`, and `daily_time_budget` apply to flexible placement only - never to fixed tasks (3.7).
- Budget accounting includes fixed tasks and external events, not just flexible ones (3.7) - a day already full of meetings shouldn't also absorb a stack of chores just because no *flexible* task has been placed there yet.
- **The daily budget's strictness is configurable via `budget_enforcement`** (3.7). In `"strict"` mode, Pass 2 never runs - a Pass-1 failure becomes `unschedulable` directly, even if a physically free slot exists elsewhere in the window. In `"soft"` mode (default), Pass 2 runs and picks the least-damaging day as described above.
- `unschedulable` is reserved for the case where no slot exists **even after ignoring the budget** (in `"soft"` mode), or where Pass 1 simply fails (in `"strict"` mode) - i.e. there's genuinely no acceptable time before the deadline under the configured policy.
- Day boundaries for budget accounting are computed in the user's configured IANA timezone, consistent with the binding rule in 14.1.
- **(Added Revision 6)** The Pass 2 tie-break now has three ordered keys: smallest overage, then most remaining slack, then earliest date. **[CONFIRMED - Revision 8, Section 11 item 2.]**
- **(Added Revision 6)** A flexible task's `deadline` having already elapsed by the time it enters this function is handled *before* it ever gets here - see new 6.7. This function should never actually receive a task with `deadline <= earliest_start`; if it does, that's a bug in the 6.7 gate, not a case this function needs to handle defensively.
- **(Added Revision 6)** Feasibility (can this duration ever fit, on any day, under any circumstance) is checked once at task creation, not per scheduling pass - see new 6.8.

### 6.3 Dependency-at-risk alerting

- Periodic check. For any non-completed instance with ≥1 incomplete dependency, if `deadline - now() <= 3 days` (flat POC threshold), create a `dependency_at_risk` Notification.
- Deduplicated - fires once per (instance, threshold-crossing) event, not every scan.

### 6.4 External calendar sync - collision handling

On each poll:
1. Fetch upcoming events, diff against previously known set.
2. Apply the filtering rules in Section 7 (Rev 6) - transparent/"Free" events and all-day events are excluded from the busy-block obstacle set before collision-checking runs.
3. For new/moved events colliding with a `scheduled` instance:
   - **Fixed:** create `sync_conflict` Notification. Never auto-moved.
   - **Flexible:** clear `scheduled_time`, set `status = "pending"`, re-enter next scheduling pass (subject to the 6.7 deadline-elapsed gate first).

### 6.5 Fixed-task creation conflict handling

- On creating/retiming a `fixed` instance, validate against all other `scheduled` fixed instances and all known external busy-blocks (filtered per Section 7).
- **Hard block on creation** if overlap found. No save-with-override in POC (Backlog 12.8).

### 6.6 Overdue-task handling

Periodic check for instances where `scheduled_time` has passed and `status` is not `completed`:
- **Flexible:** clear `scheduled_time`, set `status = "pending"` (re-enters 6.2 on next pass, subject to the 6.7 deadline-elapsed gate first), create an informational `overdue` Notification so the move isn't silent.
- **Fixed:** status unchanged, create an `overdue` Notification whose action menu offers both **"reschedule"** (opens edit, subject to 6.5 validation for the new time) and **"mark complete"** - covering the case where the user simply forgot to check it off.

**(Added Revision 7)** "Reschedule" on a fixed instance is formally a "this occurrence" edit (3.10) of `scheduled_time` - it sets `detached = true` on that instance. Practical consequence: after a manual reschedule, that instance is excluded from the timezone-change re-projection in 14.1 (the user's manually-chosen time is treated as deliberate and is not silently re-projected against a later timezone-setting change), and it will not be overwritten if the template's `fixed_time_of_day` is later edited with "this and future" scope.

### 6.7 Deadline-elapsed handling for flexible tasks (`missed` state) - added Revision 6

Distinct from 6.6, which governs `scheduled_time` elapsing on an already-placed task. This addresses a flexible instance's **`deadline`** elapsing while the instance was never successfully scheduled or completed - e.g. it has been sitting `pending` with an active `unschedulable` notification, or `blocked` on a dependency that never completed in time.

Without this gate, a flexible task overdue past its own deadline would hand `find_first_free_slot` an inverted window (`not_before > not_after`), fail instantly, and re-trigger an `unschedulable` notification on every subsequent scheduling pass forever - a silent infinite-retry loop with no path to resolution.

**Checked:**
1. Periodically, for all `pending`/`blocked` flexible instances.
2. Inline, any time a flexible instance is about to (re-)enter the `pending` pool - initial creation, dependency unblock, sync-eviction (6.4), overdue-revert (6.6). If `deadline <= now()` at that moment, the instance goes straight to `missed` instead of being hand to the scheduler with an already-inverted window.

**On transition to `missed`:**
- `status = "missed"`; excluded from the 6.2 candidate pool.
- Create a `deadline_missed` Notification (3.4/5).

**Resolution (user-driven, one of):**
- **Extend the deadline** → instance returns to `pending`, re-enters the next scheduling pass, notification auto-resolves (3.9). **(Added Revision 7)** This is itself a "this occurrence" edit of `deadline` (3.10) and sets `detached = true`, so a later "this and future" edit to the template's `deadline_offset` won't silently re-shorten a deadline the user just deliberately extended.
- **Mark complete** directly → terminal, notification auto-resolves.
- **Delete the instance/template** → per 3.8 deletion rules; notification becomes moot.

**Dependency-graph note:** if another instance depends on a `missed` instance, that dependent remains `blocked` indefinitely - `missed` is not `completed`, and does not satisfy a dependency requirement. It clears only when the `missed` instance is completed, or the dependency link is removed via deletion (3.8).

**[CONFIRMED - Revision 7, Section 11 item 6. No change from the Revision 6 design above.]**

### 6.8 Creation-time feasibility validation for flexible tasks - added Revision 6

Before a flexible `TaskTemplate` (and its initial instance) is saved, validate that `estimated_duration` fits within **at least one** day's applicable active-hours window - the per-day `active_hours_override` if set on the template, else `user_settings.active_hours` - i.e.:

```
max_window = max( (end - start) for every day-of-week entry that is non-null
                   in the applicable active_hours map )

if estimated_duration > max_window (or no day-of-week has a non-null window at all):
    reject save with validation error "infeasible_duration"
```

This mirrors the existing hard-block pattern already used for fixed-task creation conflicts (6.5), rather than introducing a new mechanism. Without it, a task like a 5-hour "Deep Clean Garage" against a 3-hour daily active-hours cap would sit `pending` forever, re-triggering `unschedulable` on every pass, with no signal to the user that the problem isn't *timing* but that the task is **structurally too big to ever fit as a single block**.

Deliberately **not** pursued for POC: automatic splitting of the task into multiple sub-slot chunks. That's a real capability (it would need partial-completion semantics, resumption logic, and its own notification design) and is exactly the kind of scope creep Section 0 and the architecture plan's "no premature abstraction" rule warn against. Recorded as new Backlog item 12.20.

**[CONFIRMED - Revision 8, Section 11 item 1. Hard-block at creation, as specified.]**

---

## 7. External Calendar Integration (POC scope)

Read-only, polling-based (webhooks require a publicly reachable endpoint, conflicting with LAN-only self-hosting - deferred, Backlog 12.5). Configured per-provider in Settings: connect account (OAuth), set `refresh_interval_minutes`. Staleness between polls should be visible to the user (e.g. "Calendar last synced: 4 minutes ago"), not hidden.

**Event filtering (added Revision 6):**
- Events explicitly marked **transparent / "Free"** by the provider (i.e. the calendar owner marked themselves as available during that event) are excluded from the busy-block obstacle set entirely - they never obstruct flexible-task placement (6.2) or fixed-task conflict checks (6.5).
- **All-day events** are imported and shown on the Timeline, but for POC are treated as **display-only overlays** - they do not block flexible placement and are not automatically converted into `blackout_dates`.

**[CONFIRMED - Revision 8, Section 11 item 4. Display-only for POC; per-event holiday-style semantics remains deferred to Backlog 12.15.]**

---

## 8. UI Scope (POC)

WebUI only (Backlog 12.2 for IM bot).

### 8.1 Screens

1. **Login screen** - username/password (see 3.6, 14.2).
2. **Timeline / Task list view** - calendar-style view of `scheduled` instances, **plus display-only virtual/"ghost" projections of upcoming recurring occurrences (9.2, added Revision 6)**, external busy-blocks overlaid read-only and visually distinguished (post-filtering per Section 7), blackout dates visibly marked.
3. **Task creation/edit form** - for a new task, or when editing a one-time (`recurrence: one_time`) template, edits the `TaskTemplate` directly as in Revision 6. **(Rev 7)** For an existing recurring task, first prompts for edit scope - **"this occurrence"** vs. **"this and future occurrences"** (3.10) - before applying the edit; includes the optional active-hours override (3.2); surfaces the archival/deletion warning (3.8); surfaces the feasibility validation error on save if applicable (6.8, added Revision 6).
4. **Task detail view** - single `TaskInstance`: status, status history, dependencies (with current status), a visible **`detached` indicator** when applicable (3.10, added Rev 7), actions: mark complete (from any non-terminal status, 3.3), mark in-progress, reschedule (for `sync_conflict`/`overdue` fixed tasks - a "this occurrence" edit per 3.10/6.6), extend deadline (for `missed` flexible tasks, 6.7 - also a "this occurrence" edit per 3.10).
5. **Notifications panel** - undismissed/unresolved `Notification` rows; auto-resolved ones show the "already resolved" state if opened (3.9).
6. **Settings** -
   - Account: change password.
   - External calendars: connect/disconnect, refresh interval, last-sync timestamp.
   - Scheduling window: global active-hours per day of week, blackout dates list, daily time-budget cap per day of week, and a budget-enforcement toggle ("respect the budget" / "meet the deadline") controlling whether the last-resort override in 6.2 is allowed at all.
   - Timezone: select IANA timezone, defaulted from container `TZ`.
   - Display: first day of the week (for Timeline layout and Settings ordering).

### 8.2 Deletion confirmation dialogs (per 3.8)

- Deleting a `TaskInstance` with dependents: informational notice only ("N task(s) depend on this - the dependency link will be removed, those tasks will not be deleted"), no hard block, since it's no longer a cascading operation.
- Deleting/archiving a `TaskTemplate` with incomplete instances: confirmation dialog listing the affected incomplete instances before proceeding.

---

## 9. Architecture & Deployment

- Self-hosted, single deployable unit - modular monolith (backend + scheduling engine + WebUI), not microservices.
- **Database:** SQLite recommended for POC (single-user, no concurrent-write pressure, no extra container). Revisit if multi-user (Backlog 12.6) lands.
- **Packaging:** single container image. Home Assistant add-on packaging is Backlog 12.10.
- **Background jobs:** (a) external calendar poll per connection, (b) reminder scan, (c) dependency-at-risk scan (6.3), (d) overdue scan (6.6), (e) recurring-template instance generation (9.1), (f) deadline-elapsed scan (6.7, added Revision 6).
- **Auth:** password-based login required for POC (3.6); session/cookie mechanism is an implementation detail but must exist - this is no longer optional per stakeholder confirmation (see 14.2).

### 9.1 Recurring instance generation

Proposed: generate the **next single instance** for a `TaskTemplate` once its current/most-recent instance reaches `completed`, rather than pre-generating a rolling window. Simpler for POC. Rolling-window pre-generation is Backlog 12.13 if this proves insufficient.

This rule is about **real, persisted** `TaskInstance` generation only, and is unchanged by Revision 6. See 9.2 for how the Timeline nonetheless shows upcoming recurring commitments without changing this rule.

**(Added Revision 7)** Generation always reads the template's *current* values at generation time, regardless of whether the just-completed prior instance was `detached` (3.10) - a one-off override never leaks into the next generated instance. `detached` is a property of an instance, not of the template.

### 9.2 Recurring template preview projection - Timeline display only (added Revision 6)

Under 9.1's one-instance-at-a-time rule, the Timeline would otherwise show nothing for a recurring commitment beyond its single currently-generated instance - e.g. a "Weekly Team Sync" every Monday would vanish from Tuesday through Sunday even though the user obviously still has it every week. That's a real usability gap for previewing upcoming workload, not just a cosmetic nice-to-have.

**Resolution:** the Timeline computes and renders **virtual, non-persisted** occurrences for recurring templates (`fixed` and `flexible`) out to a fixed display horizon (default: 30 days), by projecting the template's `recurrence` pattern forward from the most recently generated/completed real instance. Virtual occurrences:
- Are visually distinguished from real, persisted instances (e.g. dimmed/hatched styling).
- Are **read-only** - cannot be marked complete, rescheduled, or otherwise interacted with, since they aren't real `TaskInstance` rows.
- Carry no `id`, participate in no dependency graph, trigger no notification.
- Are excluded entirely from the scheduling algorithm (6.2) and from `daily_time_budget` accounting - only real, persisted instances affect scheduling and budget math.

Real instance generation itself remains exactly as specified in 9.1. This section changes **display only**.

**[CONFIRMED - Revision 8, Section 11 item 3. Display-only, non-persisted, 30-day horizon - confirmed as a hardcoded constant for POC, not a `UserSettings` field.]**

---

## 10. Worked Examples

**Example A - Fixed task creation, hard block.** User tries to create a `fixed` instance "Team sync" Monday 18:00–19:00; an external busy-block "Date night" occupies Monday 18:00–22:00. Creation is rejected; user must pick another time or switch to `flexible`.

**Example B - Flexible task placement respecting active hours.** User creates `flexible` "Replace HVAC filters," monthly, 30m duration, 5-day deadline offset, with an `active_hours_override` extending to 22:30 (this task doesn't mind late hours, unlike most others). The scheduling pass finds the first free 30-minute slot before the deadline, honoring the override rather than the global window.

**Example C - Sync invalidates a scheduled flexible task.** The HVAC-filter instance was scheduled Tuesday 16:00. The user books concert tickets, syncing in as a new event Tuesday 16:00–19:00. Per 6.4, the instance's slot is cleared, status reverts to `pending`, and it's re-placed in the next pass.

**Example D - Dependency chain, then deletion.** "Prepare car for inspection" (10-day deadline) and "Perform annual inspection" (14-day deadline, depends on the first) - inspection starts `blocked`. If the user instead deletes "Prepare car" outright, the dependency link is removed per 3.8, and "Perform annual inspection" transitions to `pending` immediately rather than being deleted itself - the user is now responsible for getting the car ready some other way, but the inspection task survives.

**Example E - Unschedulable task.** A `flexible` task with a tight deadline and long duration finds no free slot within the active-hours window before its deadline. It stays `pending`; an `unschedulable` Notification is created.

**Example F - Forgot to mark complete.** A `fixed` "Doctor's appointment" instance's `scheduled_time` passes. The overdue scan (6.6) fires an `overdue` Notification. The user opens it, realizes they did go, and taps "mark complete" directly from the notification's action menu - no need to hunt down the task in the list view.

**Example G - Daily budget yields to a deadline (soft cap).** The user sets `daily_time_budget["saturday"] = 3h` and `budget_enforcement = "soft"`. Three `flexible` chores totaling 2.5 hours are already scheduled this Saturday. A new `flexible` task, "Deep-clean garage" (1.5h estimated, deadline Saturday night - no other eligible day remains before the deadline), enters the scheduling pass. Pass 1 (budget-respecting) finds no compliant slot, since `2.5h + 1.5h = 4h` exceeds the 3h cap and no other day qualifies before the deadline. Because missing the deadline is treated as worse than a moderate overflow, Pass 2 retries with the budget ignored, finds the same 1.5-hour opening still physically free that day, and schedules it there - pushing Saturday to 4 hours of flexible work. A `budget_exceeded` Notification is created so the user knows the day ran over and why. Had no physically free slot existed at all that day (e.g. fixed commitments filled every remaining minute, budget aside), the task would still fall back to `pending` with an `unschedulable` Notification, exactly as in Example E.

**Example H - Pass 2 picks the least-damaging day, not the earliest one.** A 20-minute `flexible` task is due Thursday. Every day before the deadline is already tight on budget: Tuesday and Wednesday have no physically free slot at all (fully booked with fixed commitments), Sunday has only 10 minutes of budget remaining, and Monday has 17 minutes remaining. Pass 1 fails everywhere. Pass 2 considers only the days with a *physically* free 20-minute opening - Sunday and Monday - and computes the overage each would cause: Sunday would go 10 minutes over (`20 - 10`), Monday only 3 minutes over (`20 - 17`). Monday has the smaller overage, so the task is scheduled Monday, even though Sunday would have been reached first in a purely chronological scan. A `budget_exceeded` Notification is created for the 3-minute overage.

**Example I - Feasibility hard block at creation (6.8, added Rev 6).** The user's global active hours are 18:00–21:00 every day (a 3-hour daily window). They try to create a `flexible` task "Deep Clean Garage," `estimated_duration = 5h`, deadline 14 days out. At save time, 6.8 finds no day-of-week window ≥ 5h (max is 3h) and rejects the save with an `infeasible_duration` error - the user is told up front the task can't fit as a single block, rather than discovering it 14 days later via a silent `unschedulable` notification that would have fired identically every day in between.

**Example J - Pass 2 buffer tie-break (6.2, added Rev 6).** A 1-hour flexible task is being placed via Pass 2. Tuesday: budget 2h, already committed 2h - adding the task creates 1h overage, and physically packs Tuesday wall-to-wall (0 minutes free afterward). Wednesday: budget effectively exceeded already, committed 1h - adding the task also creates exactly 1h overage, but leaves 4 hours physically free afterward. Both days tie on overage (1h each). The Revision 6 secondary tie-break prefers Wednesday, since it leaves far more slack for anything else that might need to land that day - rather than defaulting to Tuesday purely because it comes first chronologically.

**Example K - Deadline elapses before ever being scheduled (6.7, added Rev 6).** A flexible task "Renew passport" was due yesterday at 17:00 and never found a slot (it's been sitting `pending` with an `unschedulable` notification). The 6.7 deadline-elapsed check runs this morning, finds `deadline <= now()`, and transitions the instance to `missed` instead of handing an inverted `[now, yesterday-17:00]` window to the scheduler. A `deadline_missed` notification is created. The user opens it, extends the deadline by a week, and the instance returns to `pending` and is placed normally on the next pass; the notification auto-resolves.

**Example L - "This occurrence" edit (3.10, added Rev 7).** A recurring "Pay Utility Bills" template normally generates a 10-minute `flexible` instance. This month's bill requires a call to dispute a charge. The user opens this month's instance and edits it with **"this occurrence"** scope, changing `estimated_duration` to 45 minutes. This sets `detached = true` on that instance only; the `TaskTemplate` is untouched. The instance re-enters 6.2 with the new duration. Next month, the normal 9.1 generation cycle produces a fresh instance from the (unchanged) template - 10 minutes, `detached = false` - with no trace of this month's override.

**Example M - "This and future" edit hits a detached instance (3.10, added Rev 7).** Continuing Example L: before this month's (detached, 45-minute) instance completes, the user separately decides all future bill-pay tasks should be budgeted at 15 minutes, and edits the template with **"this and future occurrences"** scope. Because the current live instance is already `detached`, it is skipped entirely - it stays at 45 minutes, unaffected. The template's `estimated_duration` is updated to 15 minutes; the *next* generated instance (after this one completes) will be 15 minutes, not 45 and not the old 10.

---

## 11. Open Questions Requiring Stakeholder Sign-off

**Status as of Revision 8: all items below are resolved. This document has zero open `[UNCONFIRMED]` items and is locked for POC implementation.** Revision 6 surfaced seven items during an implementation-readiness review; Revision 7 resolved items 6 and 7 (one of which - item 7 - reversed a Revision 6 decision, see 3.10); Revision 8 resolved items 1–5, all confirmed exactly as originally specified.

1. ~~**(6.8) Flexible-task feasibility hard-block at creation.**~~ **RESOLVED - Revision 8: CONFIRMED, hard-block as specified.** No softer save-with-warning; no pull-forward of Backlog 12.20.
2. ~~**(6.2, Pass 2) Physical-buffer secondary tie-break.**~~ **RESOLVED - Revision 8: CONFIRMED as specified.** Three-key tie-break (overage, then slack, then earliest date) stands.
3. ~~**(9.2) Virtual/ghost recurring-instance projection for Timeline display.**~~ **RESOLVED - Revision 8: CONFIRMED.** Display-only, non-persisted, 30-day horizon - hardcoded constant for POC, not a `UserSettings` field.
4. ~~**(Section 7) All-day / transparent external-event handling.**~~ **RESOLVED - Revision 8: CONFIRMED.** Display-only for POC; per-event holiday-style semantics stays deferred to Backlog 12.15, unchanged.
5. ~~**(14.1) Wall-clock vs. fixed-UTC-instant semantics for `fixed_time_of_day`.**~~ **RESOLVED - Revision 8: CONFIRMED, wall-clock only.** A fixed-UTC-instant option was considered and deliberately not built for POC - recorded as new Backlog 12.21 rather than lost.
6. ~~**(Section 4, new 6.7) New `missed` state for flexible tasks whose deadline elapses unmet.**~~ **RESOLVED - Revision 7: CONFIRMED as specified.** No change to the Revision 6 design; the `[UNCONFIRMED]` markers in Section 4 and 6.7 are removed.
7. ~~**Instance-level field overrides - raised, but NOT adopted.**~~ **RESOLVED - Revision 7: option (b), reversed.** Per stakeholder direction, modeled on Google Calendar's edit-scope prompt and adapted to this app's one-instance-at-a-time model (which collapses GCal's three scopes to two - see 3.10 for why). `TaskInstance` gains a `detached` flag (3.3); the full edit-scope and propagation rules are in new **Section 3.10**. The original scenario (a "Pay Utility Bills" task needing a one-off 45-minute call) is now Worked Examples L and M (Section 10). This also retroactively fixes the "(3.6)" citations in the original text of this item and in 3.1/8.1 - they pointed to edit-propagation content that was never actually written under Section 3.6 (which is, and remains, the `User` schema).

Two related items were resolved **without** flagging, since they don't change load-bearing behavior and follow directly from rules already on the books:
- Instances may be marked `completed` directly without first being `scheduled` (3.3/4) - this is a natural reading of "the user did the task," not a new mechanism.
- Dependency eviction (an upstream task reverting to `pending` via external sync) does **not** cascade to downstream tasks, because unblocking was always gated on dependency *completion* (terminal, immutable), never on scheduling status - there was nothing here to newly resolve, just a clarification of behavior the existing rules already implied.

---

## 12. Backlog (explicitly deferred, with source/rationale)

| # | Item | Why deferred |
|---|---|---|
| 12.1 | Location-aware scheduling (commute time between tasks, geofenced reminders) | Real routing/maps feature, too much for POC |
| 12.2 | IM messaging bot (reminders, quick actions, on-the-go task creation) | Full second client surface; WebUI is the POC deliverable |
| 12.3 | Email notification channel | POC uses WebUI banner only |
| 12.4 | Write access to external calendars | Extra OAuth scope/risk surface, not needed to prove core value |
| 12.5 | Webhook-based external calendar sync | Requires a publicly reachable endpoint; conflicts with LAN-only target. POC uses polling |
| 12.6 | Collaboration: shared timeline, multiple owners | Ownership/claiming semantics and per-user calendar conflict-checking unresolved; deferred whole |
| 12.7 | Priority-based auto-rescheduling (bumping lower-priority tasks) | High complexity; POC only reports `unschedulable` |
| 12.8 | Soft override for fixed-task creation conflicts | POC is hard-block only |
| 12.9 | Multiple selectable scheduling algorithms + picker UI | POC ships exactly one algorithm |
| 12.10 | Home Assistant add-on / sensor integration | Alternate deployment target, needs its own design pass; may conflict with containerization choices |
| 12.11 | Dynamic dependency-at-risk threshold (scale with cumulative precondition duration) | POC uses a flat 3-day heuristic |
| 12.12 | Template-level dependencies (recurring-to-recurring) | "Which occurrence depends on which occurrence" unresolved |
| 12.13 | Rolling-window instance pre-generation (real, persisted instances) | POC generates only the next single real instance (9.1); Timeline usability gap addressed instead via non-persisted display projection (9.2, Rev 6) |
| 12.14 | Actual-vs-estimated duration tracking / completion analytics, feeding future duration prediction | Approved direction, but depends on accumulated completion history the POC hasn't generated yet - sequencing issue, not a scope objection |
| 12.15 | Multi-tradition holiday calendars (e.g. Christian, Jewish, others) with scheduling effect | See open questions below - genuinely underspecified, not a small add-on |
| 12.16 | Business/location working-hours registry, with tasks taggable to a business so scheduling respects that business's real hours | Natural extension of `active_hours_override` (3.2), but needs its own entity (`Business`) and tagging UI - POC ships the override mechanism only, generalized manually per task |
| 12.17 | Full account-recovery flows, SSO, 2FA | POC ships password-only auth with a container-env-based reset path (3.6) |
| 12.18 | Reschedule audit trail (`scheduled_time_history`) - tracking manual retimes of fixed tasks separately from `status_history` | Nice-to-have visibility, not required to prove core functionality |
| 12.19 | Per-task exemption from the daily time budget (analogous to `active_hours_override`, e.g. "this urgent task can exceed today's budget") | Not requested - raised only as a natural extension of 3.7's daily-budget feature, worth a future conversation rather than building preemptively |
| 12.20 | Automatic splitting/chunking of a flexible task into multiple sub-slots when its duration exceeds any single day's active-hours window | Real capability, but needs partial-completion semantics, resumption logic, and its own notification design. POC ships a creation-time hard block instead (6.8, Rev 6) |
| 12.21 | Per-template fixed-UTC-instant option for `fixed_time_of_day`, for tasks that should NOT re-project on a timezone change (e.g. a global webinar at a genuinely fixed absolute moment) | Additive to the wall-clock rule (14.1), not a replacement - layers on cleanly later as a per-template flag. Not requested for POC; raised and deliberately deferred during Section 11 item 5's resolution (Rev 8) |

### 12.15 - Open questions to resolve before holiday calendars are taken into active development

1. **Which calendars, and how many simultaneously?** Single selection, or can a user follow multiple traditions' calendars at once?
2. **Data source and computation.** Fixed-date/Easter-offset math is simple for some traditions; lunisolar calendars (e.g. Jewish) require a proper library, not hand-rolled logic.
3. **Scheduling effect is not uniform** - does a given holiday fully block the day (all-day busy-block), shift the active-hours window (e.g. sundown-to-sundown restrictions), or remain purely informational with no scheduling effect at all? This likely varies **per holiday**, not just per tradition. *(Note: the same per-event-semantics question now also applies to imported all-day calendar events generally - Section 7, Rev 6 - and was resolved the same way for POC: display-only, no scheduling effect, pending this broader design work.)*
4. **Personalization** - not everyone who nominally belongs to a tradition observes every holiday the same way (stakeholder's own observation). Does the app need per-holiday opt-in/out within a selected calendar, rather than an all-or-nothing toggle?

---

## 13. Non-Goals for POC (explicit exclusions, not just "later")

- Multi-user accounts or any authorization/permission model beyond the single-user password login defined in 3.6/9.
- Native mobile apps.
- Offline operation (self-hosted and LAN-reachable, not designed for fully disconnected use).
- Any form of AI/ML-based scheduling suggestion - POC scheduling is deterministic and rule-based (6.2), not learned. (Duration prediction, Backlog 12.14, is a distinct future capability building on data the POC will start collecting, not a POC feature itself.)
- **(Added Revision 6)** Automatic splitting/chunking of a flexible task into multiple sub-slots (see Backlog 12.20) - POC hard-blocks an infeasible duration at creation instead (6.8).

---

## 14. Design Decisions Log (binding, cross-cutting)

### 14.1 Timezone and DST - binding implementation rule

This is **not** a feature ticket, it's a constraint on how the entire codebase handles time:
- Store all persisted timestamps in UTC.
- Store the user's timezone as an **IANA timezone name** (e.g. `"America/New_York"`), never as a fixed UTC offset.
- All date/time arithmetic - scheduling, reminders, recurrence generation, active-hours window checks - must use a timezone-aware datetime library, never naive local-time or fixed-offset math.
- DST transitions are then handled correctly "for free" by the library. If any part of the implementation takes a shortcut around this (e.g. storing a raw offset, or doing manual hour arithmetic), it will silently drift by an hour at each DST boundary - this must be treated as a bug, not an edge case, if found in review.
- Default timezone is sourced from the container's `TZ` environment variable at first run; user can override in Settings (8.1).

**Fixed-task time semantics (added Revision 6):** `fixed_time_of_day` (3.2) represents a **wall-clock local time**, evaluated against the user's *current* `UserSettings.timezone` at the moment each instance's absolute UTC `scheduled_time` is computed or recomputed - not a UTC instant frozen at creation time. Practically: if the user changes their timezone setting, future (not-yet-occurred) fixed instances are re-projected against the new timezone the next time their `scheduled_time` is computed (e.g. at next recurrence generation, or via an explicit recompute triggered by the timezone-change save action); already-completed instances are historical and untouched. **(Added Revision 7)** A `detached` instance (3.10) - including one manually rescheduled via 6.6 - is also excluded from this re-projection: a manual retime is treated as an explicit wall-clock choice the user already made, and a later timezone-setting change should not silently move it again.

**DST edge cases:** a wall-clock time that falls in a spring-forward gap (doesn't exist that day) is shifted forward to the next valid instant; a wall-clock time that falls in a fall-back ambiguity (occurs twice) resolves to the first occurrence - this is standard behavior of a timezone-aware library applied per the binding rule above, not custom logic to write.

**[CONFIRMED - Revision 8, Section 11 item 5. Wall-clock is the only `fixed_time_of_day` semantics for POC.** A genuinely fixed-UTC-instant option (e.g. for a global webinar) was considered and deliberately not built - it's additive to this rule, not a replacement of it, so it can be layered on later as a per-template flag without touching the wall-clock default path. Recorded as new **Backlog 12.21** rather than built now, consistent with this document's "no premature abstraction" stance elsewhere.]**

### 14.2 Authentication is mandatory, not optional - binding rule (added Revision 6)

Per stakeholder confirmation (see 3.6, 9): every deployment of the POC requires password-based login; there is no anonymous/no-auth mode, even for a fully LAN-local single-user deployment. Recorded here, rather than only in Section 9, because it's a cross-cutting constraint on every screen and endpoint (a session/auth guard must wrap the entire app), not a feature confined to one section.

*(This entry also resolves a dangling `14.2` cross-reference from 8.1 present in earlier revisions of this document, where Section 14 previously contained only 14.1.)*