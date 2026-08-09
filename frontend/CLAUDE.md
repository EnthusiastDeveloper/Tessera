# frontend/CLAUDE.md

## Frontend Notes

React + Vite, same-origin served from the FastAPI app (no CORS). Key features:
- Timeline view uses FullCalendar or equivalent, overlaying scheduled instances + external busy-blocks + blackout dates + virtual recurring projections (design-doc 9.2)
- Task creation/edit form prompts for edit scope ("this occurrence" vs. "this and future") for recurring tasks (design-doc 3.10, 8.1)
- Notifications panel with auto-resolved state display (design-doc 3.9)
- Settings screen: timezone, active-hours per day-of-week, blackout dates, daily budget, budget enforcement toggle, first-day-of-week display preference (design-doc 8.1, 3.7)

**Design tokens & conventions:** see `frontend/DESIGN.md` - written before any UI code per implementation-plan Stage 9's hard prerequisite. Components consume CSS custom properties from `src/styles/tokens.css`, never hardcoded colors/spacing.

**Auth & routing (built in Stage 9a):** `src/auth/AuthContext.tsx` resolves one of `loading | setup_required | unauthenticated | authenticated` from a single `GET /auth/me` call on load - `setup_required` is a real, distinct backend error code (not inferred client-side): the backend guard itself refuses every route but setup/health while zero `User` rows exist, see `backend/app/api/middleware.py`'s `SETUP_ALLOWED_ROUTES`. `src/routes/RouteGuard.tsx` redirects to whichever screen the current status belongs on - this is the single mechanism behind every screen's access rule, not a per-screen check. `src/api/client.ts` is the one place that talks to `/api/v1` (fetch, `credentials: 'include'`, throws `ApiError{status, code, message}` matching the backend's error envelope).

**End-to-end tests:** `frontend/e2e/` (Playwright) boots the real backend (`alembic upgrade head` then `uvicorn`, via `frontend/e2e/backend-process.ts`) against a temp SQLite file - never a mock - per implementation-plan Stage 9's "Playwright hits the real thing" rule. Run with `npm run e2e`; needs backend dependencies installed and on `python3`'s `PATH` (or set `TESSERA_BACKEND_PYTHON`), and `npx playwright install chromium` once.
