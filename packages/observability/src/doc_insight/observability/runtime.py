"""Process-owned providers; importing the package never starts an exporter."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from time import perf_counter

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DI_")

    otel_endpoint: HttpUrl | None = None
    otel_service_name: str | None = Field(default=None, min_length=1, max_length=64)
    env: str = Field(default="development", min_length=1, max_length=64)


class Telemetry:
    def __init__(
        self,
        service: str,
        traces: trace.TracerProvider,
        meters: metrics.MeterProvider,
    ) -> None:
        self.service = service
        self.traces = traces
        self.meters = meters
        self.tracer = traces.get_tracer("doc_insight.observability")
        meter = meters.get_meter("doc_insight.observability")
        self.stages = meter.create_histogram("di_stage_duration_seconds", unit="s")
        self.documents = meter.create_counter("di_documents_processed_total")
        self.requests = meter.create_histogram("di_request_duration_seconds", unit="s")

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started, status = perf_counter(), "processed"
        with self.tracer.start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        ) as span:
            try:
                yield
            except BaseException as error:
                status = "failed"
                span.set_status(trace.StatusCode.ERROR)
                span.set_attribute("error.type", type(error).__name__)
                raise
            finally:
                self.stages.record(
                    perf_counter() - started, {"stage": name, "service": self.service}
                )
                if name == "process":
                    self.documents.add(1, {"status": status})


_lock = Lock()
_configured = False
current = Telemetry("", trace.NoOpTracerProvider(), metrics.NoOpMeterProvider())


def configure(service_name: str) -> None:
    """Call once at startup, before instrumenting apps or starting worker threads."""
    global current, _configured
    with _lock:
        if _configured:
            return
        settings = Settings()
        service = settings.otel_service_name or service_name
        if not service.strip() or len(service) > 64:
            raise ValueError("Service name must contain 1-64 characters")
        if settings.otel_endpoint is None:
            current = Telemetry(
                service, trace.NoOpTracerProvider(), metrics.NoOpMeterProvider()
            )
        else:
            current = _exporting(service, settings)
        _configured = True


def _exporting(service: str, settings: Settings) -> Telemetry:
    endpoint = str(settings.otel_endpoint).rstrip("/")
    resource = Resource(
        {"service.name": service, "deployment.environment.name": settings.env}
    )
    traces = TracerProvider(resource=resource)
    traces.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    meters = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")
            )
        ],
    )
    return Telemetry(service, traces, meters)
