# Technical assignment review

> Historical baseline review before the same-day implementation. Follow the
> [delivery plan](finish-today-plan.md) and [current readiness](online-readiness.md)
> for changes made after this review.

Review date: 2026-09-10. Baseline: GitHub main `3ec103b9d4e549f5c18405211a735a42540dda47`.
Source: `inputs/TechAssignment_ AI Tech Lead.pdf`, all four pages. The assignment
and sample inputs are intentionally ignored and are not distributed with the code.

The initial local checkout was `16f0983` (the CLI/storage milestone). It was clean
and was fast-forwarded to the verified GitHub main before documenting the current
system. The HTTP services, RLS, telemetry and Docker delivery are already merged;
their presence on older feature branches does not mean they still need integration.
The unmerged `perf/chunker` branch contains a separate optimization, not a prerequisite
for the current service architecture.

## Overall assessment

The core functional slice exists and has a local Compose entry point. The remaining
work is submission evidence and production operation, with several concrete gaps
below. It is not yet demonstrated as a publicly deployed, production-ready service.

The PDF is inconsistent: page 1 calls observability/load testing optional, page 3
expects both, and page 4 explicitly asks for demonstrable metrics/traces. Treat both
as submission work. Page 1 asks for image publication on every push; page 3 narrows
publication to main. This review uses main for image publication and flags the
feature-branch push gap separately. Kubernetes is explicitly optional on page 4.

## Deliverables

| PDF requirement | Current evidence | Remaining work |
| --- | --- | --- |
| Public GitHub repository, Python core (p1) | All four core services are Python; GitHub API reported repository **PRIVATE** | Publish only after a deliberate visibility decision and review of tracked history/assets; private access does not meet this deliverable |
| `docs/architecture.md`: diagram, responsibilities, flow, trade-offs (p1/p3) | Present; stale delivery claims corrected in this review | Confirm final diagram renders for the reviewer; no standalone rendered architecture image is committed |
| 1–3 ADRs, about a page each (p1) | Eleven ADRs now document real decisions | Select three representative ADRs for the submission reading path (0001, 0003, 0011); retain the others as supporting material |
| CI lint/tests/security; publish images on main (p1/p3) | Latest main run passed quality, test, security and four image jobs | CI triggers on PRs and main pushes, not every feature-branch push; no automatic deployment to a running environment |
| README: local/Docker setup, API calls, design (p1/p3/p4) | Present and refreshed; `make local-run` and token/API calls exist | Record a clean-clone demonstration; K8s may remain explicitly deferred |
| At least 70% unit coverage and meaningful documentation (p3) | Coverage threshold enforced; see verification below; module docs and service guides exist | Code walkthrough and boundary docstrings added here; keep them aligned with behavior |
| Unit + service integration + one E2E scenario (p3) | Unit tests and Postgres/Redis/MinIO adapter integration tests exist; CI runs both | Add an automated real-stack scenario covering JWT, upload, asynchronous processing, query/citations and tenant isolation |
| `benchmark/` load script + results near 100 requests/s (p1/p3) | No `benchmark/` directory or HTTP load report | Add repeatable workload, hardware/data/model configuration, achieved throughput, latency percentiles, errors and saturation analysis |
| Metrics + distributed request trace, screenshot/live evidence (p1/p3/p4) | Stage/request metrics, OTel collector, Prometheus, Tempo and Grafana provisioning exist | Fix gateway context propagation; demonstrate a connected request trace and attach metrics/trace evidence |
| Leadership extras (p1/p3) | CONTRIBUTING, CODEOWNERS, templates, pre-commit, security policy and meaningful history | Refresh stale cross-references as features evolve; license choice remains open, though not explicitly required by the PDF |

CI evidence: [successful main run 34455240811](https://github.com/Karlo93/doc-insight/actions/runs/34455240811).
The run's image jobs report successful publication for gateway, ingest, query and worker.
That demonstrates build/publish, not a running cloud deployment.

## Functional requirements

| Requirement (PDF p2) | Implementation | Qualification |
| --- | --- | --- |
| `POST /ingest`, PDF/images at least 10 MiB | Ingest multipart parser, supported magic bytes, default 50 MiB file limit; gateway streaming limits | Existing tests cover upload limits; add a valid >=10 MiB file to the real-stack acceptance scenario |
| Store originals and emit processing event | MinIO/S3 adapter, document/outbox transaction, Redis relay | Object write is not atomic with SQL; failed registration may leave an orphan. Compose relay handles only `DI_DEMO_TENANT` |
| OCR/PDF parsing, language, NER, vectors | PDFium/Tesseract, Lingua/spaCy, pinned multilingual MiniLM on CPU, pgvector | TIFF currently uses only its first frame; unknown orientation and large OCR workloads have limits; see pipeline guide |
| `/query` with question/filter/top_k | Hybrid vector/full-text retrieval, grounded Mistral or extractive answer | Works without a paid key through fallback; hosted provider calls have not been verified in this review |
| Answer, confidence, quoted sources, entities | Typed response with citations, heuristic confidence and abstention | Confidence is uncalibrated; answer evaluation is small; citation formatting alone does not prove factual grounding |
| One authenticated, per-user limited API | Gateway RS256/JWKS, Redis token buckets, proxy routes, Caddy | Local issuer and localhost TLS are development configuration; real identity and public ingress are not provisioned |
| Tenant isolation | Tenant filters, composite foreign keys, forced RLS, restricted runtime role, object prefixes | Internal services trust identity headers; network access must enforce the gateway boundary |
| Encryption in transit and at rest | Local public-facing HTTPS and MinIO SSE-S3 | Internal HTTP/Redis/Postgres traffic is not comprehensively TLS configured; DB/cache/telemetry volumes and backups have no demonstrated at-rest encryption |

The PDF permits extractive QA and also mentions using an LLM API. The implementation
supports both; include one opt-in hosted-provider demonstration if the evaluator
expects that wording literally. A missing key does not prevent local search or QA.

## Concrete findings to resolve

1. **Gateway tracing loses the active parent.**
   `apps/gateway/src/doc_insight/gateway/proxy.py:forwarded_headers` copies the
   caller's `traceparent`; it does not inject `get_current_span()` context. Ordinary
   clients supply no header, so the downstream service starts another trace. With
   a supplied header, spans share a trace but use the caller as parent rather than
   the gateway. Inject active context on outbound requests and test both cases
   with two service apps and an in-memory exporter. This behavior was documented,
   not changed, in this review.
2. **Credential injection was absent from Compose.** Query settings already defined
   `DI_LLM_API_KEY`, but query inherited only common container variables. This
   review adds query-only mappings for the key/model, timeouts, breaker and retrieval
   settings. Empty defaults preserve extractive operation. No key was created or
   provider call made.
3. **There is no application token ledger or spend cap.**
   `apps/query/src/doc_insight/query/mistral.py` reads completion content but ignores
   provider usage; it also sends no explicit output-token limit. Gateway request
   quotas are not token budgets. Add usage extraction, aggregate accounting,
   output limits and budget enforcement before enabling broad hosted access.
4. **Only one tenant's outbox is relayed by the default deployment.** Other tenants
   can upload but wait indefinitely unless their relay runs. Add tenant onboarding
   and relay supervision, or a deliberately designed multi-tenant dispatcher.
5. **No measured 100-RPS claim is justified.** Full-text search uses an unindexed
   `to_tsvector` expression; one hosted generation runs per query process and busy
   calls fall back; workers are sequential; a long stage can outlast the 30-second
   heartbeat. Measure these before choosing indexes, process counts and timeouts.
   The default per-user quota is 5 RPS: use multiple test users or an explicit test
   policy, and distinguish accepted queries from 429s and hosted from fallback answers.
6. **Production authentication and network settings require explicit wiring.**
   Compose hard-codes the development JWKS URL/path and local service endpoints;
   changing similarly named `.env` entries alone does not replace that wiring.
   Use a production override and verify the resolved configuration without exposing secrets.
7. **The documentation had merge drift.** README stopped the stack before its API
   examples, described gateway as pending and omitted migration 0003. Architecture
   called existing images/services future work, and deployment linked a renamed ADR.
   These claims and links are corrected in this review.

## Verification and limits

- GitHub repository visibility, main SHA and latest CI job conclusions were read
  through `gh` on the review date.
- The old CLI checkout passed 153 default tests at 92.17% coverage. This is historical
  context only and must not be presented as coverage of the newer HTTP services.
- Current checkout: `uv run --locked --all-packages pytest` passed **463 tests**,
  with 88 deselected and **93.93% coverage**. Two upstream TestClient deprecation
  warnings remain. Model and service integration tiers were not rerun locally;
  the linked upstream CI run passed its integration tier.
- Ruff lint and format checks passed (174 files formatted); strict mypy passed
  on 73 source files. `docker compose --profile '*' config --quiet` and
  `git diff --check` passed.
- AST comparison against the baseline confirmed the 14 edited Python files differ
  only in docstrings. No algorithm or pipeline-version change was introduced.
- Resolved Compose configuration was checked with empty and dummy model credentials:
  query received the expected settings and other services received no LLM key.
  Every relative Markdown file target in README/docs resolved; rendered Mermaid
  layout and section anchors were not automatically checked.
- Source inspection covered entry points, service orchestration, model/provider edges,
  storage/migrations, deployment, configuration, tests and existing runbooks. This is
  an implementation/delivery review, not an exhaustive security audit.
- No public deployment, live Mistral invocation, new load benchmark or whole-stack
  E2E run was performed during this review. Existing CI and recorded manual results
  are evidence with those limits, not substitutes for a new live demonstration.

## Suggested completion order

1. Fix and test trace propagation; add the complete automated acceptance scenario.
2. Produce load-test results and metrics/trace screenshots with representative fixtures.
3. Choose hosted versus extractive demo mode; add token accounting/budgets for hosted mode.
4. Configure public identity, HTTPS, encrypted storage/backups, tenant relay coverage,
   secrets, alerts and deployment/rollback. See [online readiness](online-readiness.md).
5. Select the submission ADRs, export the architecture diagram if needed, verify
   clone/start/API instructions, then resolve repository visibility and share the result.
