"""Safe stage telemetry and W3C trace propagation for service boundaries."""

from contextlib import AbstractContextManager

from doc_insight.contracts.telemetry import StageObserver
from doc_insight.observability import runtime
from doc_insight.observability.http import instrument_app as instrument_app
from doc_insight.observability.runtime import configure as configure
from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

__version__ = "0.1.0"
__all__ = ["configure", "extract", "inject", "instrument_app", "stage"]
_propagator = TraceContextTextMapPropagator()


def stage(name: str) -> AbstractContextManager[None]:
    """Use static stage names; 'process' counts one complete document attempt."""
    observer: StageObserver = runtime.current
    return observer.stage(name)


def inject(headers: dict[str, str]) -> dict[str, str]:
    """Copy the carrier, replacing stale context without propagating baggage."""
    result = {
        k: v
        for k, v in headers.items()
        if k.lower() not in {"traceparent", "tracestate", "baggage"}
    }
    _propagator.inject(result)
    result.pop("tracestate", None)
    return result


def extract(headers: dict[str, str]) -> Context:
    """Missing or invalid remote context starts a new trace, not an ambient one."""
    carrier = {k.lower(): v for k, v in headers.items() if k.lower() == "traceparent"}
    return _propagator.extract(carrier, context=Context())
