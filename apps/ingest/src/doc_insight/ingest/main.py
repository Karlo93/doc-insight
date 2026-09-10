"""Internal tenant-scoped HTTP API; credentials are verified by the gateway."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from tempfile import TemporaryFile
from typing import BinaryIO, cast
from uuid import UUID

from doc_insight.ingest.runtime import Resources, create_resources
from doc_insight.ingest.service import register
from doc_insight.ingest.settings import Settings, get_settings
from doc_insight.ingest.upload import UploadBody
from doc_insight.observability import configure, instrument_app
from doc_insight.worker.extraction import UnsupportedMediaType
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException


def tenant(request: Request) -> str:
    value = request.headers.get("x-tenant-id", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value):
        raise HTTPException(400, "A valid X-Tenant-Id is required")
    return value


def resources(request: Request) -> Resources:
    return cast(Resources, request.app.state.resources)


async def ingest(request: Request) -> dict[str, str]:
    owner = tenant(request)
    settings: Settings = request.app.state.settings
    with TemporaryFile(mode="w+b") as temporary:
        stream = cast(BinaryIO, temporary)
        upload = UploadBody(stream, settings.max_upload_bytes)
        await upload.read(request)
        clients = resources(request)
        return await run_in_threadpool(
            register,
            owner,
            upload,
            stream,
            clients.repository,
            clients.objects,
        )


async def document(document_id: UUID, request: Request) -> dict[str, object]:
    record = await run_in_threadpool(
        resources(request).repository.get_document,
        tenant(request),
        document_id,
    )
    if record is None:
        raise HTTPException(404, "Document not found")
    values = record.model_dump(
        mode="json",
        include={
            "status",
            "filename",
            "page_count",
            "language",
            "pipeline_version",
            "created_at",
            "processed_at",
            "error",
        },
    )
    return {"document_id": str(record.id), **values}


async def health() -> dict[str, str]:
    return {"status": "ok"}


async def ready(request: Request) -> dict[str, str]:
    await run_in_threadpool(resources(request).ready)
    return {"status": "ok"}


async def error_response(request: Request, error: Exception) -> JSONResponse:
    status, message = 503, "Service dependency unavailable"
    if isinstance(error, StarletteHTTPException):
        status, message = error.status_code, str(error.detail)
    elif isinstance(error, UnsupportedMediaType):
        status, message = 415, "Expected PDF, PNG, JPEG or TIFF bytes"
    elif isinstance(error, MultipartParseError):
        status, message = 400, "Invalid multipart upload"
    elif isinstance(error, RequestValidationError):
        status, message = 422, "Invalid request"
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": str(status), "message": message},
        },
    )


def create_app(
    supplied: Resources | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure("ingest")
        app.state.settings = settings or get_settings()
        app.state.resources = supplied or create_resources(app.state.settings)
        try:
            yield
        finally:
            if supplied is None:
                app.state.resources.close()

    app = FastAPI(lifespan=lifespan)
    app.add_api_route("/ingest", ingest, methods=["POST"], status_code=202)
    app.add_api_route("/documents/{document_id}", document, methods=["GET"])
    app.add_api_route("/healthz", health, methods=["GET"])
    app.add_api_route("/readyz", ready, methods=["GET"])
    for exception in (
        StarletteHTTPException,
        UnsupportedMediaType,
        MultipartParseError,
        RequestValidationError,
        Exception,
    ):
        app.add_exception_handler(exception, error_response)
    instrument_app(app)
    return app


app = create_app()
