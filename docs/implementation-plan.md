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
| 9 | Frontend | **In progress** (9a, 9b, 9c done) | `stage-09a`…`stage-09f` | 9a, 9b, 9c done - see Stage 9 section below for full detail |
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
- This-and-future propagation (`edit_template_this_and_future`) updates the live instance's `name`/`description`/`location`/`priority`/`estimated_duration_minutes` only. `fixed_time_of_day` re-projection and `deadline_offset_minutes` deadline recomputation are **not** propagated - neither is exercised by a Stage 5 required test, and both need real conflict/re-placement handling to do properly rather than half-implement silently.
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