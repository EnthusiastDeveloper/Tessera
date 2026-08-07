# Task Scheduling Application - Implementation Plan (POC)
### Companion to: Design Document Rev 9, Architecture & Implementation Plan Rev 3

## 0. How to use this document

- **Purpose:** sequences the architecture into buildable, independently-testable stages, with hard gates between them.
- **Audience:** human developer *and* an LLM coding agent (e.g. Claude Code) picking up a stage cold. Instructions are written to be followed literally.
- **Authority chain:** design doc Rev 9 = *what* the system does. Architecture plan Rev 3 = *how* it's structured. This document = *order, gates, and process*. Where this document conflicts with either of the other two, they win - stop and flag it, don't silently resolve it in code.
- **Golden rule:** a stage does not begin until the previous stage's Exit Criteria are met and green in CI on `main`. The one exception is Stage 5, which deliberately bundles three components - reasoning given inline, per the process rule that grouping is only allowed when isolated testing isn't meaningful.
- **Traceability:** every stage cites the exact design-doc/architecture-doc section numbers it implements. If you find yourself implementing a rule that isn't traceable to one of those two documents, stop and flag it - don't invent behavior (this mirrors the design doc's own Section 0 authority rule).
- **Open review:** `docs/implementation-readiness-review-2.md` (IRR-2) is the findings register and decision log behind design doc Revision 9 and architecture plan Revision 3. Everything gating Stages 1, 2 and 3 is now **decided and drafted into those documents**; findings gating Stage 5 and later remain open. Its Section 6 lists which gates which stage. Do not start a stage whose gating findings are still open - the point of a findings register is that the invention it prevents is exactly the invention the Traceability rule above forbids. Note that design-doc Section 11 also reopened at Revision 9 with two `[UNCONFIRMED]` items (`dismiss` semantics, gating Stage 5; the setup token, gating Stage 3).

---

## 1. Assumptions Locked for This Plan

| Decision | Value |
|---|---|
| Team size | Solo developer |
| Git hosting / CI | GitHub + GitHub Actions |
| Branching strategy | Trunk-based, short-lived branches (see Section 3 - chosen over GitFlow specifically *because* it's solo: GitFlow's develop/release branches exist to coordinate parallel workstreams across people, which doesn't apply here and would just add merge overhead) |

If any of these change (e.g. a second developer joins), revisit Section 3 before continuing - don't quietly change process mid-project.

---

## 2. Definition of Done (applies to every stage - not repeated per stage)

A stage is **DONE** only when all of the following hold:

1. Code merged to `main` via a completed, CI-green PR (Section 3).
2. Every test category listed in that stage's "Tests required" exists **and passes** - written-but-failing doesn't count.
3. `ruff check`, `ruff format --check`, `mypy --strict` (backend) / `eslint`, `tsc --noEmit` (frontend) all clean. Any suppressed warning has an inline comment explaining why.
4. The `import-linter` contract (architecture doc §2.1) passes - no layering violation.
5. Any new environment variable is added to `.env.example` and the reference table (architecture doc §7.1) stays in sync.
6. Any new/changed endpoint is reflected correctly in the auto-generated OpenAPI schema (spot-checked).
7. No `TODO`/`FIXME` left without a linked GitHub issue.
8. This document's Progress Tracker (Section 5) is updated.

---

## 3. Git & CI Workflow

**Model:** trunk-based. `main` is always deployable and is protected - a PR cannot merge unless the GitHub Actions workflow is green.

- **Branch per stage** (or per named sub-stage, e.g. Stage 9's 9a–9f): `stage-0N-slug`, branched from latest `main`.
- For a large stage, sub-task branches (`feat/...`) may merge into the stage branch first; the stage branch merges into `main` only once, once the whole stage's Definition of Done is met. This keeps `main`'s history as one clean, working, tested increment per stage - always bisectable, always safe to roll back to.
- **Merge strategy:** squash-merge into `main`. One commit per completed stage on `main`.
- **Commit messages:** [Conventional Commits](https://www.conventionalcommits.org/) - `feat:`, `fix:`, `test:`, `refactor:`, `chore:`, `docs:`. Scope tag for large stages, e.g. `feat(scheduling-engine): implement pass-2 budget tie-break`.
- **Issues:** one GitHub Issue per stage (or sub-stage), referenced in the PR (`Closes #N`). This is what makes the plan followable by an LLM agent picking up mid-project - the issue + this doc's stage entry is the complete brief.
- **Tags:** tag `main` after each stage merges, e.g. `stage-05-task-domain-done` - cheap, gives an easy rollback point without heavyweight release branching.
- **PRs even solo:** the point isn't code review from someone else, it's making the CI gate mechanical rather than a matter of remembering to run tests locally.

---

## 4. Coding Standards

### Backend (Python 3.12)
- **Format/lint:** `ruff` (replaces black + isort + flake8), config in `pyproject.toml`, line length 130.
- **Types:** `mypy --strict` on `app/`. `scheduling_engine/` in particular must have zero `Any` in public signatures - it's the highest-value module to keep airtight.
- **Tests:** `pytest` + `pytest-cov`. CI enforces the coverage gates from architecture doc §8 (~90% `scheduling_engine/`, ~80% overall) - a stage doesn't pass if it drops the gate. **Not yet true:** as of Stage 0 there is no `--cov-fail-under` in `pyproject.toml` or `ci.yml`, and codecov is configured with `fail_ci_if_error: false`, so the gate is documented but unenforced. Wiring it is a Stage 1 in-scope item.
- **Import boundaries:** `import-linter` config (`.importlinter`) as a blocking CI check, plus the redundant AST-walk pytest test - both from architecture doc §2.1, both live from Stage 0.
- **Naming:** modules/functions/vars `snake_case`; classes `PascalCase`; constants `UPPER_SNAKE_CASE`. Pydantic domain models are named to match the design doc's interface names exactly (`TaskTemplate`, `TaskInstance`, ...) - this *is* the traceability mechanism, not just a convention. SQLAlchemy ORM classes get their own naming (decide once in Stage 2, e.g. `TaskTemplateORM`, and stay consistent - don't let it drift).
- **Docstrings:** Google-style, mandatory on every public service-layer function. First line cites the design-doc section it implements, e.g. `"""See design doc §6.2."""` - traceability baked into the code itself, not just this plan.
- **Pre-commit hooks:** ruff, ruff-format, a fast mypy pass, whitespace/EOF hygiene. Full mypy + full suite run in CI only, to keep commits fast.

### Frontend (React + Vite + TypeScript)
- **Lint/format:** ESLint (`@typescript-eslint`, strict-ish base config) + Prettier. `tsconfig` with `strict: true`.
- **Naming:** component files `PascalCase.tsx`; hooks `useCamelCase.ts`; utility modules `camelCase.ts`.
- **Tests:** Vitest + React Testing Library, colocated `*.test.tsx`. Thin Playwright layer on top for real end-to-end flows against the live backend.
- **Before writing any Stage 9 UI code:** establish and write down the design-token/styling constraints (colour, spacing, type scale, component conventions) as a short `frontend/DESIGN.md`, and build against it. This is a hard prerequisite for Stage 9, not optional. *(Earlier revisions cited an absolute path to an external design skill file; that path does not exist in this environment, so the requirement is restated as a deliverable rather than a reference.)*

### General
- `.env` is gitignored; `.env.example` is the source of truth for what variables exist (kept in sync per the Definition of Done).
- Secrets never appear in logs or error messages (explicitly re-verified in Stage 11).

---

## 5. Progress Tracker

| Stage | Title | Status | Branch | Notes |
|---|---|---|---|---|
| 0 | Bootstrap & Tooling | **Done** (merged `28c2104`) | `stage-00-bootstrap` | Coverage gate not actually wired - see Stage 1 in-scope |
| 1 | Scheduling Engine | **Ready** | `stage-01-scheduling-engine` | All six gating findings (B3, B4, B8, B9, H1, M7) drafted into design doc Rev 9. Also in scope: wire the coverage gate (see §4) |
| 2 | Data Access Layer | Not started | `stage-02-data-layer` | |
| 3 | Auth & Sessions | Not started | `stage-03-auth` | |
| 4 | User Settings | Not started | `stage-04-settings` | |
| 5 | Task Domain (Templates/Instances/Notifications) | Not started | `stage-05-task-domain` | Multi-component stage - see rationale in Stage 5 |
| 6 | Jobs & Reconciliation | Not started | `stage-06-jobs` | |
| 7 | Calendar Sync | Not started | `stage-07-calendar-sync` | |
| 8 | API Hardening & Backend E2E | Not started | `stage-08-api-hardening` | |
| 9 | Frontend | Not started | `stage-09a`…`stage-09f` | |
| 10 | Deployment & Packaging | Not started | `stage-10-deployment` | |
| 11 | Hardening & Release Readiness | Not started | `stage-11-release-readiness` | |

*(Keep this table honestly current - it's the recovery point if work pauses and resumes later, or hands off to an LLM agent.)*

---

## 6. Implementation Stages

### Stage 0 - Project Bootstrap & Tooling Foundation

**Depends on:** nothing
**Design doc refs:** n/a (process only)
**Architecture doc refs:** §1 (stack), §2/§2.1 (layering + enforcement), §7 (deployment skeleton), §9 (coding practices)
**Branch:** `stage-00-bootstrap`

**In scope**
- Repo on GitHub, default branch `main`, branch protection requiring the CI workflow green before merge.
- `app/` skeleton. **Decide and document now, once:** intra-module layering. Recommendation - each feature module (`task_templates/`, `task_instances/`, `notifications/`, `calendar_sync/`, `auth/`, and a new `settings/` module not explicitly in architecture doc's tree but implied by §3.7/the Settings screen - flagging this addition explicitly) is a **vertical slice** containing `router.py` (API), `service.py` (business logic), `models.py` + `repository.py` (data access). The architecture doc's three-layer diagram (§2) describes *responsibility*, not mandatory top-level folders; `import-linter` enforces import *direction* between these files regardless of layout. `scheduling_engine/` and `jobs/` stay flat, cross-cutting modules.
- `pyproject.toml` with all backend dependencies (FastAPI, SQLAlchemy, Alembic, APScheduler, argon2-cffi, cryptography, pytest, pytest-cov, ruff, mypy, import-linter).
- `.importlinter` config: `layers` contract (api → service → data, one-directional) + `independence` contract for `scheduling_engine/` (zero `fastapi`/`sqlalchemy` imports) - must exist from commit one per architecture doc §2.1, even though it passes vacuously now.
- Backup architecture pytest test (AST-walk of `scheduling_engine/` imports).
- GitHub Actions workflow: install → ruff check → ruff format --check → mypy → import-linter → pytest w/ coverage. All blocking. Separate job for frontend lint/test.
- `frontend/` Vite+React+TS skeleton with its own ESLint/Prettier config and one placeholder passing test.
- `Dockerfile` (multi-stage) + `docker-compose.yml` with a named volume for the SQLite path + a healthcheck against a placeholder `/health` endpoint.
- `.env.example` seeded from architecture doc §7.1's full variable table (placeholder values).
- `pre-commit` config.
- `README.md` stub: local run instructions, test instructions, links to both source docs and this plan.

**Out of scope:** any real business logic, schema, or auth - those are Stages 1–3.

**Tests required**
- A trivial `/health` endpoint + one pytest asserting 200 OK - this *is* the CI pipeline test at this stage.
- import-linter and the AST-walk test both run and pass (vacuously, since there's no real code yet).
- `docker compose up` → container reports healthy.

**Exit criteria**
- [ ] CI green on the PR for this stage.
- [ ] `docker compose up` → healthy within a reasonable timeout.
- [ ] Branch protection active on `main`.

---

### Stage 1 - Scheduling Engine (pure, isolated)

**Depends on:** Stage 0
**Design doc refs:** §6.1 (cycle detection), §6.2 (core placement - Pass 1 + soft-budget Pass 2 + 3-key tie-break), §6.5 (fixed-task overlap predicate), §6.7 (deadline-elapsed *predicate* only - not the orchestration), §6.8 (feasibility validation), Worked Examples A, B, C (placement half only), E, G, H, I, J, K (gate predicate only)
**Architecture doc refs:** §2 (zero FastAPI/SQLAlchemy imports - binding), §8 (this stage first, fully isolated, before anything else is wired up; ~90%+ coverage target)
**Branch:** `stage-01-scheduling-engine`

**In scope**
- Plain-Python (dataclass/Pydantic-without-ORM) input shapes for everything the engine needs - instance-like records, template config, settings-like config. These are engine-local input types the engine defines for itself; it must not import Stage 2's persisted domain models.
- `cycle_check(edges) -> bool` (§6.1).
- `find_first_free_slot(...)` - §6.2 Pass 1: `allowed_hours`, `excluded_dates`, `daily_time_budget`, `obstacles`.
- `schedule_pending_flexible_tasks(candidates, ...)` - full §6.2: topological sort, stable sort by `(deadline ASC, priority DESC)`, Pass 2 soft-budget override with the 3-key tie-break (overage → remaining slack → earliest date).
- `check_fixed_conflict(...)` - §6.5 pure overlap predicate.
- `is_deadline_elapsed(deadline, now) -> bool` - §6.7's gate only. The `missed`-transition orchestration (status change, notification) is service-layer and belongs to Stage 5 - keep this function pure and dumb on purpose.
- `validate_feasible_duration(estimated_duration_minutes, effective_active_hours_map) -> bool` (§6.8) - note the map is the **merged** one (§3.2) and the window is measured from the first 15-minute grid point (§6.2/§6.8).
- Every function is framework-agnostic and deterministic: no DB, no HTTP, no hidden `now()` - `now` is always a parameter.
- **Wire the coverage gate that Stage 0 documented but didn't enforce:** `--cov-fail-under` in CI for both thresholds (~90% `scheduling_engine/`, ~80% overall). Without this, every later stage's "coverage gate met" exit criterion is unverified.

**Gating findings (IRR-2) - all resolved in design doc Revision 9, and each changes what this stage builds:** B3 (obstacle set now includes every `scheduled`/`in_progress` instance of either type, and placement is an incremental fit that never moves existing placements), B4 (`active_hours_override` merges per day; one `null` meaning), B8 (all durations are integer minutes), B9 (15-minute placement grid aligned to the hour in local wall-clock; durations unquantised), H1 (topological sort deleted - **do not build it**), M7 (Examples A–P are now concrete fixtures).

**Explicitly out of scope**
- Anything touching `status`, `detached`, notifications, or persistence.
- Edit-scope/detach resolution (§3.10, Examples L/M) - architecture doc §8 explicitly assigns this to the task_templates/task_instances service layer.
- Timezone wall-clock projection (§14.1) - the engine takes already-resolved, tz-aware datetimes in; projection itself is Stage 5.

**Key modules/files:** `app/scheduling_engine/` only.

**Tests required**
- Unit tests directly encoding Worked Examples B, E, G, H, I, J (table-driven where convenient). **Example A moved to the service-layer suite** in architecture plan Rev 3 - it is a creation-validation path, not a placement one.
- Two of these carry deliberate regression weight: **B** fails if `active_hours_override` is implemented as a whole-map replacement instead of a per-day merge, and **H** fails if durations or budgets get quantised to the grid along with start times.
- Example C: placement-only half - feed a freshly-pending task, confirm correct re-placement.
- Example K: only `is_deadline_elapsed` returning `True` at the correct boundary.
- Edge cases beyond the worked examples: zero-remaining budget day, `budget_enforcement=strict` (confirm Pass 2 never runs), no dependencies, `deadline == now`, exact three-way tie-break equality, empty candidate list.
- Recommended sanity checks: scheduled slots never overlap obstacles, never fall outside `allowed_hours`, never land on a hard-excluded `blackout_dates` day.
- import-linter + AST-walk test pass against real code now.
- Coverage ≥ 90% on `app/scheduling_engine/` (CI-enforced).

**Exit criteria**
- [ ] All tests above green.
- [ ] Coverage gate met.
- [ ] `mypy --strict` clean, zero `Any` in public signatures.
- [ ] Zero `fastapi`/`sqlalchemy` imports anywhere under `scheduling_engine/`.

---

### Stage 2 - Data Access Layer

**Depends on:** Stage 1
**Design doc refs:** §3 (full data model), §3.8 (deletion/archival semantics at schema level)
**Architecture doc refs:** §1 (SQLite/SQLAlchemy/Alembic), §2 (data access - no business logic)
**Branch:** `stage-02-data-layer`

**In scope**
- SQLAlchemy ORM models for all **seven** §3 entities (Rev 9 added `ExternalEvent`, §3.11), field-for-field, including `TaskInstance.detached` (§3.3), the `created_at`/`updated_at`/`version` columns (§3.3), and `dependencies` as a **join table** rather than an array column (§3.3). Decide and document: priority stored as int per §3.2's numeric mapping; status/type as string enums with DB-level constraints.
- Alembic migration(s) - reversible, `upgrade`/`downgrade` both implemented and tested.
- Repository classes (one per aggregate): plain CRUD plus the specific lookups the service layer will need (e.g. "all pending flexible instances", "instance with dependencies loaded"). Decide once: repositories return domain-shaped data, not raw ORM objects leaking past this layer.
- Dependency storage decision for §3.8's unlink-not-cascade semantics (join table vs. JSON column) - document the choice and why.

**Out of scope:** business-rule enforcement beyond what the schema itself expresses (cycle detection is Stage 1 + Stage 5's wiring, not a DB constraint).

**Key modules/files:** `models.py`/`repository.py` inside each feature module (per Stage 0's layering decision); `alembic/versions/`.

**Tests required**
- Migration test: fresh DB → `upgrade head` succeeds; `downgrade base` succeeds; round-trip.
- Repository CRUD tests per entity against a real test SQLite DB, including the §3.8 unlink-without-cascade case at the repository level.
- Constraint tests: invalid enum rejected, required-field omission rejected.
- import-linter `layers` contract extended and passing now that data layer has real code.

**Exit criteria**
- [ ] Every entity migratable and round-trippable.
- [ ] Repository suite green.
- [ ] Layers contract passes.

---

### Stage 3 - Auth & Session Management

**Depends on:** Stage 2
**Design doc refs:** §3.6 (User schema, password reset mechanism), §14.2 (auth mandatory, wraps entire app)
**Architecture doc refs:** §6 (argon2id, session cookie, throttling, `RESET_ADMIN_PASSWORD`)
**Branch:** `stage-03-auth`

**In scope**
- `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`; session-cookie issuance (`httpOnly`, `secure`), server-side session table.
- `argon2id` hashing/verification via `argon2-cffi`.
- Login rate limiting/throttling.
- `RESET_ADMIN_PASSWORD` mechanism exactly per §3.6: one-time consumption, local marker written, warning logged (not re-applied) if the same value persists across restarts; a changed value is honored as a new reset.
- Auth guard/dependency, applied to every route from here on (even though most routes don't exist yet).
- Single-user bootstrap: **new decision this plan makes, not in either source doc - flagged as such.** Recommendation: on first run with no `User` row, create a locked placeholder admin account, unlockable only via `RESET_ADMIN_PASSWORD`. Confirm this doesn't conflict with §3.6's intent before building it; if in doubt, raise it as a real open question rather than assuming.

**Out of scope:** 2FA, SSO, multi-user (Backlog 12.17); OAuth calendar auth (different credential type, Stage 7).

**Key modules/files:** `app/auth/`.

**Tests required**
- Integration: correct cookie flags on success; wrong password rejected; throttling triggers after N attempts (define and document N) and resets appropriately; logout invalidates the session.
- `RESET_ADMIN_PASSWORD`: two consecutive simulated "restarts" with the same value - second must NOT reset, must warn-log; a changed value on a third restart DOES reset.
- Auth guard: unauthenticated request to a protected placeholder route → 401; authenticated → passes.

**Exit criteria**
- [ ] All tests green.
- [ ] Cookie attributes manually confirmed once in real browser dev tools (automated later via Playwright, Stage 9).

---

### Stage 4 - User Settings

**Depends on:** Stage 3
**Design doc refs:** §3.7 (UserSettings), §14.1 (timezone default from `TZ`)
**Architecture doc refs:** §3 (`/settings` resource), §7.1 (`TZ` var)
**Branch:** `stage-04-settings`

**In scope**
- `GET`/`PATCH /api/v1/settings` (singleton, single-user POC).
- Default row created on first run; `timezone` defaulted from container `TZ`.
- Validation: real IANA timezone name; `budget_enforcement` enum; `active_hours`/`daily_time_budget` shape (7 valid day keys, `null` allowed).
- `first_day_of_week` stored as specified - display-only. Prove it, don't just assert it (see test below).

**Out of scope:** anything reading these settings for actual scheduling - that wiring is Stage 5.

**Key modules/files:** `app/settings/`.

**Tests required**
- CRUD/validation integration tests (bad timezone rejected, bad enum rejected, valid partial PATCH succeeds).
- **Regression guard:** two `UserSettings` identical except for `first_day_of_week`, fed through Stage 1's engine functions directly, produce identical output - proves display-only in code, guards against a future "helpful" regression.

**Exit criteria**
- [ ] Tests green.
- [ ] §7.1 table still accurate.

---

### Stage 5 - Task Templates, Task Instances & Notifications (core domain)

**Why one stage, not three:** Notifications are almost entirely side effects of instance mutations and the scheduling pass (§5) - most notification types can't be meaningfully tested without a mutation to trigger them. Templates and Instances stopped being separable at design doc §3.10 - a "this and future" template edit mutates a live instance in the same transaction. Splitting these three would mean writing throwaway stubs of the other two just to test each in isolation, producing less real coverage than testing them together. This is this plan's one deliberate multi-component stage, per the process rule that grouping is allowed only when isolated testing isn't meaningful.

**Depends on:** Stage 4
**Design doc refs:** §3.2, §3.3, §3.4, §3.8, §3.9, §3.10 (core of this stage), §4 (state machine), §5 (notification table), §6.1/§6.2/§6.5/§6.8 (wiring), §6.7 (inline gate + orchestration), §9.1 (generation rule itself), Worked Examples D, F (mark-complete action only), K (the transition itself), L, M
**Architecture doc refs:** §3 (edit-scope API shape), §4.1 (co-location principle - job side effects stubbed here, wired for real in Stage 6), §8 (edit-scope/detach tests belong here, not in `scheduling_engine/`)
**Branch:** `stage-05-task-domain` (sub-branches per sub-task acceptable, e.g. `stage-05a-templates-crud`, `stage-05b-edit-scope`, `stage-05c-notifications`, all merging into the stage branch before that merges to `main`)

**In scope**
- `TaskTemplate` CRUD: create (always spawns the initial instance, §3.1/9.1), archive-on-delete with confirmation payload (§3.8), edit with `scope` param (`PATCH /task-templates/{id}?scope=this_and_future`).
- `TaskInstance` actions: `PATCH /task-instances/{id}` (this-occurrence), `POST .../reschedule` (fixed only, sugar over `PATCH scheduled_time`), `POST .../complete`, `POST .../extend-deadline`.
- Full §3.10 logic: this-occurrence sets `detached=true`; this-and-future propagates to a non-detached live instance in the same transaction, skips a detached one entirely; propagation invalidating placement re-enters the instance into Stage 1's engine.
- Status lifecycle (§4): `completed` reachable directly from `pending`/`blocked`/`scheduled`; `missed` inline-gate transition (§6.7) at every pending-pool entry point this stage owns (creation, dependency unblock - sync/overdue triggers are Stage 6/7, but the gate function is wired wherever they'll eventually call it).
- Cycle validation at save (wired to Stage 1's `cycle_check`) and feasibility validation at save (wired to `validate_feasible_duration`), both returning the correct error code.
- Dependency deletion semantics (§3.8): unlink-not-cascade, downstream `blocked`→`pending` on last-link removal.
- `Notification` CRUD (list/dismiss) + self-resolution (§3.9) wired wherever the trigger actually lives - **be precise per notification type**, don't assume everything resolves here; verify row-by-row against §5's table and list what's genuinely deferred to Stage 6/7.
- Recurring-generation function (§9.1) - pure-ish function producing the next instance's fields from the template, including §14.1 wall-clock re-projection. The completion-triggered *call* to it is Stage 6.
- Job side-effect calls as **no-op stubs** behind the `schedule_at()`/`cancel()` interface - correct call sites now, Stage 6 swaps the stub for the real adapter without touching these sites. This directly targets architecture doc §4.1's warning that this wiring is "the one path most likely to be half-implemented by accident."

**Out of scope:** anything touching real APScheduler, any periodic/background trigger, calendar sync.

**Key modules/files:** `app/task_templates/`, `app/task_instances/`, `app/notifications/`.

**Tests required**
- Unit: edit-scope/detach resolution encoding **Worked Examples L and M** exactly.
- Unit: recurring-generation function - a detached instance's overrides never leak into the next generated instance.
- Integration: full CRUD + every §4 status-lifecycle edge case; **Example D** (dependency deletion → downstream unblocks, upstream survives); **Example K**'s transition half (inline gate firing on an already-past-deadline creation); **Example F**'s "complete directly from non-`in_progress`" half.
- Integration: cycle rejection (`cycle_detected`); infeasible-duration rejection (`infeasible_duration`) for both template creation and a this-occurrence override.
- Integration: dependency-removal unlink semantics at service level (distinct from Stage 2's repo-level test - this one verifies the `blocked→pending` side effect too).
- Notification self-resolution: table-driven test walking §5 row by row, asserting each trigger is checked where this stage claims, and explicitly listing what's deferred.
- Job-wiring **stub** tests: correct stub calls for every mutation path (create/this-occurrence-edit/reschedule/delete/complete/extend-deadline/this-and-future-propagation).

**Exit criteria**
- [ ] All tests green, including Examples D, F(partial), K, L, M.
- [ ] Every §5 notification type has a passing *creation*-trigger test; deferred resolution triggers explicitly listed, not silently missing.
- [ ] Coverage ≥ 80%.

---

### Stage 6 - Background Jobs, APScheduler Adapter & Startup Reconciliation

**Depends on:** Stage 5
**Design doc refs:** §6.3, §6.6, §6.7 (periodic half), §9 (job list), §9.1 (completion trigger)
**Architecture doc refs:** §4 (job breakdown), §4.1 (real adapter + job-wiring tests), §4.2 (reconciliation)
**Branch:** `stage-06-jobs`

**In scope**
- Real `app/jobs/` APScheduler adapter (`schedule_at()`, `cancel()`, `schedule_interval()`), SQLAlchemy-backed persistent store.
- Swap every Stage 5 stub for the real adapter call - **call sites shouldn't need to change**; if they do, that's a sign Stage 5's interface was wrong, fix it there.
- Reminder job (one-off, rescheduled on every relevant mutation), dependency-at-risk job (§6.3, `deadline - 3d`), overdue job (§6.6, fixed vs. flexible branching exactly as specified), deadline-elapsed job + periodic sweep (§6.7, second safety net alongside Stage 5's inline gate).
- Recurring-generation hook: fires on transition to `completed`, calls Stage 5's generation function.
- External-poll job scaffolding (interval-based) - mechanism only, Stage 7 supplies the fetch logic.
- Startup reconciliation (§4.2): both halves - recreate missing jobs, cancel stale ones - run once before serving traffic.

**Out of scope:** the actual calendar-fetch logic (Stage 7).

**Key modules/files:** `app/jobs/`.

**Tests required**
- Job-wiring integration tests per mutation path, against a real test job store, exactly per architecture doc §4.1's examples (two-reminder create → two jobs; delete → both cancelled; reschedule → old cancelled/new scheduled; deadline-unscheduled-flexible-task → exactly one missed job, no residue) - plus the this-and-future propagation case architecture doc §8 calls out explicitly.
- Reconciliation tests: simulate a killed process (write inconsistent state directly, bypassing normal mutation paths), assert the startup pass restores consistency for both §4.2 halves.
- Periodic-check tests: dependency-at-risk fires and dedupes; overdue fires correctly for both types; deadline-elapsed sweep catches what the inline gate might miss.
- **Worked Example C** completed for the non-calendar-sync overdue path (full calendar-triggered version is Stage 7).

**Exit criteria**
- [ ] All job-wiring tests green for every §4.1 mutation path.
- [ ] Reconciliation tests green.
- [ ] Manual check: kill `docker compose` mid-scenario, restart, confirm no orphaned/missing jobs via the job store directly.

---

### Stage 7 - External Calendar Sync

**Depends on:** Stage 6
**Design doc refs:** §3.5, §6.4, §7, Worked Example C (full version)
**Architecture doc refs:** §6 (OAuth env vars, Fernet token encryption)
**Branch:** `stage-07-calendar-sync`

**In scope**
- OAuth connect/disconnect per provider, using operator-supplied client id/secret env vars + `APP_BASE_URL`.
- Token storage: Fernet-encrypted, keyed by `SECRET_KEY`, never raw in `ExternalCalendarConnection`.
- Poll: fetch, diff, apply §7 filtering (transparent/"Free" excluded entirely; all-day imported display-only, never converted to blackout dates or obstacles).
- Collision handling (§6.4): fixed → `sync_conflict`, never auto-moved; flexible → clear/`pending`, subject to §6.7's gate.
- `last_synced_at` exposed for the Settings UI's staleness display.

**Out of scope:** write access (Backlog 12.4), webhooks (Backlog 12.5).

**Key modules/files:** `app/calendar_sync/`.

**Tests required**
- OAuth flow against a **mocked** provider (never a real one in CI).
- Token encryption round-trip.
- Filtering unit tests: transparent event excluded from obstacles; all-day event visible but non-blocking.
- Collision integration tests, both §6.4 branches.
- **Worked Example C, full version**, now genuinely end-to-end.

**Exit criteria**
- [ ] All tests green.
- [ ] Manual smoke test against a real personal calendar in dev (not CI).

---

### Stage 8 - API Contract Finalization, Error Envelope & Backend E2E

**Depends on:** Stage 7 - this is the "all backend components exist" checkpoint.
**Design doc refs:** all of §3–§9 (consistency pass, no new behavior)
**Architecture doc refs:** §3 (error envelope), §8 (backend e2e list)
**Branch:** `stage-08-api-hardening`

**In scope**
- Audit every endpoint for the consistent error envelope; retrofit drift.
- OpenAPI review against design-doc field names/types.
- Confirm throttling is applied exactly where the design doc mandates it (login) and nowhere it doesn't - don't over-build.
- No new business logic. A gap found here is a bug in an earlier stage - fix at the source, re-run that stage's gate, then return here.

**Tests required**
- Backend E2E (API-level, no browser): login, create-with-conflict, create-flexible-and-schedule, complete-task, extend-a-missed-deadline, edit-a-recurring-task-both-scopes-and-verify-detach.
- Error-envelope contract test: one per distinct code (`cycle_detected`, `creation_conflict`, `infeasible_duration`, `sync_conflict` shape, generic validation).

**Exit criteria**
- [ ] Full backend suite (all stages) green in one CI run.
- [ ] Coverage ≥ 80% overall, ≥ 90% `scheduling_engine/` maintained.
- [ ] OpenAPI spot-checked.

---

### Stage 9 - Frontend (React)

**Depends on:** Stage 8 - building UI against a moving API wastes rework.
**Design doc refs:** §8 (full UI scope), §9.2 (virtual/ghost projections)
**Architecture doc refs:** §1 (React/Vite/FullCalendar); **frontend-design skill is a hard prerequisite before any sub-stage below**
**Branch:** `stage-09a` … `stage-09f`, each individually gated

**Decision to make explicitly (not specified by either source doc):** where virtual/ghost projections (§9.2) are computed - client-side from the template's recurrence pattern, or served by a small read-only backend endpoint. Either is valid; pick one in 9d and document why, don't leave it implicit.

**9a - App shell, routing, API client, Login** (§8.1 screen 1)
Tests: login form component states (success/failure), mocked-API integration, one real Playwright test against the live Stage 8 backend.

**9b - Task creation/edit form** (§8.1 screen 3)
Scope prompt for recurring non-one-time tasks, `active_hours_override` input, `infeasible_duration` surfacing, archival/deletion confirmation (§8.2).
Tests: per form state (one-time vs. recurring), explicit test that the scope prompt is *absent* for `recurrence: one_time`.

**9c - Task detail view** (§8.1 screen 4)
Status/history, dependencies-with-status, `detached` indicator, mark-complete/in-progress/reschedule/extend-deadline.
Tests: per status/action-availability combination; `detached` indicator visibility rule.

**9d - Timeline view** (§8.1 screen 2, §9.2)
FullCalendar, real `scheduled` instances, virtual projections (visually distinct, read-only), external busy-blocks, blackout dates.
Tests: virtual occurrences non-interactive (no click-through to edit), visual-distinction assertion (class/style presence, not pixel diffing), correct 30-day horizon.

**9e - Notifications panel** (§8.1 screen 5, §3.9)
Tests: stale-click race (notification resolves server-side between list-load and click) shows "already resolved."

**9f - Settings screens** (§8.1 screen 6)
Account, calendars (OAuth connect UI), scheduling window, timezone, display.
Tests: per settings section; one Playwright test for the OAuth connect flow against Stage 7's mocked provider.

**Cross-cutting for 9a–9f:** ESLint/Prettier/`tsc --noEmit` clean; every screen consumes the real backend (mocks only in unit tests, Playwright hits the real thing).

**Exit criteria (whole Stage 9)**
- [ ] All six sub-stages individually gated and green.
- [ ] Full Playwright suite covering architecture doc §8's e2e list, green, against the real backend.

---

### Stage 10 - Deployment & Packaging

**Depends on:** Stage 9
**Design doc refs:** §9 (single deployable unit)
**Architecture doc refs:** §7, §7.1
**Branch:** `stage-10-deployment`

**In scope**
- Finalize multi-stage `Dockerfile` (frontend build → static assets served via FastAPI `StaticFiles`, same-origin).
- Finalize `docker-compose.yml`: SQLite on a named/mounted volume (verified, not assumed), healthcheck, every §7.1 var wired.
- CI: build the image on every push to `main`, run it, hit `/health`, tear down.
- `README.md` finalized: setup, env vars, first-run/reset-password, test instructions, branching conventions (link Section 3).

**Tests required**
- CI build-and-boot smoke test.
- Manual from-scratch operator walkthrough (documented as a checklist): fresh clone → `docker compose up` → login via `RESET_ADMIN_PASSWORD` → create a task → confirm scheduling → restart container → confirm persistence.

**Exit criteria**
- [ ] CI image build+smoke test green.
- [ ] Operator walkthrough completed and documented once.

---

### Stage 11 - Hardening & POC Release Readiness

**Depends on:** Stage 10
**Design doc refs:** §11 (fully-locked spec, nothing left to re-check), §13 (Non-Goals - final accidental-scope-creep check)
**Architecture doc refs:** §8, §9, §10
**Branch:** `stage-11-release-readiness`

**In scope**
- Full regression run of every stage's suite together, once, clean checkout.
- Coverage reviewed for real gaps in business-critical paths, not just gate pass/fail.
- Security pass: cookie flags re-verified in a real browser, argon2id params reviewed, throttling re-confirmed, Fernet key never logged/surfaced in errors, rate limiting reviewed.
- Non-Goals/Backlog audit: confirm nothing from §13 or §12 was accidentally built "while in there."
- Traceability spot-check: sample service-layer docstrings against their cited section, confirm still accurate after any refactors.
- Tag `v0.1.0-poc`.

**Tests required:** none new - this stage verifies, it doesn't add. Any gap found gets fixed at its owning stage, that stage's gate re-run, then this stage's regression re-run.

**Exit criteria**
- [ ] Full regression green on a clean checkout.
- [ ] Security pass documented.
- [ ] Non-Goals/Backlog audit: zero scope creep found (or found and removed).
- [ ] `v0.1.0-poc` tagged.

---

## 7. Cross-Cutting Checklist (revisit at every stage, not just once)

- **Timezone/DST (§14.1):** any new datetime handling uses the tz-aware library, never naive/offset math.
- **Layering (architecture §2):** service layer stays REST-shape-agnostic; `scheduling_engine/` stays untouched by anything else.
- **Error envelope:** stays consistent as new endpoints are added.
- **Env vars:** documented the moment they're introduced, not batched up.
- **No premature abstraction (architecture §9):** don't build Backlog §12 items "while you're in there."

---

## 8. Open Risks to Watch (not blocking - flag if they actually bite)

- FullCalendar rendering performance with the full 30-day virtual/ghost projection horizon - not called out as a concern in either source doc, worth watching in Stage 9d.
- APScheduler's SQLAlchemy-backed job store sharing one SQLite file with the app's own data, inside a single process - should be fine (SQLite WAL mode), but verify explicitly in Stage 6 rather than assume it.
- OAuth mocks in CI (Stage 7) are not a substitute for the real-account manual smoke test - don't let the mock give false confidence.
- Solo-dev bus factor: this document + the two source docs are the full recovery plan if work pauses or hands off to an LLM agent - keep Section 5 honestly current for exactly that reason.