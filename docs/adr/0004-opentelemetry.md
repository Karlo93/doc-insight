# ADR-0004: OpenTelemetry with OTLP to a collector

Status: accepted. Date: 2026-09-10.

## Decision

Use OpenTelemetry traces and metrics with OTLP/HTTP export to a collector.
Services share five helpers. Stage observation has a Protocol and deterministic
fake; the SDK adapter is tested with in-memory exporters without a collector.
Providers and instruments belong to the process and are initialized once.
An unset endpoint selects explicit no-op providers. Global OTel providers are
left alone so embedding applications and tests do not overwrite each other.

Use one ASGI middleware for FastAPI request spans and request duration metrics.
Automatic FastAPI instrumentation can capture URL values and exception text;
our middleware only records route templates, status codes and error classes.
The FastAPI instrumentation dependency is locked with the SDK for compatibility,
but automatic instrumentation is not enabled. HTTPX and SQLAlchemy automatic
instrumentation are not installed. No document data enters telemetry.

## Alternatives and consequences

- Vendor SDKs tie application code to a backend. OTLP keeps that choice in the collector.
- Prometheus-only metrics cannot carry trace context across HTTP and queue messages.
- Automatic framework instrumentation gives more attributes and spans, but needs
  a broader sanitization policy. The smaller middleware provides the required signals.

Export adds background threads only when enabled. The SDK flushes providers on
normal process exit; abrupt termination can lose buffered observations. Collector
deployment is a separate infrastructure change. Stored pipeline output is unchanged.
