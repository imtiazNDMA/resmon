# syntax=docker/dockerfile:1
# Shared multi-stage base for api + workers + orchestration (plan 01 T-05).
# Build context is the repo root; service command is set per-service in compose.

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Workspace manifests + member sources (each member is a workspace package).
COPY pyproject.toml uv.lock ./
COPY core ./core
COPY db ./db
COPY pipelines ./pipelines
COPY orchestration ./orchestration
COPY api ./api

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13-slim AS runtime
# libpq for psycopg, then a non-root user (NFR-SEC-3).
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER app
CMD ["python", "-c", "print('reservoir-app base image; set a command in compose')"]
