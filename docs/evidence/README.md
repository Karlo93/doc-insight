# Metrics and trace examples

These captures use generated repository fixtures on 2026-09-10. They illustrate
the observable service paths at that time; they are not current uptime or latency
guarantees. For live access and signal definitions, see [observability](../observability.md).

## A user question

![Gateway, query and OpenAI spans](query-trace.png)

A single user question produces six connected spans: gateway `/query`, query
`/query`, embedding, retrieval, generation and `openai.responses`.
Trace ID: `e3b97b2ea62e4431b973aea0576dc1d2`.

This capture took 4.93 seconds during concurrent image building. It demonstrates
trace parentage; the [benchmark](../../benchmark/README.md) measures load separately.

## An upload through background processing

![Gateway, ingest, relay and worker spans](ingest-trace.png)

The 10-MiB upload contains ten spans across gateway, ingest, relay and worker.
The worker inherits the relay's publication context; extraction, analysis,
embedding and storage are child spans.
Trace ID: `e4c55749fcfb4fc9852ebd0aeb9d0503`.

Use a fresh generated upload to reproduce this path. A duplicate may return
immediately without another worker attempt.

## Metrics

![Request and processing duration metrics](metrics.png)

The provisioned **Doc Insight** Grafana dashboard shows request and stage duration
series. The captured hour contains startup errors and successful traffic; it does
not establish an error-free interval. Route templates and bounded labels exclude
raw questions, filenames and credentials.

Tempo retains traces for 24 hours in the default deployment. These screenshots
remain useful after the individual traces expire; generate fresh requests for
live inspection.
