FROM ghcr.io/astral-sh/uv:0.11.2 AS uv
FROM python:3.12.13-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages
RUN uv sync --locked --package doc-insight-gateway --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH" DI_GATEWAY_HOST=0.0.0.0
USER 10001:10001
EXPOSE 8000
CMD ["di-gateway", "serve"]
