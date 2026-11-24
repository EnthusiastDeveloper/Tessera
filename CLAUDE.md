# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

**Tessera** is a self-hosted task scheduling application that auto-places flexible tasks into your calendar while respecting fixed commitments, deadlines, and priorities. It's a Python FastAPI backend + React frontend, single-user, containerized.

### Key References
- **Product specification:** `docs/design-doc.md` (Revision 20) - this is the authoritative source for what the system *does*
- **Implementation plan:** `docs/architecture-plan.md` (Revision 10) - defines how it's structured and built
- **Findings register / decision log:** `docs/implementation-readiness-review-2.md` (IRR-2) - why Revisions 9 and 3 say what they say (Revision 10's through 13's decisions are recorded in design-doc Section 11); every finding in it - High, Medium and editorial - is now resolved
- **Architecture enforcement:** `backend/pyproject.toml` has an `import-linter` configuration that blocks layering violations at CI

### Common Commands

- `lint-imports` - check layering violations (also runs in CI, blocking); see `backend/pyproject.toml` and `frontend/package.json` for the rest of the standard install/test/build/lint commands.

---

Backend layering rules and module map: see `backend/CLAUDE.md`.

## Reference notes: read before changing the matching area

The design-doc summaries (the non-negotiable rules, data model, API contract and deployment) live in `docs/claude/`, so they're only loaded when needed. They are binding. Read the one for the area you change before writing code, and **read the full design-doc before implementing**.

| Before you change… | Read |
|---|---|
| templates and instances, recurrence, edit scopes, the scheduling algorithm, Optimize Schedule, statuses, notifications, timezone/DST, auth | `docs/claude/domain-rules.md` |
| models, fields, user settings, migrations | `docs/claude/data-model.md` |
| endpoints, request/response shapes, error codes, optimistic locking | `docs/claude/api-contract.md` |
| env vars, the container, persistence, the health check | `docs/claude/deployment.md` |

---

Background job wiring and reconciliation rules: see `backend/CLAUDE.md`.

## Testing Strategy (architecture-plan Section 8)

**Build order:** Scheduling engine first, tested in isolation, before wiring anything else. Then service layer, then API.

**Required test categories:**
1. **Unit tests** on scheduling engine (~90%+ coverage on this module specifically) - place tasks against various constraint combinations
2. **Scheduling algorithm acceptance tests** - design-doc Section 10's Worked Examples A–K are concrete input/output scenarios; implement these as test fixtures
3. **Edit-scope/detach tests** - Worked Examples L–M (design-doc 3.10); verifies "this occurrence" vs. "this and future" scoping and the detach flag
4. **Job-wiring integration tests** - assert that every mutation creates/cancels the right job(s) at the right time; don't just test the business logic, test the job plumbing too (architecture-plan 4.1)
5. **Reconciliation tests** - simulate a killed process, verify startup 4.2 reconciliation restores consistency
6. **Architecture tests** - `import-linter` run on every push; also a pytest test that walks the AST and fails if `scheduling_engine/` imports forbidden modules

---

## Scope: What's In vs. Out for POC

**In POC (locked, design-doc Section 2):**
- Single user, password login, read-only external calendar sync (polling)
- WebUI only (no IM bot)
- One fixed greedy scheduling algorithm
- Global active-hours + per-task override + manual blackout dates + soft daily time-budget
- Fixed-task hard-block on conflicts (no soft override)
- In-app notifications only (no email/IM push)

**Explicitly out of POC (Backlog sections 12 & 13, will not be built "while you're in there"):**
- Multi-user / shared timeline
- Location-aware scheduling or commute time
- Automatic task splitting (design-doc 12.20) - hard-block at creation instead (design-doc 6.8)
- Multiple selectable algorithms (design-doc 12.9)
- Holiday calendars (design-doc 12.15 has open questions)
- Email/IM notification channels
- Write access to external calendars (read-only polling only)

**Critical discipline rule (design-doc Section 0):** Do not build backlog items "while you're in there" under the guise of prep work. The scope boundaries are deliberate.

---

## Common Pitfalls

1. **Don't edit the design doc casually.** Sections 3 (Data Model) and 6 (Algorithm) are load-bearing; Section 14 (Design Decisions) has binding constraints. Section 11 is locked - all `[UNCONFIRMED]` items were resolved in Rev 8. Changes need to go through a revision process with stakeholder sign-off.

2. **Don't skip the layering.** Import-linter will catch it in CI, but a violation caught in code review is cheaper than a failed CI run. Specifically: `scheduling_engine/` must not import FastAPI, SQLAlchemy, or anything under `app/`.

3. **Don't periodic-scan when you should event-drive.** Background jobs are event-driven (architecture-plan 4). If you find yourself adding a new job, ask: "Can this fire off an event (a task state change, a dependency completion) or a precise timestamp?" If the answer is yes, schedule a one-off job. If not, reconcile why.

4. **Don't half-implement job wiring.** A mutation writes to the DB *and* updates jobs in the same method, or it's wrong. The orphaned-job failure mode has no error to surface - it's a silent miss.

5. **Don't assume `schedule_time` means the task actually happened.** A flexible task can be marked `completed` without ever being `scheduled` (design-doc 3.3, Section 4) - user already did the task. The timestamp is `completed_at`, not `scheduled_time`.

6. **Don't forget detach.** "This occurrence" edits and manual fixed-task reschedules set `detached=true` (design-doc 3.10, 6.6). A detached instance is skipped by later "this and future" edits unless the user ticks the dialog's checkbox, which also clears the flag. The UI should indicate it visibly, and the edit dialog must name the occurrences it will skip (design-doc 8.1).

7. **Don't store raw UTC offsets for timezone.** Use IANA timezone names (design-doc 14.1). `pytz` or `zoneinfo` (Python 3.9+) handle DST automatically; custom UTC offset math will silently drift by an hour at DST boundaries.

8. **Don't build search/filtering as a separate layer.** The API layer already filters `GET /task-instances?status=scheduled&priority=high` through the service layer; the service layer calls the data layer with constraints. Keep the direction one-way: API → Service → Data.

---

Debugging playbook (scheduling bugs, missed jobs, stuck dependencies, unexpected 409s, calendar filtering): use the `debug-tessera` skill.

---

Code review checklist: use the `tessera-code-review` skill.

Frontend notes: see `frontend/CLAUDE.md`.

---

## References

- **Product spec:** `/docs/design-doc.md` - authoritative source for what to build
- **Architecture & implementation:** `/docs/architecture-plan.md` - how to structure the code
- **Build order & testing:** architecture-plan Section 8 - scheduling engine first
- **Worked examples:** design-doc Section 10 (A–M) - concrete scenarios to test against
- **Backlog & non-goals:** design-doc Sections 12–13 - explicitly out of scope for POC
