import asyncio

import httpx
import pytest
from doc_insight.gateway.http import HttpUpstream
from doc_insight.gateway.main import create_app
from doc_insight.observability import runtime
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

pytestmark = pytest.mark.anyio


async def empty_body():
    yield b""


async def test_shared_client_never_replays_session_cookie():
    observed = []

    def handler(request):
        observed.append(dict(request.headers))
        return httpx.Response(
            200, json={}, headers={"set-cookie": "session=private; Path=/"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        upstream = HttpUpstream(client, "http://ingest")
        for tenant in ("first", "second"):
            await upstream.exchange(
                "POST", "/ingest", {"x-tenant-id": tenant}, empty_body(), 2
            )
        assert await upstream.ready()
    assert all("cookie" not in headers for headers in observed)


@pytest.mark.parametrize("status,expected", [(200, True), (503, False), (302, False)])
async def test_upstream_readiness(status, expected):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status))
    ) as client:
        assert await HttpUpstream(client, "http://upstream").ready() is expected


async def test_total_deadline_and_readiness_connection_failure():
    async def stall(request):
        await asyncio.Event().wait()

    async with httpx.AsyncClient(transport=httpx.MockTransport(stall)) as client:
        with pytest.raises(TimeoutError):
            await HttpUpstream(client, "http://upstream").exchange(
                "POST", "/query", {}, empty_body(), 0.01
            )

    def fail(request):
        raise httpx.ConnectError("private")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        assert not await HttpUpstream(client, "http://upstream").ready()


async def test_one_span_with_ids_and_no_credentials(gateway, token, monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        runtime, "current", runtime.Telemetry("gateway", provider, NoOpMeterProvider())
    )
    monkeypatch.setattr(runtime, "_configured", True)
    app = create_app(gateway)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client,
    ):
        credential = token()
        assert (
            await client.post(
                "/query",
                headers={"authorization": "Bearer " + credential},
                content=b"private question",
            )
        ).status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["tenant.id"] == "demo"
    assert spans[0].attributes["user.id"] == "alice"
    assert credential not in str(spans[0].attributes)
    assert "private question" not in str(spans[0].attributes)
    provider.shutdown()


@pytest.mark.parametrize("cors", [False, True])
async def test_unexpected_error_still_has_security_headers(gateway, monkeypatch, cors):
    gateway.settings.cors_origins = "https://client.example" if cors else ""

    async def fail(identity):
        raise RuntimeError("private")

    monkeypatch.setattr(gateway.auth, "authenticate", fail)
    app = create_app(gateway)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client,
    ):
        response = await client.post(
            "/query",
            headers={
                "authorization": "Bearer anything",
                "origin": "https://client.example",
            },
        )
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    assert "private" not in response.text
    if cors:
        assert (
            response.headers["access-control-allow-origin"] == "https://client.example"
        )
