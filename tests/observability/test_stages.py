import pytest
from doc_insight.observability import extract, inject, stage
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from .conftest import measurements


def test_stage_spans_and_histograms(telemetry, monkeypatch):
    from doc_insight.observability import runtime

    times = iter([10.0, 10.25, 20.0, 20.5, 30.0, 31.0, 40.0, 42.0])
    monkeypatch.setattr(runtime, "perf_counter", lambda: next(times))
    for name in ("extract", "analyze", "embed", "store"):
        with stage(name):
            pass
    _, spans, reader = telemetry
    assert [span.name for span in spans.get_finished_spans()] == [
        "extract",
        "analyze",
        "embed",
        "store",
    ]
    points = measurements(reader)["di_stage_duration_seconds"]
    assert [(point.attributes, point.count, point.sum) for point in points] == [
        ({"stage": name, "service": "test-service"}, 1, seconds)
        for name, seconds in zip(
            ("extract", "analyze", "embed", "store"), (0.25, 0.5, 1.0, 2.0)
        )
    ]


@pytest.mark.parametrize("fails", [False, True])
def test_document_outcome_and_failure_privacy(telemetry, fails):
    error = ValueError("private question and document contents")
    try:
        with stage("process"), stage("extract"):
            if fails:
                raise error
    except ValueError as raised:
        assert raised is error
    _, exporter, reader = telemetry
    spans = exporter.get_finished_spans()
    assert spans[0].parent.span_id == spans[1].context.span_id
    assert all(
        span.status.status_code.name == ("ERROR" if fails else "UNSET")
        for span in spans
    )
    assert all(not span.events and span.status.description is None for span in spans)
    assert "private" not in str([dict(span.attributes) for span in spans])
    points = measurements(reader)["di_documents_processed_total"]
    assert [(point.attributes, point.value) for point in points] == [
        ({"status": "failed" if fails else "processed"}, 1)
    ]


def test_trace_propagates_to_another_provider(telemetry):
    other = TracerProvider()
    exported = InMemorySpanExporter()
    other.add_span_processor(SimpleSpanProcessor(exported))
    carrier = {"event_id": "123", "TraceParent": "stale", "baggage": "private"}
    with stage("publish"):
        headers = inject(carrier)
        parent = trace.get_current_span().get_span_context()
    try:
        with other.get_tracer("consumer").start_as_current_span(
            "consume", context=extract(headers)
        ) as child:
            assert child.get_span_context().trace_id == parent.trace_id
        span = exported.get_finished_spans()[0]
        assert span.parent.span_id == parent.span_id
        assert span.parent.is_remote
        assert carrier == {
            "event_id": "123",
            "TraceParent": "stale",
            "baggage": "private",
        }
        assert set(headers) == {"event_id", "traceparent"}
    finally:
        other.shutdown()


@pytest.mark.parametrize("headers", [{}, {"traceparent": "invalid"}])
def test_invalid_or_missing_context_does_not_inherit_ambient_trace(telemetry, headers):
    instance, _, _ = telemetry
    with stage("ambient"):
        ambient = trace.get_current_span().get_span_context()
        with instance.tracer.start_as_current_span(
            "remote", context=extract(headers)
        ) as remote:
            assert remote.get_span_context().trace_id != ambient.trace_id
