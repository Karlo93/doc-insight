from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from doc_insight.contracts.gateway import UpstreamReply
from doc_insight.gateway.http import HttpUpstream
from doc_insight.gateway.main import create_app
from doc_insight.testing.gateway import FakeUpstream
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def client_for(gateway):
    app = create_app(gateway)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client,
    ):
        yield client


def auth(token):
    return {"authorization": "Bearer " + token()}


@pytest.mark.parametrize(
    "tenant,expected", [("demo", 200), ("other", 200), ("third", 403)]
)
async def test_only_provisioned_tenants_reach_upstream(
    gateway, token, tenant, expected
):
    # Provisioning is checked before proxying so unknown tenants cannot reach internal services.
    gateway.settings.tenants = "demo,other"
    async with client_for(gateway) as client:
        response = await client.get(
            "/documents",
            headers={"authorization": "Bearer " + token({"tenant": tenant})},
        )
    assert response.status_code == expected
    if expected == 403:
        assert response.json()["error"]["code"] == "tenant_unavailable"
        assert not gateway.ingest.requests


async def test_forged_headers_stripped_with_real_asgi_upstream(gateway, token):
    upstream = FastAPI()
    captured = []

    @upstream.post("/ingest")
    async def ingest(request: Request):
        captured.append((dict(request.headers), await request.body()))
        return JSONResponse(
            {"document_id": str(uuid4()), "status": "uploaded"},
            202,
            headers={"set-cookie": "secret", "cache-control": "public"},
        )

    trace = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(upstream)) as outbound:
        gateway.ingest = HttpUpstream(outbound, "http://ingest")
        async with client_for(gateway) as client:
            response = await client.post(
                "/ingest",
                files={"file": ("test.pdf", b"%PDF-test")},
                headers={
                    **auth(token),
                    "X-Tenant-Id": "forged",
                    "X-User-Id": "admin",
                    "traceparent": trace,
                    "X-Request-Id": "test-request",
                    "Cookie": "private",
                    "Connection": "x-tenant-id",
                    "X-Forwarded-For": "forged",
                },
            )
    assert response.status_code == 202
    headers, body = captured[0]
    assert headers["x-tenant-id"] == "demo" and headers["x-user-id"] == "alice"
    assert headers["traceparent"] == trace and headers["x-request-id"] == "test-request"
    assert not {"authorization", "cookie", "x-forwarded-for"} & headers.keys()
    assert b"%PDF-test" in body and "multipart/form-data" in headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"] == "test-request"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "path,method",
    [("/ingest", "POST"), ("/query", "POST"), ("/documents/" + str(uuid4()), "GET")],
)
async def test_auth_required_and_routing(gateway, token, path, method):
    async with client_for(gateway) as client:
        denied = await client.request(method, path)
        assert denied.status_code == 401
        assert denied.json() == {
            "error": {"code": "unauthorized", "message": "invalid token"}
        }
        accepted = await client.request(
            method, path, headers=auth(token), content=b"{}"
        )
    assert accepted.status_code == 200
    target = gateway.query if path == "/query" else gateway.ingest
    request = target.requests[0]
    assert request[0:2] == (method, path)
    assert request[4] == gateway.settings.upstream_timeout_seconds * (
        1 if path == "/query" else 4
    )


@pytest.mark.parametrize("streamed", [False, True])
async def test_upload_limit(gateway, token, streamed):
    gateway.settings.max_upload_bytes = 4

    async def chunks():
        yield b"123"
        yield b"456"

    async with client_for(gateway) as client:
        response = await client.post(
            "/ingest", headers=auth(token), content=chunks() if streamed else b"123456"
        )
    assert response.status_code == 413
    assert gateway.ingest.requests == []


async def test_upload_streams_before_client_finishes(gateway, token):
    consumed = []
    upstream = FastAPI()

    @upstream.post("/ingest")
    async def ingest(request: Request):
        async for chunk in request.stream():
            consumed.append(chunk)
        return {"ok": True}

    async def chunks():
        yield b"first"
        assert consumed == [b"first"]
        yield b"second"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(upstream)) as outbound:
        gateway.ingest = HttpUpstream(outbound, "http://ingest")
        async with client_for(gateway) as client:
            assert (
                await client.post("/ingest", headers=auth(token), content=chunks())
            ).status_code == 200


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (404, b'{"error":{"code":"not_found","message":"not found"}}', 404),
        (404, b'{"error":{"code":"404","message":"Document not found"}}', 404),
        (
            415,
            b'{"error":{"code":"415","message":"Expected PDF, PNG, JPEG or TIFF bytes"}}',
            415,
        ),
        (422, b'{"detail":[{"input":"private"}]}', 502),
        (500, b"traceback private", 502),
        (504, b"traceback private", 504),
        (302, b"redirect private", 502),
        (400, b'{"error":{"code":"invalid","message":"bad"},"private":"secret"}', 502),
        (400, b"[]", 502),
        (400, b'{"error":null}', 502),
    ],
)
async def test_error_sanitization(gateway, token, status, body, expected):
    gateway.query.reply = UpstreamReply(status, body)
    async with client_for(gateway) as client:
        response = await client.post("/query", headers=auth(token))
    assert response.status_code == expected
    assert "private" not in response.text
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize(
    "exception,expected",
    [
        (httpx.ConnectError("private"), 502),
        (httpx.ReadTimeout("private"), 504),
        (TimeoutError("private"), 504),
    ],
)
async def test_transport_failures(gateway, token, exception, expected):
    async def fail(request):
        raise exception

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as outbound:
        gateway.query = HttpUpstream(outbound, "http://query")
        async with client_for(gateway) as client:
            response = await client.post("/query", headers=auth(token))
    assert response.status_code == expected and "private" not in response.text


async def test_rate_limit_and_isolation(gateway, token):
    gateway.limiter.burst = 2
    async with client_for(gateway) as client:
        responses = [await client.post("/query", headers=auth(token)) for _ in range(3)]
        for claims in ({"tenant": "other"}, {"sub": "bob"}):
            response = await client.post(
                "/query", headers={"authorization": "Bearer " + token(claims)}
            )
            assert response.status_code == 200
    assert [r.status_code for r in responses] == [200, 200, 429]
    assert responses[-1].headers["retry-after"] == "1"
    assert responses[-1].headers["x-ratelimit-remaining"] == "0"


@pytest.mark.parametrize("fail_open,expected", [(False, 503), (True, 200)])
async def test_redis_outage_policy(gateway, token, fail_open, expected):
    gateway.limiter.available = False
    gateway.settings.rate_limit_fail_open = fail_open
    async with client_for(gateway) as client:
        assert (
            await client.post("/query", headers=auth(token))
        ).status_code == expected
        assert (await client.get("/readyz")).status_code == 503


async def test_health_readiness_unknown_routes_and_request_ids(gateway):
    async with client_for(gateway) as client:
        for path, expected in (
            ("/healthz", 200),
            ("/readyz", 200),
            ("/missing", 404),
            ("/.well-known/jwks.json", 404),
        ):
            response = await client.get(path, headers={"x-request-id": "bad space"})
            assert response.status_code == expected
            assert response.headers["x-request-id"] != "bad space"
            assert response.headers["cache-control"] == "no-store"
        gateway.query.available = False
        assert (await client.get("/readyz")).status_code == 503
        assert (await client.get("/healthz")).status_code == 200


@pytest.mark.parametrize(
    "origins,expected", [("", 405), ("https://client.example", 200)]
)
async def test_cors_opt_in(gateway, origins, expected):
    gateway.settings.cors_origins = origins
    async with client_for(gateway) as client:
        response = await client.options(
            "/query",
            headers={
                "origin": "https://client.example",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization",
            },
        )
    assert response.status_code == expected
    assert ("access-control-allow-origin" in response.headers) == bool(origins)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("provider", ["fake", "http"])
async def test_upstream_contract(provider):
    async def body():
        yield b"one"
        yield b"two"

    async def handler(request):
        assert request.headers["x-tenant-id"] == "demo"
        assert await request.aread() == b"onetwo"
        return httpx.Response(202, json={"status": "uploaded"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        upstream = (
            FakeUpstream(UpstreamReply(202, b'{"status":"uploaded"}'))
            if provider == "fake"
            else HttpUpstream(client, "http://ingest")
        )
        reply = await upstream.exchange(
            "POST", "/ingest", {"x-tenant-id": "demo"}, body(), 5
        )
        assert reply.status == 202 and reply.body == b'{"status":"uploaded"}'
