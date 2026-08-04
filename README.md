# Tessera

**Self-hosted task scheduling that respects the real shape of your day.**

Tessera fits your flexible tasks into the gaps left by fixed commitments, deadlines, priorities, and dependencies - inside a daily capacity you set, not just wherever a slot happens to be free.

## Overview

- 📋 **Two task types:** fixed (at a specific time) and flexible (fit anywhere within a deadline)
- ⏰ **Daily capacity:** set a daily time budget per day-of-week; Tessera respects it or breaks it only as a last resort to hit a deadline
- 🔗 **Task dependencies:** chain tasks, block dependent work until prerequisites complete
- 📅 **Recurring tasks:** one-time, daily, weekly, monthly - each instance is schedulable and editable independently
- 🔔 **Smart notifications:** reminders, conflicts, missed deadlines, dependency alerts, overdue tasks
- 🌐 **External calendar sync:** read-only polling from Google Calendar, Outlook, etc. - Tessera never double-books
- 🕐 **Timezone-aware:** all times computed in *your* timezone; DST transitions handled automatically
- 🔐 **Single-user:** password-protected, self-hosted, no multi-user coordination overhead

## Documentation

- **[Design Document](docs/design-doc.md)** - authoritative product specification (Revision 8, locked for POC)
- **[Architecture Plan](docs/architecture-plan.md)** - how the system is structured and built (Revision 2)
- **[Implementation Plan](docs/implementation-plan.md)** - staged build sequence with gates and tests
- **[CLAUDE.md](CLAUDE.md)** - guidance for Claude Code when working in this repository

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker + Docker Compose (recommended for deployment)

### Local Development

1. **Clone and set up the environment:**
   ```bash
   git clone <repo-url>
   cd tessera
   cp .env.example .env
   # Edit .env with your SECRET_KEY and other config
   ```

2. **Backend setup:**
   ```bash
   cd backend
   pip install -e ".[dev]"
   pytest  # Run tests
   lint-imports  # Check layering
   ruff check app tests  # Lint
   mypy app  # Type check
   python -m app.main  # Run the app
   ```

3. **Frontend setup:**
   ```bash
   cd frontend
   npm install
   npm run dev  # Dev server with hot reload
   npm run build  # Production build
   npm run lint  # Check linting
   ```

### Docker

```bash
docker-compose up
# Open http://localhost:8000
# First run: set RESET_ADMIN_PASSWORD env var in .env and restart
```

## Development

### Branching & CI

- **Trunk-based development:** all work branches off `main`, which is always deployable
- **Branch naming:** `stage-0N-slug` for implementation stages, `feat/...` or `fix/...` for side work
- **CI:** GitHub Actions runs on every push - must be green before merging to `main`
- **Git hooks:** pre-commit hook runs linting and tests locally (see `.git/hooks/pre-commit`)

### Testing

**Backend:**
```bash
cd backend
pytest                          # All tests
pytest tests/unit/              # Unit tests only
pytest -v --tb=short           # Verbose output
pytest --cov=app               # Coverage report
```

**Frontend:**
```bash
cd frontend
npm test                        # Run tests
npm run type-check             # TypeScript check
```

### Code Quality

**Backend (Python):**
- `ruff check app tests` - linting
- `ruff format app tests` - format check (or `ruff format app tests --fix` to auto-fix)
- `mypy app` - type checking (strict mode)
- `lint-imports` - architecture layering verification
- Coverage target: ~90% on `scheduling_engine/`, ~80% overall

**Frontend (TypeScript/React):**
- `npm run lint` - ESLint
- `npm run type-check` - TypeScript strict mode
- `npm run build` - build check
- Prettier formatting (configured in `.prettierrc`)

### Architecture

**Three-layer backend:**
1. **API layer** (`app/api/`) - thin, request/response only
2. **Service layer** (`app/task_templates/`, `app/task_instances/`, etc.) - all business logic
3. **Data layer** (`app/db/`) - SQLAlchemy models, repositories

**Critical rule:** `scheduling_engine/` has zero imports of FastAPI or SQLAlchemy - it's pure Python, testable in isolation.

## Configuration

See `.env.example` for all required environment variables. Key ones:

- `SECRET_KEY` - for session signing and token encryption (required)
- `DATABASE_PATH` - SQLite file location (default: `./data/tessera.db`)
- `APP_BASE_URL` - base URL for OAuth redirects (required if using calendar sync)
- `TZ` - default timezone (IANA name, e.g. `America/New_York`)
- `RESET_ADMIN_PASSWORD` - one-time password reset on container startup

## Deployment

**Single Docker container, all-in-one:**
- Python backend (FastAPI)
- React frontend (static assets served from Python)
- SQLite database (on mounted volume)
- Background job scheduling (APScheduler)

**Multi-stage Docker build:**
- Stage 1: Python dependencies
- Stage 2: Node.js frontend build
- Stage 3: Runtime (tiny, Python-only)

**Data persistence:** SQLite database lives on a Docker volume (`tessera_data`), not in the container. On container recreate, all data survives.

## Development Status

**Current Stage:** Stage 0 (Project Bootstrap & Tooling Foundation)

- ✅ Git repo + CI workflow
- ✅ Backend scaffold + health endpoint
- ✅ Frontend React skeleton
- ✅ Docker build + compose
- ✅ Testing infrastructure
- ⏳ Stage 1: Scheduling engine (pure algorithm, isolated tests)
- ⏳ Stage 2–11: See [implementation plan](docs/implementation-plan.md)

## Contributing

This is a single-developer POC. If you're picking up work:

1. Start with the [implementation plan](docs/implementation-plan.md) to understand the stage gates
2. Read [CLAUDE.md](CLAUDE.md) for codebase patterns and common pitfalls
3. Read the design doc (Sections 3, 6, 14) before implementing anything in those areas
4. Branch per stage: `stage-0N-slug`
5. One PR per completed stage; CI must be green
6. Tag `main` after each stage merges: `git tag stage-0N-done && git push --tags`

## License

[See LICENSE file]

## References

- **Product spec:** `docs/design-doc.md` - what the system does
- **Architecture:** `docs/architecture-plan.md` - how it's built
- **Build sequence:** `docs/implementation-plan.md` - stages and gates
- **Code guidance:** `CLAUDE.md` - patterns and pitfalls for this codebase
