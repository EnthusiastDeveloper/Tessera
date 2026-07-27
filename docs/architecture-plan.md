# Tessera - Architecture & Implementation Plan
### Companion to: Tessera - Design Document (POC), Revision 7

## 0. Purpose of this document

The design document defines **what** the system does - data model, business rules, algorithm behavior. It is the stable, authoritative product spec and should not be re-derived here.

This document defines **how it gets built** - stack, layering, API shape, job execution, deployment, testing, and coding standards. These are implementation choices: expected to be swappable without changing product behavior, and lower-stakes to revisit than anything in the design doc. Where a decision here affects swap risk later, that's called out explicitly.

Whoever (human or LLM) implements against this repo should treat the design doc as the source of truth for behavior, and this document as the source of truth for structure and process.

### 0.1 Revision 1 changes

Two implementation-level gaps were surfaced during an implementation-readiness review of the design doc (companion edge-case list) and were addressed:
- **Section 5** - a policy for how the frontend handles `409 Conflict` responses caused by the *background scheduler* writing to a row the user is concurrently editing, rather than surfacing a raw conflict error for what is, in a single-user app, never actually a two-human conflict.
- **Section 4.2** - a startup job-reconciliation scan, guarding against the APScheduler job store and the SQLite `TaskInstance` table drifting out of sync after a crash or partial batch failure.

Both were implementation/process decisions (per Section 0's own framing, lower-stakes and more freely revisable than the design doc), so neither was marked `[UNCONFIRMED]` in the design-doc sense - but the 409-handling policy was flagged for a quick sign-off since it changed previously-stated behavior in Section 5.

### 0.2 Revision 2 changes - sync with Design Doc Revision 7

The design doc's Revision 7 added Section 3.10 (Edit Scope & Propagation), reversing the "edit always targets the template" assumption several parts of this document were built on. This revision updates every place that assumption leaked into an architectural decision:
- **Section 3** - Resource shape now specifies how edit-scope is submitted over the API.
- **Section 4 / 4.1** - the job-wiring mutation list now distinguishes a "this occurrence" instance edit from a "this and future" template edit, and adds the latter's conditional-propagation case as its own job-rewiring trigger.
- **Section 5.1 - substantively rewritten, not just re-cited.** The field-partition this section's 409-handling logic depends on was built on the now-superseded claim that instance-level user edits were narrow. They're not, as of design doc 3.10. This also surfaces a new question: template-propagation writes are a third writer to `TaskInstance`, not just "user" and "scheduler" - flagged below for sign-off, same as the original 5.1 change was.
- **Section 8** - testing strategy now covers edit-scope/detach logic explicitly, and the Worked-Examples reference is corrected to A–M.
- **Section 7.2** - same Worked-Examples correction.

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
| Auth | Session cookie (`httpOnly`, secure) + `argon2id` password hashing | See Section 6 |

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

### Auth
Session cookie (`httpOnly`, `secure`), not a bearer token in `localStorage` - since frontend and backend are same-origin (Section 7), this avoids exposing the session token to JS entirely, which is meaningfully better against XSS.

### Error envelope
Consistent shape across all endpoints: HTTP status code + machine-readable error code + human-readable message. Needed because the design doc has several distinct rejection reasons (`cycle_detected`, `creation_conflict`, `infeasible_duration` (new, design doc 6.8), generic validation error) that the frontend must handle differently, not just display generically.

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
| Recurring-instance generation | **Pure event hook** - fires directly off an instance transitioning to `completed`, not time-based at all |
| Deadline-elapsed (`missed` transition, design doc 6.7) | **Event-driven / precisely scheduled** - schedule a one-off check at `deadline`, mirroring the overdue job's pattern; also checked inline at the points listed in design doc 6.7 |

**Consequence:** every mutation path on `TaskInstance` - create, **this-occurrence edit**, reschedule, delete, complete, extend-deadline, **and (added Rev 2) this-and-future template edits that propagate to a live instance** - must hook into scheduling or cancelling the relevant one-off job(s). This is more wiring than a blind periodic scan, but each job fires exactly when needed instead of wastefully re-scanning the whole table on every interval tick.

### Swap risk
Low, if isolated behind a thin internal interface (`schedule_at()`, `cancel()`, `schedule_interval()`) that the rest of the app calls - never importing APScheduler directly outside `app/jobs/`. If a future need arises for distributed execution (e.g. Celery+Redis, likely only relevant if multi-user/Backlog 12.6 ever lands), only this adapter is rewritten.

### 4.1 Enforcing job-wiring correctness

The event-driven design in the table above is only correct if every mutation path remembers to update the jobs it owns - a reminder job left stray after a task is deleted, or not rescheduled after a task is retimed, is a silent bug with no error to surface it. Two things to prevent that from depending on developer memory:

- **Co-locate the DB write and the job side effect in one place.** Each direct `TaskInstance` mutation (create, this-occurrence edit, reschedule, delete, complete, extend-deadline) is handled by exactly one service-layer method that performs *both* the DB write and the corresponding `schedule_at()`/`cancel()` calls in the same function body. Route handlers never call job scheduling directly, and no mutation happens through more than one code path. This isn't decoupled via an event bus - at this scale that's indirection without payoff - it's one method per mutation type, and that method is the single place responsible for getting both halves right.
- **(Added Rev 2, design doc 3.10)** A "this and future" `TaskTemplate` edit is a **separate trigger**, not a variant of the instance-mutation methods above. Its service method must: (1) write the template, (2) check whether the current live instance is `detached` - if not, apply the matching fields to it in the same transaction, (3) if that propagation changed anything job-relevant (`scheduled_time`, `reminder_offsets`-derived fire times, `deadline`), re-wire that instance's jobs exactly as the direct-mutation methods would. This is the one path most likely to be half-implemented by accident, since it's easy to write the template-write half and forget the conditional instance/job half - call it out explicitly in code review, not just here.
- **Job-wiring tests as their own required test category** (see Section 8): for every mutation path, an integration test asserts job-store state directly - e.g. "creating a flexible task with two reminder offsets results in exactly two scheduled jobs at the correct times," "deleting that task cancels both," "rescheduling it cancels the old jobs and schedules new ones at the new time," "a task reaching its deadline unscheduled results in exactly one `missed`-transition job firing and no residual jobs left behind." These are distinct from scheduling-*algorithm* correctness tests (Section 8) - algorithm tests check placement logic, wiring tests check that jobs get created/cancelled at all.

### 4.2 Startup job reconciliation (added this revision)

**The gap:** jobs are event-driven, not periodic scans (4.1) - which means an orphaned or missing job entry doesn't announce itself. If the container is killed mid-batch-update (e.g. a scheduling pass has written new `scheduled_time` values to several `TaskInstance` rows in SQLite but hasn't finished updating the corresponding APScheduler jobs, or vice versa), the SQLite state and the job store silently diverge. Because there's no periodic scan to eventually catch it, the practical effect is a reminder or overdue check that is **silently lost forever** for that task - no error, no log line, nothing for the user to notice until the reminder simply never fires.

**The fix:** on process start, before serving traffic, run a fast reconciliation pass:
1. For every `TaskInstance` with status `scheduled` (fixed or flexible), or with future reminder offsets, confirm a matching active job exists in the APScheduler store for each expected fire time (reminders, the overdue check, and - per 4's new row - the deadline-elapsed check for flexible instances). Recreate any that are missing.
2. For every `pending`/`blocked`/`missed` flexible instance, confirm no *stale* scheduled-fire job lingers from a prior `scheduled` state. Cancel any orphans.

This is a single pass at boot, low cost, and directly closes the failure mode above. It's a robustness addition consistent with the job-wiring philosophy already established in 4.1, not a behavior change - not flagged as needing product sign-off.

---

## 5. Concurrency & Data Integrity

- All writes wrapped in DB transactions.
- **Optimistic locking** via `updated_at`: every write includes a check against the `updated_at` value the client last read; if it doesn't match, the write is rejected with `409 Conflict` rather than silently overwriting a concurrent change. This is the mechanism for the scenario the design doc doesn't otherwise address - e.g. a background job and a live user edit touching the same `TaskInstance` at once.
- Chosen over locking (blocking access) because operations should hold shared resources as briefly as possible; optimistic checks let concurrent reads proceed freely and only reject the losing write.

### 5.1 Background-vs-user write conflicts (added Rev 1; substantively revised Rev 2)

**The original gap:** the POC is single-user, so most optimistic-lock conflicts on a `TaskInstance` are a collision between the user's own live edit and a *background job* (scheduling pass, sync, overdue/deadline-elapsed scan) - not a second human. A blanket `409` on every such collision means routine background recomputation (which can touch many rows in one pass - see design doc Example G/H-style scenarios) can bounce the user's unrelated edit (e.g. changing a title) just because the row's `updated_at` moved underneath them.

**(Rev 2) Why the original fix no longer works as written:** the Rev 1 fix partitioned `TaskInstance` into a fixed "user-owned" field list (name, description, priority, dependencies) and a fixed "scheduler-owned" list (`scheduled_time`, `status`), on the premise - accurate at the time - that instance-level user edits were narrow. Design doc 3.10 broke that premise: `name`, `description`, `estimated_duration`, `priority`, `deadline`, and `scheduled_time` can now *all* be written directly by the user via a "this occurrence" edit. The same fields can *also* be written by template propagation (3.10) when a "this and future" edit lands on a non-`detached` instance. A fixed two-bucket list can no longer classify every field correctly, because several fields now sit in both buckets depending on which write path touched them.

**The corrected fix: classify by field-overlap, not by writer identity.** Drop the fixed field lists. On a `409`, the service layer diffs which fields actually changed between the `updated_at` the client last read and the current row:
- **No overlap** between the fields the user is saving and the fields that changed underneath them → auto-retry once, silently: re-fetch, reapply the user's edits on top of the fresh row, resubmit. This covers the original scheduler-recompute case, and now also covers template propagation touching fields the user isn't currently editing.
- **Overlap** → genuine double-write on the same field(s), regardless of who the other writer was (scheduler, sync, or a template propagation). Show the real conflict UI: both values, user picks. This is rarer than it might sound - propagation only ever reaches a *non-`detached`* instance (3.10), so the only way to hit this case is a template "this and future" edit landing on the same field, in the same narrow window, as a user's in-flight "this occurrence" edit on an instance that hadn't detached yet. Worth handling correctly, not worth over-building for.

This generalizes cleanly to the two writers that already existed (user, scheduler) plus the one 3.10 added (template propagation), without maintaining a field list that Section 3.10 can silently invalidate again the next time an edit surface changes.

**Flagged for sign-off (still open from Rev 1, now slightly changed in shape):** the underlying decision - auto-retry on non-overlapping fields, real conflict UI only on overlap - is unchanged from Rev 1's intent. What changed is the *mechanism* (diff-based, not a hardcoded field list), which is arguably lower-risk than before, not higher. Still calling it out per this document's own Section 0 framing (implementation-level, freely revisable, but a real behavior change from the original blanket-409 text).

---

## 6. Authentication & Secrets

| Concern | Decision |
|---|---|
| Password hashing | `argon2id` via `argon2-cffi` - current best-practice default, resistant to GPU-based cracking |
| Session storage | Server-side session table in SQLite + signed `httpOnly` `secure` cookie |
| Password reset | One-time `RESET_ADMIN_PASSWORD` env var / mounted secret file mechanism, per design doc 3.6 |
| Login throttling | Basic rate-limiting on the login endpoint against brute-force - the app is at minimum reachable on the LAN, so this isn't optional |
| OAuth redirect URI | `APP_BASE_URL` env var, used to construct the redirect URI at OAuth-flow time; documented as a required operator-set value (standard pattern for self-hosted apps, since the public URL isn't known at build time) |
| OAuth client credentials | Per-provider client id/secret as env vars (operator registers their own OAuth app with Google/Outlook) |
| Secrets at rest | OAuth tokens encrypted with `cryptography`'s Fernet symmetric encryption, keyed by a `SECRET_KEY` env var - no external secrets vault needed at this scale |

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
| `RESET_ADMIN_PASSWORD` | One-time password reset trigger (design doc 3.6) | Optional |
| `APP_BASE_URL` | Base URL for OAuth redirect construction | Required if using calendar sync |
| `SECRET_KEY` | Key for session signing + Fernet encryption of stored OAuth tokens | Required |
| `DATABASE_PATH` | Path to the SQLite file (should point into the mounted volume) | Required, with default |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Operator's registered Google OAuth app credentials | Required if using Google sync |
| `OUTLOOK_CLIENT_ID` / `OUTLOOK_CLIENT_SECRET` | Operator's registered Outlook OAuth app credentials | Required if using Outlook sync |
| `PORT` | Port the app listens on | Optional, sensible default |
| `LOG_LEVEL` | Logging verbosity | Optional, sensible default |

### 7.2 Local development

`docker-compose.yml` for local dev, plus a seed script that reproduces the design doc's Worked Examples (A–M, expanded through design doc Rev 7) as fixture data - so the scheduling engine can be sanity-checked against known scenarios immediately, without hand-crafting test data each time.

---

## 8. Testing Strategy

**Build order (confirmed):** the scheduling engine is built and thoroughly tested end-to-end, in isolation, before any other component is wired up. It is the highest-risk, highest-value piece and the one place subtle bugs are most expensive to find late. This is possible specifically because Section 2 keeps it a pure, framework-agnostic module.

| Test type | Scope | Coverage target |
|---|---|---|
| Unit tests | Scheduling engine, validation logic (cycle detection, conflict checks, `infeasible_duration` per design doc 6.8), edit-scope/detach resolution logic (design doc 3.10, added Rev 2 - this-occurrence override application, this-and-future propagation including the detach skip-check), other service-layer business logic | ~90%+ on the scheduling engine specifically |
| Integration tests | API endpoints against a real test DB - contract, auth, error envelope shape | - |
| **Job-wiring tests** | Every direct `TaskInstance` mutation path (create/this-occurrence-edit/reschedule/delete/complete/extend-deadline), **plus (Rev 2) the "this and future" template-propagation path** - asserts job-store state directly, per 4.1 | Required for every mutation path, not optional/best-effort. Propagation case needs its own test: "editing a template's `estimated_duration` with 'this and future' scope while the live instance is non-detached reschedules that instance's jobs; while `detached`, it does not." |
| **Reconciliation tests** (new) | Simulate a killed process leaving SQLite and the job store out of sync; assert the 4.2 startup pass restores consistency | Required - this is the one path with no other test coverage, since it only runs at boot |
| **Architecture tests** | Import-boundary checks per 2.1 - fails if `scheduling_engine/` imports FastAPI/SQLAlchemy, or if layering is violated | Runs in CI on every push, blocking |
| End-to-end tests | Small set of critical flows only: login, create-with-conflict, create-flexible-and-schedule, complete-task, extend-a-missed-deadline, **(added Rev 2)** edit-a-recurring-task-both-scopes-and-verify-detach | Not exhaustive - e2e suites get expensive to maintain if over-built |
| Overall backend | - | ~80% - chasing full coverage past this tends to produce low-value tests rather than catching real bugs |

The design doc's **Worked Examples A–K (Section 10)** become the initial acceptance-test suite for the scheduling engine directly - each one is already a concrete input/expected-output scenario. **(Added Rev 2)** Examples L and M (design doc 3.10) are a different kind of test: they exercise edit-scope/detach/propagation logic, which lives in the `task_instances`/`task_templates` service-layer modules (Section 2), not the pure `scheduling_engine/` module - so they belong in the service-layer test suite, not bundled into the scheduling-engine's isolated build-and-test-first phase (Section 8's build order above).

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