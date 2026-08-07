# frontend/CLAUDE.md

## Frontend Notes

React + Vite, same-origin served from the FastAPI app (no CORS). Key features:
- Timeline view uses FullCalendar or equivalent, overlaying scheduled instances + external busy-blocks + blackout dates + virtual recurring projections (design-doc 9.2)
- Task creation/edit form prompts for edit scope ("this occurrence" vs. "this and future") for recurring tasks (design-doc 3.10, 8.1)
- Notifications panel with auto-resolved state display (design-doc 3.9)
- Settings screen: timezone, active-hours per day-of-week, blackout dates, daily budget, budget enforcement toggle, first-day-of-week display preference (design-doc 8.1, 3.7)

The frontend hasn't been built yet (skeleton only at this point), so detailed patterns TBD.
