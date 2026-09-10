# syntax=docker/dockerfile:1.7
FROM python:3.12.13-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" HOME=/home/di \
    DI_MODEL_CACHE=/home/di/.cache/doc-insight/models
RUN groupadd --gid 10001 di && useradd --uid 10001 --gid di --create-home di
WORKDIR /app

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
ARG APP
COPY pyproject.toml uv.lock ./
COPY apps/gateway/pyproject.toml apps/gateway/pyproject.toml
COPY apps/ingest/pyproject.toml apps/ingest/pyproject.toml
COPY apps/query/pyproject.toml apps/query/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/contracts/pyproject.toml packages/contracts/pyproject.toml
COPY packages/domain/pyproject.toml packages/domain/pyproject.toml
COPY packages/observability/pyproject.toml packages/observability/pyproject.toml
COPY packages/testing/pyproject.toml packages/testing/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package doc-insight-${APP} --no-install-workspace
COPY apps apps
COPY packages packages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package doc-insight-${APP}
COPY scripts/warm_models.py /tmp/warm_models.py
# Query warms the same cache when its real worker dependency replaces the stub.
RUN mkdir -p "$DI_MODEL_CACHE" && \
    if [ "$APP" = worker ]; then python /tmp/warm_models.py; \
    elif [ "$APP" = query ] && python -c 'import doc_insight.worker'; then \
    python /tmp/warm_models.py; fi

FROM base AS runtime
ARG APP
RUN if [ "$APP" = worker ]; then \
    apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-hrv && \
    rm -rf /var/lib/apt/lists/*; fi
COPY --from=builder /opt/venv /opt/venv
# Hub tree metadata is mode 0600; it must belong to the runtime user for offline loads.
COPY --from=builder --chown=10001:10001 /home/di/.cache/doc-insight/models /home/di/.cache/doc-insight/models
COPY alembic.ini ./
COPY migrations migrations
COPY scripts/container_health.py /usr/local/lib/container_health.py
COPY scripts/dev_issuer.py /usr/local/lib/dev_issuer.py
# Named volumes inherit this ownership on first use, so the issuer job can write them.
RUN mkdir -p /issuer /jwks && chown 10001:10001 /issuer /jwks
COPY scripts/container_entrypoint.sh /usr/local/bin/container-entrypoint
ENV DI_CONTAINER_APP=${APP} HF_HUB_OFFLINE=1
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 \
    CMD ["python", "/usr/local/lib/container_health.py"]
ENTRYPOINT ["/bin/sh", "/usr/local/bin/container-entrypoint"]
