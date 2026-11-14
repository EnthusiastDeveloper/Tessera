# Deployment & Configuration (architecture-plan Section 7)

> Moved out of the root `CLAUDE.md` so it isn't loaded on every request. Binding: read it before changing this area. The design doc stays the authoritative source.


**Single container, single process.** React builds to static assets; FastAPI serves them directly (no separate nginx container for same-origin simplicity).

**Required env vars** (see `.env.example`):
- `SECRET_KEY` - for session signing + Fernet encryption of OAuth tokens (required)
- `DATABASE_PATH` - path to SQLite file, should point into a mounted volume (default: `./data/tessera.db`)
- `APP_BASE_URL` - base URL for OAuth redirect construction (required if using calendar sync)
- `TZ` - default timezone, overridable in Settings (optional, sensible default)
- `RESET_ADMIN_PASSWORD` - one-time password recovery (optional, requires container restart)
- `SESSION_COOKIE_SECURE` - `auto` (default) | `true` | `false`; `auto` derives the cookie's `Secure` flag from `APP_BASE_URL`. Never hardcode it to `true` - it silently breaks login on plain-HTTP LAN, which is a supported deployment
- `OPTIMIZATION_SLOW_AFTER_SECONDS` (default `10`) / `OPTIMIZATION_TIMEOUT_SECONDS` (default `30`) - when "Optimize Schedule" says it is taking longer than expected, and when it is declared failed (nothing applied, editing unlocked); the timeout must exceed the notice
- Calendar provider credentials if using sync (`GOOGLE_CLIENT_ID`, etc.)

**Data persistence:** SQLite file must live on a mounted Docker volume, never in the container's writable layer. Otherwise all tasks, history, and credentials evaporate on container recreate.

**Health check included** in the container - standard practice under orchestration.
