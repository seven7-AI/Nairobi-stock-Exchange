# syntax=docker/dockerfile:1
#
# nse-be — NSE Analytics Backend
#
# Multi-stage: dependencies resolve from uv.lock in the builder, so the final
# image carries no build toolchain and no uv cache.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Install dependencies before copying source: the layer is then cached across
# every change that does not touch the lockfile.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY app ./app
COPY alembic.ini start_celery.py indicators.txt README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Never run the service as root.
RUN useradd --create-home --shell /bin/bash --uid 10001 nse

WORKDIR /srv/app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app ./app
COPY --from=builder /build/alembic.ini /build/start_celery.py /build/indicators.txt ./

RUN mkdir -p /srv/app/logs /srv/app/reports/daily /srv/app/reports/weekly \
             /srv/app/reports/monthly /srv/app/research/data \
    && chown -R nse:nse /srv/app

USER nse

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
