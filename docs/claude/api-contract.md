# API Contract (architecture-plan Section 3)

> Moved out of the root `CLAUDE.md` so it isn't loaded on every request. Binding: read it before changing this area. The design doc stays the authoritative source.


**REST, versioned (`/api/v1/...`), session-cookie auth (`HttpOnly`, `SameSite=Lax`, `Secure` derived from `APP_BASE_URL`'s scheme via `SESSION_COOKIE_SECURE=auto`).**

### Key Endpoints
- `GET /api/v1/task-instances` - list with filtering
- `POST /api/v1/task-instances` - create (auto-enters `pending` if flexible, `scheduled` if fixed)
- `PATCH /api/v1/task-instances/{id}` - "this occurrence" edit (sets `detached=true`)
- `POST /api/v1/task-instances/{id}/reschedule` - reschedule a fixed task (also a "this occurrence" edit per design-doc 6.6, sets `detached=true`)
- `POST /api/v1/task-instances/{id}/complete` - mark complete
- `POST /api/v1/task-instances/{id}/extend-deadline` - extend deadline on a `missed` instance (also a "this occurrence" edit per design-doc 6.7)
- `PATCH /api/v1/task-templates/{id}?scope=this_and_future&from_instance={id}` - "this and future" edit (template + the edited and later open occurrences; `include_detached` to include individually edited ones)
- `DELETE /api/v1/task-instances/{id}` - delete (dependency unlink, not cascade)
- `PUT /api/v1/task-instances/{id}/dependencies` - replace one occurrence's dependency list (design-doc 6.1, Rev 17): adding an unfinished one blocks it, removing the last one unblocks it (6.9); refused on `in_progress`/terminal instances; never detaches
- `POST /api/v1/auth/login`, `/logout` - session-based auth
- `POST /api/v1/task-instances/{id}/dismiss` - "skip this occurrence"; terminal, preserves the row, and for a completion-anchored template **must generate the successor** or the series silently ends
- `POST /api/v1/auth/setup` - first-run account creation; requires the setup token logged at startup; `410 Gone` once a user exists
- `DELETE /api/v1/task-instances/{id}?scope=this_occurrence|this_and_future` - deletion scope mirrors edit scope (design-doc 3.8); required for recurring templates. `this_and_future` ends the series: **every open occurrence is deleted** (in-progress included), finished ones kept, template archived (Rev 11)
- `GET /api/v1/settings/schedule-repair` - progress of the background repair a stricter settings save starts (design-doc 6.10)
- `GET /api/v1/task-instances?view=backlog` - the Backlog view is a filter, not its own resource

### Error Envelope
Consistent across all endpoints: HTTP status + machine-readable code + human message. Distinct error codes:
- `validation_error` (`422`) - a field outside the bounds in design-doc 3.13 (implemented once in `backend/app/api/v1/validation.py`)
- `cycle_detected` - dependency creates a cycle
- `creation_conflict` - fixed task collides with existing event
- `infeasible_duration` - flexible task can't fit any single day's active-hours window (design-doc 6.8)
- `invalid_recurrence_anchor` - `anchor: "completion"` on a fixed template
- `invalid_start_date` - a template's `start_date` is before today
- `session_expired` - distinct from a generic 401 so the client redirects to login
- `409 Conflict` - optimistic lock collision; see architecture-plan 5.1. The client sends an `expected` map of the values it read for the fields it is changing; the server compares only those and merges onto the current row. **PATCH must be genuinely partial** - sending the whole object defeats the mechanism
