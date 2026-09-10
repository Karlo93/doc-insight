"""One request span and duration, containing only route templates and statuses."""

from time import perf_counter

from doc_insight.observability import runtime
from fastapi import FastAPI
from opentelemetry.trace import Span, SpanKind, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _finish(
    scope: Scope, span: Span, status: int, started: float, telemetry: runtime.Telemetry
) -> None:
    """Record the resolved route template and status without raw URLs or query strings."""
    # Routing fills this after dispatch; raw paths would leak IDs and inflate cardinality.
    route = getattr(scope.get("route"), "path", "unmatched")
    span.update_name(route)
    span.set_attribute("http.route", route)
    span.set_attribute("http.response.status_code", status)
    if status >= 500:
        span.set_status(StatusCode.ERROR)
    telemetry.requests.record(
        perf_counter() - started, {"route": route, "status": str(status)}
    )


class RequestTelemetry:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Trace HTTP lifetime while excluding payloads and exception messages."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from doc_insight.observability import extract

        telemetry = runtime.current
        started, status, sent = perf_counter(), 500, False
        headers = {
            k.decode("latin1"): v.decode("latin1")
            for k, v in scope["headers"]
            if k.lower() == b"traceparent"
        }

        async def send_response(message: Message) -> None:
            nonlocal status, sent
            if message["type"] == "http.response.start":
                status, sent = message["status"], True
            await send(message)

        with telemetry.tracer.start_as_current_span(
            "http.request",
            context=extract(headers),
            kind=SpanKind.SERVER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                await self.app(scope, receive, send_response)
            except BaseException as error:
                # A body that fails after the start line was still a 200 to the client.
                status = status if sent else 500
                span.set_status(StatusCode.ERROR)
                span.set_attribute("error.type", type(error).__name__)
                raise
            finally:
                _finish(scope, span, status, started, telemetry)


def instrument_app(app: FastAPI) -> None:
    """Install before serving; repeated calls do not duplicate observations."""
    if not getattr(app.state, "di_instrumented", False):
        app.add_middleware(RequestTelemetry)
        app.state.di_instrumented = True
