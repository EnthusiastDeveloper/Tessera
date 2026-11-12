# Multi-stage build for Tessera

# Stage 1: Backend dependencies
FROM python:3.12-slim AS backend-builder

# The builder runs as root in a throwaway stage, so pip's "running as root" advice
# does not apply here.
ENV PIP_ROOT_USER_ACTION=ignore

WORKDIR /build

COPY backend/pyproject.toml ./

# Install only the runtime dependencies listed in pyproject.toml, not the project
# itself. The runtime stage runs `python -m app.main` from /app with the source copied
# in, so an install of the tessera package would be dead weight - and an editable one
# (`pip install -e .`) leaves a .pth pointing at /build, which the runtime image does
# not have. Copying only pyproject.toml keeps this layer cached across code changes.
RUN pip install --no-cache-dir --upgrade pip && \
    python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Frontend build
# Node 24 is the current LTS (Node 20 reached end-of-life in April 2026); keep this in
# step with node-version in .github/workflows/ci.yml.
FROM node:24-alpine AS frontend-builder

# npm comes with the base image, so its "new major version available" notice is noise.
ENV NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false

WORKDIR /build

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 3: Runtime
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy Python dependencies from backend-builder
COPY --from=backend-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy application code
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY docker/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Copy frontend build
COPY --from=frontend-builder /build/dist ./static

# Create data directory for SQLite
RUN mkdir -p /app/data && chown -R nobody:nogroup /app/data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').close()" || exit 1

USER nobody

# Apply migrations, then run the application - see entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]