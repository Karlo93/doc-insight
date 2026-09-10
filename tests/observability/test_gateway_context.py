from doc_insight.contracts.gateway import Identity
from doc_insight.gateway.proxy import forwarded_headers
from doc_insight.observability import extract, stage
from opentelemetry.trace import get_current_span
from starlette.requests import Request


def test_gateway_injects_active_span_and_discards_caller_baggage(telemetry):
    # The downstream span must be the gateway's child, not merely share the caller's trace ID.
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"traceparent", b"untrusted"),
                (b"baggage", b"secret"),
                (b"authorization", b"Bearer secret"),
            ],
        }
    )
    request.state.request_id = "request-id"
    with stage("gateway"):
        gateway = get_current_span().get_span_context()
        headers = forwarded_headers(request, Identity("demo", "alice"))
        with telemetry[0].tracer.start_as_current_span(
            "ingest", context=extract(headers)
        ):
            assert get_current_span().get_span_context().trace_id == gateway.trace_id
    spans = telemetry[1].get_finished_spans()
    assert spans[0].parent.span_id == gateway.span_id
    assert "baggage" not in headers and "authorization" not in headers
    assert headers["x-tenant-id"] == "demo"
