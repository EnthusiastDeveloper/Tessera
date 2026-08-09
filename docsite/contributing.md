# Contributing

This is currently a single-developer POC. If you're picking up work on it, start here.

## Before you write code

1. Read [Project Status & Scope](project-status.md) - the scope boundary is deliberate; don't build backlog items "while you're in there."
2. Read [`docs/implementation-plan.md`](https://github.com/EnthusiastDeveloper/Tessera/blob/main/docs/implementation-plan.md) to understand the stage gates and what's already done.
3. Read [`CLAUDE.md`](https://github.com/EnthusiastDeveloper/Tessera/blob/main/CLAUDE.md) for codebase patterns, layering rules, and common pitfalls.
4. Read the [design document](https://github.com/EnthusiastDeveloper/Tessera/blob/main/docs/design-doc.md) - Sections 3 (Data Model), 6 (Algorithm), and 14 (binding design decisions) especially - before implementing anything in those areas.

## Local development setup

**Prerequisites:** Python 3.12+, Node.js 20+, Podman + podman-compose (or Docker + Docker Compose).

```bash
git clone https://github.com/EnthusiastDeveloper/Tessera.git
cd Tessera
cp .env.example .env
```

**Backend:**

```bash
cd backend
pip install -e ".[dev]"
pytest              # run tests
lint-imports        # check architecture layering
ruff check app tests
mypy app
python -m app.main  # run the app
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev     # dev server with hot reload
npm run build   # production build
npm run lint
```

**Everything CI runs, in one shot:**

```bash
make check
```

## Architecture

**Three-layer backend:**

1. **API layer** (`app/api/`) - thin, request/response only
2. **Service layer** (`app/task_templates/`, `app/task_instances/`, etc.) - all business logic
3. **Data layer** (`app/db/`) - SQLAlchemy models, repositories

**Critical rule:** `scheduling_engine/` has zero imports of FastAPI or SQLAlchemy - it's pure Python, tested in isolation, and `import-linter` (`lint-imports`) enforces this at CI as a blocking check. See `backend/CLAUDE.md` for the full module map and layering rules; `frontend/CLAUDE.md` for frontend-specific notes.

## Testing strategy

Build order is scheduling engine first (tested in isolation), then the service layer, then the API - see architecture-plan Section 8. Required categories:

1. **Unit tests on the scheduling engine** - ~90%+ coverage target on that module specifically
2. **Scheduling algorithm acceptance tests** - design-doc Section 10's Worked Examples A-P, implemented as test fixtures
3. **Edit-scope/detach tests** - Worked Examples L-M
4. **Job-wiring integration tests** - every mutation must create/cancel the right background job(s)
5. **Reconciliation tests** - simulate a killed process, verify startup reconciliation restores consistency
6. **Architecture tests** - `import-linter`, plus an AST-walking pytest test that fails if `scheduling_engine/` imports forbidden modules

## Branching & CI

- Trunk-based: all work branches off `main`, which stays deployable
- Branch naming: `stage-0N-slug` for implementation stages, `feat/...` or `fix/...` for side work
- CI runs on every push and must be green before merging to `main`
- One PR per completed stage; tag `main` after each stage merges: `git tag stage-0N-done && git push --tags`

## This documentation site

This guide lives under `docsite/` (built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)) and is separate from `docs/`, which holds the internal design/architecture/planning documents. If you change user-facing behavior, update the relevant page here rather than the README - that's the whole point of having it. Preview locally with:

```bash
pip install mkdocs-material
mkdocs serve
```
