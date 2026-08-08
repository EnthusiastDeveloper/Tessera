# Multi-stage build for Tessera

# Stage 1: Backend dependencies
FROM python:3.12-slim as backend-builder

WORKDIR /build

COPY backend/pyproject.toml backend/requirements.txt* ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Stage 2: Frontend build
FROM node:20-alpine as frontend-builder

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