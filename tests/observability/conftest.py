import pytest
from doc_insight.observability import runtime
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def telemetry(monkeypatch):
    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    resource = Resource({"service.name": "test-service"})
    traces = TracerProvider(resource=resource)
    traces.add_span_processor(SimpleSpanProcessor(spans))
    meters = MeterProvider(resource=resource, metric_readers=[reader])
    instance = runtime.Telemetry("test-service", traces, meters)
    monkeypatch.setattr(runtime, "current", instance)
    monkeypatch.setattr(runtime, "_configured", True)
    yield instance, spans, reader
    traces.shutdown()
    meters.shutdown()


def measurements(reader):
    data = reader.get_metrics_data()
    return {
        metric.name: metric.data.data_points
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
