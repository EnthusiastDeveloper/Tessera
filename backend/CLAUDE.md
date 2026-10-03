# backend/CLAUDE.md

## Architecture Layers & Module Map

**Binding rule:** backend architecture has three **strictly enforced** layers (import-linter blocks violations):

```
API layer (backend/app/api/)
    ↓ (thin: request/response only, no business logic)
Service layer (framework-agnostic pure Python)
    ↓ (all scheduling, validation, CRUD rules, state transitions)
Data access layer (backend/app/db/)
    ↓ (SQLAlchemy models, repositories)
```

**Module structure mirrors design-doc sections:**
- `backend/app/task_templates/` - TaskTemplate CRUD + schema (design-doc Section 3.2)
- `backend/app/task_instances/` - TaskInstance CRUD + edit-scope logic (design-doc Sections 3.3, 3.10)
- `backend/app/scheduling_engine/` - core placement algorithm (design-doc Section 6), **must be pure Python, zero FastAPI/SQLAlchemy imports**
- `backend/app/notifications/` - notification types and state (design-doc Sections 3.4, 5)
- `backend/app/calendar_sync/` - external calendar polling + conflict handling (design-doc Sections 3.5, 6.4, 7)
- `backend/app/auth/` - password hashing, session management (design-doc Sections 3.6, 6)
- `backend/app/jobs/` - APScheduler adapter for background jobs (architecture-plan Section 4)
- `backend/app/settings/` - user settings + active-hours windows (design-doc Section 3.7)

**Key design decision:** The scheduling engine must have **zero imports of FastAPI, SQLAlchemy, or anything under `app/`** - it operates on plain Python data structures. This makes it unit-testable in isolation and keeps it swappable if the ORM/framework ever changes.

---

## Background Jobs (architecture-plan Section 4)

APScheduler with persistent SQLite job store - **jobs are event-driven, not periodic scans**:
- **Reminder:** precise one-off job per reminder_offset, rescheduled on task reschedule
- **Overdue check:** one-off job at `scheduled_time`
- **Deadline-elapsed (`missed` state):** one-off job at `deadline`
- **Dependency-at-risk scan:** one-off job at `deadline - 3 days`
- **Recurring instance generation:** event hook (fires when prior instance reaches `completed`)
- **External calendar poll:** interval-based (per `refresh_interval_minutes`)

**Critical:** Every mutation path that affects a task (`create`, `edit`, `reschedule`, `complete`, `delete`, `extend_deadline`) **must co-locate the DB write and job side-effect in one service method** (architecture-plan 4.1) - never in the route handler. This is what prevents orphaned or missing jobs.

Routes take their DB session as `db: Session = DB_SESSION` (`app/api/dependencies.py`), never `Depends(get_db)`: FastAPI's default dependency scope commits *after* the response is sent, so a client could act on data that isn't committed yet (and a failed commit would already have been reported as success). `tests/integration/api/test_commit_before_response.py` enforces it.

Job calls are **commit-bound**: routes (`get_request_job_scheduler`), fired jobs (`_dispatch`) and startup reconciliation all hand services a `TransactionalJobScheduler` (`app/jobs/transactional.py`), which buffers calls and replays them only after the DB transaction commits. A rollback discards them. Keep calling the scheduler from inside the service method as usual; don't reorder calls to "commit first".

**Startup reconciliation (architecture-plan 4.2):** On app start, before serving traffic, reconcile the job store against `TaskInstance` rows - recreate any missing jobs, cancel any orphaned ones. This guards against crashes mid-batch leaving them out of sync.

## Database schema & migrations

The whole schema is **one baseline migration**, `backend/alembic/versions/0001_initial_schema.py`. No deployment has ever held data worth carrying forward, so while that stays true:

- Change the schema by editing the models **and** that file together. A test (`test_the_baseline_matches_the_models_exactly`, i.e. `alembic check`) fails when they drift, and another (`test_there_is_exactly_one_migration`) fails if a second file appears.
- A database created by an earlier build can't be brought forward - delete it and run the setup wizard again.

**From the first release that real data lives on, stop.** Never edit `0001` again: an existing database records its version in `alembic_version` and can only be moved forward by *new* steps. Add one migration per change (`alembic revision --autogenerate`, then review it - SQLite needs `batch_alter_table`, and autogenerate emits every `Enum`'s CHECK constraint again as a redundant `CheckConstraint`), write its downgrade, test it against a database holding real rows, and delete `test_there_is_exactly_one_migration`.
