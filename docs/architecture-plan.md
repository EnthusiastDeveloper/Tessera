# Tessera - Architecture & Implementation Plan
### Revision 3 - companion to: Tessera - Design Document (POC), Revision 9

> **Open review:** `docs/implementation-readiness-review-2.md` (IRR-2) is the findings register behind Revisions 9 and 3. Its findings gating Stages 1, 2 and 3 are now drafted into these documents. **Still undecided and open against this revision:** H9 (no job misfire policy), H14 (the single-worker constraint is unenforced), M11 (field validation rules), M12 (SQLite WAL and `busy_timeout`), M13 (backup/restore guidance). Resolve those before the stage that consumes them - IRR-2 Section 6 says which.

## 0. Purpose of this document

The design document defines **what** the system does - data model, business rules, algorithm behavior. It is the stable, authoritative product spec and should not be re-derived here.

This document defines **how it gets built** - stack, layering, API shape, job execution, deployment, testing, and coding standards. These are implementation choices: expected to be swappable without changing product behavior, and lower-stakes to revisit than anything in the design doc. Where a decision here affects swap risk later, that's called out explicitly.

Whoever (human or LLM) implements against this repo should treat the design doc as the source of truth for behavior, and this document as the source of truth for structure and process.

### 0.1 Revision history

| Rev | What changed |
|---|---|
| 1 | Section 5 - a policy for `409 Conflict` responses caused by the background scheduler writing to a row the user is concurrently editing. Section 4.2 - a startup job-reconciliation scan, guarding against the job store and the `TaskInstance` table drifting apart after a crash |
| 2 | Sync with design doc Revision 7 (Section 3.10, Edit Scope & Propagation), which reversed the "edit always targets the template" assumption several decisions here were built on. Section 3 gained the edit-scope API shape; Section 4/4.1 split instance edits from template edits as job-rewiring triggers; **Section 5.1 was substantively rewritten**; Section 8 gained edit-scope/detach coverage |
| 3 | Sync with design doc Revision 9 - see below |

### 0.2 Revision 3 changes - sync with Design Doc Revision 9

Design doc Revision 9 resolved sixteen findings from a second implementation-readiness review (IRR-2). Most are product-level and land there; eight had architectural consequences, and **two invalidated mechanisms this document specified**:

- **Section 5 - the concurrency token is now `version`, not `updated_at`.** The old token was a field the design doc's schema did not contain, and a timestamp cannot distinguish two writes inside one clock tick - precisely the background-job-versus-user-edit case 5.1 exists for.
- **Section 5.1 - rewritten a second time, because the Revision 2 mechanism was not implementable.** It asked the service layer to diff against a snapshot of the row as the client last read it; the server keeps no such snapshot, and a version token records *that* a row changed, never *what* changed. Replaced with an **expected-values PATCH**, which moves the comparison to the client's side of the contract and delivers the same intent with no history storage. See 5.1 for the contract and the four requirements it places on the frontend.
- **Section 3** - `DELETE` gains a `scope` parameter mirroring edit scope (design doc 3.8); new setup and backlog endpoints; new error codes.
- **Section 4** - a new one-off job for `calendar`-anchored recurrence generation, plus two event hooks. Revision 2's single "generation fires off a `completed` transition" row was only ever true for what is now the `completion` anchor.
- **Section 4.1 / 4.2** - the mutation list and the reconciliation pass extend to cover the new job type, the new deletion scopes, and **missed events** (occurrence boundaries that elapsed while the process was down).
- **Section 6** - session lifetime, rotation and revocation; the cookie's `Secure` flag becomes deployment-derived; the auth guard's public-route allowlist; mandatory OAuth `state`; framework-generated API docs disabled in production.
- **Section 7.1** - `SESSION_COOKIE_SECURE`; `RESET_ADMIN_PASSWORD`'s "Optional" label is now accurate, since first-run account creation moved to a setup wizard.
- **Section 8** - worked-example suite split re-derived for Examples A–P; five new required test categories.

---

## 1. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend language/framework | Python 3.12 + FastAPI | Pydantic models map directly onto the design doc's `TaskTemplate`/`TaskInstance`/etc. interfaces; auto-generates the OpenAPI schema from those same models; async support fits I/O-bound calendar polling; mature libraries for every POC requirement (OAuth, hashing, scheduling) |
| Database | SQLite | Single-user, no concurrent-write pressure, zero extra container to self-host - matches the "convenient self-hosting" goal directly. Revisit only if multi-user (Backlog 12.6) lands |
| ORM / migrations | SQLAlchemy + Alembic | Standard pairing, schema evolves over the POC's life, migrations needed from commit one |
| Frontend | React (Vite build) | Uniform codebase end-to-end, easier to debug/extend than a mixed-stack approach; justified specifically by the Timeline view's real interactive complexity (overlaid scheduled instances, external busy-blocks, blackout dates, and - as of design doc Rev 6 - virtual/ghost recurring projections, 9.2) |
| Calendar UI component | FullCalendar (or equivalent) | Only for the Timeline view; other screens are standard forms/lists needing no special library |
| Background jobs | APScheduler (in-process, SQLAlchemy-backed persistent job store) | See Section 4 |
| Auth | Session cookie (`HttpOnly`, `SameSite=Lax`, `Secure` **derived from the deployment scheme**) + `argon2id` password hashing | See Section 6 |

**Deployment target confirmed:** standard consumer hardware (home server, NAS, PC, mini-PC, laptop) - not a resource-constrained embedded device. This is why Python/FastAPI's ecosystem fit outweighs Go's smaller footprint; the memory difference isn't decisive at this scale.

---

## 2. Backend Architecture - layering (binding)

Three layers, strictly separated:

```
┌─────────────────────────────────────┐
│  API layer (FastAPI routes)          │  thin - request/response only,
│                                       │  no business logic
├─────────────────────────────────────┤
│  Service layer                       │  all business logic: scheduling,
│  (framework-agnostic, pure Python)   │  validation, CRUD rules, state
│                                       │  transitions
├─────────────────────────────────────┤
│  Data access layer                   │  SQLAlchemy models, repositories
└─────────────────────────────────────┘
```

**This is not a style preference - it's what makes several other decisions in this doc low-risk instead of high-risk:**
- If REST ever needs to become GraphQL (Section 3), only a new adapter layer is written; the service layer doesn't move.
- If APScheduler ever needs to become something distributed (Section 4), only its adapter is rewritten; nothing that calls it changes.
- The scheduling engine specifically must have **zero imports of FastAPI or SQLAlchemy** - it operates on plain data structures, which is what makes it unit-testable in isolation per the agreed build order (Section 8).

Module structure mirrors the design doc's own section boundaries, so any section number maps directly to a code location:

```
app/
  task_templates/
  task_instances/
  notifications/
  calendar_sync/
  scheduling_engine/   # pure, framework-agnostic - see above
  auth/
  jobs/                # APScheduler adapter - see Section 4
```

### 2.1 Enforcing the layering (not just documenting it)

A paragraph describing the layering is not enough - it will erode under time pressure unless something actually blocks a violation from merging. Two mechanisms, both required:

- **Static enforcement:** `import-linter`, configured with a `layers` contract (api → service → data, one-directional only) plus an `independence` contract asserting `scheduling_engine/` has zero imports of `fastapi`, `sqlalchemy`, or anything under `app/api/`. Run as a **blocking CI check** - a layering violation fails the build, the same as a failing test, not a lint warning someone can ignore.
- **Backup architecture test:** a plain pytest test that walks the AST/imports of every file under `scheduling_engine/` and fails if a forbidden import appears. Redundant with import-linter by design - cheap insurance in case the linter config lags behind a refactor.

Both live in CI from the first commit, not added retroactively once a violation has already happened.

---

## 3. API Contract

**REST, resource-oriented, versioned (`/api/v1/...`), same-origin session-cookie auth.**

### Why REST over GraphQL, including at full-app scope
GraphQL earns its complexity when heterogeneous clients need meaningfully different data shapes from the same resources. The IM bot (V2) is the one plausible future case - but bot interactions are typically simple command/response ("today's tasks," "mark complete"), not ad-hoc flexible queries, so this doesn't clearly materialize. REST stays simpler, better-understood, and FastAPI generates interactive docs (Swagger UI) from it for free.

### Swap risk if this turns out wrong later
Low, because of the layering in Section 2. The service layer has no REST-specific shape baked into it. Moving to GraphQL later means writing resolvers that call the existing services - not rewriting scheduling, validation, or CRUD logic.

### Resource shape
Maps directly to Section 3 of the design doc:
- `/task-templates`, `/task-instances`, `/notifications`, `/calendar-connections`, `/settings`
- Non-CRUD actions become sub-resource actions: `POST /task-instances/{id}/complete`, `POST /task-instances/{id}/extend-deadline` (for clearing a `missed` status per design doc 6.7 - also a detaching "this occurrence" edit per 3.10)
- **(Added Rev 2, design doc 3.10)** Edit scope is an explicit, required param, not inferred:
  - `PATCH /task-instances/{id}` - a **"this occurrence"** edit. Any of the override-capable fields (3.3/3.10). Sets `detached = true` server-side; the client never sends that flag directly.
  - `POST /task-instances/{id}/reschedule` - sugar for the common single-field case of a `PATCH` on `scheduled_time` (fixed tasks only); kept as its own endpoint because 6.5/6.6 validation applies specifically to it. Also sets `detached = true` (3.10).
  - `PATCH /task-templates/{id}?scope=this_and_future` - a template edit. If the template's current live instance is not `detached`, the service layer also applies matching fields to that instance in the same transaction (3.10) and may re-enter it into 6.2 if placement is invalidated.
  - A one-time (`recurrence: one_time`) template has no scope choice - `PATCH /task-templates/{id}` with no `scope` param is unambiguous, since there's only ever one instance.
- **(Added Rev 3, design doc 3.8)** Deletion scope mirrors edit scope, and is likewise explicit rather than inferred:
  - `DELETE /task-instances/{id}?scope=this_occurrence` - removes this instance; the series continues and its successor is generated per design doc 9.1.
  - `DELETE /task-instances/{id}?scope=this_and_future` - removes this instance and archives the template, ending the series.
  - The parameter is **required** when the instance's template is recurring, and rejected as meaningless when it is `one_time`. Defaulting it would silently pick one of two destructive outcomes on the user's behalf.
- **(Added Rev 3)** `POST /api/v1/task-instances/{id}/dismiss` - "skip this occurrence" (design doc 3.8). Transitions to the terminal `dismissed` status, preserving the row. A sub-resource action rather than a `PATCH` on `status`, matching `/complete` - status transitions with side effects are never plain field writes.
- **(Added Rev 3)** `POST /api/v1/auth/setup` - first-run account creation (design doc 3.6). Available only while zero `User` rows exist; `410 Gone` afterwards, not `401` or `403`, because the resource is permanently gone rather than access-controlled. **Requires the setup token** (Section 6).
- **(Added Rev 3)** `GET /task-instances?view=backlog` - the Backlog view (design doc 8.1) is a **filter on the existing collection**, not its own resource. It returns instances in `blocked` or `missed` status, plus `pending` instances carrying an active `unschedulable` notification. Modelling it as `/backlog` would imply an entity that does not exist and cannot be mutated independently.

### Auth
Session cookie, not a bearer token in `localStorage` - since frontend and backend are same-origin (Section 7), this avoids exposing the session token to JS entirely, which is meaningfully better against XSS. Cookie attributes and the guard's public-route allowlist are in Section 6.

### Error envelope
Consistent shape across all endpoints: HTTP status code + machine-readable error code + human-readable message. Needed because the design doc has several distinct rejection reasons that the frontend must handle differently, not just display generically.

| Code | Meaning | Source |
|---|---|---|
| `cycle_detected` | The submitted dependency list would create a direct or indirect cycle | design doc 6.1 |
| `creation_conflict` | A fixed task's time collides with an existing fixed task or external busy-block | design doc 6.5 |
| `infeasible_duration` | The duration cannot fit any day's effective active-hours window | design doc 6.8 |
| `invalid_recurrence_anchor` *(Rev 3)* | `anchor: "completion"` was submitted on a `fixed` template | design doc 3.2 |
| `session_expired` *(Rev 3)* | Distinct from a generic `401`, so the client redirects to login rather than surfacing an error | design doc 3.6 |
| `conflict` *(Rev 3)* | Optimistic-lock failure; the body **must name the conflicting fields and their current server-side values** so the UI can show a specific conflict rather than a generic reload prompt | 5.1 |
| generic validation error | Field-level validation | - |

---

## 4. Background Job Execution

### Mechanism
APScheduler, running in-process inside the FastAPI application, with its **SQLAlchemy-backed persistent job store**. Persistence is not optional: without it, every scheduled reminder/overdue check is silently lost on container restart, which will happen on any self-hosted deployment.

### Job breakdown - most of these are event-driven, not periodic scans

Of the job types identified in the design doc's Section 9, most are event-driven rather than time-interval-based:

| Job | Mechanism |
|---|---|
| External calendar poll | **Interval-based** (per `refresh_interval_minutes`) - no event to hang it off, has to check the external API on a schedule |
| Reminder | **Event-driven / precisely scheduled** - compute the next fire time on task create/reschedule, schedule one one-off job for it, cancel and reschedule on any edit |
| Dependency-at-risk | **Event-driven / precisely scheduled** - schedule a one-off check at `deadline - 3 days` when a dependency is set, rather than scanning the whole table on an interval |
| Overdue | **Event-driven / precisely scheduled** - schedule a one-off check at `scheduled_time`; it no-ops if already completed by then |
| Recurring-instance generation, **`completion` anchor** | **Pure event hook** - fires directly off an instance transitioning to `completed`, not time-based at all |
| Recurring-instance generation, **`calendar` anchor** *(added Rev 3)* | **Event-driven / precisely scheduled** - a one-off job at the next occurrence's nominal time. Generation here is *not* gated on the predecessor completing (design doc 9.1), so there is no completion event to hang it off. On firing it generates the instance and schedules the next boundary job |
| Deadline-elapsed (`missed` transition, design doc 6.7) | **Event-driven / precisely scheduled** - schedule a one-off check at `deadline`, mirroring the overdue job's pattern; also checked inline at the points listed in design doc 6.7 |
| Dependency unblock → placement *(added Rev 3)* | **Pure event hook, no job at all** - when the last dependency of an instance reaches `completed`, design doc 6.9 requires that instance to be placed **in the same service method and transaction as that completion**. Deferring it to a job would open a window in which an unblocked task is neither blocked nor scheduled |

**Revision 3 note on the generation split.** Revision 2's single "fires off a `completed` transition" row was correct only for what is now the `completion` anchor. A calendar-anchored template whose instance is never ticked off must still generate its successor, and under the old rule it silently never would - the single highest-impact defect IRR-2 found. The two rows above are genuinely different mechanisms, not a stylistic distinction.

**Consequence:** every mutation path on `TaskInstance` - create, **this-occurrence edit**, reschedule, **delete (either scope, added Rev 3)**, **dismiss (added Rev 3)**, complete, extend-deadline, **and (added Rev 2) this-and-future template edits that propagate to a live instance** - must hook into scheduling or cancelling the relevant one-off job(s). This is more wiring than a blind periodic scan, but each job fires exactly when needed instead of wastefully re-scanning the whole table on every interval tick.

### Swap risk
Low, if isolated behind a thin internal interface (`schedule_at()`, `cancel()`, `schedule_interval()`) that the rest of the app calls - never importing APScheduler directly outside `app/jobs/`. If a future need arises for distributed execution (e.g. Celery+Redis, likely only relevant if multi-user/Backlog 12.6 ever lands), only this adapter is rewritten.

### 4.1 Enforcing job-wiring correctness

The event-driven design in the table above is only correct if every mutation path remembers to update the jobs it owns - a reminder job left stray after a task is deleted, or not rescheduled after a task is retimed, is a silent bug with no error to surface it. Two things to prevent that from depending on developer memory:

- **Co-locate the DB write and the job side effect in one place.** Each direct `TaskInstance` mutation (create, this-occurrence edit, reschedule, delete, complete, extend-deadline) is handled by exactly one service-layer method that performs *both* the DB write and the corresponding `schedule_at()`/`cancel()` calls in the same function body. Route handlers never call job scheduling directly, and no mutation happens through more than one code path. This isn't decoupled via an event bus - at this scale that's indirection without payoff - it's one method per mutation type, and that method is the single place responsible for getting both halves right.
- **(Added Rev 2, design doc 3.10)** A "this and future" `TaskTemplate` edit is a **separate trigger**, not a variant of the instance-mutation methods above. Its service method must: (1) write the template, (2) check whether the current live instance is `detached` - if not, apply the matching fields to it in the same transaction, (3) if that propagation changed anything job-relevant (`scheduled_time`, `reminder_offsets_minutes`-derived fire times, `deadline`), re-wire that instance's jobs exactly as the direct-mutation methods would. This is the one path most likely to be half-implemented by accident, since it's easy to write the template-write half and forget the conditional instance/job half - call it out explicitly in code review, not just here.
- **(Added Rev 3, design doc 3.8) Deletion is two mutation paths, not one.** `scope=this_occurrence` must cancel that instance's jobs **and** trigger successor generation - re-anchoring at `now + cadence` for a `completion`-anchored template, since there is no `completed_at` to anchor against. `scope=this_and_future` must cancel that instance's jobs, archive the template, **and cancel the template's pending occurrence-boundary job** if it is calendar-anchored. Forgetting that last cancellation leaves a job that will resurrect a series the user just ended - an orphan that actively creates data rather than silently failing to fire.
- **(Added Rev 3, design doc 3.8) `dismiss` is a mutation path with four side effects**, all in one service method: cancel every job for the instance (reminder, overdue, deadline-elapsed); auto-resolve its open notifications; leave dependents `blocked`, since `dismissed` does not satisfy a dependency; and, for a `completion`-anchored template, **generate the successor anchored at `now + cadence`**. Omitting that last one silently ends the series - the same dead-end design doc 9.1 exists to prevent, reintroduced through a new door.
- **(Added Rev 3, design doc 6.9) Completion is now two side effects, not one.** The `complete` service method already generated the successor for a completion-anchored template; it must **also** place any instance that this completion unblocked, and wire that instance's reminder, overdue and deadline-elapsed jobs, all in the same transaction. This is the second-most likely path to be half-implemented, after template propagation, for the same reason: the obvious half is easy and the conditional half is easy to forget.
- **Job-wiring tests as their own required test category** (see Section 8): for every mutation path, an integration test asserts job-store state directly - e.g. "creating a flexible task with two reminder offsets results in exactly two scheduled jobs at the correct times," "deleting that task cancels both," "rescheduling it cancels the old jobs and schedules new ones at the new time," "a task reaching its deadline unscheduled results in exactly one `missed`-transition job firing and no residual jobs left behind." These are distinct from scheduling-*algorithm* correctness tests (Section 8) - algorithm tests check placement logic, wiring tests check that jobs get created/cancelled at all.

### 4.2 Startup job reconciliation (added this revision)

**The gap:** jobs are event-driven, not periodic scans (4.1) - which means an orphaned or missing job entry doesn't announce itself. If the container is killed mid-batch-update (e.g. a scheduling pass has written new `scheduled_time` values to several `TaskInstance` rows in SQLite but hasn't finished updating the corresponding APScheduler jobs, or vice versa), the SQLite state and the job store silently diverge. Because there's no periodic scan to eventually catch it, the practical effect is a reminder or overdue check that is **silently lost forever** for that task - no error, no log line, nothing for the user to notice until the reminder simply never fires.

**The fix:** on process start, before serving traffic, run a fast reconciliation pass:
1. For every `TaskInstance` with status `scheduled` (fixed or flexible), or with future reminder offsets, confirm a matching active job exists in the APScheduler store for each expected fire time (reminders, the overdue check, and - per 4's new row - the deadline-elapsed check for flexible instances). Recreate any that are missing.
2. For every `pending`/`blocked`/`missed`/`dismissed` instance, confirm no *stale* scheduled-fire job lingers from a prior `scheduled` state. Cancel any orphans. *(Rev 3: `dismissed` added - it is terminal, so any surviving job is by definition an orphan.)*
3. **(Added Rev 3)** For every non-archived template with `recurrence.anchor == "calendar"` and a pattern other than `one_time`, confirm exactly one pending occurrence-boundary job exists (Section 4). Recreate it if missing, **and fire it immediately if its nominal time has already passed while the process was down** - otherwise a container that was off over a weekend silently skips those occurrences. Cancel any such job belonging to an archived template.
4. **(Added Rev 3)** For every `blocked` instance whose dependencies have *all* since reached `completed`, run the 6.9 unblock path. This is the reconciliation counterpart to the new event hook: if the process died between writing a dependency's completion and placing its dependent, nothing else will ever notice, because the triggering event has already been consumed.

This is a single pass at boot, low cost, and directly closes the failure mode above. It's a robustness addition consistent with the job-wiring philosophy already established in 4.1, not a behavior change - not flagged as needing product sign-off.

**(Rev 3)** Note that items 3 and 4 are qualitatively different from 1 and 2. The original pass reconciled the *job store* against the database. These reconcile **missed events** - work that should have happened while the process was not running and that no future event will re-trigger. Both are consequences of design doc Revision 9 moving more logic onto event hooks, and both need their own reconciliation tests (Section 8).

---

## 5. Concurrency & Data Integrity

- All writes wrapped in DB transactions.
- **Optimistic locking** via a monotonic integer **`version`** column (design doc 3.2/3.3): every conditional update carries `WHERE id = ? AND version = ?`, and a zero-row result is the `409 Conflict` signal rather than a silent overwrite of a concurrent change. This is the mechanism for the scenario the design doc doesn't otherwise address - e.g. a background job and a live user edit touching the same `TaskInstance` at once.
- Chosen over locking (blocking access) because operations should hold shared resources as briefly as possible; optimistic checks let concurrent reads proceed freely and only reject the losing write.

**(Revised Rev 3) The token is `version`, not `updated_at`.** A timestamp is the wrong token here: SQLite's resolution cannot distinguish two writes inside one clock tick, and the background-job-plus-user-edit race 5.1 exists to handle is precisely that sub-millisecond case. `updated_at` remains, for display and auditing, and **must not be used for locking**.

**Binding on the implementation:** `version` is incremented at the **ORM layer** - SQLAlchemy's `version_id_col` or an equivalent mapper-level hook - never by individual service methods. A single write path that forgets to bump it defeats the mechanism entirely, silently, and with no error to observe. That includes writes made by background jobs and by template propagation, which are the writers most likely to be added later by someone who has not read this section.

### 5.1 Background-vs-user write conflicts

**The gap:** the POC is single-user, so most optimistic-lock conflicts on a `TaskInstance` are a collision between the user's own live edit and a *background job* (scheduling pass, sync, overdue/deadline-elapsed scan) - not a second human. A blanket `409` on every such collision means routine background recomputation (which can touch many rows in one pass - see design doc Example G/H-style scenarios) can bounce the user's unrelated edit (e.g. changing a title) just because the row's version moved underneath them.

**Two approaches that do not work, recorded so they are not re-proposed:**

- **A fixed field partition** - "user-owned" (name, description, priority, dependencies) versus "scheduler-owned" (`scheduled_time`, `status`). Design doc 3.10 makes this unclassifiable: `name`, `description`, `estimated_duration_minutes`, `priority`, `deadline` and `scheduled_time` can *all* be written by the user via a "this occurrence" edit, **and** by template propagation when a "this and future" edit lands on a non-`detached` instance. Several fields sit in both buckets depending on which path touched them.
- **A server-side diff** - "compare the row now against the row as the client last read it". The server keeps no such snapshot. A version token records *that* a row changed, never *what* changed, so this needs row history, which nothing in this plan provides. Any future proposal along these lines has the same problem.

**The mechanism: expected-values PATCH.** Move the comparison to the client's side of the contract. The browser already knows what it read, so it says so. For each field it is changing, it sends the value it originally read:

```
PATCH /api/v1/task-instances/42
{ "priority": "medium",
  "expected": { "priority": "high" } }
```

Server side, in one transaction:
1. Read the current row.
2. For each field present in the patch, reject with `409` if `current[field] != expected[field]`.
3. Otherwise apply the patch **onto the current row**, increment `version`, write.

Fields nobody is writing are preserved, so a concurrent job's `status` change survives a user's `priority` edit untouched - which is exactly the outcome Revision 1 wanted and Revision 2 could not compute. **There is no retry loop, on either side**; the server applies or rejects, which resolves the ownership ambiguity rather than reassigning it. SQLite serialises writers and the app is a single process (Section 7), so one transaction around read-check-write is sufficient; no advisory locking is needed.

`version` still guards the write itself, but it is **no longer the client-facing token** - the expected values are. Clients do not echo a version.

**Four requirements this places on the implementation. All four need tests, and the first is the one that silently voids the whole mechanism:**

1. **`PATCH` must be genuinely partial.** A frontend that sends its whole task object - because that is what it holds in state - puts `status` in the patch, where it *is* compared and *will* conflict. Dirty-fields-only is a binding requirement on the frontend, not a nicety.
2. **Omitted must be distinguishable from `null` on the wire.** "I am not touching `description`" and "I am clearing `description`" cannot serialise identically. This is a live trap in Pydantic, where both commonly deserialise to the same value; the model needs an explicit sentinel or a `model_fields_set` check. The same trap applies to `active_hours_override`'s merge semantics (design doc 3.2).
3. **Structured fields need a defined comparison.** Compare `dependencies` and `reminder_offsets_minutes` as **sets**, so a reordering is not reported as a false conflict; deep-compare `active_hours_override`.
4. **Field-level agreement is not semantic agreement.** A job writing `status: missed` and a user writing `scheduled_time` touch disjoint fields and can still produce an invalid combination. Ordinary service-layer validation runs *after* the merge and rejects those on business rules. The field check is a concurrency control, not a correctness guarantee, and must not be read as one.

**Sign-off status:** the intent - do not interrupt the user when the concurrent write did not touch what they are editing - has been stable since Revision 1; only the mechanism has changed. The `expected` field is additive, so if this proves to be more machinery than the POC needs, it degrades to a plain version check without an API break.

---

## 6. Authentication & Secrets

| Concern | Decision |
|---|---|
| Password hashing | `argon2id` via `argon2-cffi` - current best-practice default, resistant to GPU-based cracking |
| Session storage | Server-side session table in SQLite + signed cookie. Row: high-entropy id, `user_id`, `created_at`, `expires_at` |
| **Account creation** *(Rev 3)* | **First-run setup wizard** (design doc 3.6), not an env var. `POST /api/v1/auth/setup` while zero users exist, `410 Gone` after |
| **Setup token** *(Rev 3)* | Generated at startup while zero users exist; **`secrets.token_urlsafe(32)`**, logged at `WARNING`, compared in **constant time**, **held in memory only - never persisted**, invalidated on successful setup. A restart reissues it, which is deliberate: a token that leaked but was never used should not stay valid. Closes the claim window in which the first visitor owns the deployment |
| Password reset | One-time `RESET_ADMIN_PASSWORD` env var / mounted secret file mechanism, per design doc 3.6. *(Rev 3)* **Recovery only** - never creation. Its one-time marker is a **database row**, not a file, so a container recreate cannot erase it and turn the variable into the standing backdoor it exists to prevent |
| Login throttling | Basic rate-limiting on the login endpoint against brute-force - the app is at minimum reachable on the LAN, so this isn't optional |
| OAuth redirect URI | `APP_BASE_URL` env var, used to construct the redirect URI at OAuth-flow time; documented as a required operator-set value (standard pattern for self-hosted apps, since the public URL isn't known at build time) |
| OAuth client credentials | Per-provider client id/secret as env vars (operator registers their own OAuth app with Google/Outlook) |
| **OAuth `state` parameter** *(Rev 3)* | **Mandatory.** Generated per authorisation request, verified on return. Unmentioned in Revisions 1 and 2; without it the callback accepts an attacker-initiated authorisation code |
| Secrets at rest | OAuth tokens encrypted with `cryptography`'s Fernet symmetric encryption, keyed by a `SECRET_KEY` env var - no external secrets vault needed at this scale |
| **API docs in production** *(Rev 3)* | `/docs`, `/redoc` and `/openapi.json` are served automatically by FastAPI and would otherwise expose the entire API surface uncredentialed. **Disabled in production**, enabled in development, via one setting |

### 6.1 Session cookie attributes (added Revision 3)

```
Set-Cookie: tessera_session=<id>; HttpOnly; SameSite=Lax; Path=/[; Secure]
```

**`HttpOnly` and `SameSite=Lax` are set unconditionally.** Both function correctly over plain HTTP and cost nothing.

**`Secure` is derived, never hardcoded.** Setting it unconditionally breaks the LAN-local deployment the design doc names as primary. Browsers treat `localhost`, `127.0.0.1` and `[::1]` as potentially trustworthy and permit `Secure` cookies there over HTTP; a private IP such as `192.168.1.50` or an `.local` name is **not** trustworthy, so the cookie is silently discarded. The resulting failure is the worst kind: login returns `200`, the server logs a success, the SPA navigates to the dashboard, its first API call `401`s, and the user loops back to the login screen with nothing in any log - and it passes every test run on a developer's `localhost`.

- **`SESSION_COOKIE_SECURE`**, values `auto` | `true` | `false`, default **`auto`**.
- `auto` reads the scheme of `APP_BASE_URL`: `https://` resolves to `Secure`, `http://` does not.
- `true` / `false` force the value, for deployments behind a TLS-terminating proxy where `APP_BASE_URL` may not reflect the browser-facing scheme.
- **The startup log line is mandatory, not optional.** The app logs the resolved value at boot, and when it resolves to not-`Secure` it emits a `WARNING` stating that the session cookie and the login password cross the network in cleartext, and naming the remedy (a TLS-terminating reverse proxy, or a WireGuard/Tailscale transport). That warning is the entire mechanism preventing an operator from stumbling into this silently, so it must appear in default log output.

**Plain-HTTP LAN is a fully supported deployment, not a degraded mode.** On a plaintext deployment `Secure` protects nothing - there is no encrypted channel for it to confine the cookie to, and the password is already in the clear on every login. Its value is entirely in preventing downgrade leakage on deployments that *do* have TLS. Hardcoding it therefore bought zero security on the primary target while breaking it. The README documents the TLS upgrade path as a recommendation rather than a prerequisite; `auto` picks the change up from `APP_BASE_URL` with no further configuration.

**`Lax`, deliberately not `Strict`.** Recorded because `Strict` looks safer and will otherwise be "hardened" later, breaking calendar sync: the OAuth callback arrives as a cross-site top-level navigation, `Strict` withholds the cookie on exactly that request, and the connection could never complete. `Lax` sends it. **Consequence: no state-changing endpoint may be exposed over `GET`**, since `Lax` still attaches the cookie to top-level `GET` navigations. The API complies today by accident; this makes it a rule.

**No CSRF token.** `Lax` withholds the cookie from every cross-site `POST`, `PATCH` and `DELETE`, which is every mutation in the API. For a single-user, single-origin app that is sufficient, and a double-submit token is defence in depth bought with real frontend plumbing. Note this becomes *more* load-bearing, not less, on a plain-HTTP LAN deployment: the app is then served from an origin any website the user visits can address directly, and the session cookie is not `Secure`. A token can be added later without an API break if the app is ever exposed beyond a LAN.

### 6.2 Session lifetime (added Revision 3)

Unspecified in Revisions 1 and 2, which in practice means sessions that never expire, because that is what you get when you write no expiry code.

- **Absolute TTL of 30 days** from issue. **No idle timeout** - a sliding window would mean a database write on every request, and idle expiry alone is weaker against a live attacker, who refreshes the session simply by using it.
- **Rotation on login:** a fresh session id per successful login, never reused. Standard session-fixation defence.
- **Revocation:** every session for the user is deleted on any password change or reset. **Not optional** - `RESET_ADMIN_PASSWORD` exists so an operator can lock somebody out, and it fails at that if existing sessions survive it.
- **Cleanup:** expired rows are swept lazily at login, not by another background job.
- **Expiry response:** `401` with the `session_expired` code (Section 3), so the client redirects to login rather than surfacing a generic error.

### 6.3 The auth guard (added Revision 3)

Design doc 14.2 requires a guard around the entire app and 14.2 now enumerates the public routes. The architectural decision is **how** it is wired:

- **Middleware with an explicit public-route allowlist.** Default-deny: a route added next year is protected unless someone deliberately exempts it.
- **Not** per-endpoint auth dependencies, which are default-allow - a forgotten dependency silently publishes an endpoint, and nothing fails to make anyone notice.
- **A test enumerates every registered route** and asserts each is either allowlisted or guarded. Same instinct as 2.1's mechanical layering checks: make the invariant enforced rather than remembered.

---

## 7. Deployment & Configuration

- **Single container, single process** - matches the design doc's "single self-hosted app/container" requirement.
- **Frontend serving:** React builds to static assets; FastAPI serves them directly (`StaticFiles`). Keeps the app same-origin, which avoids CORS entirely and is what makes the session-cookie auth approach (Section 3) simple rather than fraught.
- **Data persistence:** the SQLite file must live on a mounted Docker volume, never inside the container's writable layer - otherwise all data (tasks, history, credentials) is lost the moment the container is recreated. This must be explicit in the compose file, not assumed.
- **Container health check** included, standard practice for anything running under Docker/Compose/orchestration.
- **Basic CI**: lint + test on push. Low effort, catches regressions early, worth having from the first commit rather than retrofitted.

### 7.1 Environment variable reference

| Variable | Purpose | Required? |
|---|---|---|
| `TZ` | Default timezone (IANA name), overridable in Settings | Optional, sensible default |
| `RESET_ADMIN_PASSWORD` | One-time password **recovery** trigger (design doc 3.6). *(Rev 3)* Genuinely optional now that first-run account creation is the setup wizard - previously this label was wrong, since there was no other way to obtain an account | Optional |
| `SESSION_COOKIE_SECURE` *(added Rev 3)* | `auto` \| `true` \| `false` - whether the session cookie carries the `Secure` attribute. `auto` derives it from `APP_BASE_URL`'s scheme. See 6.1 | Optional, defaults to `auto` |
| `APP_BASE_URL` | Base URL for OAuth redirect construction | Required if using calendar sync |
| `SECRET_KEY` | Key for session signing + Fernet encryption of stored OAuth tokens | Required |
| `DATABASE_PATH` | Path to the SQLite file (should point into the mounted volume) | Required, with default |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Operator's registered Google OAuth app credentials | Required if using Google sync |
| `OUTLOOK_CLIENT_ID` / `OUTLOOK_CLIENT_SECRET` | Operator's registered Outlook OAuth app credentials | Required if using Outlook sync |
| `PORT` | Port the app listens on | Optional, sensible default |
| `LOG_LEVEL` | Logging verbosity | Optional, sensible default |

### 7.2 Local development

`docker-compose.yml` for local dev, plus a seed script that reproduces the design doc's Worked Examples (**A–P**, expanded through design doc Rev 9) as fixture data - so the scheduling engine can be sanity-checked against known scenarios immediately, without hand-crafting test data each time. **(Rev 3)** This is now mechanical rather than interpretive: Revision 9 rewrote every example as an explicit given/expected table, so the seed script transcribes stated values instead of inferring them.

---

## 8. Testing Strategy

**Build order (confirmed):** the scheduling engine is built and thoroughly tested end-to-end, in isolation, before any other component is wired up. It is the highest-risk, highest-value piece and the one place subtle bugs are most expensive to find late. This is possible specifically because Section 2 keeps it a pure, framework-agnostic module.

| Test type | Scope | Coverage target |
|---|---|---|
| Unit tests | Scheduling engine, validation logic (cycle detection, conflict checks, `infeasible_duration` per design doc 6.8), edit-scope/detach resolution logic (design doc 3.10, added Rev 2 - this-occurrence override application, this-and-future propagation including the detach skip-check), other service-layer business logic | ~90%+ on the scheduling engine specifically |
| Integration tests | API endpoints against a real test DB - contract, auth, error envelope shape | - |
| **Job-wiring tests** | Every direct `TaskInstance` mutation path (create/this-occurrence-edit/reschedule/delete/complete/extend-deadline), **plus (Rev 2) the "this and future" template-propagation path** - asserts job-store state directly, per 4.1 | Required for every mutation path, not optional/best-effort. Propagation case needs its own test: "editing a template's `estimated_duration_minutes` with 'this and future' scope while the live instance is non-detached reschedules that instance's jobs; while `detached`, it does not." |
| **Reconciliation tests** (new) | Simulate a killed process leaving SQLite and the job store out of sync; assert the 4.2 startup pass restores consistency | Required - this is the one path with no other test coverage, since it only runs at boot |
| **Architecture tests** | Import-boundary checks per 2.1 - fails if `scheduling_engine/` imports FastAPI/SQLAlchemy, or if layering is violated | Runs in CI on every push, blocking |
| End-to-end tests | Small set of critical flows only: login, create-with-conflict, create-flexible-and-schedule, complete-task, extend-a-missed-deadline, **(added Rev 2)** edit-a-recurring-task-both-scopes-and-verify-detach | Not exhaustive - e2e suites get expensive to maintain if over-built |
| Overall backend | - | ~80% - chasing full coverage past this tends to produce low-value tests rather than catching real bugs |

The design doc's **Worked Examples (Section 10)** are the initial acceptance-test suite - but they split across two suites, and not all of them are engine tests:

- **Scheduling-engine suite (pure, Stage 1):** B, C (placement half only), E, G, H, I, J, and K's `is_deadline_elapsed` predicate only. **(Rev 3)** Also N's step-2 placement arithmetic, in isolation from the transaction that triggers it.
- **Service-layer suite (Stage 5/6):** A (creation conflict - it is a validation path, not a placement one), D (dependency deletion), F (overdue + mark-complete), C's sync-eviction half, K's `missed`-transition orchestration, L and M (edit scope, below), and **(Rev 3)** N's unblock orchestration, plus **O and P**, which test recurrence generation rather than placement and therefore belong nowhere near the pure engine.

**(Rev 3)** Revision 9 rewrote Examples A, B, C and E as explicit given/expected fixtures and re-derived every expected value in G–K against the 15-minute placement grid and minute-typed durations. The earlier note that these examples could not be transcribed without inventing fixture data no longer applies. Two of them now carry deliberate teaching weight worth preserving in the tests: **B** fails if `active_hours_override` is implemented as a whole-map replacement rather than a per-day merge, and **H** fails if durations or budgets are quantised to the grid along with start times.

**(Added Rev 3) Additional required test categories**, arising from design doc Revision 9:

| Test type | Scope |
|---|---|
| **Recurrence-anchor tests** | Both anchors, both failure modes: a `calendar` template generates its successor even when the predecessor was never completed (design doc Example P); a `completion` template generates **nothing** when its instance is never completed, and that is asserted as correct rather than as a bug (design doc 9.1). Plus the save-time rejection of `anchor: "completion"` on a `fixed` template |
| **Deletion-scope tests** | Both scopes, and specifically that `this_and_future` cancels a calendar-anchored template's pending occurrence-boundary job (4.1) - an orphan there resurrects a series the user ended |
| **Missed-event reconciliation tests** | 4.2 items 3 and 4: occurrence boundaries that elapsed while the process was down, and dependents whose last dependency completed in the same window. Distinct from the existing job-store reconciliation tests, because there is no stale job to find - the event is simply gone |
| **Concurrency tests** | The 5.1 contract: a partial `PATCH` succeeds while a concurrent job writes an untouched field; the same `PATCH` `409`s when the job wrote the field being edited; the `409` body names the field and its current value; a whole-object `PATCH` is rejected or fails, so requirement 1 of 5.1 cannot regress silently |
| **Auth-boundary test** | Enumerate every registered route; assert each is either in the public allowlist or behind the guard (6.3) |
| **Dismiss tests** | The four side effects above, individually. Specifically: dismissing the live instance of a `completion`-anchored template **generates its successor** - the regression that would silently end a series - and dismissing does **not** unblock a dependent |
| **Setup-token tests** | Setup rejects a missing, wrong, or already-consumed token; the token is absent from the response body; a restart before setup issues a different one |

**(Added Rev 2)** Examples L and M (design doc 3.10) are a different kind of test: they exercise edit-scope/detach/propagation logic, which lives in the `task_instances`/`task_templates` service-layer modules (Section 2), not the pure `scheduling_engine/` module - so they belong in the service-layer test suite, not bundled into the scheduling-engine's isolated build-and-test-first phase (Section 8's build order above).

---

## 9. Coding Practices

Stated operationally, not as abstract principles:

- **Layered architecture** (Section 2) is mandatory, not optional - it's what keeps REST→GraphQL and APScheduler→other swap risk low if either is ever revisited.
- **Scheduling engine stays pure** - no FastAPI or SQLAlchemy imports inside it, ever.
- **Module structure mirrors design-doc section numbers** - anyone (or any LLM) implementing against the spec should be able to find the matching code by section number without guessing.
- **Type hints enforced throughout** (mypy/Pydantic) - Python won't check this for you, and it keeps implementation honest against the schemas already defined in the design doc.
- **No premature abstraction** - e.g. do not build a plug-in point for "multiple scheduling algorithms" now (Backlog 12.9), and do not build task-splitting/chunking now (Backlog 12.20, design doc 6.8) just because it was raised during edge-case review. Building either early would repeat the exact scope creep the design doc's own Section 0 warns against.
- **Config via environment variables only** (12-factor style) - never hardcoded, per the reference table in 7.1.

---

## 10. Summary - status before coding starts

All blocking architectural decisions identified during planning are resolved: stack, API shape, job execution mechanism, concurrency strategy, auth/secrets handling, deployment/config, testing strategy, and coding standards. Section 5.1 (background-write 409 handling) and Section 4.2 (startup reconciliation) closed two robustness gaps found during the design doc's Revision 6 edge-case review. **Revision 2 of this document** brought Sections 3, 4/4.1, 5.1, and 8 into sync with design doc Revision 7's edit-scope model (3.10) - most notably a substantive rework of 5.1, not just a citation fix. Implementation can begin with the scheduling engine, per the agreed build order.