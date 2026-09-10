import pytest
from doc_insight.observability import inject, instrument_app, stage
from fastapi import FastAPI

from .conftest import measurements


def request(app, path, headers):
    messages = []
    route, _, query = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": route,
        "raw_path": route.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [
            (key.lower().encode(), value.encode()) for key, value in headers.items()
        ],
        "client": ("test", 1),
        "server": ("test", 80),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    # These in-memory handlers never suspend; no Windows event-loop socketpair is needed.
    coroutine = app(scope, receive, send)
    try:
        coroutine.send(None)
    except (StopIteration, ValueError):
        pass
    else:
        pytest.fail("The in-memory ASGI request unexpectedly suspended")
    finally:
        coroutine.close()
    return next(
        item["status"] for item in messages if item["type"] == "http.response.start"
    )


@pytest.mark.parametrize(
    "path,status,route",
    [
        (
            "/documents/private-filename?question=secret",
            200,
            "/documents/{document_id}",
        ),
        ("/missing-private", 404, "unmatched"),
        ("/fail?question=secret", 500, "/fail"),
    ],
)
def test_requests_are_counted_once_and_sanitized(telemetry, path, status, route):
    # Raw paths and request headers must not become high-cardinality or sensitive telemetry.
    app = FastAPI()

    @app.get("/documents/{document_id}")
    async def document(document_id: str):
        with stage("retrieve"):
            return {"id": document_id}

    @app.get("/fail")
    async def failure():
        raise ValueError("secret document contents")

    instrument_app(app)
    instrument_app(app)
    _, exporter, reader = telemetry
    with stage("caller"):
        headers = inject({"Authorization": "secret"})
    assert request(app, path, headers) == status
    spans = exporter.get_finished_spans()
    request_span = next(span for span in spans if span.name == route)
    assert request_span.parent.span_id == spans[0].context.span_id
    assert request_span.kind.name == "SERVER"
    assert request_span.attributes["http.response.status_code"] == status
    assert not request_span.events
    assert request_span.status.description is None
    assert all(
        "secret" not in str(span.attributes) and "private" not in span.name
        for span in spans
    )
    points = measurements(reader)["di_request_duration_seconds"]
    assert len(points) == 1
    assert points[0].count == 1 and points[0].sum >= 0
    assert points[0].attributes == {"route": route, "status": str(status)}
    if status == 200:
        assert (
            next(span for span in spans if span.name == "retrieve").parent.span_id
            == request_span.context.span_id
        )


def test_failure_after_response_start_keeps_the_sent_status(telemetry):
    from doc_insight.observability.http import RequestTelemetry

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("body iterator failed")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    scope = {"type": "http", "headers": [], "route": None}
    coroutine = RequestTelemetry(app)(scope, receive, send)
    with pytest.raises(RuntimeError, match="body iterator"):
        coroutine.send(None)
    _, exporter, reader = telemetry
    span = exporter.get_finished_spans()[0]
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.status.status_code.name == "ERROR"
    point = measurements(reader)["di_request_duration_seconds"][0]
    assert point.attributes == {"route": "unmatched", "status": "200"}
