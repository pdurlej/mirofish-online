# syntax=docker/dockerfile:1

FROM node:22-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev --no-cache

COPY backend/ ./backend/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist/

EXPOSE 3000

# One process preserves the in-process run queue; threads handle concurrent polling.
CMD ["/app/backend/.venv/bin/gunicorn", "--chdir", "/app/backend", "--bind", "0.0.0.0:3000", "--workers", "1", "--threads", "8", "--timeout", "300", "--graceful-timeout", "60", "--no-control-socket", "app:create_app()"]
