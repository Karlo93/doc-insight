"""Internal HTTP boundary. The gateway alone authenticates tenant headers."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from doc_insight.contracts.query import QueryRequest, QueryResponse
from doc_insight.observability import configure, instrument_app
from doc_insight.query.runtime import Runtime
from doc_insight.query.service import QueryService, QuestionTooLong
from doc_insight.query.settings import get_settings
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure("query")
    runtime = Runtime(get_settings())
    app.state.runtime = runtime
    try:
        yield
    finally:
        runtime.close()


def create_app(service: QueryService | None = None) -> FastAPI:
    app = FastAPI(lifespan=lifespan if service is None else None)
    app.state.service = service
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, unexpected_error)
    app.add_api_route("/healthz", health, methods=["GET"])
    app.add_api_route("/readyz", ready, methods=["GET"])
    app.add_api_route("/query", query, methods=["POST"], response_model=QueryResponse)
    instrument_app(app)
    return app


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    # Pydantic's default errors echo input, which may include private questions.
    return error(422, "validation_error", "Invalid query request")


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return error(500, "internal_error", "Query operation failed")


def health() -> dict[str, str]:
    return {"status": "ok"}


def ready(request: Request) -> JSONResponse:
    try:
        if request.app.state.service is None:
            request.app.state.runtime.ready()
        return JSONResponse({"status": "ready"})
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        return error(503, "not_ready", "Query dependencies unavailable")


def query(
    body: QueryRequest, request: Request, x_tenant_id: str | None = Header(default=None)
) -> QueryResponse | JSONResponse:
    if (
        x_tenant_id is None
        or re.fullmatch(r"[A-Za-z0-9._-]{1,64}", x_tenant_id) is None
    ):
        return error(400, "invalid_tenant", "A valid X-Tenant-Id header is required")
    try:
        service: QueryService = (
            request.app.state.service or request.app.state.runtime.get_service()
        )
        if body.top_k > service.settings.query_top_k_max:
            return error(
                422,
                "validation_error",
                f"top_k limit is {service.settings.query_top_k_max}",
            )
        return service.query(x_tenant_id, body)
    except QuestionTooLong:
        return error(
            400,
            "question_too_long",
            "Question exceeds the 126 content token limit; refusing truncation",
        )
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        return error(503, "query_unavailable", "Query dependencies unavailable")


app = create_app()
