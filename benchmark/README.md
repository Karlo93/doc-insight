# HTTP performance report

Measured on 2026-09-10: **100 document-list requests/s succeeded; 100 offered
extractive queries/s overloaded the query service.** The sustainable tested query
rate was 25 req/s on a small generated corpus.

These measurements predate the document-name retrieval and hosted-answer fixes in
PR #18. They describe the recorded builds below, not a fresh benchmark of current
main. OpenAI generation was disabled throughout the load tests.

## 100 req/s results

Each endpoint received 12,000 scheduled requests over 120 seconds.

| Endpoint | HTTP 200 | Client drops | Successful req/s, including drain | Successful p95 |
| --- | ---: | ---: | ---: | ---: |
| `GET /documents` | 12,000 (100%) | 0 | 100.00 | 11.32 ms |
| `POST /query` | 3,075 (25.62%) | 8,925 | 23.74 | 11,858.59 ms |

There were no HTTP 429 or 5xx responses in these stages. Client drops mean the
driver's 256-request concurrency ceiling was reached; they are failed offered
work, not server successes. Query drain extended the run to 129.54 seconds.
Successful-response latency excludes dropped work, which is reported separately.

![Throughput, delivery and latency at 100 requests per second](capacity.png)

For comparison, 25 req/s returned 3,000/3,000 successful queries, p50/p95/p99
63.13/103.58/113.72 ms. Query CPU reached approximately four cores while memory
stayed around 1.05 GiB of the 2-GiB cap. CPU inference was the first observed limit.
The 30-second ramps at 10/25/50/100 req/s showed the same saturation boundary.

## Environment and method

- Shared Linux server: 16 logical CPUs, 30.99 GiB RAM, encrypted SSD.
  Docker 29.6.1 / Compose 5.3.0. Query limited to 4 CPUs/2 GiB; worker 4 CPUs/3 GiB.
- Caddy → authenticated/quota-controlled gateway → ingest or query → PostgreSQL
  and Redis. One query process, two native embedding threads, warm CPU MiniLM
  model, hybrid retrieval, extractive generation and telemetry enabled.
- Six generated documents, 29 chunks and 60 entities across two tenants; five
  documents belong to the queried tenant. This does not establish large-corpus scaling.
- Open-loop Linux driver on the same server, using Caddy's internal HTTP endpoint.
  Forty identities stay below the per-user 5 req/s quota. WAN, Tailscale and TLS
  overhead are excluded.
- At most 256 concurrent requests, 30-second HTTP timeout, no retries. Latency
  starts at scheduled dispatch. Dispatch p99 was 1.26–2.92 ms in the confirmation
  stages. Throughput includes drain time.
- Initial candidate query image:
  `sha256:aa4a27a05f8600e07578d57711aedc3f2f4b03c27c2d8508a9c96371e0e25877`.
  Later confirmation and corrective samples are separate from this baseline.

## Reliability and overload follow-ups

| Scenario | Result | Successful p95 | Samples |
| --- | --- | ---: | --- |
| Initial 20 req/s, 10 minutes | 11,999 HTTP 200; one 502 | 95.71 ms | [Initial soak](raw/soak.json.gz) |
| Repeated 20 req/s, 10 minutes | 12,000/12,000 HTTP 200; no drops/errors | 97.72 ms | [Corrected soak](raw/release-soak.json.gz) |
| 100 offered query req/s, forced JWKS refresh, 60 seconds | 1,465 HTTP 200; 4,535 drops; no HTTP errors | 14,920 ms | [Auth overload](raw/auth-overload.json.gz) |
| 20 req/s, forced JWKS refresh, 5 minutes | 6,000/6,000 HTTP 200; no drops/errors | 96.20 ms | [Auth soak](raw/auth-soak.json.gz) |

The initial 502 matched stale upstream connection reuse; Caddy now retires idle
connections before Uvicorn closes them. A later overloaded run recorded one 401
during signing-key refresh; the gateway now uses a separate authentication HTTP
pool. Forced-refresh checks verified that saturation no longer starved that pool.
They did not eliminate the query capacity limit. Earlier results remain available.

## Reproduce

Use generated fixtures in an isolated deployment, with telemetry enabled. Follow
[private hosting](../docs/private-deployment.md) for configuration and token issuance.
The existing driver reserves the first two entries in its token JSON for acceptance;
provide at least 42 entries to exercise 40 load identities. Keep tokens ignored.

Recreate query with the load overlay last and omit the provider secret overlay:

```sh
docker compose -f docker-compose.yml -f deploy/compose.private.yml \
  -f deploy/compose.load.yml --profile '*' up -d --no-deps --wait query
uv run --locked python scripts/load_test.py --base http://127.0.0.1:9080 \
  --tokens .cache/load-tokens.json --seconds 120 --rates 25,100 \
  --modes documents,query --output .cache/confirmation.json
```

The driver refuses load if preflight reports hosted generation. Restore the normal
query configuration afterwards and verify a real answer:

```sh
docker compose -f docker-compose.yml -f deploy/compose.secret.yml \
  -f deploy/compose.private.yml --profile '*' up -d --no-deps --wait query
uv run --locked --with matplotlib==3.10.7 python benchmark/plot_results.py
```

The plot renders the committed historical data. New runs write ignored output;
review and label a new dataset explicitly before replacing published measurements.

[Summaries](results.json) · [Confirmation samples](raw/confirmation.json.gz) ·
[Ramp samples](raw/ramp.json.gz) · [Transferred-image confirmation](raw/release-confirmation.json.gz) ·
[Resource observations](resources.json) · [Plot source](plot_results.py)

Raw load samples contain status, latency and dispatch lag, without tokens or
document contents. Live traces and metrics are documented in
[observability](../docs/observability.md).
