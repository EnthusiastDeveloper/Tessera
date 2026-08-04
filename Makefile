.PHONY: check backend-check frontend-check \
        backend-lint backend-typecheck backend-imports backend-test \
        frontend-lint frontend-typecheck frontend-test frontend-build

## Run everything CI runs, in one shot. Use before opening/merging a PR.
check: backend-check frontend-check
	@echo ""
	@echo "All checks passed."

backend-check: backend-lint backend-typecheck backend-imports backend-test

frontend-check: frontend-lint frontend-typecheck frontend-test frontend-build

backend-lint:
	cd backend && ruff check app tests && ruff format --check app tests

backend-typecheck:
	cd backend && mypy app

backend-imports:
	cd backend && lint-imports

backend-test:
	cd backend && pytest

frontend-lint:
	cd frontend && npm run lint

frontend-typecheck:
	cd frontend && npm run type-check

frontend-test:
	cd frontend && npm run test

frontend-build:
	cd frontend && npm run build
