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

**Startup reconciliation (architecture-plan 4.2):** On app start, before serving traffic, reconcile the job store against `TaskInstance` rows - recreate any missing jobs, cancel any orphaned ones. This guards against crashes mid-batch leaving them out of sync.
