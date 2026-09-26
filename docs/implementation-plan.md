# Task Scheduling Application - Implementation Plan (POC)
### Companion to: Design Document Rev 9, Architecture & Implementation Plan Rev 3

## 0. How to use this document

- **Purpose:** sequences the architecture into buildable, independently-testable stages, with hard gates between them.
- **Audience:** human developer *and* an LLM coding agent (e.g. Claude Code) picking up a stage cold. Instructions are written to be followed literally.
- **Authority chain:** design doc Rev 9 = *what* the system does. Architecture plan Rev 3 = *how* it's structured. This document = *order, gates, and process*. Where this document conflicts with either of the other two, they win - stop and flag it, don't silently resolve it in code.
- **Golden rule:** a stage does not begin until the previous stage's Exit Criteria are met and green in CI on `main`. The one exception is Stage 5, which deliberately bundles three components - reasoning given inline, per the process rule that grouping is only allowed when isolated testing isn't meaningful.
- **Traceability:** every stage cites the exact design-doc/architecture-doc section numbers it implements. If you find yourself implementing a rule that isn't traceable to one of those two documents, stop and flag it - don't invent behavior (this mirrors the design doc's own Section 0 authority rule).
- **Open review:** `docs/implementation-readiness-review-2.md` (IRR-2) is the findings register and decision log behind design doc Revision 9 and architecture plan Revision 3. Everything gating Stages 1, 2 and 3 is now **decided and drafted into those documents**; findings gating Stage 5 and later remain open. Its Section 6 lists which gates which stage. Do not start a stage whose gating findings are still open - the point of a findings register is that the invention it prevents is exactly the invention the Traceability rule above forbids. Design-doc Section 11 has **no open items** at Revision 9.

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
| 1 | Scheduling Engine | **Done** (merged `61a1454`) | `stage-01-scheduling-engine` | All six gating findings (B3, B4, B8, B9, H1, M7) resolved per design doc Rev 9. Coverage gate wired (90% engine / 80% overall, both enforced in CI + `make backend-test`). Worked Examples B, C (placement half), E, G, H, I (+ grid variant), J, K, N (step-2) plus edge cases; `scheduling_engine/` at 100% branch coverage |
| 2 | Data Access Layer | **Done** (merged `c2cb2c0`) | `stage-02-data-layer` | ORM models + repositories for all seven §3 entities plus the `task_instance_dependencies` join table. `UTCDateTime` column type added to fix a real SQLite+SQLAlchemy gap (tzinfo silently dropped on read - not in either source doc, a Stage 2 implementation-level fix). `Enum` columns use `create_constraint=True` for real DB-level CHECK constraints (SQLAlchemy 2.0 defaults this off). Alembic wired end-to-end (`alembic.ini`, `env.py` incl. a `render_item` hook for the custom type, initial migration) - upgrade/downgrade/round-trip verified. 42 new tests (migrations, per-entity repository CRUD, DB-level constraint rejection, dependency unlink-not-cascade) |
| 3 | Auth & Sessions | **Done** (merged `26bd55a`) | `stage-03-auth` | Built to design doc Rev 9 §3.6 + architecture-plan Rev 3 §6 (first-run setup wizard + setup token, IRR-2 B10/B10-token) - see the corrected "In scope" bullet below; the original placeholder-account recommendation this section carried was superseded before this stage started. `sessions` and `admin_password_reset_marker` tables added (new migration). Default-deny auth guard middleware, signed session cookie, argon2id, login throttle (N=5/15min, documented in `app/auth/throttle.py`). 63 new tests. Also fixed the container image: nothing ran migrations before app startup once the lifespan started querying the DB - added `docker/entrypoint.sh` |
| 4 | User Settings | **Done** (merged `33766ad`) | `stage-04-settings` | `GET`/`PATCH /api/v1/settings`, singleton row auto-created at startup (timezone from `TZ`, falling back to UTC if unset/invalid). `active_hours`'s first-run default (09:00-17:00 every day) is confirmed with the user, not sourced from either doc - see the note below. Validation: real IANA timezone (`zoneinfo`), exact 7-day-key shape on `active_hours`/`daily_time_budget_minutes`, enums via Pydantic `Literal`. Regression guard test proves `first_day_of_week` has zero effect on `find_first_free_slot`'s output, per §3.7. 25 new tests |
| 5 | Task Domain (Templates/Instances/Notifications) | **Done** (merged `1ab1079`) | `stage-05-task-domain` | `TaskTemplate`/`TaskInstance`/`Notification` service layers + routes, §3.10 edit-scope/detach, §6.7 inline missed-gate, §9.1 recurring generation, job-wiring stubs. New shared `app.scheduling` layering tier (import-linter) so the two independent sibling services can share DB-aware placement logic without importing each other. **Deferred, documented, not silently missing:** the `dismiss` ("skip this occurrence") endpoint, `DELETE ...?scope=` (only unscoped delete exists), and this-and-future propagation of `fixed_time_of_day`/`deadline_offset_minutes` (needs real conflict/re-placement handling) - all pushed to Stage 6/8, see the Stage 5 section below. 65 new tests |
| 6 | Jobs & Reconciliation | **Done** (merged `cfe9fbd`) | `stage-06-jobs` | Real `APSchedulerJobScheduler` + job handlers (reminder, overdue §6.6, deadline-elapsed one-off + periodic sweep §6.7, dependency-at-risk §6.3), completion-anchor and calendar-anchor recurring-generation hooks, full startup reconciliation (architecture-plan §4.2, all 4 items). **Verified and corrected an architecture-plan assumption**: the job store cannot share the app's own SQLite file/engine given this codebase's own synchronous job-wiring co-location rule (§4.1) - reproduced the resulting deadlock directly, fixed by giving the job store its own SQLite file. Also fixed a real, previously-latent bug the real scheduler exposed: `notifications.related_instance_id` had no `ON DELETE CASCADE`, so deleting an instance with any unresolved notification hard-failed. See the Stage 6 section below for full detail. 38 new tests |
| 7 | Calendar Sync | **Done** | `stage-07-calendar-sync` | OAuth connect/disconnect/list (`app/api/v1/routes/calendar_connections.py`), Fernet-encrypted token storage (new `oauth_tokens` table), Google + Outlook provider clients (real HTTP, never exercised in CI), stateless signed+expiring `state` param (no server-side row needed). Poll (`app.calendar_sync.service.sync_connection`): fetch/diff/upsert, §3.12 retention purge, §6.4 collision handling both branches, §3.9 `sync_conflict` auto-resolution. Wired `ExternalEvent` obstacles into `app.scheduling.adapter.gather_obstacles`/`has_fixed_conflict` for the first time (§7 filtering: transparent/all-day excluded) - Examples A and B now genuinely exercise a persisted `ExternalEvent` row rather than a bare fixture, and Example C is now end-to-end through the real poll path. Calendar-poll interval job wired into Stage 6's scheduler + startup reconciliation (a connection-scoped addition to §4.2's four items, since no connection could exist before this stage). 74 new tests. **Deferred, documented, not silently missing:** IRR-2 M6's `calendar_ids` selection and failed-sync notification/status field (Medium finding, not gating - see Stage 7 section below) |
| 8 | API Hardening & Backend E2E | **Done** | `stage-08-api-hardening` | Error-envelope/OpenAPI/throttling audit, plus four real contract gaps found and fixed (confirmed with the user before building each): `dismiss`, scoped `DELETE`, the previously-nonexistent `GET /task-instances` list/backlog endpoint, and `GET /task-templates/{id}` (found separately, needed by Stage 9's edit-existing-recurring-task flow). `app.scheduling.orchestration` gained `archive_template_and_cancel_jobs`, shared by `app.task_templates.service.archive_template` and `app.task_instances.service.delete_instance`'s `this_and_future` scope (independent siblings, can't call each other directly). **Deliberately deferred to its own follow-up PR:** architecture-plan §5.1's expected-values PATCH optimistic-locking mechanism - large and design-sensitive enough to warrant a focused PR of its own. 53 new tests. See the Stage 8 section below for full detail |
| 9 | Frontend | **Done** | `stage-09a`…`stage-09f` | 9a, 9b, 9c, 9d, 9e, 9f all done - see Stage 9 section below for full detail |
| 10 | Deployment & Packaging | **Done** | `stage-10-deployment` | Found and fixed a gap left over from Stage 0/9: `app.main` never actually mounted the built frontend (the `StaticFiles` mount was still a commented-out placeholder), so the production container served the API only despite the Dockerfile building and copying the frontend into the image. Added an SPA-aware static mount (falls back to `index.html` for client-side routes) plus an `AuthGuardMiddleware` exemption for static/SPA requests (auth stays fully enforced at the API layer). Verified with a real `podman-compose` build/boot/setup/login/create-task/confirm-scheduling/restart/confirm-persistence walkthrough. Dockerfile, `docker-compose.yml` (named volume, healthcheck, full §7.1 var set), and the CI image-build-and-smoke-test job were already in place from Stage 0 and needed no changes |
| 11 | Hardening & Release Readiness | **Done** | `stage-11-release-readiness` | Full regression run clean on a from-scratch clone (backend, frontend, Playwright e2e, container build+boot). Coverage review closed a real gap: `app/jobs/scheduler.py`'s `_dispatch` (the single chokepoint every background job fires through) was only proven to route one of seven job kinds correctly by a real APScheduler firing; the other six were only exercised via handler unit tests or scheduling-only wiring tests, never through the actual key-parsing dispatch logic. Also closed two untested `edit_template_this_and_future` branches (`not_found`, `invalid_recurrence_anchor`). Security pass closed a real, previously-deferred gap: `/docs`/`/redoc`/`/openapi.json` were unconditionally enabled (Stage 3 flagged this and explicitly deferred it here) - added `ENABLE_API_DOCS` (default `false`), verified both directions live. Non-Goals/Backlog audit and traceability spot-check found no scope creep and no drift. See the Stage 11 section below for full detail. |

*(Keep this table honestly current - it's the recovery point if work pauses and resumes later, or hands off to an LLM agent.)*

### Post-POC follow-ups

Items deferred by a stage above and picked up after `v0.1.0-poc`, oldest deferral first.

| Item | Deferred by | Status | Branch | Notes |
|---|---|---|---|---|
| This-and-future propagation of `fixed_time_of_day` and `deadline_offset_minutes` (design doc §3.10, §6.5, §6.7, §9.1, §14.1) | Stage 5 | **Done** | `claude/next-feature-implementation-0a5dpf` | `edit_template_this_and_future` now re-projects a non-detached live fixed instance's `scheduled_time` onto its own local date (statuses `scheduled`/`blocked`; `in_progress` is left alone because it is already underway). A collision is §6.5's hard block: `409 creation_conflict`, checked before the template write or any job call, so the whole edit is rejected. An offset change moves a non-detached flexible instance's `deadline` by the same delta, keeping its nominal date (§9.1). A still-valid slot is kept (incremental fit, §6.2); an invalidated one is evicted and re-placed; an elapsed deadline goes to `missed` through §6.7's gate. `missed` instances are skipped because §6.7 makes leaving `missed` user-driven. Both fields trigger on an actual value change, not on key presence, because the edit form resends every field on each save. Job wiring (architecture-plan §4.1): overdue/reminder jobs follow a retime, dropped reminder offsets are cancelled (`run_reminder` doesn't re-check timing), a blocked instance's dependency-at-risk job follows its new deadline, and a calendar-anchored template's occurrence-boundary job follows a `fixed_time_of_day`/`recurrence` change. **Latent bug fixed along the way:** a scheduled flexible instance that a this-and-future duration edit made unplaceable stayed `scheduled` in the database with its stale slot. `place_or_defer` only persists on success or `missed`, and this path never persisted the move to `pending`. It now evicts the instance the same way §6.4/§6.6 do. 20 new tests (service, job-wiring, route). |
| Series occurrence dates and explicit start date (design doc Rev 10: §3.2 `start_date`, §9.1 first occurrence, §6.2 earliest start) | Design doc Rev 10 | **Not started** | - | `POST /task-templates` requires `start_date` (`invalid_start_date` if before today); the first instance's `nominal_date` follows the §9.1 table instead of "one cadence after now"; every flexible occurrence, the first included, is gated at its `nominal_date` (today the first completion-anchored one is not). Creation form gains the start-date field. Worked Example O's Rev 10 paragraph is the acceptance fixture. |
| "This and future" reaches every open occurrence (design doc Rev 10: §3.10, §8.1; architecture-plan Rev 4 §3, §4.1) | Design doc Rev 10 | **Not started** | - | `edit_template_this_and_future` loops over the `from_instance` occurrence and every later non-terminal one (by `nominal_date`), validating all before writing any; `include_detached` flag; `from_instance` required. `GET /task-instances?template_id=`. Edit dialog names skipped occurrences and offers the checkbox. Worked Example M (both checkbox states) is the acceptance fixture. |

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
- `schedule_pending_flexible_tasks(candidates, ...)` - full §6.2: stable sort by `(deadline ASC, priority DESC)` (no topological sort - see H1 below), Pass 2 soft-budget override with the 3-key tie-break (overage → remaining slack → earliest date).
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
- [x] All tests above green.
- [x] Coverage gate met.
- [x] `mypy --strict` clean, zero `Any` in public signatures.
- [x] Zero `fastapi`/`sqlalchemy` imports anywhere under `scheduling_engine/`.

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

**Key modules/files:** `app/db/models/` (ORM), `app/db/schemas.py` (Pydantic domain objects - what repositories actually return/accept), `app/db/repositories/`, `app/db/base.py`/`session.py`, `alembic/versions/`. **Resolves Stage 0's "decide and document now, once" note**: Stage 0's own prose described `models.py`/`repository.py` living inside each feature module, but the `.importlinter` config it actually shipped with (`pyproject.toml`) already encodes a three-layer contract with `app.db` as its own bottom layer, separate from `app.task_templates`/`app.task_instances`/etc. The binding CI contract wins per this document's own authority rule (§0) - data access is consolidated under `app.db`, not scattered per feature module.

**Tests required**
- Migration test: fresh DB → `upgrade head` succeeds; `downgrade base` succeeds; round-trip.
- Repository CRUD tests per entity against a real test SQLite DB, including the §3.8 unlink-without-cascade case at the repository level.
- Constraint tests: invalid enum rejected, required-field omission rejected.
- import-linter `layers` contract extended and passing now that data layer has real code.

**Exit criteria**
- [x] Every entity migratable and round-trippable.
- [x] Repository suite green.
- [x] Layers contract passes.

---

### Stage 3 - Auth & Session Management

**Depends on:** Stage 2
**Design doc refs:** §3.6 (User schema, first-run setup wizard, password reset mechanism), §14.2 (auth mandatory, wraps entire app, public-route allowlist)
**Architecture doc refs:** §6 (argon2id, session cookie, setup token, throttling, `RESET_ADMIN_PASSWORD`), §6.1-§6.3 (cookie attributes, session lifetime, auth guard)
**Branch:** `stage-03-auth`

**In scope**

**Correction (superseding this section's original text):** this bullet list originally described a "single-user bootstrap" as a new decision this plan would have to invent, recommending a locked placeholder admin account unlockable via `RESET_ADMIN_PASSWORD`. That was written before IRR-2 finding B10/B10-token was decided and drafted into design doc §3.6 and architecture-plan §6 (Revision 9/Rev 3) - both source documents now specify a concrete mechanism (first-run setup wizard + setup token) that supersedes the placeholder-account idea entirely. Per this document's own authority rule (§0), the source docs win; built to that spec, not the stale recommendation below.

- `POST /api/v1/auth/setup` (§3.6, added Rev 9) - public only while zero `User` rows exist, `410 Gone` afterwards. Requires a setup token (`secrets.token_urlsafe(32)`, generated at startup while unconfigured, logged at `WARNING`, constant-time compared, held in memory only, invalidated on success). Username fixed as `admin`, 12-character minimum password.
- `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`; session-cookie issuance (`HttpOnly`, `SameSite=Lax`, `Secure` derived from `APP_BASE_URL` via `SESSION_COOKIE_SECURE=auto|true|false`), signed with `SECRET_KEY` (HMAC-SHA256, stdlib `hmac` - no new dependency), server-side session table (new `sessions` table, not one of design doc §3's seven entities).
- `argon2id` hashing/verification via `argon2-cffi`.
- Login rate limiting/throttling - **documented choice:** 5 failed attempts within 15 minutes locks out further attempts from that `client_ip:username` key; a success resets it immediately (`app/auth/throttle.py`).
- `RESET_ADMIN_PASSWORD` mechanism exactly per §3.6: one-time consumption via a DB marker row (new `admin_password_reset_marker` table, not a file), warning logged (not re-applied) if the same value persists across restarts; a changed value is honored as a new reset; all sessions for the user revoked on any reset.
- Auth guard: default-deny middleware with an explicit public allowlist (`/health`, `POST /auth/setup`, `POST /auth/login`) per architecture-plan §6.3 - not per-endpoint dependencies.

**Out of scope:** 2FA, SSO, multi-user (Backlog 12.17); OAuth calendar auth (different credential type, Stage 7); disabling `/docs`/`/redoc`/`/openapi.json` by environment (architecture-plan §6 lists this, but implementation-plan never scheduled it for this stage - deferred to Stage 11. The auth guard already blocks unauthenticated access to them in every environment, which is the harm the environment toggle exists to prevent; the toggle itself is defense-in-depth on top of that).

**Key modules/files:** `app/auth/` (passwords, setup token, throttle, cookie signing, service orchestration - framework-agnostic, imports no FastAPI), `app/api/middleware.py` (guard), `app/api/errors.py` (error envelope), `app/api/v1/routes/auth.py`, `app/db/models/session.py` + `admin_password_reset_marker.py`.

**Tests required**
- Integration: correct cookie flags on success; wrong password rejected; throttling triggers after N attempts and resets appropriately; logout invalidates the session.
- `RESET_ADMIN_PASSWORD`: two consecutive simulated "restarts" with the same value - second must NOT reset, must warn-log; a changed value on a third restart DOES reset.
- Auth guard: unauthenticated request to a protected route → 401; authenticated → passes. Enumerates every registered route (including ones added via `include_router`, which a naive `app.routes` walk silently misses on this FastAPI version - see the comment on `_iter_api_routes` in `test_auth_routes.py`) and asserts each is allowlisted or guarded.
- Setup-token tests: missing/wrong/already-consumed token all rejected; token absent from the success response body; a restart issues a different token.

**Exit criteria**
- [x] All tests green.
- [ ] Cookie attributes manually confirmed once in real browser dev tools (automated later via Playwright, Stage 9) - **not done by this stage's implementation; needs a human with a browser**, tracked here rather than silently skipped.

---

### Stage 4 - User Settings

**Depends on:** Stage 3
**Design doc refs:** §3.7 (UserSettings), §14.1 (timezone default from `TZ`)
**Architecture doc refs:** §3 (`/settings` resource), §7.1 (`TZ` var)
**Branch:** `stage-04-settings`

**In scope**
- `GET`/`PATCH /api/v1/settings` (singleton, single-user POC).
- Default row created on first run (at app startup, alongside Stage 3's setup-token/`RESET_ADMIN_PASSWORD` bootstrap - not lazily on first `GET`, so the row is guaranteed to exist by the time any request is handled); `timezone` defaulted from container `TZ`, falling back to UTC (with a startup warning) if `TZ` is unset or not a real IANA name.
- **Gap not covered by either source doc, resolved with the user:** neither design doc §3.7 nor architecture-plan states a default `active_hours` for a freshly-created row. This matters more than a typical default gap - a per-day `null` means *excluded* (§3.2/§3.7), so "every day null" would silently prevent any flexible task from ever being scheduled until the user visits Settings. Confirmed with the user: every day defaults to `09:00-17:00`. `daily_time_budget_minutes` defaults to `null` (unlimited) for every day and `blackout_dates` to `[]` - both the uncontroversial "no constraint yet" neutral state for their respective shapes, not treated as needing the same sign-off.
- Validation: real IANA timezone name; `budget_enforcement` enum; `active_hours`/`daily_time_budget` shape (7 valid day keys, `null` allowed).
- `first_day_of_week` stored as specified - display-only. Prove it, don't just assert it (see test below).

**Out of scope:** anything reading these settings for actual scheduling - that wiring is Stage 5. The regression-guard test below calls Stage 1's `find_first_free_slot` directly with a test-local translation from `UserSettings.active_hours` into the engine's `ActiveHoursMap` - that translation is test code proving the invariant holds, not the Stage 5 wiring itself.

**Key modules/files:** `app/settings/` (service layer - default creation, validation), `app/api/v1/routes/settings.py`.

**Tests required**
- CRUD/validation integration tests (bad timezone rejected, bad enum rejected, valid partial PATCH succeeds).
- **Regression guard:** two `UserSettings` identical except for `first_day_of_week`, fed through Stage 1's engine functions directly, produce identical output - proves display-only in code, guards against a future "helpful" regression.

**Exit criteria**
- [x] Tests green.
- [x] §7.1 table still accurate (added `tz` to `app.core.config.Settings` - `TZ` itself was already documented and in `.env.example` since Stage 0).

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

**Architecture decision made during this stage:** `task_templates`/`task_instances` are independent siblings by import-linter's layering contract and must not import each other, but both need identical DB-aware placement/generation logic (`app.scheduling.adapter`, `app.scheduling.orchestration`). Rather than duplicate it or weaken the contract, added a new shared tier - `app.scheduling` - between the sibling group and `app.db`, mirroring `app.db`'s existing role as a shared foundation. Also added to the "Scheduling engine stays pure" contract's forbidden-imports list, since it is DB-aware and must never be importable from `scheduling_engine/`.

**Explicitly deferred to a later stage (not silently missing):**
- `POST /task-instances/{id}/dismiss` ("skip this occurrence", §3.8) - not built this stage. A completion-anchored template's dismiss-must-generate-successor rule (§3.9) depends on the completion-triggered generation call, which architecture doc §9.1 assigns to Stage 6.
- `DELETE /task-instances/{id}?scope=this_occurrence|this_and_future` - only unscoped delete exists (§3.8's simple case). The `this_and_future` deletion scope needs template-level state Stage 5 doesn't otherwise touch; revisit alongside Stage 6's generation wiring.
- This-and-future propagation (`edit_template_this_and_future`) updates the live instance's `name`/`description`/`location`/`priority`/`estimated_duration_minutes` only. `fixed_time_of_day` re-projection and `deadline_offset_minutes` deadline recomputation are **not** propagated - neither is exercised by a Stage 5 required test, and both need real conflict/re-placement handling to do properly rather than half-implement silently. **Resolved post-POC** - see "Post-POC follow-ups" below.
- `creation_conflict` is a synchronous rejection at creation/reschedule time only (Example A) - it is never persisted as a `Notification` row, matching the design doc's "no TaskTemplate and no TaskInstance are created" outcome.

**Out of scope:** anything touching real APScheduler, any periodic/background trigger, calendar sync.

**Key modules/files:** `app/task_templates/`, `app/task_instances/`, `app/notifications/`, `app/scheduling/` (new shared tier, see architecture decision above).

**Tests required**
- Unit: edit-scope/detach resolution encoding **Worked Examples L and M** exactly.
- Unit: recurring-generation function - a detached instance's overrides never leak into the next generated instance.
- Integration: full CRUD + every §4 status-lifecycle edge case; **Example D** (dependency deletion → downstream unblocks, upstream survives); **Example K**'s transition half (inline gate firing on an already-past-deadline creation); **Example F**'s "complete directly from non-`in_progress`" half.
- Integration: cycle rejection (`cycle_detected`); infeasible-duration rejection (`infeasible_duration`) for both template creation and a this-occurrence override.
- Integration: dependency-removal unlink semantics at service level (distinct from Stage 2's repo-level test - this one verifies the `blocked→pending` side effect too).
- Notification self-resolution: table-driven test walking §5 row by row, asserting each trigger is checked where this stage claims, and explicitly listing what's deferred.
- Job-wiring **stub** tests: correct stub calls for every mutation path (create/this-occurrence-edit/reschedule/delete/complete/extend-deadline/this-and-future-propagation).

**Exit criteria**
- [x] All tests green, including Examples D, F(partial), K, L, M.
- [x] Every §5 notification type has a passing *creation*-trigger test; deferred resolution triggers explicitly listed, not silently missing (see `tests/integration/notifications/test_service.py`'s ownership table).
- [x] Coverage ≥ 80% (95.54% overall this stage; `mypy app`, `ruff`, both import-linter contracts, all clean).

---

### Stage 6 - Background Jobs, APScheduler Adapter & Startup Reconciliation

**Depends on:** Stage 5
**Design doc refs:** §6.3, §6.6, §6.7 (periodic half), §9 (job list), §9.1 (completion trigger)
**Architecture doc refs:** §4 (job breakdown), §4.1 (real adapter + job-wiring tests), §4.2 (reconciliation)
**Branch:** `stage-06-jobs`

**In scope**
- Real `app/jobs/` APScheduler adapter (`schedule_at()`, `cancel()`, `schedule_interval()`), SQLAlchemy-backed persistent store.
- Swap every Stage 5 stub for the real adapter call - **call sites shouldn't need to change**; if they do, that's a sign Stage 5's interface was wrong, fix it there. (True in practice - reminder/overdue/deadline-elapsed call sites from Stage 5 were untouched.)
- Reminder job (one-off, rescheduled on every relevant mutation), dependency-at-risk job (§6.3, `deadline - 3d`), overdue job (§6.6, fixed vs. flexible branching exactly as specified), deadline-elapsed job + periodic sweep (§6.7, second safety net alongside Stage 5's inline gate).
- Recurring-generation hook: fires on transition to `completed`, calls Stage 5's generation function.
- **Correction to this section's original scope:** also built the **calendar-anchor** recurring-generation trigger (the one-off occurrence-boundary job architecture-plan §4's job breakdown table lists as a *separate* mechanism from the completion trigger, added in that doc's own Rev 3 as "the single highest-impact defect IRR-2 found"). The original bullet above named only the completion trigger; omitting the calendar-anchor one would have re-shipped that exact defect at the implementation layer. Wired into `create_template` (schedules the first boundary job), `archive_template` (cancels it), and reconciliation item 3.
- External-poll job scaffolding (interval-based) - mechanism only (`schedule_interval()` built and tested directly), Stage 7 supplies the fetch logic and the actual wiring.
- Startup reconciliation (§4.2): all four items - recreate missing jobs, cancel stale ones, reconcile occurrence-boundary jobs (item 3), run missed §6.9 unblocks (item 4) - run once before serving traffic.

**Findings from this stage, not assumed going in:**
- **architecture-plan's shared-SQLite-file assumption for the job store does not hold.** §4 calls the job store sharing the app's own file "should be fine (SQLite WAL mode), but verify explicitly" - doing that verification (not just inspection) found a genuine deadlock: §4.1 requires every mutation to co-locate its DB write and job call in one synchronous method, so a job-store write routinely happens on a second connection while the triggering request's transaction is still open on the first. WAL mode only relaxes reader-vs-writer contention, not writer-vs-writer, and SQLite's `busy_timeout` cannot fix a genuine circular wait - it only turns an instant failure into one that hangs for the full timeout, confirmed by direct reproduction. Fixed by giving the job store its own SQLite file (`app.db.session.jobs_database_path`) - two files means two independent lock domains. `busy_timeout` (5s) is still set on both, as normal SQLite hygiene, not as the fix.
- **Found and fixed a real, latent bug**, exposed (not caused) by the real scheduler actually firing a job mid-test for the first time: `notifications.related_instance_id` had no `ON DELETE CASCADE`. Deleting any `TaskInstance` with an unresolved notification (overdue, unschedulable, ...) hard-failed with a bare FK error - previously invisible because `NoOpJobScheduler` never actually created one. A `Notification` has no meaning once its instance is gone (contrast `task_instance_dependencies`' deliberate unlink-not-cascade for dependency edges, §3.8), so this cascades. New migration `a880890c42ea`.
- Refactored the "promote a blocked instance if unblocked" check (previously duplicated across `complete()` and `delete_instance()`) into one public `task_instances.service.promote_if_unblocked()`, reused by reconciliation item 4. This also fixed a real pre-existing bug in `delete_instance()`'s own copy: it checked "does this instance have zero remaining dependency links" rather than "are all remaining dependencies completed", so deleting one of several dependencies while another was already-completed-but-still-linked failed to unblock.

**Explicitly still deferred (unchanged from Stage 5, reaffirmed rather than silently dropped):** the `dismiss` endpoint and `DELETE ...?scope=` remain unbuilt - neither is required by anything this stage's reconciliation or job-wiring work touches, and implementation-plan's own Stage 6 scope never named them. Revisit alongside Stage 8's API-contract finalization.

**Out of scope:** the actual calendar-fetch logic (Stage 7).

**Key modules/files:** `app/jobs/` (`interface.py`, `handlers.py`, `scheduler.py`, `reconciliation.py`).

**Tests required**
- Job-wiring integration tests per mutation path (`tests/job_wiring/`) - dependency-at-risk job on blocked creation, occurrence-boundary job on recurring calendar-anchor creation (and its absence for `one_time`/`completion`-anchor), successor-job-wiring on completion-anchor `complete()`, occurrence-boundary cancellation on archive.
- Real-adapter tests (`tests/integration/jobs/test_scheduler.py`) - a due job actually fires and runs its handler, `cancel` prevents the side effect, `cancel_all_for_instance` cancels only the right jobs, `schedule_interval` registers with the right cadence and replaces on re-schedule.
- Handler-behavior tests (`tests/integration/jobs/test_handlers.py`) - what each job does when it fires: reminder notification creation, overdue's fixed/flexible branch, deadline-elapsed one-off + periodic sweep (including the blocked-instance case the one-off never reaches), dependency-at-risk's notification + dedup, occurrence-boundary's generation + self-rescheduling + archived-template no-op.
- Reconciliation tests (`tests/reconciliation/`): simulate a killed process by writing inconsistent state directly via repositories (bypassing the normal service-layer mutation paths), assert the startup pass restores consistency for all four §4.2 items, plus an idempotency test (running it twice is harmless).
- **Worked Example C's non-sync-eviction overdue path** is exercised via the overdue handler tests above (the full calendar-triggered eviction half is Stage 7's).

**Exit criteria**
- [x] All job-wiring tests green for every mutation path this stage touches.
- [x] Reconciliation tests green (all four §4.2 items, plus idempotency).
- [ ] Manual check: kill `docker compose` mid-scenario, restart, confirm no orphaned/missing jobs via the job store directly. **Not performed in this environment** (no running deployment to kill) - the automated reconciliation suite exercises the same restore-consistency guarantee against directly-written inconsistent state, but a real container-kill verification is recommended before POC release (Stage 11).

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

**Findings from this stage, not assumed going in:**
- **§3.5's "reference to secret storage, not raw tokens in this table" needed a real table to point at**, which neither source doc names. Added `oauth_tokens` (new migration) - `id`, Fernet-encrypted `encrypted_access_token`/`encrypted_refresh_token`, `access_token_expires_at`, timestamps - keyed by `ExternalCalendarConnection.oauth_credentials_ref`. Same category of implementation-level addition as Stage 3's `sessions`/`admin_password_reset_marker` tables.
- **The OAuth `state` parameter (architecture-plan §6, mandatory) doesn't need server-side storage.** It's HMAC-signed and time-limited (`app.calendar_sync.oauth_state`, 10-minute window), bound to the initiating session id and provider - the same stateless-signing pattern `app.auth.cookie_signing` already uses for the session cookie. This also carries the connect flow's one caller-supplied setting (`refresh_interval_minutes`) through the provider's redirect round trip without a second lookup.
- **The callback is a plain `GET`, not routed through a POST-only mutation**, despite architecture-plan §6.1's "no state-changing endpoint may be exposed over `GET`" rule - the callback's own mandatory, session-bound, signed `state` parameter is exactly the per-request unguessable-token property that rule exists to substitute for, and the callback cannot be anything but a `GET` (it's the provider's own redirect). Documented inline in `app/api/v1/routes/calendar_connections.py` rather than left as an unexplained exception.
- **§6.2/§6.5 needed external obstacles for the first time.** `app.scheduling.adapter.gather_obstacles`/`has_fixed_conflict` (Stage 5) only ever gathered `TaskInstance` rows - Stage 5's own docstring said as much ("External-calendar obstacles are Stage 7's concern"). This stage adds `gather_external_obstacles`, filtered per §7 (transparent/all-day excluded), feeding both functions. Consequence: Worked Examples A and B (§10) now genuinely exercise a persisted `ExternalEvent` row instead of a bare `Obstacle` fixture, for the first time since Stage 1.
- **`sync_conflict` auto-resolution (§3.9) needed a trigger from two independent, non-importable siblings** - the poll (`app.calendar_sync.service`) when the event moves/is removed, and a manual fixed-instance reschedule (`app.task_instances.service.reschedule`) when the user moves clear of it. Added `resolve_cleared_sync_conflicts` to the shared `app.scheduling.orchestration` tier both siblings already sit below, rather than duplicating the check.
- **The calendar-poll interval job needed a fifth reconciliation item.** Stage 6's architecture-plan §4.2 four items predate `ExternalCalendarConnection` existing at all - `_reconcile_calendar_poll_jobs` (same idempotent `schedule_interval`-replaces-existing pattern as items 1-3) keeps every enabled connection's poll job alive across a restart and cancels it for a disabled one.
- **Google and Outlook clients are real, not stubs** (`app/calendar_sync/providers/google.py`/`outlook.py`, plain `httpx` calls) - they are simply never exercised in CI, per implementation-plan's own instruction. A `MockCalendarProvider` test double is what every automated test drives instead.

**Out of scope:** write access (Backlog 12.4), webhooks (Backlog 12.5). Also still deferred, per IRR-2 M6 (Medium, non-gating): a `calendar_ids` selection on `ExternalCalendarConnection` (a connected account may have several calendars; POC syncs the primary one only) and a failed-sync notification/status field - neither blocks anything this stage's own scope names, revisit alongside Stage 8.

**Key modules/files:** `app/calendar_sync/`.

**Tests required**
- OAuth flow against a **mocked** provider (never a real one in CI).
- Token encryption round-trip.
- Filtering unit tests: transparent event excluded from obstacles; all-day event visible but non-blocking.
- Collision integration tests, both §6.4 branches.
- **Worked Example C, full version**, now genuinely end-to-end.

**Exit criteria**
- [x] All tests green (74 new tests: token crypto round-trip, OAuth `state` signing, Google/Outlook event-parsing, provider registry, OAuth token repository CRUD, `ExternalEvent` retention purge, external-obstacle filtering + Examples A/B end-to-end, calendar-sync service poll/collision/resolution, calendar-connection routes, job-wiring, job-handler, reconciliation, `reschedule`'s `sync_conflict` resolution, and Example C full end-to-end).
- [ ] Manual smoke test against a real personal calendar in dev (not CI). **Not performed in this environment** (no operator-registered Google/Outlook OAuth app credentials or reachable `APP_BASE_URL` available here, same category of gap as Stage 6's container-kill check) - the mocked-provider test suite exercises the same OAuth/token/poll/collision code paths against a fake upstream, but a real-account smoke test is recommended before POC release (Stage 11).

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

**Corrections to this section's original framing - confirmed with the user before building, not assumed:** the audit surfaced three real contract gaps, each explicitly deferred to "Stage 8" by name from an earlier stage or documented in architecture-plan §3/§124 but never scheduled anywhere:
- `POST /task-instances/{id}/dismiss` (§3.8) and `DELETE /task-instances/{id}?scope=this_occurrence|this_and_future` (§3.8) - explicitly deferred here by both the Stage 5 and Stage 6 sections above. Built: `dismiss()` (terminal `dismissed` status, cancels all jobs, resolves `overdue`/`unschedulable`/`deadline_missed` notifications, dependents stay `blocked`, generates a `now + cadence`-anchored successor for a `completion`-anchored template) and scoped `delete_instance()` (`scope` required for a recurring template's instance, optional/ignored for `one_time`; `this_and_future` archives the template via a new shared `archive_template_and_cancel_jobs` in `app.scheduling.orchestration` - `app.task_templates`/`app.task_instances` are independent siblings under the layering contract, so this couldn't be a direct call into `app.task_templates.service.archive_template`).
- `GET /task-instances` (list with `status`/`priority`/`type` filters, plus `?view=backlog` per architecture-plan §124 Rev 3) - documented as part of the core API contract but never scheduled in any stage's "In scope" bullets, not even as deferred. Built at the repository layer (`TaskInstanceRepository.list_filtered`, real `WHERE` constraints, not in-memory filtering) with the Backlog view composed from `blocked`/`missed` instances plus `pending` instances carrying an active `unschedulable` notification.
- `GET /task-templates/{id}` - a fourth gap, found while answering "what's left before Stage 9 can start" post-review: the task edit form (design doc §8.1 screen 3) needs to load an *existing* recurring template's current state (`recurrence`, `active_hours_override`, etc.) before it can prompt for edit scope, and no endpoint could return a template outside of a create/patch/archive response. Returns an archived template rather than 404ing - §3.8 keeps the row specifically so `template_id` references stay valid. `GET /task-templates` (list) and `GET /task-instances/{id}` (single) were considered and deliberately not added - no §8.1 screen needs the former, and the list endpoint above already covers the latter at POC scale.
- **Deliberately NOT built, left for a dedicated follow-up PR:** architecture-plan §5.1's "expected-values PATCH" optimistic-locking mechanism (`409 Conflict` with a client-supplied `expected` map naming the fields being changed, set-comparison semantics for `dependencies`/`reminder_offsets_minutes`, an omitted-vs-null sentinel on the wire). The ORM-level `version_id_col` plumbing already exists (Stage 2); the PATCH-level `expected` comparison, the `conflict` error code, and the four numbered semantic requirements §5.1 lists do not. Confirmed with the user that this is large and design-sensitive enough to deserve its own focused PR rather than being folded into this one.

**Tests required**
- Backend E2E (API-level, no browser): login, create-with-conflict, create-flexible-and-schedule, complete-task, extend-a-missed-deadline, edit-a-recurring-task-both-scopes-and-verify-detach.
- Error-envelope contract test: one per distinct code (`cycle_detected`, `creation_conflict`, `infeasible_duration`, `sync_conflict` shape, generic validation).
- `cycle_detected` has no HTTP-reachable trigger in the current API surface - dependencies are only ever set at creation, and a brand-new node cannot itself close a cycle through creation alone. Its contract test asserts the mechanism directly against the service-layer helper `create_template` shares (already built in Stage 5); documented, not silently skipped.

**Exit criteria**
- [x] Full backend suite (all stages) green in one CI run - 460 passing (53 new this stage).
- [x] Coverage ≥ 80% overall (94.28%), ≥ 90% `scheduling_engine/` maintained (100%, unchanged - this stage never touches it).
- [x] OpenAPI spot-checked - every design-doc §3 field name present verbatim on `TaskInstance`/`TaskTemplate`, `scope`/`status`/`priority`/`type`/`view` query params correctly typed as enums/nullable.

---

### Stage 9 - Frontend (React)

**Depends on:** Stage 8 - building UI against a moving API wastes rework.
**Design doc refs:** §8 (full UI scope), §9.2 (virtual/ghost projections)
**Architecture doc refs:** §1 (React/Vite/FullCalendar); **frontend-design skill is a hard prerequisite before any sub-stage below**
**Branch:** `stage-09a` … `stage-09f`, each individually gated

**Decision to make explicitly (not specified by either source doc):** where virtual/ghost projections (§9.2) are computed - client-side from the template's recurrence pattern, or served by a small read-only backend endpoint. Either is valid; pick one in 9d and document why, don't leave it implicit.

**9a - App shell, routing, API client, Login** (§8.1 screen 1) - **Done**
Tests: login form component states (success/failure), mocked-API integration, one real Playwright test against the live Stage 8 backend.

**As built:** wrote `frontend/DESIGN.md` first (color/spacing/type tokens as CSS custom properties in `src/styles/tokens.css`, component conventions) per this section's hard-prerequisite note - no external design system for the POC.

**Real backend contract gap found and fixed, confirmed with the user before building** (same category as Stage 8's mid-stage gaps): design doc §8.1 screen 0 requires every screen to redirect to first-run setup while zero `User` rows exist, but no endpoint told the frontend which case it was in - `GET /auth/me` returned the same `401 unauthenticated` whether no account existed yet or one existed and this browser just wasn't logged in. Fixed at the source the user pointed at (the backend, not client-side inference): `AuthGuardMiddleware` now checks the already-existing in-memory `setup_token_store.is_active` flag (issued/invalidated exactly when the `User` count is/isn't zero - no new DB query) before its normal routing, and rejects every route except `GET /health`/`POST /auth/setup` with a new `setup_required` (403) code - including `POST /auth/login`, which must not work pre-setup either, since there is nothing to log into yet. `SETUP_ALLOWED_ROUTES` in `backend/app/api/middleware.py`. Required updating several existing route test files' `test_requires_authentication` tests to complete setup first (otherwise they now observe `setup_required` instead of the `unauthenticated` they were actually testing for) - not a behavior regression, a test-precision fix once the two states became distinguishable.

Frontend auth flow: `AuthContext` exposes a `status` of `loading | setup_required | unauthenticated | authenticated`, resolved from one `GET /auth/me` call on load; `RouteGuard` redirects to whichever screen the current status belongs on. Deliberately **not** using React Router navigation state to hand off the post-setup "Account created" message to the login screen - an early version did, and it raced RouteGuard's own status-driven redirect (two competing navigations to `/login`, one with state and one without, non-deterministic which wins). Fixed by adding a small `justCompletedSetup` flag directly on `AuthContext` instead, set alongside the status transition it depends on.

One real Playwright test file (`frontend/e2e/login.spec.ts`) boots the actual Stage 8 backend (`alembic upgrade head` then `uvicorn`, mirroring `docker/entrypoint.sh` exactly - a fresh SQLite file has no schema until migrations run, which the existing pytest fixtures paper over by calling `Base.metadata.create_all` directly) against a temp SQLite file, captures the real startup-logged setup token from the process's stdout/stderr, and drives setup → login → logout through a real Chromium instance. New CI job `e2e` (`.github/workflows/ci.yml`) installs both toolchains and runs it after `backend`/`frontend` pass. 5 new backend tests (`TestSetupGuard`), 12 new frontend unit tests, 4 Playwright tests.

**Fixed post-merge, at the start of 9b:** the login e2e suite was observed flaky in CI (one of the two duplicate `push`/`pull_request` runs failed - see [PR #12](https://github.com/EnthusiastDeveloper/Tessera/pull/12)). Root cause was self-inflicted: `test.describe.serial` + `retries: 1` means a failure anywhere replays the *whole* group from its first test, and the first test asserted "zero accounts exist," which stopped being true the moment a later test in the same group had already completed setup. Fixed by merging the one-time zero-accounts-to-one-account transition into a single atomic test and disabling retries for that file specifically, rather than papering over it with a longer timeout.

**9b - Task creation/edit form** (§8.1 screen 3) - **Done**
Scope prompt for recurring non-one-time tasks, `active_hours_override` input, `infeasible_duration` surfacing, archival/deletion confirmation (§8.2).
Tests: per form state (one-time vs. recurring), explicit test that the scope prompt is *absent* for `recurrence: one_time`.

**As built:** `TaskForm` (`frontend/src/views/tasks/`) serves both create and edit, branching on design doc §3.10's field table rather than guessing at it per-field: a one-time template's edit goes straight to `PATCH /task-templates/{id}?scope=this_and_future` (no prompt - there's no "future" to distinguish); a recurring template's edit shows `ScopePrompt` (`this_occurrence` vs `this_and_future`, shared verbatim with the delete flow) and the form hides every template-only field (recurrence, `fixed_time_of_day`, reminders, active-hours override) the moment `this_occurrence` is chosen, since none of them apply to a single instance and showing them would silently no-op. `this_occurrence` submits to `PATCH /task-instances/{id}` instead, including converting the UI's string `priority` enum to the numeric value that endpoint expects (design doc §3.2's `low=1..critical=4` mapping) - the two endpoints disagree on priority's wire type and the form is what reconciles it.

Duration entry (§8.1a) is a small standalone module (`frontend/src/lib/duration.ts`, not React) precisely because the round-trip requirement ("formatting a stored value and re-parsing it must yield the same integer") needed its own direct unit test independent of any component - `minutesToDuration`/`durationToMinutes` are exact inverses by construction (always picks a unit that divides the stored minutes evenly, falling back to the smallest allowed unit as a decimal rather than a unit that would lose precision), and a separate `formatDurationCompact` handles the read-only greedy display case (`4320` → "3 days", `90` → "1h 30m") the doc gives as its own explicit example.

Deletion (§3.8/§8.2) is unified on `DELETE /task-instances/{id}` for the same reason Stage 8 built it that way - `scope: this_and_future` already archives the template as part of deleting the instance, so there's no separate "archive the template but keep the current instance" button; no §8.1 screen calls for one. `DeleteTaskDialog` fetches the full instance list once to compute a dependents count for §3.8's informational notice ("N task(s) depend on this...") - there is no dedicated endpoint for it, the same POC-scale simplification Stage 8 used to justify not adding a single-instance `GET`.

**Deliberately deferred, not silently missing:** `active_hours_override`'s per-day `time` inputs don't yet account for the user's configured IANA timezone display (Settings/9f isn't wired in yet) - browser-local wall-clock is used as an interim POC simplification, matching how `datetime-local` inputs work generally; revisit once 9f's settings context exists. Dependencies (`CreateTemplatePayload.dependencies`) are create-only in the UI, matching the backend - there is no endpoint to edit them after creation (design doc §3.2's own note), so the edit form doesn't attempt to expose them. 7 new frontend unit tests (`TaskForm`) plus 30 for the duration module, 1 new Playwright test (`tasks.spec.ts`, ordered after `login.spec.ts` by filename - documented in-file, since the shared backend's one-time setup transition is `login.spec.ts`'s alone to perform).

**9c - Task detail view** (§8.1 screen 4) - **Done**
Status/history, dependencies-with-status, `detached` indicator, mark-complete/in-progress/reschedule/extend-deadline.
Tests: per status/action-availability combination; `detached` indicator visibility rule.

**Real backend contract gap found and fixed** (same category as Stage 8's and 9a's mid-stage gaps): the design doc's state diagram (§4, "user marks 'in progress' (optional step)") and this section's own bullet list both call for a mark-in-progress action, but no endpoint or service function existed anywhere to perform the `scheduled` → `in_progress` transition - confirmed by grepping the whole backend. Added `POST /api/v1/task-instances/{id}/start`, mirroring `dismiss`'s route/service shape exactly. Unlike `dismiss`/`complete`, `start_progress` takes no `jobs` parameter and the route takes no `JobScheduler` dependency at all: the reminder and overdue-check handlers (`backend/app/jobs/handlers.py`) already treat `in_progress` identically to `scheduled`, so the transition is a pure status/`status_history` write with nothing to co-locate - `app.notifications.service.dismiss` (a different, pre-existing `dismiss`) was the precedent found for a job-free mutation omitting the parameter entirely rather than taking an unused one. Valid only from `status == "scheduled"`, the diagram's only inbound edge; otherwise `invalid_field`. 7 new backend tests (3 service-layer, 3 route-layer, 1 job-wiring no-op assertion confirming the call touches no job-store state).

**As built:** `TaskDetailPage` (`frontend/src/views/tasks/TaskDetailPage.tsx`) follows `EditTaskPage`/`DeleteTaskDialog`'s established pattern for a POC-scale detail screen with no single-instance `GET`: fetches the full instance list once via `listInstances()` and finds the match client-side. That same list supplies both dependency directions design doc Example D calls for - forward (`instance.dependencies` ids resolved against the list for name/status) and reverse "blocking" (a scan for any instance whose `dependencies` array contains this one) - without a second endpoint. Five actions are each gated to match the service layer's own validation exactly, not a looser or stricter client-side guess: mark complete and skip-this-occurrence from any non-terminal status, mark-in-progress only when `scheduled`, reschedule only when `type === 'fixed'` (no status restriction, mirroring `reschedule()`'s actual check), extend-deadline only when `missed`. Reschedule/extend-deadline use a small inline `datetime-local` form (the same `toDatetimeLocal`/`fromDatetimeLocal` pair `TaskForm.tsx` already uses for its own absolute-instant deadline field) rather than a new date-picker component. `frontend/src/api/taskInstances.ts` gained `completeInstance`/`dismissInstance`/`startInstance`/`rescheduleInstance`/`extendDeadline` - `dismissInstance` in particular closes a gap where the backend's `dismiss` endpoint (built in Stage 8) had no frontend client function at all yet.

**Scope note, flagged for a human decision:** `App.tsx`'s `backlog` route carried a stale `ComingSoon` note ("Built in Stage 9c") left over from an earlier draft, but this section's own bullet list never mentioned the Backlog view (§8.1 screen 5a) - it isn't assigned to any lettered 9a-9f sub-stage anywhere in this plan. Building it here would have been exactly the unscoped "while you're in there" addition CLAUDE.md's Common Pitfalls warn against, so it was deliberately **not** built; the stale note was corrected to `"Not yet scheduled - see implementation-plan.md."` instead. Someone should decide which stage owns it before it's needed.

11 new frontend unit tests (`TaskDetailPage`, covering terminal-status action suppression, per-status action availability, `detached` visibility both ways, dependency/blocking rendering, and an in-place status update after a mutating action), 1 new Playwright test (`task-detail.spec.ts`, ordered after `login.spec.ts` by filename per the existing convention - creates a task, navigates to its detail view by id captured from the create response since no Timeline list view exists yet to click through, marks it complete, asserts the button set updates).

**9d - Timeline view** (§8.1 screen 2, §9.2) - **Done**
FullCalendar, real `scheduled` instances, virtual projections (visually distinct, read-only), external busy-blocks, blackout dates.
Tests: virtual occurrences non-interactive (no click-through to edit), visual-distinction assertion (class/style presence, not pixel diffing), correct 30-day horizon.

**Decision made (§9.2 projection computation):** server-side, not client-side. §9.2 requires the projection to "agree with 9.1's real generator, or the Timeline actively lies to the user" - the real generator's recurrence-advance math (`_next_nominal_instant`/`_advance`/`_next_weekday_on_or_after`/`_add_months`/`project_fixed_time` in `backend/app/scheduling/generation.py`) is `zoneinfo`-based and already handles the DST/weekday/month-day edge cases design doc §14.1 requires; reimplementing it in TypeScript would be a second, drift-prone copy of genuinely tricky logic, and this codebase's own stated philosophy (`UTCDateTime`'s docstring in `app/db/base.py`: "fix it once, centrally") argues against it. `generation.py` gained `project_virtual_occurrences`, calling the existing private helpers directly rather than re-deriving them, plus a new `VirtualOccurrence` dataclass (deliberately not a stub `TaskInstance` - no `id`, never persisted). New route `GET /task-templates/projections` (`backend/app/api/v1/routes/task_templates.py`, registered *before* `/{template_id}` so `"projections"` is never captured as a path param) delegates to a new `app.task_templates.service.list_virtual_occurrences`, which fetches every non-archived template plus its most-recent instance (`TaskInstanceRepository.list_by_template`, most-recent-first, index 0 - the same pattern `app.jobs.reconciliation`/`app.jobs.handlers` already use) and hands both to `project_virtual_occurrences`. The completion-anchor "already past nominal date" rebase (§9.2, design doc Example O: ghosts must not "pile up in the past") is its own isolated helper (`_completion_projection_base`) specifically so it has a direct unit test independent of the projection loop.

**Real backend contract gap found and fixed** (same category as Stage 8's/9a's/9c's mid-stage gaps): `ExternalEventRepository` has existed since Stage 7 and the scheduler has read the cache internally since then (`app.scheduling.adapter.gather_external_obstacles`), but no route ever exposed `ExternalEvent` rows to a client at all - confirmed by grepping the whole backend. This stage's own "external busy-blocks" requirement needed one. Added `GET /api/v1/external-events` (`backend/app/api/v1/routes/external_events.py`, a new small router - `ExternalEvent` is its own aggregate spanning every connection, same reasoning `/task-instances` isn't nested under `/task-templates`), backed by a new `app.calendar_sync.service.list_display_events`. Deliberately **not** reusing `gather_external_obstacles`'s filter predicate, despite reusing its connection-iteration pattern: §7 excludes both transparent *and* all-day events from the *obstacle* set, but all-day events are explicitly "imported and shown on the Timeline ... as display-only overlays" for *display* - so `list_display_events` excludes only `is_transparent` and passes `is_all_day` through so the frontend can render the distinct non-blocking overlay category §7 describes. A code comment on `gather_external_obstacles` itself cross-references this so a future reader doesn't assume the two filters should match.

**View choice:** `timeGridWeek` as the default FullCalendar view (`@fullcalendar/react`/`core`/`daygrid`/`timegrid`, pinned to the 6.1.x line - the newer 7.x line pulls in an experimental `temporal-polyfill` peer dependency not worth the risk for a POC), not `dayGridMonth`. The app's entire value proposition (design doc §6.2) is precise *time* placement inside active-hours windows on a 15-minute grid; a month grid shows which day a task landed on but not when. `dayGridMonth` is kept one click away via FullCalendar's own header toolbar specifically because §9.2's ghost horizon is 30 days - a week view alone would need several manual page-forwards to see the whole horizon at a glance. Justified against `frontend/DESIGN.md`: no new colors were invented for the four layers - virtual/external/blackout styling reuses existing tokens (`--color-text-muted`, `--color-danger`) plus opacity/hatching/dashed-border variations, matching DESIGN.md's "status is never color-only" accessibility baseline (each layer also differs in interactivity and, for virtual occurrences, an additional opacity step for the completion anchor per §9.2's "best guess, not a prediction" closing paragraph).

Event-shape mapping (`frontend/src/views/timeline/buildEvents.ts`) is a plain-TS module, not inlined in the component, for the same reason `duration.ts` was in 9b: it needs its own direct unit tests (which layer, which classes, which `editable`/interactivity flags) independent of actually mounting FullCalendar. `TimelinePage.tsx` composes it with `eventClick` branching on `extendedProps.kind` - only `'real'` navigates to `TaskDetailPage`; `'virtual'`/`'external'`/`'blackout'` are no-ops by construction (§9.2: "cannot be marked complete, rescheduled, or otherwise interacted with"; §7: read-only sync), backed up by `pointer-events: none` in CSS for real-browser hit-testing. New API client functions: `listProjections` (`taskTemplates.ts`), `listExternalEvents` (new `externalEvents.ts`), and a deliberately minimal `getSettings` (new `settings.ts` + `types/settings.ts`) - exactly enough to read `blackout_dates`, not the full Settings screen, which stays Stage 9f's job.

**Environment fix required to test any of this:** actually rendering FullCalendar under Vitest's jsdom environment crashed on mount (`Cannot read properties of null (reading 'style')` inside `computeCanVGrowWithinCell`) - traced to a genuine jsdom 23.2.0 bug where `querySelector` on a *detached* element's `<table>`-containing `innerHTML` fails to find a nested descendant (works fine once the element is attached to `document`). Confirmed fixed in jsdom 25; bumped the `jsdom` devDependency accordingly and reran the full pre-existing frontend suite to confirm no other test's behavior changed.

**Deliberately deferred, not silently missing:** the calendar's timezone is browser-local (FullCalendar's default), not the user's configured IANA timezone (design doc §14.1) - `TaskDetailPage`'s `datetime-local` handling already made this same simplification in 9b/9c pending Settings/9f's timezone context, and the Timeline follows the same precedent rather than inventing a different partial solution. FullCalendar rendering performance at the full 30-day ghost horizon was not specifically load-tested (flagged as a watch-item in the Open Risks section below, written before this stage started).

New tests: 9 backend unit tests (`test_virtual_occurrences.py` - both anchor branches, the completion-anchor rebase, the horizon boundary, archived/one-time exclusion), 4 backend service tests (`list_display_events`), 9 backend route tests (5 for `/task-templates/projections` - shape, path-ordering, one-time/archived exclusion; 4 for `/external-events` - auth, empty case, transparent/all-day/disabled-connection filtering) - 22 new backend tests total, bringing the full backend suite to 494 tests, all green. 24 new frontend unit tests (`buildEvents.test.ts` for the pure mapping logic, `TimelinePage.test.tsx` for actual FullCalendar interactivity/navigation/class-presence assertions), 1 new Playwright test (`timeline.spec.ts`, ordered after `tasks.spec.ts` by filename - creates a fixed task, confirms it renders as a real, clickable Timeline event, and that clicking it navigates to its detail page).

**9e - Notifications panel** (§8.1 screen 5, §3.9) - **Done**
Tests: stale-click race (notification resolves server-side between list-load and click) shows "already resolved."

**As built:** no backend gap this time - `GET /notifications` and `POST /notifications/{id}/dismiss` (built in Stage 8) were already sufficient, confirmed by grepping the whole backend before starting (same discipline as every prior sub-stage). `NotificationsPanel.tsx` (`frontend/src/views/notifications/`) follows the established list-fetch-once pattern (`TaskDetailPage`/`EditTaskPage`), with a manual "Refresh" button for the case where the user wants an up-to-date view without acting on anything.

**Interaction design decided here (this stage's own "decide the exact interaction" instruction):** there is no single-notification GET, matching the established no-detail-endpoint-at-POC-scale precedent, and unlike `TaskInstance` a `Notification` (§3.4) carries no field beyond what the list response already includes - so there is no separate "detail" a click could reveal the way `TaskDetailPage` reveals status history/dependencies. "Opening" a notification therefore collapses into the one interaction the panel actually offers: Dismiss. That call is also the only server round-trip available to discover a race that happened after the list loaded, which is exactly the mechanism this stage is named for.

**The stale-click race, handled precisely per the traced mechanics:** `NotificationRepository.list_active()` filters `dismissed_at IS NULL AND resolved_at IS NULL` at the DB layer, so an auto-resolved notification simply vanishes from the next `GET /notifications` rather than coming back with `resolved_at` set - meaning every row the panel loads is guaranteed active at load time. `app.notifications.service.dismiss` is deliberately unconditional (its own docstring: "§3.9's 'already resolved' state is a frontend display concern") and never touches `resolved_at` - it always succeeds and returns the row's current `resolved_at` untouched. So after a dismiss call, a non-null `resolved_at` in the response can only mean the condition cleared server-side sometime between this panel's list load and the click landing, never because of this dismissal. `NotificationsPanel.tsx` checks exactly that: `updated.resolved_at` non-null renders the row in an "Already resolved" state (Dismiss button replaced with a status message, row stays visible rather than vanishing) instead of the normal path, where the row is removed from the visible list immediately.

**Real e2e-suite bug found and fixed, unrelated to the Notifications panel itself:** the full Playwright suite was intermittently red - confirmed independently on `main`'s own post-Stage-9d CI run (`gh run view` on the merge commit of PR #18, failing for the identical reason at nearly the same wall-clock time this stage's own run hit it) and reproduced identically against a clean `origin/main` checkout with none of this stage's changes applied. Root cause: `timeline.spec.ts`'s fixed task left its "Time of day" at the form's 09:00 default, on the assumption ("no other e2e spec creates a fixed task") that nothing else could collide with it - but a flexible task auto-placed by an earlier spec (`tasks.spec.ts`, `task-detail.spec.ts`) always lands somewhere inside the default 09:00-17:00 active-hours window (design doc §6.2's `effective_hours`), including exactly 09:00 whenever the suite happens to run before 09:00 local time (so "now" itself falls outside the window and the placement search's first available grid point is the window's own start). When that collided with `timeline.spec.ts`'s own 09:00 fixed task, the real `creation_conflict` (§6.5, both instance types are obstacles) correctly fired - a genuine test-isolation bug, not a product bug. Fixed by moving `timeline.spec.ts`'s fixed task to an explicit 21:00, outside the active-hours window a flexible placement can ever land in, making the test's pass/fail independent of wall-clock time. One-line-plus-comment change in `frontend/e2e/timeline.spec.ts`, no application code touched.

7 new frontend unit tests (`NotificationsPanel.test.tsx` - empty state, multi-notification rendering with type/message/created_at/link, the stale-click race, normal-path dismiss removing the row, link navigation, list-fetch error banner, manual refresh), 1 new Playwright test (`notifications.spec.ts`, ordered after `login.spec.ts` by filename - creates a flexible task whose duration (90 minutes) cannot fit before its deadline (1 hour), a condition that is deterministic regardless of active-hours settings or time of day, confirms the resulting real `unschedulable` notification appears on the panel with the right type label, and dismisses it).

**9f - Settings screens** (§8.1 screen 6) - **Done**
Account, calendars (OAuth connect UI), scheduling window, timezone, display.
Tests: per settings section; one Playwright test for the OAuth connect flow against Stage 7's mocked provider.

**Real backend contract gap found and fixed, confirmed before building** (same category as every prior 9a-9e mid-stage finding): grepping `app/auth/service.py` and `app/api/v1/routes/auth.py` in full found `setup`/`login`/`logout`/`validate_session`/`apply_reset_admin_password_if_needed` but no self-service change-password path at all, even though design doc §3.6 screen 6 requires "Account: change password" and §3.6/§14.2's session policy is explicit and non-optional ("every session for the user is revoked on any password change or reset"). Added `POST /api/v1/auth/change-password` (`app.auth.service.change_password`, `backend/app/api/v1/routes/auth.py`) - not in the auth guard's public allowlist, matching `logout`/`me`. It reuses `apply_reset_admin_password_if_needed`'s exact revocation call (`SessionRepository.delete_all_for_user`) rather than reimplementing it, but is a genuinely different path from that function: `apply_reset_admin_password_if_needed` is *operator recovery* (no current-password check - the whole point is unlocking someone locked out), `change_password` is *self-service* and verifies the caller's current password (`verify_password`, same helper `login()` uses) before applying `MIN_PASSWORD_LENGTH`. Since revoking "every session" necessarily includes the one making the change request itself, the endpoint mirrors `login()`'s rotate-on-success behavior: after revoking all sessions it issues and returns a **fresh** session, which the route sets as the new cookie exactly like `login_endpoint` does - net effect, this device stays logged in on the new password, every other device/tab is signed out. 11 new backend tests (6 service-layer in `tests/integration/auth/test_service.py`'s new `TestChangePassword`, 5 route-layer in `tests/integration/api/test_auth_routes.py` - wrong current password, too-short new password, auth-required, successful change setting a fresh cookie whose session actually works, and the other-session-revoked case using the same "simulate a second tab" cookie-swap technique the file's own pre-existing revoked-session test uses), bringing the backend suite to 505, all green.

**Everything else Settings needed already existed** (confirmed by grepping the backend before building, same discipline as 9a/9c/9d/9e): `GET`/`PATCH /api/v1/settings` (Stage 4) already covered `timezone`/`active_hours`/`blackout_dates`/`daily_time_budget_minutes`/`budget_enforcement`/`first_day_of_week` with a genuinely partial PATCH, and `GET`/`GET .../{provider}/connect`/`GET .../{provider}/callback`/`DELETE /calendar-connections/{id}` (Stage 7) already covered the whole OAuth connect/disconnect lifecycle - this sub-stage built UI against both rather than adding more backend.

**Scope decision - `refresh_interval_minutes` (documented per this stage's own instruction not to leave it implicit):** shown read-only with a "disconnect and reconnect to change" note, not made editable post-connect. `GET /{provider}/connect` only accepts it as a query param at connect time; there is no endpoint to change it on an already-connected calendar, and design doc §8.1 screen 6's own bullet only says the interval is *shown*, not that it's editable after the fact. Adding a new PATCH endpoint purely to make this one field editable would have been exactly the "while you're in there" scope creep CLAUDE.md's Common Pitfalls warn against - disconnect-and-reconnect is the documented path instead, since it's what the backend actually exposes.

**Scope decision - OAuth Playwright coverage (documented per this stage's own "figure out the right scope" instruction):** `tests/fixtures/calendar_providers.py`'s `MockCalendarProvider` is a Python object swapped in via `monkeypatch` at the pytest level, not a real HTTP server - there is nothing listening on that URL for a genuine browser to complete a full authorize-code round trip against in CI, and standing up a stub HTTP OAuth server just for one e2e test was judged more machinery than the marginal coverage over the existing backend integration tests is worth. Scoped down to what a real browser genuinely exercises: `frontend/e2e/backend-process.ts` now sets `APP_BASE_URL`/`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (fake test values) on the e2e backend so a real, unmocked `GET /calendar-connections/google/connect` (`backend/app/calendar_sync/providers/google.py`'s real `build_authorize_url`) succeeds; `settings.spec.ts` clicks "Connect Google Calendar", intercepts the resulting real top-level navigation with `page.route('https://accounts.google.com/**', ...)` (fulfilled locally, never leaves the test process), and asserts the intercepted request's `client_id`/`redirect_uri`/`state`/`response_type` are exactly what the real backend produced. Token exchange, connection persistence, and disconnect are already covered end-to-end against `MockCalendarProvider` in `backend/tests/integration/api/test_calendar_connections_routes.py` (`TestCallback`/`TestDisconnect`) - real HTTP through FastAPI's `TestClient`, matching implementation-plan §7's own provider-mocking precedent, just not through an actual browser.

**Frontend:** `frontend/src/views/settings/` (`SettingsPage.tsx` composing five section components, matching the `views/<feature>/` layout every other Stage 9 sub-stage used). A new `frontend/src/components/DayOfWeekRows.tsx` (paired with `frontend/src/lib/days.ts`'s canonical Monday-first order/labels) is the one reusable "value per day of week" component the stage's own instructions anticipated - used by both `SchedulingWindowSection`'s active-hours and daily-budget rows. Deliberately **not** merged with the task form's pre-existing `ActiveHoursOverrideInput` (§3.2): that component represents a genuinely different shape (a partial map with an "inherit" state, merging over `UserSettings.active_hours`) from `UserSettings.active_hours` itself (§3.7: always all 7 days, explicit window or explicit `null`, no inherit state) - forcing them onto one abstraction would have papered over a real semantic difference. Daily time-budget entry reuses `frontend/src/lib/duration.ts`'s pre-existing `DAILY_BUDGET_UNITS` (added in 9b, unused until now) via the existing `DurationInput` component, plus an "Unlimited" checkbox for the `null` case §3.7 defines. Each of the five sections saves independently via its own `PATCH /settings` call and reports the server's response back up through `onUpdated`, so a later section's save always patches onto the most current row. `AppShell.tsx` picks up the OAuth callback's `?calendar_connected=<provider>` query param (previously unconsumed by any frontend route - the backend's own comment on `calendar_connections.py`'s callback endpoint flagged this as pending "Stage 9") and hands it to `/settings` via router state, so `ExternalCalendarsSection` can show a one-time "<Provider> connected." success banner. New API client functions: `updateSettings` (extending Stage 9d's existing minimal `settings.ts`), `changePassword` (extending Stage 9a's existing `auth.ts`), and a new `calendarConnections.ts` (`listConnections`/`connect`/`disconnect`).

26 new frontend unit tests (`AccountSection` 4, `ExternalCalendarsSection` 7, `SchedulingWindowSection` 8, `TimezoneSection` 2, `DisplaySection` 2, `SettingsPage` 3 - covering each section's happy path plus at least one validation-error path: wrong current password, password-too-short, mismatched confirmation, `invalid_timezone`, a generic settings-save failure, and a blackout-date end-before-start client-side check), 3 new Playwright tests (`settings.spec.ts`, ordered after `login.spec.ts` by filename - the OAuth-connect-URL assertion above, a real change-password flow proving a second browser context's session is revoked while the acting tab's stays logged in, and a scheduling-window save/reload round trip), bringing the e2e suite to 10 spec files, all green.

**Cross-cutting for 9a–9f:** ESLint/Prettier/`tsc --noEmit` clean; every screen consumes the real backend (mocks only in unit tests, Playwright hits the real thing).

**Exit criteria (whole Stage 9)**
- [x] All six sub-stages individually gated and green.
- [x] Full Playwright suite covering architecture doc §8's e2e list, green, against the real backend.

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
- [x] CI image build+smoke test green.
- [x] Operator walkthrough completed and documented once.

---

**As built:** three of this stage's four "in scope" items (Dockerfile, `docker-compose.yml`, CI image build+smoke test) were already built in Stage 0, ahead of schedule, and needed no changes here - confirmed by re-reading each against this section's requirements rather than assuming: the compose file already wires every §7.1 variable, mounts `tessera_data` as a named volume, and has a healthcheck; `.github/workflows/ci.yml`'s `docker` job already builds the image and curls `/health` on every push. `README.md` was also already finalized, via the hosted docs site (`docsite/`, PR #13) rather than the README itself - `docsite/installation.md` covers setup, env vars, the first-run setup wizard, and `RESET_ADMIN_PASSWORD`-based password recovery; `docsite/contributing.md` covers branching/CI conventions (Section 3).

**Real gap found and fixed, the one item genuinely incomplete:** `backend/app/main.py` still had the frontend `StaticFiles` mount commented out behind a "Placeholder: in Stage 9, serve the frontend build here" note - Stage 9 built and shipped the whole frontend, and the Dockerfile has copied `frontend/dist` into the image as `./static` since Stage 0, but nothing ever mounted it. The production container was API-only; visiting the app's root URL 401'd instead of serving the SPA. Fixed by:
- Adding `SPAStaticFiles` (`app/main.py`), a thin `StaticFiles` subclass that falls back to `index.html` on a 404 for any non-`api/` path, so a hard reload on a React Router client route (e.g. a bookmarked `/timeline`) doesn't 404 - mounted at `/` last, after every real `/api/...` router, so those always match first.
- `AuthGuardMiddleware`'s allowlist (`app/api/middleware.py`) is a fixed set of `(method, path)` tuples, which can't express "every static asset and every client route" (hashed filenames, arbitrary paths). Added `_is_frontend_request` instead - any `GET`/`HEAD` outside `/api/` and not `/health` bypasses both the setup gate and the session check entirely. This is safe because the bypass only ever serves static files; real authorization still lives entirely at the API layer, which the SPA itself calls on load (`AuthContext`) to resolve its own `setup_required`/`unauthenticated`/`authenticated` state - matching the same "backend is the source of truth, frontend just reacts to it" pattern Stage 9a established for the analogous setup-vs-login distinction.
- That bypass incidentally exposed a pre-existing, previously-latent prefix inconsistency: FastAPI's `docs_url`/`redoc_url`/`openapi_url` were already scoped under `/api/v1/`, but `swagger_ui_oauth2_redirect_url` defaults to `/docs/oauth2-redirect`, outside that prefix - so it would have started resolving as a public static path too. Fixed at the source by scoping it under `/api/v1/` like its siblings, rather than special-casing it in the middleware.
- 4 new unit tests (`tests/unit/test_frontend_serving.py`, exercising `SPAStaticFiles` directly against a throwaway static dir - real asset served, index served at root, unknown client route falls back to index, an unmatched `api/` path is *not* masked by the fallback) and 7 new integration tests (`tests/integration/api/test_auth_routes.py` - `TestFrontendRequestsBypassTheGuard`, `TestIsFrontendRequest`) confirming the bypass doesn't leak onto `/api/...` paths and doesn't weaken the setup gate.

**Operator walkthrough, performed and documented here per this section's requirement (podman, not the plan's literal `docker compose` - both are supported, see `docsite/installation.md`):**
1. Fresh `.env` from `.env.example` with a real generated `SECRET_KEY`.
2. `podman-compose up -d --build` - multi-stage image builds clean (frontend `vite build`, then the Python runtime layer), container reports healthy.
3. `GET /` → `200`, serves the real built `index.html`; the hashed JS asset it references (`/assets/index-*.js`) → `200`; an unbookmarked client route (`/timeline`) → `200` via the SPA fallback, not a 404; `/api/v1/auth/me` still correctly `403 setup_required` throughout - confirms the frontend-bypass fix didn't weaken the API guard.
4. First-run setup: the plan's literal checklist item says "login via `RESET_ADMIN_PASSWORD`," but that's this plan's own original assumption from before Stage 3, which the setup-token wizard superseded (see Stage 3's retrospective above) - there is no default account to reset into anymore. Completed the actual current flow instead: pulled the setup token from `podman-compose logs`, `POST /api/v1/auth/setup`, then `POST /api/v1/auth/login`.
5. Set active hours via `PATCH /api/v1/settings`, then created a one-time flexible task via `POST /api/v1/task-templates` - the response's `instance.status` came back `scheduled` with a `scheduled_time` inside the configured window, confirming the scheduling engine actually ran end-to-end through the real container, not just in the test suite.
6. `podman-compose restart tessera` - container comes back healthy; the task template and the pre-restart session cookie both still resolved correctly afterward, confirming the SQLite volume (data) and the jobs SQLite file both survive a container restart as designed.
7. Torn down with `podman-compose down` and the temporary `.env` removed.

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
- [x] Full regression green on a clean checkout.
- [x] Security pass documented.
- [x] Non-Goals/Backlog audit: zero scope creep found (or found and removed).
- [x] `v0.1.0-poc` tagged.

---

**As built:**

**Full regression, clean checkout.** `git clone` into a scratch directory from the real GitHub remote (not this working tree), fresh backend venv + `pip install -e ".[dev]"`, fresh `npm ci`: `ruff`/`ruff format`/`mypy`/`lint-imports`/`pytest` all green (522 tests, 94.5% overall, 100% `scheduling_engine/`), frontend `eslint`/`tsc`/`vitest`/`build` all green (125 tests), full Playwright e2e suite green (10/10, against the real backend - required pointing the harness's `TESSERA_BACKEND_PYTHON` at the clean checkout's own venv rather than system `python3`), and the actual container: `podman build` from the Dockerfile, boot, `/health` 200, root serves the real SPA shell, `/api/v1/auth/me` correctly still `403 setup_required`.

**Coverage review - one real, business-critical gap closed.** Went past the 80%/90% gate numbers to look at *what* the misses were, not just how many. `app/jobs/scheduler.py` was the standout at 69% (every other module was 90%+): its `_dispatch` function is the single place a fired APScheduler job turns back into a handler call, by string-matching the `job_key`'s kind prefix - and only the `reminder` branch of its seven-way `elif` chain had ever actually fired through a real APScheduler thread (`tests/integration/jobs/test_scheduler.py`'s existing `TestScheduleAtFiring`). Every other kind was only exercised two other ways - calling `handlers.run_*` directly (bypassing key-parsing entirely) or asserting a job got *scheduled* (`tests/job_wiring/`, never fired) - neither of which would catch a typo in the dispatch string-matching itself. That's exactly the "no error to surface, a silent miss" failure mode CLAUDE.md's Common Pitfalls warns about, one level deeper than the job-wiring co-location it usually refers to. Added `TestDispatchRoutesEveryJobKind` (7 new tests, one per kind, each monkeypatching only the target handler to a recording stub so just the dispatch/parsing logic is under test) plus a test proving a raising handler is logged and doesn't kill the scheduler thread (the module's own documented guarantee, previously unverified). `scheduler.py` is now 100% covered. Also found and closed two untested branches in `edit_template_this_and_future` (the "this and future" edit path's own copies of checks already tested at template-creation time, but never at the edit call site): an unknown `template_id` (`not_found`), and setting `anchor: "completion"` on a template whose `type` the same edit makes non-flexible (`invalid_recurrence_anchor`). Remaining misses (a handful of lines in `task_instances/service.py`/`task_templates/service.py`, and the repository layer generally) are consistent, deliberate `RuntimeError`/`LookupError` invariant guards for states the call graph already prevents (e.g. a `TaskTemplate` row missing for a `TaskInstance` that references it) - reviewed and judged not worth chasing to 100%, consistent with this project's "don't validate what can't happen" discipline. Overall coverage: 94.5% -> 95.3%.

**Security pass.** Cookie flags verified against a real running instance (not just unit tests) via raw `Set-Cookie` header inspection - `HttpOnly`/`SameSite=Lax` unconditional as designed, `Secure` correctly present with an `https://` `APP_BASE_URL` and correctly absent without one, matching architecture-plan §6.1 exactly in both branches. `argon2id` via `PasswordHasher()`'s library defaults (Argon2id, m=64MiB/t=3/p=4) - exceeds OWASP's minimum recommendation, no explicit tuning needed. Login throttling re-confirmed live: 5 failed attempts return `401`, the 6th onward returns `429 too_many_attempts`, matching Stage 3's documented N=5. Grepped `app/auth`/`app/calendar_sync` for any logger call touching a token/secret/key/password value - none found; the one password-adjacent log line (`RESET_ADMIN_PASSWORD` applied) states only that a reset happened, never the value. `TokenDecryptionError`'s message is a static string, never ciphertext or key material. Rate limiting confirmed scoped to login only, matching design doc's stated scope (nothing else calls for it). **Closed a real, previously-deferred gap:** Stage 3's own retrospective flagged that `/docs`/`/redoc`/`/openapi.json` were unconditionally enabled - architecture-plan §6 (Rev 3) requires them "disabled in production, enabled in development, via one setting" - and explicitly deferred the toggle to this stage (the auth guard already blocked unauthenticated access, so the toggle itself is defense-in-depth, not the only thing standing between them and the internet). Added `ENABLE_API_DOCS` (default `false`) - `app.main._docs_urls` is a small pure function returning the four FastAPI kwargs, split out specifically so the on/off decision is unit-testable without constructing the real app singleton. Verified both directions against a live running instance, not just the unit test: unset -> `404` on all three paths (post-auth, since an unregistered `/api/...` path and a registered-but-unauthenticated one are indistinguishable to an anonymous request - the auth guard runs before routing either way); `ENABLE_API_DOCS=true` -> `200` on all three. `.env.example`, architecture-plan §7.1, `docker-compose.yml`, and `docsite/configuration.md` all updated together per the Definition of Done's env-var-sync rule.

**Non-Goals/Backlog audit.** Grepped the whole backend and frontend against every design doc §12/§13 item with a plausible code signature - webhooks, commute time, SSO/2FA, email/SMS channels, multi-user/shared-timeline fields, soft-override conflict handling, a selectable-algorithm concept, holiday calendars, business-hours registries, task splitting/chunking, reflow/re-optimize, duration-prediction/analytics. One hit: `User.two_factor_enabled`. Traced it before flagging it as a violation - it's in the *locked* design doc itself (§3.6: `"two_factor_enabled: boolean; // always false in POC; field reserved for Backlog"`), never read anywhere in the auth flow, always `False`. A deliberate, traceable spec decision (probably to avoid a future `NOT NULL` migration on a populated table), not implementer-introduced scope creep - left as-is. Everything else came back clean, consistent with every prior stage's own documented scope discipline (e.g. 9f declining a PATCH endpoint for `refresh_interval_minutes`, 9c declining to build the Backlog view).

**Traceability spot-check.** Sampled docstrings citing design-doc/architecture-plan sections across `task_instances`, `task_templates`, `calendar_sync`, and `jobs` (`complete_instance`, `dismiss_instance`, `archive_template`, `sync_connection`'s retention purge, `run_dependency_at_risk_check`'s 3-day threshold) and verified each specific claim against the actual code: terminal-status gating, the `archived=true` soft-delete, the retention-purge call site, and the `timedelta(days=3)` constant all matched their docstrings exactly. No drift found.

**Tagging note:** `v0.1.0-poc` was deliberately not tagged as part of this stage's own PR (#31) - tagging, and whether/when to push it, was treated as a user decision rather than an autonomous one. Tagged and pushed as a small follow-up once #31 merged, pointing at its merge commit.

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