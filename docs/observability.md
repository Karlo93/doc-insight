# Observability

`doc_insight.observability` exports `configure`, `instrument_app`, `stage`,
`inject` and `extract`. Add `doc-insight-observability` as a workspace dependency
when adopting it in a service. Call `configure(service_name)` at process startup,
before starting threads or serving requests. The first successful call wins;
restart the process after changing configuration.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DI_OTEL_ENDPOINT` | Unset | OTLP/HTTP base URL; unset or empty installs no-op providers |
| `DI_OTEL_SERVICE_NAME` | `configure` argument | Override the resource service name and stage metric service label |
| `DI_OTEL_TIMEOUT_SECONDS` | `3` | Bound on every export attempt, including the flush at process exit; 0 < value ≤ 60 |
| `DI_ENV` | `development` | Resource `deployment.environment.name` |

The shared package validates these settings once. App settings remain owned by
each app. Environment variables must be exported to Python; `.env.example` is
a reference and this package does not load `.env` files automatically.
Use an HTTP or HTTPS base endpoint such as `http://localhost:4318`:
the package appends `/v1/traces` and `/v1/metrics`. Inside a container network,
use the collector service URL, for example `http://otel-collector:4318`.
Do not include a signal suffix. Leave the variable unset or empty to disable export.
When the collector is unreachable, each export attempt gives up after
`DI_OTEL_TIMEOUT_SECONDS`, including the flush at process exit, so a missing
collector delays a command by at most a few seconds instead of blocking it.

```python
from fastapi import FastAPI
from doc_insight.observability import configure, instrument_app, stage

configure("query")
app = FastAPI()
instrument_app(app)

# Within a handler or worker operation:
with stage("retrieve"):
    pass  # Run the service operation here.
```

Call `instrument_app` before FastAPI builds its middleware stack. Repeated calls
on the same app are safe. It creates one server span and one duration observation
per HTTP request, including unmatched routes and failures. Do not also enable
automatic FastAPI instrumentation. Non-HTTP ASGI traffic passes through unchanged.

| Signal | Attributes | Meaning |
| --- | --- | --- |
| Stage span | Error class on failure | One span per `stage(name)` block; children inherit the active trace |
| `di_stage_duration_seconds` histogram | `stage`, `service` | Elapsed wall time in seconds, including failed stages |
| `di_documents_processed_total` counter | `status` = `processed` or `failed` | One increment when a `stage("process")` block exits |
| Request span | `http.route`, `http.response.status_code`, optional `error.type` | Route template, status and error class |
| `di_request_duration_seconds` histogram | `route`, `status` | Time until the downstream ASGI call finishes, including response streaming |

Wrap each document attempt once in `stage("process")`. Nested stages use other
names. The CLI wraps `index_file` this way, with `extract`, `analyze`, `embed`,
and `store` child spans. It still prints all four durations. Direct `index_file`
callers get those four stages and may supply their own process span. The counter
measures attempts, including replays, rather than distinct stored documents.

Use static stage names and route templates. Never put document text, questions,
filenames, vectors, credentials, tenant IDs or user IDs in stage names or labels.
Unmatched requests use `unmatched`, never the raw path. Exception events,
messages and stack traces are disabled; failures record the class and error
status only. Resource attributes contain only service and environment. No
automatic host/process discovery or HTTP header capture is enabled.

Trace propagation uses only W3C `traceparent`; it does not establish identity.
Tenant and user headers remain the caller's separate responsibility.

```python
from opentelemetry.context import attach, detach
from doc_insight.observability import extract, inject, stage

with stage("publish"):
    fields = inject({"event_id": "example"})

# At the receiving HTTP or Redis boundary:
token = attach(extract(fields))
try:
    with stage("process"):
        pass  # Process one message here.
finally:
    detach(token)
```

`inject` returns a new dict, preserving other fields and replacing stale trace
headers. Baggage and tracestate are omitted. `extract` accepts case-insensitive
header names and returns an isolated context; missing or invalid traceparent
starts a new trace. Always detach an attached context after processing a message.

Without an endpoint, helpers create no exporters or background threads and
leave global providers unchanged. With export enabled, batch traces and periodic
metrics reuse their providers; the SDK flushes on normal process exit.

Run `uv run --locked --all-packages pytest tests/observability --no-cov` for
in-memory SDK, propagation, configuration, HTTP privacy and pipeline wiring tests.
The normal offline suite needs no collector. See [ADR-0004](adr/0004-opentelemetry.md)
for alternatives. See [pipeline setup](pipeline.md) for the existing CLI prerequisites.
