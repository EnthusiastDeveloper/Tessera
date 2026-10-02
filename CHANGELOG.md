# Changelog

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
