"""Gateway ASGI entry point; outbound clients belong to the application lifespan."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from doc_insight.gateway.auth import Authenticator, public_jwks
from doc_insight.gateway.http import HttpJwksSource, HttpUpstream
from doc_insight.gateway.middleware import CorsPolicy, ResponsePolicy
from doc_insight.gateway.proxy import Gateway
from doc_insight.gateway.rate_limit import RedisRateLimiter
from doc_insight.gateway.responses import error
from doc_insight.gateway.settings import get_settings
from doc_insight.observability import configure, instrument_app
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from redis.asyncio import Redis
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response


@asynccontextmanager
async def production_gateway() -> AsyncIterator[Gateway]:
    settings = get_settings()
    async with (
        httpx.AsyncClient(follow_redirects=False, trust_env=False) as client,
        # Query saturation must not starve signing-key refresh of a connection.
        httpx.AsyncClient(follow_redirects=False, trust_env=False) as identity_client,
        Redis.from_url(
            str(settings.redis_url),
            socket_timeout=settings.redis_timeout_seconds,
            socket_connect_timeout=settings.redis_timeout_seconds,
        ) as redis,
    ):
        yield Gateway(
            settings,
            Authenticator(
                HttpJwksSource(identity_client, str(settings.jwks_url)), settings
            ),
            RedisRateLimiter(redis, settings.rate_limit_rps, settings.rate_limit_burst),
            HttpUpstream(
                client, str(settings.ingest_url), settings.max_upstream_response_bytes
            ),
            HttpUpstream(
                client, str(settings.query_url), settings.max_upstream_response_bytes
            ),
        )


def configure_runtime(app: FastAPI, gateway: Gateway) -> None:
    configure("gateway")
    app.state.gateway = gateway
    app.state.jwks = None
    if gateway.settings.dev_jwks_path:
        document = json.loads(gateway.settings.dev_jwks_path.read_text())
        # Serve only public RSA fields, even if the source contains extra metadata.
        app.state.jwks = public_jwks(document)


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def ready(request: Request) -> Response:
    gateway: Gateway = request.app.state.gateway
    results = await asyncio.gather(
        gateway.limiter.ready(),
        gateway.ingest.ready(),
        gateway.query.ready(),
        return_exceptions=True,
    )
    if all(result is True for result in results):
        return JSONResponse({"status": "ready"})
    return error(503, "not_ready", "dependencies unavailable")


async def jwks(request: Request) -> Response:
    if request.app.state.jwks is None:
        return error(404, "not_found", "not found")
    return JSONResponse(request.app.state.jwks)


async def ingest(request: Request) -> Response:
    gateway: Gateway = request.app.state.gateway
    return await gateway.proxy(request, "/ingest", True)


async def document(request: Request, document_id: UUID) -> Response:
    gateway: Gateway = request.app.state.gateway
    return await gateway.proxy(request, f"/documents/{document_id}", True)


async def query(request: Request) -> Response:
    gateway: Gateway = request.app.state.gateway
    return await gateway.proxy(request, "/query", False)


async def documents(
    request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
) -> Response:
    gateway: Gateway = request.app.state.gateway
    return await gateway.proxy(
        request, f"/documents?limit={limit}&offset={offset}", True
    )


async def usage(request: Request) -> Response:
    gateway: Gateway = request.app.state.gateway
    return await gateway.proxy(request, "/usage", False)


async def validation_error(request: Request, exc: Exception) -> Response:
    return error(422, "validation_error", "invalid request")


async def http_error(request: Request, exc: Exception) -> Response:
    status = exc.status_code if isinstance(exc, HTTPException) else 500
    return error(status, "http_error", "request rejected")


def create_app(gateway: Gateway | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if gateway is not None:
            configure_runtime(app, gateway)
            yield
        else:
            async with production_gateway() as runtime:
                configure_runtime(app, runtime)
                yield

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )
    app.add_api_route("/healthz", health, methods=["GET"])
    app.add_api_route("/readyz", ready, methods=["GET"])
    app.add_api_route("/.well-known/jwks.json", jwks, methods=["GET"])
    app.add_api_route("/ingest", ingest, methods=["POST"])
    app.add_api_route("/documents/{document_id}", document, methods=["GET"])
    app.add_api_route("/documents", documents, methods=["GET"])
    app.add_api_route("/usage", usage, methods=["GET"])
    app.add_api_route("/query", query, methods=["POST"])
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_middleware(CorsPolicy, settings=gateway.settings if gateway else None)
    app.add_middleware(ResponsePolicy)
    instrument_app(app)
    return app


app = create_app()
