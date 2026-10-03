# Changelog

## Unreleased

- **Optimize Schedule** (design doc Revision 14, section 6.11). One button on the Timeline re-places every scheduled and pending flexible task in a single global pass, the escape hatch for the greedy placement's occasional corner-painting. It runs in the background; while it does, the Timeline and task screens are read-only (**New task** and every task action are disabled with a hint) and the server refuses schedule-changing writes with `409 optimization_in_progress`. If the result takes nothing away it applies at once; if a scheduled task would lose its place, or a task would go over its day's budget, nothing changes until the user approves the plan as a whole (Cancel changes nothing); a plan that would place fewer tasks than today is never offered. A summary of every change is always shown, and an **Undo** button is offered for 10 minutes - only while undoing is still safe, and only for the latest optimization.
- New settings `OPTIMIZATION_SLOW_AFTER_SECONDS` (default 10: the screen says it is taking longer than expected) and `OPTIMIZATION_TIMEOUT_SECONDS` (default 30: it is declared failed, nothing applied, editing unlocked). New API: `/api/v1/schedule-optimizations` (start, `latest`, `approve`, `decline`, `undo`). The `ScheduleOptimization` table is part of the baseline migration, so, as for 0.3.0, a database from an earlier build must be recreated.

- Docs: the last editorial findings of IRR-2 (L1-L10) are closed. The status-lifecycle diagram (design doc 4) now shows every transition into and out of `blocked` and `missed`, and its stale rule that a blocked instance never has a `scheduled_time` is corrected for fixed ones; the holiday-calendar subsection no longer shares the number 12.15 with its backlog row.
- CI: the container smoke test runs on a named volume and checks the admin account survives recreating the container.
- `docker-compose.yml` drops the obsolete `version` key.

## 0.3.0

Design doc Revisions 12 and 13: the IRR-2 Medium findings, and a list of active-hours windows per day with overnight windows. **Two API changes and a database reset - read both notes.**

### Upgrade note: reset the database

The incremental migrations written while the design settled (nine of them) are replaced by a single baseline, `0001_initial_schema`, which produces the same schema. `task_templates.start_date` and `task_instances.nominal_date` are now `NOT NULL` (they were nullable only for rows from before design doc Rev 10), and the code that worked around such rows is gone.

Nothing converts data from an earlier build. A database created by one - recognisable by the app refusing to start with "Can't locate revision" - must be deleted and recreated through the setup wizard. This is the last time that is acceptable: once a release holds data worth keeping, schema changes become new migrations again (the baseline's docstring says so).

### API changes (breaking)

- **Active hours are a list of windows per day.** `active_hours` (`PATCH /settings`) and a template's `active_hours_override` are `{day: [{start, end}, ...] | null}` instead of `{day: {start, end} | null}`. An empty list or the old single-object shape is `422 validation_error`; a zero-length or overlapping window is `422 invalid_field`.
- **Task instances use priority labels.** `low`/`medium`/`high`/`critical`, like templates, in instance responses, `PATCH /task-instances`, its `expected` map and the `priority` list filter - no longer the integers 1-4.

### Scheduling

- A day can be split (`08:00`-`10:00` and `18:00`-`22:00`), and a window whose end is before its start runs overnight (`22:00`-`02:00`). Tasks may straddle midnight inside one. A blackout date cuts at midnight and the daily budget counts the calendar date (design doc 3.7, 6.2).
- Fix: placement measures a task's length in real elapsed time. Around a daylight-saving change the old wall-clock arithmetic mis-sized a window by an hour (a task could overrun the short spring-forward night, or be refused on the long fall-back one); it mattered little for daytime windows and a lot for overnight ones.

### Tasks and settings

- Every request field is bounded (names, durations, intervals, reminders, clock times, budgets, blackout ranges); violations are `422 validation_error`. See design doc 3.13.
- The Settings scheduling window and a task's override both edit a list of windows per day.
- A one-time flexible task can take its deadline from a date picker.
- The undefined `custom` recurrence pattern is gone (it had always behaved as `daily` with an interval).

### Docs

- Documented, with the gaps recorded as Backlog 12.26-12.27: the external-sync behaviour, SQLite pragmas, blackout-range inclusivity, monthly clamping, and that a generated occurrence starts with no dependencies.

## 0.2.0

Design doc Revisions 10 and 11, plus the bug fixes and refactors that came out of using the POC.

### Scheduling
- A scheduled flexible task gives way to a fixed one instead of blocking its creation (design doc 6.5, Rev 10).
- A fixed task waiting on a dependency holds its slot, goes overdue normally, gets `dependency_at_risk` warnings and shows on the Timeline (Rev 10).
- A started (`in_progress`) task is never flagged overdue.
- Stricter rules repair the schedule: narrowing active hours, adding blackout dates or tightening a strict budget re-places every scheduled flexible occurrence that no longer fits, in a background job with a progress overlay (design doc 6.10, Rev 11).

### Recurring tasks
- A template starts on its `start_date`, and every occurrence carries its own `nominal_date`, so one override can't shift the series (Rev 10).
- "This and future" edits reach every later open occurrence; later `detached` occurrences are skipped unless the user opts in (Rev 10).
- "This and future" edits propagate `fixed_time_of_day` and `deadline_offset_minutes`.
- Deleting a series (`scope=this_and_future`) deletes every open occurrence, including in-progress ones, keeps finished ones, and archives the template (Rev 11).

### Timezones
- A timezone change moves nothing: existing occurrences keep their instants and later ones are generated in the new zone. The UI flags a mismatch between the device and the setting (Rev 11).

### Operations and fixes
- The app refuses to start a second scheduler process; backup and restore are documented.
- Each request's database work is committed before its response is sent.
- Calendar sync calls the provider before writing, and keeps a refreshed token when the fetch fails.
- Fixed-task duration conflicts are held to the 6.5 hard block.
- Duplicated helpers unified across services, jobs, routes and the frontend; the backend test suite was de-duplicated and end-to-end coverage extended.
- Docs: external calendar integration guide, occurrence dates, completion-anchor timing and time zones.

## 0.1.0-poc

First proof-of-concept: all 12 stages of `docs/implementation-plan.md`.
