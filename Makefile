.PHONY: check backend-check frontend-check \
        backend-lint backend-typecheck backend-imports backend-test \
        frontend-lint frontend-typecheck frontend-test frontend-build \
        run

COMPOSE := $(shell command -v podman-compose 2>/dev/null || command -v docker-compose 2>/dev/null || echo "docker compose")
PORT ?= 8000

## Run everything CI runs, in one shot. Use before opening/merging a PR.
check: backend-check frontend-check
	@echo ""
	@echo "All checks passed."

## Build and start the full stack in a container, then open it in a browser.
run:
	@if [ ! -f .env ]; then \
		echo "No .env found - copying .env.example (edit it with your own SECRET_KEY before real use)."; \
		cp .env.example .env; \
	fi
	$(COMPOSE) up -d --build
	@echo "Waiting for Tessera to become healthy at http://localhost:$(PORT) ..."
	@for i in $$(seq 1 60); do \
		if curl -sf http://localhost:$(PORT)/health >/dev/null 2>&1; then \
			echo "Tessera is up - opening http://localhost:$(PORT)"; \
			(xdg-open http://localhost:$(PORT) 2>/dev/null || open http://localhost:$(PORT) 2>/dev/null || echo "Open http://localhost:$(PORT) in your browser") & \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Timed out waiting for the health check - inspect with: $(COMPOSE) logs"; \
	exit 1

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
