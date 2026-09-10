from unittest.mock import Mock

import pytest
from doc_insight.observability import configure, inject, runtime, stage
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def reset_configuration(monkeypatch):
    monkeypatch.setattr(runtime, "_configured", False)
    monkeypatch.setattr(runtime, "current", runtime.current)


def test_no_endpoint_is_noop_and_configuration_is_once(monkeypatch):
    exporter = Mock(side_effect=AssertionError("Exporter must not be created"))
    monkeypatch.setattr(runtime, "_exporting", exporter)
    global_provider = trace.get_tracer_provider()
    configure("worker")
    instance = runtime.current
    assert isinstance(instance.traces, trace.NoOpTracerProvider)
    assert isinstance(instance.meters, metrics.NoOpMeterProvider)
    with stage("process"):
        assert not trace.get_current_span().is_recording()
    assert inject({"traceparent": "stale"}) == {}
    configure("query")
    assert runtime.current is instance
    assert trace.get_tracer_provider() is global_provider


def test_export_configuration_and_reuse(monkeypatch):
    exporter = InMemorySpanExporter()
    span_factory = Mock(return_value=exporter)
    metric_factory = Mock()
    reader = InMemoryMetricReader()
    monkeypatch.setattr(runtime, "OTLPSpanExporter", span_factory)
    monkeypatch.setattr(runtime, "OTLPMetricExporter", metric_factory)
    monkeypatch.setattr(
        runtime, "PeriodicExportingMetricReader", lambda exporter: reader
    )
    monkeypatch.setenv("DI_OTEL_ENDPOINT", "http://localhost:4318/collector/")
    monkeypatch.setenv("DI_OTEL_SERVICE_NAME", "override")
    monkeypatch.setenv("DI_ENV", "test")
    configure("worker")
    instance = runtime.current
    try:
        configure("worker")
        assert runtime.current is instance
        span_factory.assert_called_once_with(
            endpoint="http://localhost:4318/collector/v1/traces"
        )
        metric_factory.assert_called_once_with(
            endpoint="http://localhost:4318/collector/v1/metrics"
        )
        with stage("extract"):
            pass
        instance.traces.force_flush()
        assert dict(exporter.get_finished_spans()[0].resource.attributes) == {
            "service.name": "override",
            "deployment.environment.name": "test",
        }
    finally:
        instance.traces.shutdown()
        instance.meters.shutdown()


@pytest.mark.parametrize(
    "variable,value",
    [
        ("DI_OTEL_ENDPOINT", "not-a-url"),
        ("DI_OTEL_ENDPOINT", "ftp://localhost"),
        ("DI_ENV", ""),
        ("DI_OTEL_SERVICE_NAME", ""),
    ],
)
def test_invalid_configuration_fails_at_startup(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError):
        configure("worker")


def test_invalid_service_name():
    with pytest.raises(ValueError, match="Service name"):
        configure(" ")
