# Tessera - Design Document (POC)
### Revision 9

> **Revision 9 resolves the second implementation-readiness review.** `docs/implementation-readiness-review-2.md` (IRR-2) is the findings register and the reasoning trail behind the changes below; this document is authoritative for *what the system does*, IRR-2 for *why it says so*. Every IRR-2 finding gating Stages 1, 2 and 3 has been drafted in here, and Section 11 has no open items. Findings gating Stage 5 and later (H2, H5, H6, H7, H9–H14, and the remaining Medium items) are **not yet resolved** and remain open against this revision - IRR-2 Section 6 lists which gates which stage.

## 0. How to use this document

This document is the authoritative specification for the Proof-of-Concept (POC) build. It was produced through a requirements-elicitation process where every field, algorithm rule, and boundary was explicitly confirmed by the product stakeholder - nothing here is a default or an assumption unless it is explicitly marked **[UNCONFIRMED - flagged during design, needs stakeholder sign-off]**.

Rules for whoever (human or LLM) implements against this doc:
- Section 3 (Data Model) and Section 6 (Scheduling Algorithm) are load-bearing. Do not deviate from them without raising the change back to the stakeholder.
- Section 12 (Backlog) is explicitly **out of scope**. Do not build it "while you're in there" - POC scope discipline is a deliberate design choice, not an oversight.
- Section 13 (Non-Goals) lists things that were considered and explicitly rejected for POC. Treat these the same as backlog items: known, deliberate, deferred.
- Section 14 (Design Decisions Log) contains binding architectural rules that don't map to a single feature but must be followed throughout implementation (e.g. timezone handling). Treat these as cross-cutting constraints, not optional style notes.

### Revision history

Full diffs are in git; IRR-2 (`docs/implementation-readiness-review-2.md`) holds the reasoning trail for Revisions 6 and 9, both of which came out of implementation-readiness reviews.

| Rev | What changed |
|---|---|
| 2 | User authentication; active-hours windows (global + per-task override); blackout dates; deletion semantics (dependency unlink, template archival); overdue handling; notification self-resolution; the binding timezone/DST rule (14.1). Holiday calendars moved to backlog |
| 3 | Per-day-of-week **daily time budget**, measured as total duration rather than task count, soft by default with a `budget_exceeded` notification |
| 4 | `budget_enforcement: strict \| soft`; Pass 2 picks the least-overage day rather than the first free one |
| 5 | `first_day_of_week` display preference (no algorithm effect) |
| 6 | Resolved a batch of edge cases from the first readiness review: `completed_at` in the earliest-start calculation, `completed` reachable from any non-terminal status, feasibility validation (6.8), the Pass 2 slack tie-break, virtual Timeline projections (9.2), external-event filtering (Section 7), wall-clock `fixed_time_of_day` (14.1), and the `missed` state (6.7) |
| 7 | **Reversed Revision 6's refusal of instance-level overrides.** Added 3.10 (Edit Scope & Propagation) and the `detached` flag, modelled on Google Calendar's edit-scope prompt. Also formalised fixed-task "reschedule" as a "this occurrence" edit |
| 8 | Closed the last five `[UNCONFIRMED]` items, all confirmed as specified. Markup only, no behaviour change |
| 9 | Resolved eighteen findings from the second readiness review (IRR-2) - see below |

**Revision 9 changelog.** Eighteen IRR-2 findings, following stakeholder decisions taken 2026-08-05 to 2026-08-07. Revision 8's "locked" status meant "no unilateral edits"; it did not mean "verified correct". IRR-2 records what each finding was and why it mattered; this lists only what the specification now says.

*Recurrence (B1, B2):*
- `recurrence.anchor` - `calendar` (the next occurrence lands where the rule says, regardless of the predecessor) or `completion` (`completed_at` + cadence). `completion` is valid on **flexible templates only** (3.2, 9.1).
- Calendar-anchored templates generate on the occurrence boundary regardless of the predecessor's state, allowing more than one live instance. Completion-anchored templates **stall when incomplete, and that is intended** for upkeep work, not a dead-end (9.1).
- Deletion prompts for scope, mirroring 3.10's edit prompt (3.8). Projection is anchor-aware (9.2).

*Scheduling algorithm (B3, B4, B8, B9, H1):*
- Obstacle set is every instance in `scheduled` or `in_progress`, both types, plus intra-pass placements and filtered external events. Placement is an **incremental fit** - existing placements are never moved by a later pass (6.2).
- `active_hours_override` **merges** per day over the global map; per-day `null` always means "day excluded" (3.2, 3.7, 6.2, 6.8).
- All durations are **integer minutes**, with the unit in the field name (3.2, 3.3, 3.7, 14.1).
- Computed start times land on a **15-minute grid** aligned to the hour in local wall-clock. **Durations are not quantised** (6.2, 6.8).
- **The topological sort is deleted** - it was unreachable under the `blocked` gate. A **Backlog view** (8.1) makes blocked work visible instead (6.1, 6.9).

*Data model (B5, B6, B7):*
- `created_at`, `updated_at` and a monotonic **`version`** on `TaskInstance`; `version` on `TaskTemplate`. `version` is the optimistic-locking token (3.2, 3.3).
- `dependencies` is persisted as a **join table** (3.3). New **`ExternalEvent`** entity (3.11) and **3.12 Data retention** - the event cache ages out, `TaskInstance` rows never do.

*Authentication (B10, B11, B12, M9, M10):*
- **First-run setup wizard** (3.6, 8.1); session lifetime, rotation and revocation; the auth guard's public-route list enumerated (14.2). Cookie `Secure` is derived from the deployment scheme rather than hardcoded, so plain-HTTP LAN is a supported deployment - architecture-plan Revision 3 has the mechanism.

*Worked examples (M7):*
- All examples are now concrete given/expected fixtures; G–K re-derived against the decisions above. New N, O and P cover the dependency chain and both recurrence anchors.

*Also settled in this revision (Section 11 items 8 and 9):*
- **`dismissed` becomes a terminal status** (Section 4), reached by "skip this occurrence" (3.8). Preferred over hard deletion because this document archives templates and never purges instances precisely to keep history, and clearing a stale occurrence is routine rather than exceptional under `calendar` anchoring.
- **The first-run setup wizard is guarded by a setup token** (3.6), generated at startup while zero users exist, logged at `WARNING`, held in memory only.

*Status:* **Section 11 has no open items at Revision 9.** IRR-2 findings gating Stage 5 and later remain open against this revision and are tracked there.

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
| Recurring-task deletion scope *(added Rev 9)* | Same two-way scope prompt on delete - "this occurrence" (series continues) or "this and future" (template archived), 3.8 | - |
| Recurrence anchoring *(added Rev 9)* | Per-template `anchor`: `calendar` (rigid) or `completion` (`completed_at` + cadence, flexible templates only), 3.2/9.1 | Anchor switching mid-series with re-derivation of the existing live instance |
| Dependency visibility *(added Rev 9)* | Dependents are not placed until their prerequisites complete; a **Backlog view** (8.1) makes blocked, unschedulable and missed work visible, with bidirectional dependency navigation | Placing dependents against a prerequisite's *scheduled* time so whole chains appear on the Timeline (12.22) |
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

    anchor: "calendar" | "completion";  // (added Rev 9) where the NEXT occurrence lands.
                                     // "calendar": at the next date the rule produces,
                                     //   regardless of when - or whether - the predecessor
                                     //   completed. Rigid commitments.
                                     // "completion": at completed_at + cadence. Upkeep work
                                     //   ("replace the filter monthly").
                                     // VALID ONLY when type == "flexible" - see notes and 9.1.
                                     // Ignored when pattern == "one_time".
  };

  // --- Fixed-type scheduling ---
  fixed_time_of_day?: string;       // e.g. "18:00" - a WALL-CLOCK local time, not a UTC
                                     // instant; see 14.1 for the binding rule on how this
                                     // is projected against the user's timezone.
                                     // required if type == "fixed"

  // --- Flexible-type scheduling ---
  deadline_offset_minutes?: number; // (Rev 9: was `deadline_offset: Duration`) minutes after
                                     // the occurrence's nominal date - see 9.1. ELAPSED time,
                                     // not calendar time; 4320 == 3 days. See 14.1.
                                     // required if type == "flexible"

  priority: "low" | "medium" | "high" | "critical"; // enum in UI

  estimated_duration_minutes: number;  // (Rev 9: was `estimated_duration: Duration`)
                                     // see 6.8: validated at save time against the applicable
                                     // active-hours window for flexible tasks.

  reminder_offsets_minutes: number[];  // (Rev 9: was `Duration[]`) minutes BEFORE
                                     // scheduled_time; e.g. [60, 15, 0]. 0 == at the time itself.

  // --- Scheduling-window override (optional) ---
  active_hours_override?: {         // (Rev 9) MERGES over the user's global active-hours map,
    [day: string]: { start: string; end: string } | null;  // per day. Days named here use these
  } | null;                         // values; days NOT named inherit the global map (3.7).
                                     // Per-day null == "that day is excluded", identically to
                                     // 3.7. There is no "no restriction" value: to allow a task
                                     // at any hour, give that day an explicit 00:00-23:59 window.

  archived: boolean;                // see 3.7 - archived instead of hard-deleted when history exists

  created_at: DateTime;
  updated_at: DateTime;
  version: number;                  // (added Rev 9) monotonic; the optimistic-locking token.
                                     // See 3.3 and architecture-plan 5.
}
```

Notes:
- `dependencies` is **not** a template field (dependencies apply to `TaskInstance` only, POC). See Backlog 12.12.
- Numeric priority mapping (internal, not exposed in UI): `low=1, medium=2, high=3, critical=4`.
- `active_hours_override` exists for two conceptually different reasons that share one mechanism: (a) the user's personal flexibility about a specific chore ("filters can wait till late"), or (b) a genuine external constraint (a business's real opening hours). POC ships the mechanism; a proper business-hours registry with task tagging is Backlog item - see scope table.
- **(Added Revision 6)** `estimated_duration_minutes` is checked at save time against every day-of-week's applicable active-hours window (override if set, else global) - see 6.8. A duration that cannot physically fit any single day is rejected at creation, not silently left to fail scheduling forever.
- **(Added Revision 7)** A template edit only reaches a currently-live `TaskInstance` if that instance is not `detached` (3.3, 3.10). A `detached` instance keeps its own values until it completes; the template's new values apply starting with the *next* generated instance (9.1) regardless.
- **`recurrence.anchor` is a type constraint, not a preference.** `anchor: "completion"` requires `type: "flexible"`, and a save that violates this is **rejected** with an `invalid_recurrence_anchor` validation error. The reason is structural rather than stylistic: completion-anchoring only means anything if the resulting occurrence can be *pushed* within a window, and that window is `deadline_offset_minutes` - a field flexible instances have and fixed instances do not (3.3 sets `deadline` for flexible tasks only; a fixed instance carries `scheduled_time` and has nothing to slide against). A fixed task must happen at its defined date and time, so there is nothing for a completion date to re-anchor. A recurring commitment that genuinely should shift with completion - "service the car six months after the last service" - is modelled as a flexible template whose `deadline_offset_minutes` expresses how far it may slip.
- **All durations are integer minutes.** Minutes are the storage and wire format **only** - the UI must never ask the user to compute them, and must never display a raw minute count. See 8.1a for the required input control and 14.1 for the elapsed-versus-calendar consequence.
- **`active_hours_override` merges, and its `null` matches 3.7's.** One rule, no exceptions: **per-day `null` always excludes that day**, an **absent** override inherits the global map entirely, and a **partial** override applies per day rather than replacing the map. The API contract must therefore distinguish an absent key from a present-but-`null` key: `{"monday": null}` excludes Monday, `{}` inherits it.

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
  estimated_duration_minutes: number;  // (Rev 9: was `estimated_duration: Duration`)
                                     // copied from the template at generation and NOT
                                     // rewritten by later template edits once set - this is
                                     // what makes Backlog 12.14's estimate-vs-actual
                                     // comparison meaningful after the fact.

  detached: boolean;                // (added Revision 7, see 3.10) - true once this occurrence
                                     // has been individually edited or manually rescheduled.
                                     // A detached instance no longer receives template
                                     // propagation (3.10) of any kind - its fields are its
                                     // own until it reaches "completed". Default false.

  scheduled_time?: DateTime;        // set once placed on the timeline
  deadline?: DateTime;              // set at generation for flexible tasks

  status: "pending" | "scheduled" | "in_progress" | "completed" | "blocked"
        | "missed" | "dismissed";   // "dismissed" added Rev 9 - see Section 4 and 3.8
  status_history: { status: string; at: DateTime }[];

  dependencies: string[];           // TaskInstance ids - this instance cannot
                                     // be scheduled/started until all are "completed".
                                     // If a dependency is deleted, its id is simply
                                     // removed from this list (see 3.8) - this instance
                                     // is not deleted or altered otherwise.
                                     // (Rev 9) PERSISTED AS A JOIN TABLE, not as an array
                                     // column - see the note below.

  completed_at?: DateTime;

  generated_at: DateTime;

  created_at: DateTime;             // (added Rev 9)
  updated_at: DateTime;             // (added Rev 9) display and audit only - NOT the
                                     //   concurrency token. See `version`.
  version: number;                  // (added Rev 9) monotonic, incremented on every persisted
                                     //   mutation including those made by background jobs and
                                     //   by template propagation. This is the optimistic-locking
                                     //   token; see architecture-plan 5.
}
```

Notes:
- `completed` is a **terminal** state - an immutable historical record. Template edits never touch completed instances (3.10). *(Rev 7: this citation previously read "(3.6)" - see the Revision 7 changelog for why that was wrong.)*
- No `owner` field in POC (single-user; collaboration deferred, Backlog 12.6).
- **(Added Revision 6)** `status` gains a new value, `missed` - flexible-only, see Section 4 and new 6.7. `missed` is *not* equivalent to `completed` for dependency-graph purposes: a downstream instance depending on a `missed` instance stays `blocked` until the upstream instance is actually completed or the dependency link is removed via deletion (3.8). **(Added Revision 9)** The same applies to `dismissed`: skipping an occurrence closes it out, it does not do the work, so it cannot unblock anything downstream.
- **(Added Revision 6)** An instance may be marked `completed` directly from `pending`, `blocked`, or `scheduled` - not only from `in_progress` - covering the "I already did this, don't bother scheduling/tracking it further" case. `completed_at` is always set on this transition regardless of whether `scheduled_time` was ever populated. `in_progress` remains an optional intermediate step, never mandatory.
- **(Added Revision 6)** Because a candidate only becomes eligible for scheduling (`pending`, unblocked from `blocked`) once **all** its dependencies have reached `completed` (never merely `scheduled`), a dependency's `completed_at` is always populated by the time it's read in 6.2's earliest-start calculation. This also means: if an upstream dependency is later evicted back to `pending` by an external-sync collision (6.4) or an overdue revert (6.6), that eviction has **no cascading effect** on any downstream instance that already unblocked - unblocking was gated on the upstream's (terminal, immutable) completion, not on it remaining scheduled. There is nothing to cascade.
- **(Added Revision 7)** `detached` is independent of `status` - a `pending`, `blocked`, or `scheduled` instance can be `detached`; the flag only concerns whether the instance's fields still track its template. See 3.10 for the full edit-scope and propagation rule, and for which fields it applies to (notably: not `type`, not `dependencies`, not `status`).
- **`dependencies` is persisted as a join table** - `task_instance_dependencies(dependent_id, dependency_id)` - rather than as an id array on the row. The array form makes the reverse question ("what is waiting on *this* task?") a full scan, and the Backlog view (8.1) asks it constantly, in both directions. The array shown above is the API representation, not the storage shape.
- **`version` is the concurrency token; `updated_at` must never be used for locking.** A timestamp is the wrong token here: SQLite's resolution makes two writes inside one clock tick indistinguishable, and the collision this mechanism exists to catch - a background job writing while the user edits - is precisely the sub-millisecond case. `version` must be incremented at the ORM layer rather than by individual service methods, because a single write path that forgets to bump it defeats the mechanism silently and with no error to observe.
- **`TaskInstance` rows are never purged.** See 3.12.

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

**First-run account creation.** Authentication is mandatory (14.2), so a deployment needs a way to obtain its first account. That is a **first-run setup wizard**:

- While **zero `User` rows exist**, the app serves a one-time setup screen (8.1) and exposes `POST /api/v1/auth/setup`. Once an account exists, that endpoint is permanently `410 Gone` - not merely unauthorised.
- **Every other route refuses to serve while unconfigured** and directs to setup. An app serving task data before an account exists would be an unauthenticated app, which 14.2 forbids.
- The zero-users check and the account insert happen in **one transaction**, backed by a uniqueness guarantee, so two concurrent setup requests cannot both succeed.
- `username` is fixed as `admin`. Single-user; a configurable username is a knob with no benefit.
- Minimum password length **12 characters**, no composition rules, validated at the setup endpoint.

**The wizard is guarded by a setup token (added Revision 9).** Without one it leaves a **claim window**: between container start and the operator's first visit, whoever reaches the app first owns the account, the task history and the OAuth calendar connections. 14.2 already establishes that this app is not open by default even on a trusted network, and plain-HTTP LAN is an explicitly supported deployment, which widens the exposure rather than narrowing it.

- On startup with **zero `User` rows**, generate a **random, high-entropy, single-use token** and log it at `WARNING` level, so it appears in default output and the operator finds it with `docker logs` / `podman logs`.
- `POST /api/v1/auth/setup` **requires** the token. Compare it in **constant time**.
- The token is **held in memory only, never persisted**. A process restart therefore invalidates the old one and issues a fresh one - which is the desired behaviour, since a token that leaked but was never used should not stay valid indefinitely.
- It is invalidated the moment setup completes successfully, along with the endpoint itself.

This is roughly twenty lines and closes the window completely. It is not deferred: a control filed as "add later" is one that gets added after something has gone wrong.

**Password reset (confirmed mechanism).** With the setup wizard above, this is purely a **recovery** path and is never used to create the initial account.

On container startup, if a `RESET_ADMIN_PASSWORD` env var (or mounted secret file) is present and non-empty, the app resets the admin password to that value **once**. On successful reset, the app writes a marker (a hash of the value it just consumed) so that if the same env var is still present on the next restart, the app does **not** reset again - it logs a warning instead. This prevents the env var from acting as a standing backdoor if the operator forgets to remove it from their compose file after use. A changed value is treated as a new reset request and is honored.

The marker is stored **as a row in the database**, not as a file. A marker written to the container's writable layer is erased on every container recreate, at which point the env var becomes exactly the standing backdoor this mechanism exists to prevent. The database lives on the mounted volume and cannot desynchronise from the account it protects.

**Session policy.** An implementer who writes no expiry code gets sessions that never expire, so each of these is stated explicitly:
- **Absolute TTL of 30 days** from issue. No idle timeout: idle expiry alone is weaker against a live attacker, who refreshes the session simply by using it, and a sliding window would mean a database write on every request.
- **Rotation on login** - a fresh session id is issued on each successful login, never reused. Standard session-fixation defence.
- **Every session for the user is revoked on any password change or reset.** This is not optional: `RESET_ADMIN_PASSWORD` exists so an operator can lock somebody out, and it fails at that if existing sessions survive it.
- Expired rows are swept **lazily at login**, not by another background job.
- An expired session returns `401` with a **distinct machine-readable code**, so the UI redirects to login rather than showing a generic error.

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

  daily_time_budget_minutes: {       // (Rev 9: was `daily_time_budget: {[day]: Duration|null}`)
    [day: string]: number | null;    // max total scheduled minutes per day, per day of week.
                                      // null = unlimited for that day. Soft cap - see 6.2:
                                      // yields as a last resort rather than causing a missed deadline
  };

  budget_enforcement: "strict" | "soft";  // "strict": the budget is a hard wall - a task that
                                           //   can't be placed within budget becomes unschedulable.
                                           // "soft" (default): the algorithm's last-resort override
                                           //   (6.2) is allowed to breach the budget to meet a deadline.

  first_day_of_week: "sunday" | "monday" | "tuesday" | "wednesday"
                    | "thursday" | "friday" | "saturday";  // display-only, see note below.
                                                            // default: "monday"
}
```

`first_day_of_week` affects **display only** - it controls the Timeline view's calendar layout (8.1) and the row order of the day-of-week settings below (`active_hours`, `daily_time_budget_minutes`, `blackout_dates`). It has no effect on scheduling algorithm behavior: those fields are already keyed by day name rather than position-in-week, so the algorithm doesn't have a concept of "week" to reorder in the first place.

A per-day `null` in `active_hours` means **that day is fully excluded**, and the same rule applies to `TaskTemplate.active_hours_override` (3.2) - one shape, one meaning. A template override **merges** over this map per day: days the override names use the override's value, days it does not name inherit the value here. To allow a task at any hour on a given day, give that day an explicit `00:00`–`23:59` window; there is no `null` that means "unrestricted".

`active_hours` (and any `TaskTemplate.active_hours_override`), `blackout_dates`, and `daily_time_budget_minutes` constrain **flexible-task auto-placement only** (6.2). Fixed tasks are user-chosen times and are never constrained by this window - the window governs what the algorithm may choose, not what the user is allowed to set manually. Note the distinction between "constrains" and "counts toward capacity" for `daily_time_budget_minutes` specifically: fixed tasks and external calendar events are never *blocked* by the budget, but their duration *does* count against a day's budget when the algorithm decides whether there's still room for more flexible tasks that day (see 6.2) - otherwise a day already packed with fixed commitments would still get flexible chores piled on top of it, which defeats the purpose of the setting. Unlike the effective active-hours window and `blackout_dates`, which are hard constraints the algorithm never crosses, `daily_time_budget_minutes` is a constraint whose strictness is itself configurable via `budget_enforcement` - see 6.2 for exactly when and how it's allowed to yield.

### 3.8 Deletion & archival rules

- **Deleting a `TaskInstance` that other instances depend on:** the dependency link is simply removed from the dependent instance(s)' `dependencies` array. The dependent instance(s) are otherwise untouched. If this removal leaves a `blocked` instance with zero remaining dependencies, it transitions to `pending` per the normal state machine (Section 4) and becomes eligible for the next scheduling pass. **No cascading delete.**
- **Deleting a `TaskTemplate` with incomplete instances:** the UI must show a confirmation dialog explaining the implications (which incomplete instances exist and what happens to them) before proceeding. On confirmation, the template is **archived**, not hard-deleted (`archived = true`) - this keeps `template_id` references on historical/completed instances valid rather than dangling, and preserves history availability.

**Deletion scope for recurring tasks.** Deleting an instance must say what happens to its *series*, not only to its dependents. Deletion **prompts for scope**, mirroring 3.10's edit-scope prompt rather than inventing a second mental model:

| Scope | Effect |
|---|---|
| **`this_occurrence`** | Delete this instance only. The series continues and its successor is generated per 9.1. |
| **`this_and_future`** | Delete this instance **and end the series** - the template is `archived` (per the rule above). |

This applies to both task types and both recurrence anchors. For a `one_time` template the prompt is skipped, since the two scopes are equivalent. The dependency-unlink rule above is unchanged and applies to whichever instances are removed.

**Re-anchoring on `this_occurrence` for a `completion`-anchored template.** Deleting is not completing, so there is no `completed_at` for 9.1 to anchor the successor against. The successor's nominal date is `now + cadence`: the user has explicitly declined to do this occurrence, so restarting the interval from that decision matches their intent better than pretending the work happened on the old nominal date.

**Skipping an occurrence - `dismiss` (added Revision 9).** Deletion destroys the row. For the routine case - a stale occurrence you are simply not going to do - that is the wrong default, because it is the one place this document would hard-delete a `TaskInstance` while archiving templates (above) and never purging instances (3.12) specifically to preserve history. Under `calendar` anchoring the case is not rare either: it recurs every time an occurrence is missed.

**"Skip this occurrence" transitions the instance to the terminal `dismissed` status (Section 4), preserving the row.** The two actions are distinguished by intent, not by effect:

| Action | Meaning | Row |
|---|---|---|
| **Skip this occurrence** (`dismiss`) | "This one is not going to happen." Routine; the expected way to clear a stale predecessor (9.1) | Preserved, terminal |
| **Delete, `this_occurrence`** | "Remove this from my records." Exceptional | Destroyed |
| **Delete, `this_and_future`** | "End this series." | Instance destroyed, template archived |

Side effects of a dismiss, all in the same service method:
- **Cancel every job** for that instance - reminder, overdue, deadline-elapsed.
- **Auto-resolve its open notifications** per 3.9 (`overdue`, `unschedulable`, `deadline_missed`): the condition has cleared because the user has closed the occurrence out.
- **Dependents stay blocked.** `dismissed` does not satisfy a dependency (Section 4). The user unblocks them by completing the work, deleting the instance so the link is unlinked, or removing the dependency.
- **For a `completion`-anchored template, generate the successor anchored at `now + cadence`**, identically to `this_occurrence` deletion above. Without this, dismissing would silently end the series - the exact dead-end 9.1 exists to prevent.
- The instance leaves the Backlog view (8.1), being terminal.

Dismissal is irreversible, like completion. Recovering from a mistaken skip means creating a new task, not un-dismissing.

**Why "how often did I skip this?" is worth the extra status.** `status_history` (3.3) is immutable and instances are never purged (3.12), so dismissals accumulate into a real answer to that question. Deletion would leave nothing behind to count, and unlike a status value - cheap to add later - **destroyed rows cannot be recovered retroactively**.

### 3.9 Notification self-resolution

If the condition a `Notification` was raised for clears on its own before the user acts on it (e.g. a `dependency_at_risk` dependency completes in time, a `sync_conflict` resolves because the external event was later removed, a `deadline_missed` instance is extended back to `pending` or completed - see 6.7), the system sets `resolved_at` automatically. If the user opens/clicks a notification that has already auto-resolved, the UI shows an "already resolved" state instead of presenting stale action buttons tied to a condition that no longer exists.

`budget_exceeded` remains the one exception (5): it records something that already happened, not an ongoing condition, so it is dismissed like a normal informational notice rather than auto-resolved.

### 3.10 Edit Scope & Propagation (added Revision 7)

This section defines what "editing a task" does, resolving the Revision 6 gap where 3.1, 8.1, and Section 11 item 7 all cited a "3.6" that never actually contained this content - Section 3.6 is, and remains, the `User` schema. It also formally resolves Section 11 item 7 (reversing the Revision 6 non-decision).

**Reference model, and why it's two-way here, not three-way.** The requested behavior is deliberately modeled on Google Calendar's recurring-event edit prompt. GCal offers three scopes ("this event" / "this and following events" / "all events") because a recurring series there is a set of events that mostly already exist as persisted rows. This app's generation model (9.1) is different: only **one real instance exists at a time**, generated fresh once its predecessor reaches `completed`. There is no persisted "following" series to fan an edit out across, and Timeline previews of upcoming occurrences (9.2) are explicitly virtual and non-editable. So the three-way GCal choice collapses to two here:

| Scope | What it touches | What it does NOT touch |
|---|---|---|
| **"This occurrence"** | The live `TaskInstance` directly - any of `name`, `description`, `location`, `priority`, `estimated_duration_minutes`, `deadline` (flexible only), or `scheduled_time` (fixed only, i.e. a manual reschedule, 6.6). Sets `detached = true`. | The `TaskTemplate`. Future-generated instances (9.1) are unaffected and will reflect the template's values, not this override. |
| **"This and future occurrences"** | The `TaskTemplate` (as in Revision 6), **plus** the currently-live instance's corresponding fields, applied immediately - *unless that instance is already `detached`* (see below). | Already-`completed` instances - terminal and immutable per 3.3, unreachable by any propagation. |

There is deliberately no third "all occurrences, including past" scope: "past" means `completed`, and 3.3 already makes `completed` instances immutable. Nothing new is needed there.

**Detach is sticky and total, not per-field.** Once an instance is `detached` (via any "this occurrence" edit, or a manual fixed-task reschedule, 6.6), it is skipped **entirely** by all subsequent "this and future" template propagation - not just the field(s) originally overridden - until it reaches `completed`, at which point it's immutable history and propagation is moot anyway. This mirrors GCal's actual behavior (a customized single event keeps its customization even after later series-wide edits) and avoids a harder problem this POC doesn't need: field-by-field merge logic between an instance's overrides and a template's new values. Full detach is simpler, matches user expectation, and is an explicit tradeoff - a finer-grained per-field merge is a possible future direction, not currently backlogged since it hasn't actually been requested.

**What "applied immediately" means for the non-detached case.** If the live instance is *not* detached, a "this and future" template edit updates its copied fields to match the new template values in the same operation - it does not wait for the next generation cycle (9.1). If the field(s) changed affect scheduling validity (e.g. `estimated_duration_minutes` grew past the remaining time before `deadline`, or past the day's effective active-hours window or budget), the instance re-enters the normal `pending` scheduling pool and is re-evaluated by 6.2 exactly as any other edit-triggered re-placement would be - this is not a new mechanism, just an added entry point into 6.2 (see 6.2's updated "runs whenever" clause).

**Interaction with 6.8 (feasibility validation).** A "this occurrence" override that changes `estimated_duration_minutes` is checked against 6.8 the same way template-level duration changes are - an override that could never fit any day's active-hours window is rejected at save time with the same `infeasible_duration` error, not silently accepted and left to fail scheduling forever.

**UI implication (see also 8.1).** The task edit form must prompt for scope ("this occurrence" vs. "this and future") whenever the task being edited is (a) recurring and (b) not a one-time (`recurrence: one_time`) template - a one-time task has no "future occurrences" to distinguish, so no prompt is needed; the edit simply applies to that instance and template alike, as in Revision 6. The task detail view should visibly indicate when an instance is `detached`, so the user understands why it didn't pick up a later template-wide edit.

Deletion uses the same two-way scope prompt - see 3.8.

### 3.11 `ExternalEvent` (added Revision 9)

External calendar events are persisted locally. Three separate rules require it: 6.4 diffs each poll against the previously known set, 6.2 needs external busy-blocks as obstacles on every scheduling pass, and 3.9 auto-resolves a `sync_conflict` when the external event is later removed - none of which is computable without a prior set.

```typescript
interface ExternalEvent {
  id: string;
  connection_id: string;            // -> ExternalCalendarConnection (3.5)
  provider_event_id: string;        // unique together with connection_id

  start: DateTime;
  end: DateTime;
  title: string;

  is_all_day: boolean;              // Section 7 filter input
  is_transparent: boolean;          // Section 7 filter input ("Free" in the provider's UI)

  fetched_at: DateTime;
  deleted_at?: DateTime;            // soft delete - see 3.12
}
```

- **The cache is what the scheduler reads.** 6.2 consumes these rows as plain data alongside every other obstacle and never makes a network call. This is what keeps placement deterministic, unit-testable in isolation, and functional while the provider is unreachable - and it is required by the architecture plan's rule that the scheduling engine imports no framework and performs no I/O.
- **`(connection_id, provider_event_id)` is unique.** This is what makes 6.4's diff a plain upsert rather than bespoke matching logic.
- Filtering per Section 7 happens when the obstacle set is assembled, not at fetch time - a transparent or all-day event is still stored and still displayed, it simply does not obstruct.

### 3.12 Data retention

The distinction is what owns the data.

- **`ExternalEvent` is a cache.** The provider is the source of truth and any purged row is refetchable. The poll (6.4) maintains a **rolling 90-day forward horizon**, and **purges events whose `end` is more than 30 days past** on the same pass. Removals detected at the provider are **soft-deleted** (`deleted_at` set) rather than hard-deleted, so 3.9's `sync_conflict` auto-resolution can observe a row rather than having to reason about absence; soft-deleted rows are purged by the same retention sweep.
- **`TaskInstance` is the system of record and is never aged out or purged.** Completed and `missed` instances persist indefinitely. 3.3 already makes `completed` terminal and immutable, and 3.8 archives templates rather than hard-deleting them specifically so `template_id` references on historical instances stay valid; a retention policy on instances would cut against both. This is stated explicitly because "keep the database small" is a reasonable-sounding instinct that would destroy primary data, including the estimate-versus-actual history Backlog 12.14 depends on.

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
      ├── user skips this occurrence ────► dismissed
      └── user deletes instance/template ─► removed (3.8)

┌────────────┐
│ dismissed  │  ◄── terminal, immutable. Reachable from ANY non-terminal
└────────────┘      status via "skip this occurrence" (3.8). Added Rev 9.
                    NOT equivalent to completed for dependencies.
```

Rules:
- A `TaskInstance` with unfulfilled dependencies starts life as `blocked`, not `pending`.
- Only `pending` instances are eligible for the scheduling algorithm.
- `fixed` instances go straight to `scheduled` at creation if hard-block validation (6.5) passes - they never enter the algorithm, since their time is user-specified.
- A `fixed` instance can also start `blocked` if it has unfulfilled dependencies; once unblocked it becomes `scheduled` directly.
- **(Added Revision 6)** `completed` is reachable directly from `pending`, `blocked`, or `scheduled` - not only via `in_progress` - see 3.3.
- **(Added Revision 6)** `missed` is reachable from `pending` or `blocked` (flexible instances only) when the deadline elapses before the instance is scheduled or completed. See 6.7 for the full trigger logic and resolution paths. **[CONFIRMED - Revision 7, Section 11 item 6 - no change from the Revision 6 design.]**
- **(Added Revision 7)** `detached` (3.3/3.10) is orthogonal to `status` - it does not add, remove, or gate any transition in this diagram. An instance can be `detached` in any non-terminal status.
- **(Added Revision 9)** `dismissed` is a **second terminal state** alongside `completed`, reachable from any non-terminal status. It means "this occurrence is not going to happen; close it out" - the counterpart to `completed`'s "it did". Like `completed` it is immutable and cannot be reversed; unlike `completed` it **does not satisfy a dependency** - a downstream instance depending on a `dismissed` one stays `blocked`, exactly as for `missed` (3.3). See 3.8 for the action and its side effects.
- **(Added Revision 9)** `blocked` is mutually exclusive with having a `scheduled_time`. The `blocked` → `pending` transition fires its placement **in the same transaction as the completion that unblocked it** (6.9), not on a later sweep.
- **(Added Revision 9)** `blocked`, `missed`, and `pending`-with-an-active-`unschedulable`-notification are the three states surfaced in the Backlog view (8.1). That view is a query over this same state machine, not a parallel one - no instance is moved, copied, or given a different status by appearing in it.

---

## 5. Notification Types - reference

| Type | Trigger | Resolution path |
|---|---|---|
| `reminder` | Now + reminder_offset == scheduled_time | User dismisses; informational only |
| `creation_conflict` | Fixed task creation collides with existing fixed task or external event | User must change the new task's time/type before saving (hard block, 6.5) |
| `sync_conflict` | External sync introduces an event colliding with a `scheduled` fixed task | Manual: user reschedules or dismisses |
| `unschedulable` | Flexible task's placement search finds no valid slot before its deadline | User relaxes deadline/duration or intervenes manually |
| `dependency_at_risk` | Deadline within 3 days (flat, POC threshold) with ≥1 incomplete dependency. **(Rev 9)** Risk is assessed by a speculative, non-persisting placement pass over the chain (6.3), since dependents are never placed in advance | Informational; user chases dependency or adjusts deadline |
| `overdue` | `scheduled_time` has passed, instance not `completed` | Flexible: auto-reschedules, notification is informational. Fixed: action menu offers "reschedule", "mark complete", **and (Rev 9) "skip this occurrence"** (see 6.6, 3.8) |
| `budget_exceeded` | A flexible task was placed by overriding its day's `daily_time_budget_minutes` because no compliant slot existed before the deadline (see 6.2) | Informational; user may relax the deadline, move another task off that day, or accept it |
| `deadline_missed` *(added Rev 6)* | A flexible instance's `deadline` elapses while status is `pending` or `blocked` (see 6.7) | User extends deadline, marks complete, or deletes the instance/template - auto-resolves when any of those happen (3.9) |

All types support auto-resolution per 3.9, **except `budget_exceeded`**: it records something that already happened (the task was placed over budget), not an ongoing condition that can clear on its own - it's dismissed like a normal informational notice, never auto-resolved.

---

## 6. Scheduling Algorithm

### 6.1 Dependency resolution & cycle detection

- Dependencies form a directed graph over `TaskInstance` ids.
- Cycle check runs at **save time** - a task cannot be saved with a dependency list that would create a direct or indirect cycle. Reject with a validation error (`cycle_detected`).
- **(Revised Revision 9) Dependency ordering is enforced by the `blocked` status gate, not by sorting within a pass. Do not build a topological sort.** One would be unreachable: Section 4 makes an instance with any incomplete dependency `blocked`, and only `pending` instances are candidates, so no candidate can ever depend on another candidate - every dependency of every candidate is already `completed`. Runtime cycle detection inside the scheduling engine is likewise unnecessary; the save-time check above is the only one.
- **(Added Revision 9)** The gate's consequence is that dependents are invisible on the Timeline until their prerequisites finish. That is addressed by making them visible in the **Backlog view** (8.1) rather than by relaxing the gate - see 6.9 for what happens when a dependency completes. Placing dependents against a prerequisite's merely *scheduled* time was considered and deferred (Backlog 12.22): it would require a dependency-invalidation cascade, which contradicts 6.2's rule that existing placements never move.

### 6.2 Core placement algorithm

Runs whenever: a new flexible instance enters `pending`, an external sync or overdue event invalidates a scheduled flexible instance (returns it to `pending`), a dependency completes/is removed and unblocks a downstream instance (6.9), or **(added Revision 7)** a non-`detached` flexible instance's `estimated_duration_minutes`/`deadline` changes via a "this and future" template propagation (3.10) in a way that invalidates its current placement.

**Placement is an incremental fit, not a reflow (added Revision 9).** A pass places only the new or changed candidate into the gaps left by everything already committed. **Existing placements are never moved by a later pass**, so adding a task never silently reshuffles what is already on the timeline. The notes below record the consequence, which is deliberate and accepted.

```
function schedule_pending_flexible_tasks():
    candidates = all TaskInstance where status == "pending" and type == "flexible"
    candidates = stable_sort(candidates, key=(deadline ASC, priority DESC))
    # (Rev 9) No topological sort - see 6.1. The `blocked` gate guarantees every
    # candidate's dependencies are already `completed`, so no candidate can depend
    # on another candidate and no ordering by dependency is possible or needed.

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

        # (Rev 9) Active hours resolve PER DAY, merging the template's override over
        # the global map (3.2/3.7). NOT a whole-object selection: a template overriding
        # one evening must keep its active hours on every other day.
        function effective_hours(day):
            if task.template.active_hours_override is not None
               and day in task.template.active_hours_override:
                return task.template.active_hours_override[day]   # may be null -> day excluded
            return user_settings.active_hours[day]                # may be null -> day excluded

        # Pass 1: respect the daily time budget (preferred outcome)
        slot = find_first_free_slot(
            duration = task.estimated_duration_minutes,
            not_before = earliest_start,
            not_after = task.deadline,
            allowed_hours = effective_hours,        # resolved per day, see above
            excluded_dates = user_settings.blackout_dates,
            daily_time_budget = user_settings.daily_time_budget_minutes,  # per-day cap, see 3.7
            grid_minutes = 15,                      # (Rev 9) see "Placement grid" below

            # (Rev 9) Includes instances placed in ANY prior pass, not just this one -
            # scheduling is event-driven and almost every pass holds exactly one
            # candidate, so a this-pass-only set would double-book nearly everything.
            # `in_progress` counts too: a task the user is actively doing is an obstacle.
            obstacles = all TaskInstances with status in ("scheduled", "in_progress")
                          # both types: fixed AND flexible, from any prior pass
                      + all flexible TaskInstances placed earlier in THIS pass
                      + all external calendar busy-blocks (ExternalEvent, 3.11,
                          filtered per Section 7)
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
                    1. overage = max(0, committed_duration(day) + task.estimated_duration_minutes
                                     - (daily_time_budget_minutes[day_of_week(day)] or +infinity))
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

`find_first_free_slot` treats the daily time budget (when passed) as an additional day-level exclusion, alongside `allowed_hours` and `excluded_dates`: for each candidate day D it is considering, it sums the duration of every obstacle already occupying D (all `scheduled`/`in_progress` instances of either type on D + external busy-blocks on D + flexible instances already placed on D in this pass) and skips D entirely for this task if `committed_duration(D) + task.estimated_duration_minutes` would exceed `daily_time_budget_minutes[day_of_week(D)]`. The day isn't invalid in general - just full for the purposes of adding more flexible work - so the search simply continues to the next eligible day.

#### Placement grid (added Revision 9)

"First free slot" is not well-defined without a time quantum: a 30-minute task in a gap from 18:07 to 19:00 could equally start at 18:07, 18:15 or 18:30. Without a stated grid no worked example is reproducible and no acceptance test can be written from one.

- **Computed start times land on a 15-minute grid aligned to the hour** - `:00`, `:15`, `:30`, `:45`.
- **The grid is aligned in the user's local wall-clock time, not UTC.** Aligning in UTC would produce `:15`-offset slots for anyone in a half-hour or quarter-hour offset zone (`Asia/Kolkata` at +05:30, `Asia/Kathmandu` at +05:45). This is a concrete instance of 14.1's binding rule.
- **The grid constrains computed starts only.** Fixed instances sit at their `fixed_time_of_day`, whatever the user chose, and external events keep their real times - so gaps still have arbitrary boundaries. Only the chosen start must land on a grid point.
- **Durations are not quantised.** A 20-minute task placed at 18:00 occupies 18:00–18:20 as an obstacle; the next flexible placement starts at 18:30. Budget arithmetic stays exact and `estimated_duration_minutes` stays an honest estimate rather than something the user has to round to fit.
- **The rule:** the chosen start is the earliest grid point `t` with `t >= gap_start` such that `t + duration <= gap_end`, `t + duration <= deadline`, and `t + duration <=` the end of that day's effective active-hours window.

Notes:
- Single fixed greedy algorithm for POC (Backlog 12.9 covers alternatives). The minimum-overage comparison in Pass 2 is a bounded, deterministic tie-break rule, not a pluggable/alternate algorithm - it stays within that scope.
- "Obstacles" accumulate within a single pass, preventing self-collision among flexible tasks placed in the same run. **(Rev 9)** This note now describes only the intra-pass increment; instances placed in *previous* passes are obstacles by virtue of their `scheduled`/`in_progress` status, per the corrected obstacle set above.
- `allowed_hours`, `excluded_dates`, and `daily_time_budget_minutes` apply to flexible placement only - never to fixed tasks (3.7).
- **(Added Revision 9) Greedy corner-painting is accepted behaviour, not a defect.** Because earlier placements are immovable, a later task can be reported `unschedulable` even though some global re-arrangement of the week would have fitted it. This is the price of placement stability, and it is deliberate: a scheduler that silently moves work you have already planned around is worse than one that occasionally tells you it cannot fit something. A user-triggered "re-optimise my schedule" reflow is the natural escape hatch and is Backlog 12.23, not POC.
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
- **(Added Revision 9) The risk assessment uses a speculative placement pass.** Because dependents are never placed until their prerequisites complete (6.1), chain-completion risk cannot be read off the timeline - there is nothing on it to read. The check runs 6.2's placement logic **hypothetically over the whole chain, persisting nothing**, and compares the projected end against the deadline. This is possible precisely because the scheduling engine is pure and side-effect-free: it must not write `scheduled_time`, must not create obstacles, and must not emit any notification other than `dependency_at_risk` itself.

### 6.4 External calendar sync - collision handling

On each poll:
1. Fetch upcoming events over the 90-day horizon (3.12) and diff against the previously known set - **the persisted `ExternalEvent` rows (3.11)**. Upsert on `(connection_id, provider_event_id)`; soft-delete rows the provider no longer returns; purge per 3.12's retention rule.
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
- **Fixed:** status unchanged, create an `overdue` Notification whose action menu offers **"reschedule"** (opens edit, subject to 6.5 validation for the new time), **"mark complete"** - covering the case where the user simply forgot to check it off - and **(Rev 9) "skip this occurrence"**, transitioning the instance to `dismissed` (3.8), for the case where it genuinely did not happen and is not going to.

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
- **Extend the deadline** → instance returns to `pending`, re-enters the next scheduling pass, notification auto-resolves (3.9). **(Added Revision 7)** This is itself a "this occurrence" edit of `deadline` (3.10) and sets `detached = true`, so a later "this and future" edit to the template's `deadline_offset_minutes` won't silently re-shorten a deadline the user just deliberately extended.
- **Mark complete** directly → terminal, notification auto-resolves.
- **Delete the instance/template** → per 3.8 deletion rules; notification becomes moot.

**Dependency-graph note:** if another instance depends on a `missed` instance, that dependent remains `blocked` indefinitely - `missed` is not `completed`, and does not satisfy a dependency requirement. It clears only when the `missed` instance is completed, or the dependency link is removed via deletion (3.8).

**[CONFIRMED - Revision 7, Section 11 item 6. No change from the Revision 6 design above.]**

### 6.8 Creation-time feasibility validation for flexible tasks - added Revision 6

Before a flexible `TaskTemplate` (and its initial instance) is saved, validate that `estimated_duration_minutes` fits within **at least one** day's **effective** active-hours window - i.e.:

```
# (Rev 9) Evaluated against the MERGED map (3.2), not the override alone - a partial
# override leaves unnamed days governed by the global map, and checking the override
# in isolation would reject feasible tasks.
effective = { day: effective_hours(day) for every day-of-week }   # see 6.2

# (Rev 9) Measured from the first GRID point at or after the window start, not from the
# window start itself - otherwise a task can pass validation here and then never be
# placeable, because 6.2 can only ever start it on a grid point.
usable(day) = window.end - first_grid_point_at_or_after(window.start)

max_window = max( usable(day) for every day-of-week entry that is non-null in `effective` )

if estimated_duration_minutes > max_window
   (or no day-of-week has a non-null window at all):
    reject save with validation error "infeasible_duration"
```

This mirrors the existing hard-block pattern already used for fixed-task creation conflicts (6.5), rather than introducing a new mechanism. Without it, a task like a 5-hour "Deep Clean Garage" against a 3-hour daily active-hours cap would sit `pending` forever, re-triggering `unschedulable` on every pass, with no signal to the user that the problem isn't *timing* but that the task is **structurally too big to ever fit as a single block**.

Deliberately **not** pursued for POC: automatic splitting of the task into multiple sub-slot chunks. That's a real capability (it would need partial-completion semantics, resumption logic, and its own notification design) and is exactly the kind of scope creep Section 0 and the architecture plan's "no premature abstraction" rule warn against. Recorded as new Backlog item 12.20.

**[CONFIRMED - Revision 8, Section 11 item 1. Hard-block at creation, as specified.]**

### 6.9 Auto-scheduling on dependency unblock (added Revision 9)

Dependents are not placed while any dependency is incomplete (6.1). When the **last** outstanding dependency of an instance reaches `completed`:

1. That instance transitions `blocked` → `pending` per Section 4, and
2. is placed by 6.2 immediately, **in the same service method and transaction as the completion that unblocked it** - not on a later periodic sweep. This is an event hook, matching the architecture plan's rule that a database write and its scheduling side-effect are co-located.
3. If 6.2 finds no slot before the deadline, the instance stays `pending` with an `unschedulable` Notification, exactly as for any other flexible task.
4. If the deadline has **already elapsed** while the instance sat blocked, the 6.7 gate applies first and the instance goes to `missed` instead.

Point 4 is a real path, not a corner case: **a deadline is a fixed point in time and its clock keeps running while an instance waits in the Backlog.** A dependent can therefore reach `missed` without ever having been schedulable, because its prerequisite ran late. The user recovers through 6.7's existing extend-deadline path, and 6.3's speculative scan is what warns them before it happens. Deadlines are never paused or rebased on unblock.

---

## 7. External Calendar Integration (POC scope)

Read-only, polling-based (webhooks require a publicly reachable endpoint, conflicting with LAN-only self-hosting - deferred, Backlog 12.5). Configured per-provider in Settings: connect account (OAuth), set `refresh_interval_minutes`. Staleness between polls should be visible to the user (e.g. "Calendar last synced: 4 minutes ago"), not hidden.

**(Added Revision 9)** Fetched events are persisted as `ExternalEvent` rows (3.11) on a rolling 90-day horizon with 30-day past retention (3.12). The scheduler reads the cache, never the provider - see 3.11 for why that matters.

**Event filtering (added Revision 6):**
- Events explicitly marked **transparent / "Free"** by the provider (i.e. the calendar owner marked themselves as available during that event) are excluded from the busy-block obstacle set entirely - they never obstruct flexible-task placement (6.2) or fixed-task conflict checks (6.5).
- **All-day events** are imported and shown on the Timeline, but for POC are treated as **display-only overlays** - they do not block flexible placement and are not automatically converted into `blackout_dates`.

**[CONFIRMED - Revision 8, Section 11 item 4. Display-only for POC; per-event holiday-style semantics remains deferred to Backlog 12.15.]**

---

## 8. UI Scope (POC)

WebUI only (Backlog 12.2 for IM bot).

### 8.1 Screens

0. **First-run setup screen (added Rev 9)** - shown only while zero `User` rows exist (3.6). Takes the **setup token** printed in the container log, and sets the admin password (minimum 12 characters, confirmed twice). The screen must say where to find the token. Unreachable once an account exists; every other screen redirects here until one does.
1. **Login screen** - username/password (see 3.6, 14.2).
2. **Timeline / Task list view** - calendar-style view of `scheduled` instances, **plus display-only virtual/"ghost" projections of upcoming recurring occurrences (9.2, added Revision 6)**, external busy-blocks overlaid read-only and visually distinguished (post-filtering per Section 7), blackout dates visibly marked.
3. **Task creation/edit form** - for a new task, or when editing a one-time (`recurrence: one_time`) template, edits the `TaskTemplate` directly as in Revision 6. **(Rev 7)** For an existing recurring task, first prompts for edit scope - **"this occurrence"** vs. **"this and future occurrences"** (3.10) - before applying the edit; includes the optional active-hours override (3.2); surfaces the archival/deletion warning (3.8); surfaces the feasibility validation error on save if applicable (6.8, added Revision 6).
4. **Task detail view** - single `TaskInstance`: status, status history, dependencies (with current status), a visible **`detached` indicator** when applicable (3.10, added Rev 7), actions: mark complete (from any non-terminal status, 3.3), mark in-progress, **skip this occurrence (Rev 9 - transitions to `dismissed`, 3.8; the primary action on a stale recurring occurrence)**, reschedule (for `sync_conflict`/`overdue` fixed tasks - a "this occurrence" edit per 3.10/6.6), extend deadline (for `missed` flexible tasks, 6.7 - also a "this occurrence" edit per 3.10).
5. **Notifications panel** - undismissed/unresolved `Notification` rows; auto-resolved ones show the "already resolved" state if opened (3.9).
5a. **Backlog view (added Rev 9)** - everything that needs the user's attention and has no place on the Timeline: instances in `blocked`, `unschedulable` *(i.e. `pending` with an active `unschedulable` notification)*, and `missed`. This is a **filtered view over `TaskInstance`, not a separate entity** - a backlog item is an ordinary instance, and nothing is moved or copied when it enters or leaves the view. Making it an entity would put one task in two places with a migration between them, which is exactly the silent-desynchronisation failure the architecture is built to avoid.
   - The dependency relation is navigable **in both directions**: from a backlog item, see and edit what is blocking it; from any task, see what is waiting on it. This is what 3.3's join-table storage exists for.
   - The view is the answer to the `blocked` gate's cost (6.1): dependent work is not hidden until its prerequisites finish, it is simply listed here rather than placed on a timeline where its time is not yet knowable.
6. **Settings** -
   - Account: change password.
   - External calendars: connect/disconnect, refresh interval, last-sync timestamp.
   - Scheduling window: global active-hours per day of week, blackout dates list, daily time-budget cap per day of week, and a budget-enforcement toggle ("respect the budget" / "meet the deadline") controlling whether the last-resort override in 6.2 is allowed at all.
   - Timezone: select IANA timezone, defaulted from container `TZ`.
   - Display: first day of the week (for Timeline layout and Settings ordering).

### 8.1a Duration entry (added Revision 9)

All durations are stored and transmitted as integer minutes (3.2). **That is a storage and wire format, never a data-entry format** - the user must never be asked to compute minutes, and must never be shown a raw minute count.

- **Input:** a duration control taking a numeric value plus a unit, converting to minutes on submit. Sensible unit sets differ per field: `estimated_duration_minutes` in minutes/hours; `deadline_offset_minutes` in hours/days/weeks; `reminder_offsets_minutes` in minutes/hours/days plus an explicit "at start time" for `0`; `daily_time_budget_minutes` in hours/minutes.
- **Display:** human-readable in both directions - `4320` renders as "3 days", `90` as "1h 30m".
- **Round-trip stability:** formatting a stored value and re-parsing it must yield the same integer. This needs an explicit test, because the natural greedy formatter ("90m") and the natural user expression ("1h 30m") differ.
- **Validation:** negative and non-integer values are rejected at the API boundary with a machine-readable code; `estimated_duration_minutes` is additionally subject to 6.8.

### 8.2 Deletion confirmation dialogs (per 3.8)

- Deleting a `TaskInstance` with dependents: informational notice only ("N task(s) depend on this - the dependency link will be removed, those tasks will not be deleted"), no hard block, since it's no longer a cascading operation.
- Deleting/archiving a `TaskTemplate` with incomplete instances: confirmation dialog listing the affected incomplete instances before proceeding.
- **(Added Rev 9)** Deleting an instance of a **recurring** template first prompts for **scope** - "this occurrence" or "this and future occurrences" (3.8) - using the same control as the edit-scope prompt in 8.1 item 3. Skipped for `one_time` templates, where the two scopes are equivalent.

---

## 9. Architecture & Deployment

- Self-hosted, single deployable unit - modular monolith (backend + scheduling engine + WebUI), not microservices.
- **Database:** SQLite recommended for POC (single-user, no concurrent-write pressure, no extra container). Revisit if multi-user (Backlog 12.6) lands.
- **Packaging:** single container image. Home Assistant add-on packaging is Backlog 12.10.
- **Background jobs:** (a) external calendar poll per connection, (b) reminder scan, (c) dependency-at-risk scan (6.3), (d) overdue scan (6.6), (e) recurring-template instance generation (9.1), (f) deadline-elapsed scan (6.7, added Revision 6). **(Added Revision 9)** (g) next-occurrence generation for `calendar`-anchored templates - a one-off job at the occurrence boundary, since generation there is no longer triggered by a completion event (9.1). Note that `completion`-anchored generation and dependency-unblock placement (6.9) are **event hooks, not jobs**: they fire inside the service method that completed the predecessor. The architecture plan governs how these are scheduled and reconciled.
- **Auth:** password-based login required for POC (3.6); session/cookie mechanism is an implementation detail but must exist - this is no longer optional per stakeholder confirmation (see 14.2).

### 9.1 Recurring instance generation

Instances are generated **one at a time**, never as a pre-generated rolling window (Backlog 12.13 if that proves insufficient). This rule is about **real, persisted** `TaskInstance` generation only. See 9.2 for how the Timeline nonetheless shows upcoming recurring commitments without changing it.

**(Rewritten Revision 9.)** Generation depends on the template's `recurrence.anchor` (3.2), and the two modes fail differently **on purpose**. Generation must never be gated solely on a `completed` transition: a `missed` instance, a fixed instance whose time passed un-ticked, a deleted instance, or one blocked on a dependency that never completed would each leave the template unable to generate again, silently and with no error - a user who forgot to tick off one Monday stand-up would lose every future Monday stand-up.

#### `anchor: "calendar"` - rigid commitments

The next instance is generated when its **occurrence boundary arrives**, regardless of the predecessor's state. Weekly team syncs, birthdays, a concert.

- Generation is driven by a one-off job scheduled at the next occurrence's nominal time, not by a completion event.
- **More than one live instance may exist at a time.** If Monday's stand-up was never ticked off, next Monday's is generated anyway and both are live. The stale predecessor keeps whatever status it had - a past-due fixed instance stays `scheduled` and carries an `overdue` notification (6.6) - and the user clears it with **"skip this occurrence"**, which transitions it to `dismissed` (3.8) and does not disturb the series.
- The nominal date comes from the recurrence rule itself, never from `completed_at`. Completing Monday's stand-up on Wednesday does not move next Monday.

#### `anchor: "completion"` - upkeep work

The next instance is generated when the live instance reaches `completed`, and its **nominal date is `completed_at` + cadence**, computed in the user's timezone (14.1). Replacing the HVAC filter monthly: complete it on the 7th and the next one is due the 7th of the following month, not the 1st.

- **At most one live instance at a time.**
- **If it is never completed, no successor is generated, and the live instance simply stays outstanding.** This is the intended behaviour, not the dead-end described above: an unreplaced filter still needs replacing, and manufacturing a second copy of the same chore would be wrong. The distinction matters - for calendar-anchored work the occurrence is tied to a date that has passed, while for completion-anchored work the obligation is still live.
- **The nominal date is an earliest-start gate**, not just a label: instance N+1 is not eligible for placement before it. Its `deadline` is `nominal_date + deadline_offset_minutes` (3.2) - `deadline_offset_minutes` is the window the user gives themselves to get it done, inside which the task may be freely rescheduled.
- Valid on **flexible templates only** (3.2). On deletion with `this_occurrence` scope the successor anchors at `now + cadence` (3.8), since there is no `completed_at` to anchor against.

**(Added Revision 7)** Generation always reads the template's *current* values at generation time, regardless of whether the just-completed prior instance was `detached` (3.10) - a one-off override never leaks into the next generated instance. `detached` is a property of an instance, not of the template.

### 9.2 Recurring template preview projection - Timeline display only (added Revision 6)

Under 9.1's one-instance-at-a-time rule, the Timeline would otherwise show nothing for a recurring commitment beyond its single currently-generated instance - e.g. a "Weekly Team Sync" every Monday would vanish from Tuesday through Sunday even though the user obviously still has it every week. That's a real usability gap for previewing upcoming workload, not just a cosmetic nice-to-have.

**Resolution:** the Timeline computes and renders **virtual, non-persisted** occurrences for recurring templates (`fixed` and `flexible`) out to a fixed display horizon (default: 30 days), by projecting the template's `recurrence` pattern forward. Virtual occurrences:
- Are visually distinguished from real, persisted instances (e.g. dimmed/hatched styling).
- Are **read-only** - cannot be marked complete, rescheduled, or otherwise interacted with, since they aren't real `TaskInstance` rows.
- Carry no `id`, participate in no dependency graph, trigger no notification.
- Are excluded entirely from the scheduling algorithm (6.2) and from `daily_time_budget_minutes` accounting - only real, persisted instances affect scheduling and budget math.

**Projection basis, per anchor (added Revision 9).** The projection must agree with 9.1's real generator, or the Timeline actively lies to the user:

- **`anchor: "calendar"`** - project the recurrence rule forward from the last nominal occurrence date. Straightforward, and it agrees with 9.1 by construction because both read the same rule.
- **`anchor: "completion"`** - future dates genuinely depend on a completion that has not happened yet, so the projection **assumes on-time completion**: project from the live instance's nominal date plus cadence. **If the live instance is already past its nominal date**, project from `today + cadence` instead, so ghost occurrences do not pile up in the past and imply a backlog that does not exist.

The completion-anchored projection is therefore a best guess by construction, not a prediction, and the UI should not present it with the same confidence as a calendar-anchored one.

Real instance generation itself remains exactly as specified in 9.1. This section changes **display only**.

**[CONFIRMED - Revision 8, Section 11 item 3. Display-only, non-persisted, 30-day horizon - confirmed as a hardcoded constant for POC, not a `UserSettings` field.]**

---

## 10. Worked Examples

**(Rewritten in Revision 9.)** Every example below is a concrete given/expected fixture, transcribable into an acceptance test without inventing data - which Section 0 forbids.

All examples use timezone `America/New_York` and the 15-minute grid (6.2). Times are local. Each example states its own settings; there is no shared baseline.

**Example A - Fixed task creation, hard block (6.5).**

| Given | |
|---|---|
| `ExternalEvent` | "Date night", Mon 2026-03-02 18:00–22:00, `is_transparent: false`, `is_all_day: false` |
| User action | Create `fixed` template "Team sync", `fixed_time_of_day: "18:00"`, `estimated_duration_minutes: 60`, first occurrence Mon 2026-03-02 |

**Expected:** save rejected with error code `creation_conflict`. No `TaskTemplate` and no `TaskInstance` are created. The user must pick another time or switch the task to `flexible`.

**Example B - Flexible placement, merged active-hours override and grid alignment (3.2, 6.2).**

| Given | |
|---|---|
| `active_hours` (global) | every day 18:00–21:00 |
| Template | "Replace HVAC filters", `flexible`, `recurrence: {pattern: monthly, interval: 1, anchor: completion}`, `estimated_duration_minutes: 30`, `deadline_offset_minutes: 7200` (5 days) |
| `active_hours_override` | `{ "tuesday": { start: "18:00", end: "22:30" } }` - **only Tuesday is named** |
| Instance | generated Mon 2026-03-02 09:00, nominal date Mon 2026-03-02 09:00, so `deadline` = Sat 2026-03-07 09:00 |
| Obstacles | Mon 2026-03-02 18:00–21:00 external event (fills Monday's window); Tue 2026-03-03 18:00–21:37 external event |
| `daily_time_budget_minutes` | all `null` (unlimited) |

**Expected:** `scheduled_time` = **Tue 2026-03-03 21:45**.

Reasoning, and what the fixture is testing: Monday's effective window is 18:00–21:00 (inherited from the global map, since the override names only Tuesday) and is fully occupied. Tuesday's effective window is 18:00–**22:30** from the override. The first free moment is 21:37, which is not a grid point; the first grid point at or after it is **21:45**, and `21:45 + 30min = 22:15 ≤ 22:30`, so it fits. **This example fails if the override is implemented as a whole-map replacement instead of a per-day merge** - Monday would then have no window at all.

**Example C - Sync evicts a scheduled flexible task (6.4).**

| Given | |
|---|---|
| Starting state | Example B's outcome: HVAC instance `scheduled` Tue 2026-03-03 21:45–22:15, `deadline` Sat 2026-03-07 09:00 |
| New poll result | `ExternalEvent` "Concert", Tue 2026-03-03 21:00–23:00, opaque |
| Obstacles | Wed 2026-03-04: nothing inside 18:00–21:00 |

**Expected:** the collision is detected; `scheduled_time` is cleared and `status` becomes `pending`. The 6.7 gate passes (the deadline has not elapsed), so the instance re-enters 6.2 and is placed at **Wed 2026-03-04 18:00** - Wednesday's effective window ends at 21:00, not 22:30, because the override named only Tuesday.

**Example D - Dependency chain, then deletion (3.8).** "Prepare car for inspection" (`flexible`, 10-day deadline) and "Perform annual inspection" (`flexible`, 14-day deadline, depends on the first). The inspection starts `blocked` and appears in the Backlog view (8.1), not on the Timeline.

**Expected:** if the user deletes "Prepare car" outright, the dependency link is removed per 3.8 and "Perform annual inspection" transitions to `pending` immediately rather than being deleted itself - the user is now responsible for getting the car ready some other way, but the inspection task survives, leaves the Backlog, and is placed by 6.2.

**Example E - Unschedulable, but feasible (6.2, contrast with I).**

| Given | |
|---|---|
| `active_hours` | every day 18:00–21:00 (a 180-minute window) |
| Template | "Write annual review", `flexible`, `estimated_duration_minutes: 150` |
| Instance | generated Mon 2026-03-02 09:00, `deadline` Thu 2026-03-05 09:00 |
| Obstacles | external events 18:00–20:00 on Mon, Tue and Wed - leaving 60 free minutes each evening |
| `daily_time_budget_minutes` | all `null`; `budget_enforcement: "soft"` |

**Expected:** the save **succeeds** (6.8 passes: 150 ≤ 180, so the task can fit *some* day in principle). Placement then fails: every eligible day offers only a 60-minute opening. Pass 2 changes nothing, because the budget is unlimited and the obstruction is physical rather than budgetary. The instance stays `pending` and an `unschedulable` Notification is created.

This is the case Example I is deliberately contrasted with: here the task is *placeable in principle* and merely unlucky, so it is accepted at creation and reported later; there it is structurally impossible and rejected up front.

**Example F - Forgot to mark complete.** A `fixed` "Doctor's appointment" instance's `scheduled_time` passes. The overdue scan (6.6) fires an `overdue` Notification. The user opens it, realizes they did go, and taps "mark complete" directly from the notification's action menu - no need to hunt down the task in the list view.

**Example G - Daily budget yields to a deadline, soft cap (6.2 Pass 2).**

| Given | |
|---|---|
| `active_hours["saturday"]` | 09:00–21:00 |
| `daily_time_budget_minutes["saturday"]` | `180`; `budget_enforcement: "soft"` |
| Already scheduled Sat 2026-03-07 | three flexible chores totalling **150 minutes**, occupying 09:00–11:30 |
| Candidate | "Deep-clean garage", `flexible`, `estimated_duration_minutes: 90`, `deadline` Sat 2026-03-07 21:00 - no earlier eligible day remains |

**Expected:** `scheduled_time` = **Sat 2026-03-07 11:30**, plus a `budget_exceeded` Notification recording a 60-minute overage.

Pass 1 fails: `150 + 90 = 240 > 180`, and no other day qualifies before the deadline. Because missing the deadline is treated as worse than a moderate overflow, Pass 2 retries with the budget ignored and finds Saturday physically free from 11:30 onward (11:30 is already a grid point). Had no physically free 90-minute opening existed at all that day - budget aside - the task would instead have stayed `pending` with an `unschedulable` Notification, exactly as in Example E.

**Example H - Pass 2 picks the least-damaging day, not the earliest (6.2).**

| Given | Sunday | Monday | Tuesday | Wednesday |
|---|---|---|---|---|
| Physically free opening ≥ 20 min | yes, from 19:00 | yes, from 19:00 | **none** (fully booked) | **none** (fully booked) |
| Budget remaining that day | 10 min | 17 min | - | - |

Candidate: a `flexible` task, `estimated_duration_minutes: 20`, `deadline` Thursday. `budget_enforcement: "soft"`.

**Expected:** `scheduled_time` = **Monday 19:00**, plus a `budget_exceeded` Notification recording a 3-minute overage.

Pass 1 fails everywhere. Pass 2 considers only the days with a physically free 20-minute opening - Sunday and Monday - and compares overage: Sunday `20 - 10 = 10` minutes, Monday `20 - 17 = 3` minutes. Monday wins on the first tie-break key despite Sunday coming first chronologically. Note that the budget figures here are deliberately not multiples of the grid: **durations and budgets are exact minutes, and only the chosen start time is quantised** (6.2).

**Example I - Feasibility hard block at creation (6.8).**

| Given | |
|---|---|
| `active_hours` | every day 18:00–21:00 (180 minutes) |
| `active_hours_override` | none |
| User action | create `flexible` "Deep Clean Garage", `estimated_duration_minutes: 300`, deadline 14 days out |

**Expected:** save rejected with `infeasible_duration`. 6.8 finds `max_window = 180` and `300 > 180`, so no day-of-week could ever hold the task as a single block. The user is told up front, rather than discovering it 14 days later via an `unschedulable` notification that would have fired identically every day in between.

**Grid variant, added Revision 9:** had `active_hours` been 18:07–21:00, the usable window would be measured from the first grid point at or after 18:07 - that is, 18:15–21:00 = **165 minutes**, not 173. A 170-minute task would pass a naive check and then never be placeable, which is why 6.8 measures from the grid.

**Example J - Pass 2 slack tie-break (6.2).**

| Given | Tuesday | Wednesday |
|---|---|---|
| `daily_time_budget_minutes` | 120 | 60 |
| Already committed | 120 min | 60 min |
| Overage if the task lands here | `120 + 60 - 120 = 60` min | `60 + 60 - 60 = 60` min |
| Physically free time remaining afterwards | **0 min** (wall-to-wall) | **240 min** |

Candidate: a `flexible` task, `estimated_duration_minutes: 60`, placed via Pass 2.

**Expected:** **Wednesday**. Both days tie on the first key at exactly 60 minutes of overage, so the second key decides: prefer the day left with more slack for whatever else might need to land there, rather than defaulting to Tuesday purely because it comes first chronologically.

**Example K - Deadline elapses before the task is ever scheduled (6.7).**

| Given | |
|---|---|
| Instance | "Renew passport", `flexible`, `status: pending` with an active `unschedulable` notification |
| `deadline` | Mon 2026-03-02 17:00 |
| Now | Tue 2026-03-03 08:00 |

**Expected:** the 6.7 check finds `deadline <= now()` and transitions the instance to `missed`, rather than handing the scheduler an inverted `[Tue 08:00, Mon 17:00]` window that would fail instantly and re-fire `unschedulable` on every subsequent pass forever. A `deadline_missed` Notification is created. The user opens it and extends the deadline by a week; the instance returns to `pending`, is placed normally on the next pass, and the notification auto-resolves (3.9). The extension is itself a "this occurrence" edit and sets `detached = true` (3.10).

**Example L - "This occurrence" edit (3.10, added Rev 7).** A recurring "Pay Utility Bills" template normally generates a 10-minute `flexible` instance. This month's bill requires a call to dispute a charge. The user opens this month's instance and edits it with **"this occurrence"** scope, changing `estimated_duration_minutes` to 45. This sets `detached = true` on that instance only; the `TaskTemplate` is untouched. The instance re-enters 6.2 with the new duration. Next month, the normal 9.1 generation cycle produces a fresh instance from the (unchanged) template - 10 minutes, `detached = false` - with no trace of this month's override.

**Example M - "This and future" edit hits a detached instance (3.10, added Rev 7).** Continuing Example L: before this month's (detached, 45-minute) instance completes, the user separately decides all future bill-pay tasks should be budgeted at 15 minutes, and edits the template with **"this and future occurrences"** scope. Because the current live instance is already `detached`, it is skipped entirely - it stays at 45 minutes, unaffected. The template's `estimated_duration_minutes` is updated to 15; the *next* generated instance (after this one completes) will be 15 minutes, not 45 and not the old 10.

**Example N - Dependency chain, unblock and auto-schedule (6.1, 6.9, 8.1 - added Rev 9).**

| Given | |
|---|---|
| `active_hours` | every day 18:00–21:00 |
| Task 1 | "Prepare car for inspection", `flexible`, `estimated_duration_minutes: 120`, `deadline` Fri 2026-03-06 21:00 |
| Task 2 | "Perform annual inspection", `flexible`, `estimated_duration_minutes: 90`, `deadline` Tue 2026-03-10 21:00, `dependencies: [Task 1]` |

**Expected, in three stages:**

1. **At creation.** Task 1 is `pending` and placed by 6.2. Task 2 is `blocked` - it has an incomplete dependency - so it has **no `scheduled_time`**, does not appear on the Timeline, and **does appear in the Backlog view** (8.1) showing "waiting on: Prepare car for inspection". From Task 1's detail view, the reverse link shows "blocking: Perform annual inspection".
2. **On completion.** The user marks Task 1 `completed` at Wed 2026-03-04 19:30. In **the same service method and transaction** (6.9), Task 2 transitions `blocked` → `pending` and is placed by 6.2 at the first grid point at or after `now` inside an active-hours window with room for 90 minutes - here **Wed 2026-03-04 19:30** (already a grid point, and 19:30 + 90min = 21:00, exactly filling the window). Task 2 leaves the Backlog and appears on the Timeline.
3. **The late-dependency path.** Had Task 1 instead been completed on Wed 2026-03-11, after Task 2's deadline had already passed, Task 2 would have reached `missed` while sitting in the Backlog - the 6.7 gate applies before placement, because **a deadline is a fixed point in time and its clock keeps running while an instance waits** (6.9). The user recovers by extending the deadline (6.7); 6.3's speculative scan is what should have warned them beforehand.

**Example O - Completion-anchored recurrence (3.2, 9.1 - added Rev 9).**

| Given | |
|---|---|
| Template | "Replace HVAC filters", `flexible`, `recurrence: {pattern: monthly, interval: 1, anchor: "completion"}`, `deadline_offset_minutes: 7200` (5 days) |
| Instance N | nominal date Sun 2026-03-01, not completed on time |
| User action | marks instance N `completed` at **Sat 2026-03-07 14:20** |

**Expected:** instance N+1 is generated at that moment, with:
- nominal date **Tue 2026-04-07 14:20** (`completed_at` + one calendar month, computed in `America/New_York`),
- `deadline` **Sun 2026-04-12 14:20** (`nominal + 7200 minutes`),
- and an earliest-start gate at the nominal date, so 6.2 will not place it before 2026-04-07.

Had `anchor` been `"calendar"`, N+1 would instead have landed on **Wed 2026-04-01** regardless of when N was completed. That difference is the entire point of the field: a filter replaced on the 7th is due again a month after the 7th, not a month after a date the user already missed.

**Timeline projection (9.2):** ghost occurrences beyond N+1 assume on-time completion, so the next one shown is 2026-05-07. If N+1 is itself still incomplete on, say, 2026-04-20, the projection rebases to `today + cadence` rather than continuing to draw occurrences in the past.

**Example P - Calendar-anchored recurrence with a stale predecessor (9.1, 3.8 - added Rev 9).**

| Given | |
|---|---|
| Template | "Weekly team sync", `fixed`, `fixed_time_of_day: "09:00"`, `recurrence: {pattern: weekly, day_of_week: monday, anchor: "calendar"}` |
| Instance | Mon 2026-03-02 09:00, never marked complete |

**Expected:** the 6.6 overdue check fires an `overdue` Notification for the 2026-03-02 instance, which - being `fixed` - keeps its `scheduled` status. When the next occurrence boundary arrives on **Mon 2026-03-09**, that instance is generated **anyway**, and both are live simultaneously.

The user clears the stale one with **"skip this occurrence"**: the 2026-03-02 instance becomes `dismissed`, its jobs are cancelled, its `overdue` notification auto-resolves (3.9), and the series runs on untouched. The row survives, so "how many stand-ups did I skip this quarter?" remains answerable.

This is the case that makes 9.1's occurrence-boundary rule necessary: gating generation on a `completed` transition that never comes would silently end the series.

---

## 11. Open Questions Requiring Stakeholder Sign-off

**Status as of Revision 9: no open items.** See the closing note below for why that is not the same as "the document is fully verified".

Items 1–7 were raised by the first readiness review and resolved in Revisions 7 and 8; their outcomes are stated in the body of this document rather than restated here, and the full text is in git history. One is worth naming, because it was a **reversal** and a future reader is otherwise liable to reinstate the original position:

- **Item 7, instance-level field overrides.** Revision 6 declined these as contradicting 3.1's "everything is a template" simplicity decision. Revision 7 **reversed that**, on stakeholder direction, modelled on Google Calendar's edit-scope prompt and adapted to this app's one-instance-at-a-time model (which collapses GCal's three scopes to two). Section 3.10 is the binding rule and `TaskInstance` carries a `detached` flag; Worked Examples L and M cover both paths. Revision 9 extended the same two-way scope to deletion (3.8).

Revision 9 resolved eighteen findings from a second review (IRR-2). Two of them were raised here as `[UNCONFIRMED]` rather than decided unilaterally, and both were subsequently settled - items 8 and 9 below.

8. ~~**Does a separate `dismiss` action exist, distinct from scoped deletion?**~~ **RESOLVED - Revision 9: yes.** `dismissed` is a terminal status (Section 4) reached by "skip this occurrence" (3.8). Chosen over deletion-only because this document archives templates and never purges instances specifically to preserve history, and clearing a stale occurrence is **routine** under `calendar` anchoring rather than exceptional - making the weekly action the destructive one would have been backwards. A status value is cheap to add later; destroyed rows cannot be recovered retroactively. Backlog 12.24 is withdrawn.

9. ~~**Does the first-run setup wizard ship with a setup token?**~~ **RESOLVED - Revision 9: yes, in the same Stage 3 work.** Random single-use token generated at startup while zero users exist, logged at `WARNING`, required by the setup endpoint, held in memory only so a restart reissues it. See 3.6. Deferring it would have shipped an open claim window on a deployment that 14.2 says should never be open by default.

**Section 11 has no open items at Revision 9.** Note this is narrower than Revision 8's claim that the document was "fully locked": IRR-2 findings gating Stage 5 and later (H2, H5–H7, H9–H14, and several Medium items) remain **open against this revision** and are tracked in that register, not here. Section 11 tracks decisions awaiting confirmation; IRR-2 tracks findings awaiting a decision.

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
| 12.22 *(added Rev 9)* | Placing dependents against a prerequisite's *scheduled* time rather than its completion, so whole chains appear on the Timeline in advance | Genuinely better for previewing a plan, but it requires a dependency-invalidation cascade: placements are immovable (6.2), so moving a prerequisite would strand every dependent placed after it, needing re-placement, new job re-wiring, and a bounded exception to the immovability rule. That is a feature with its own design, not a side effect of deleting dead code. POC makes the work visible via the Backlog view (8.1) instead |
| 12.23 *(added Rev 9)* | User-triggered "re-optimise my schedule" reflow - clear and re-place all `pending`/`scheduled` flexible instances in one global pass | The natural escape hatch for 6.2's accepted greedy corner-painting. Deferred because it must be explicit and user-initiated: an automatic reflow would silently move work the user has already planned around, which 6.2 rules out deliberately |
| 12.24 *(added and withdrawn in Rev 9)* | ~~Non-destructive `dismiss` for a stale recurring occurrence~~ | **Withdrawn - built into the POC**, not deferred. Section 11 item 8 resolved in favour of a `dismissed` terminal status (3.8, Section 4). Number retained rather than reused, so existing citations do not silently repoint |

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
- Any form of AI/ML-based scheduling suggestion - POC scheduling is deterministic and rule-based (6.2), not learned. (Duration prediction, Backlog 12.14, is a distinct future capability building on data the POC will start collecting, not a POC feature itself. **Revision 9 qualifier:** the POC collects that data only for instances that pass through `in_progress`. 3.3 makes `in_progress` explicitly optional and permits `completed` directly from `pending`, `blocked` or `scheduled`, so every task completed without it contributes an estimate with no matching actual. The corpus is **partial by construction**, and the missing signal is behavioural rather than structural - no additional field can recover it. Whoever builds 12.14 should know this before training on the data rather than after. Everything else 12.14 needs *is* preserved: `estimated_duration_minutes` is copied onto the instance at generation and never rewritten (3.3), `completed` instances are immutable, `status_history` is an immutable trail, and instances are never purged (3.12).)
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

**Durations are elapsed time, not calendar time (added Revision 9).** All duration fields are integer minutes (3.2), and `deadline_offset_minutes = 4320` means 4320 minutes of elapsed time, not "three calendar days at the same wall-clock hour". Across a DST boundary the resulting deadline therefore lands an hour off the original wall-clock time. **This is an accepted simplification, not a bug** - recorded here so it is not later filed as one. It costs an hour on a personal deadline twice a year, and it keeps the scheduling engine free of any timezone dependency for duration arithmetic, which is what lets 6.2 stay pure integer comparison.

Recurrence **cadence** is unaffected and remains calendar-correct: 3.2 expresses it as `pattern` + `interval`, so "monthly" is calendar-month arithmetic performed in the user's timezone (9.1), never a minute count.

**Grid alignment is a local-time operation (added Revision 9).** 6.2's 15-minute placement grid aligns to the hour in the user's local wall-clock, never in UTC. Aligning in UTC produces `:15`-offset slots for anyone in a half-hour or quarter-hour offset zone (`Asia/Kolkata` at +05:30, `Asia/Kathmandu` at +05:45) - a concrete instance of the general rule above.

**[CONFIRMED - Revision 8, Section 11 item 5. Wall-clock is the only `fixed_time_of_day` semantics for POC.** A genuinely fixed-UTC-instant option (e.g. for a global webinar) was considered and deliberately not built - it's additive to this rule, not a replacement of it, so it can be layered on later as a per-template flag without touching the wall-clock default path. Recorded as new **Backlog 12.21** rather than built now, consistent with this document's "no premature abstraction" stance elsewhere.]**

### 14.2 Authentication is mandatory, not optional - binding rule (added Revision 6)

Per stakeholder confirmation (see 3.6, 9): every deployment of the POC requires password-based login; there is no anonymous/no-auth mode, even for a fully LAN-local single-user deployment. Recorded here, rather than only in Section 9, because it's a cross-cutting constraint on every screen and endpoint (a session/auth guard must wrap the entire app), not a feature confined to one section.

**The guard's public routes, enumerated (added Revision 9).** "Wraps the entire app" cannot be literally true, since some routes must serve before a session exists. The exceptions are listed exhaustively below, because an unlisted carve-out is how auth bypasses happen: not through a deliberate hole, but through a route somebody adds later without considering which side of the boundary it belongs on.

**Public:**

| Route | Why |
|---|---|
| `GET /health` | The container healthcheck calls it without credentials. Payload limited to `{"status": "ok"}` - no version string, no database state, nothing an unauthenticated caller can fingerprint. |
| Static assets, `index.html`, all SPA client routes | The login screen has to load. These carry no user data. |
| `POST /api/v1/auth/login` | Self-evident. |
| `POST /api/v1/auth/setup` and its screen | Public **only** while zero `User` rows exist; `410 Gone` afterwards (3.6). |

**Not public, contrary to what one might assume:**
- **The OAuth callback requires a valid session.** It arrives as a cross-site top-level navigation, and the session cookie's `SameSite=Lax` setting is chosen precisely so the cookie *is* sent on that request (architecture-plan Revision 3). Requiring auth is also correct on the merits, since the callback binds a calendar connection to an account. Together with the mandatory `state` parameter check, that closes it properly. If the session expires mid-flow the connection fails and the user retries.
- **`POST /api/v1/auth/logout`** requires a session and returns `204` either way.
- **`/docs`, `/redoc` and `/openapi.json`** are served automatically by the web framework and would otherwise expose the entire API surface uncredentialed. Disabled in production builds, enabled in development, controlled by one setting.

**Binding on the implementation:** the guard is **middleware with an explicit allowlist**, not per-endpoint auth dependencies. That makes it default-deny, so a route added next year is protected unless someone deliberately exempts it; per-endpoint dependencies are default-allow, and a forgotten one silently publishes an endpoint with nothing failing to signal it. A test must enumerate every registered route and assert each is either allowlisted or guarded - the same instinct as the architecture plan's mechanical layering checks.

*(This entry also resolves a dangling `14.2` cross-reference from 8.1 present in earlier revisions of this document, where Section 14 previously contained only 14.1.)*