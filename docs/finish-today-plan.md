# Finish-today delivery plan

Target date: **2026-09-10**, Europe/Warsaw. Target handover: **23:00**, with
23:00–23:59 reserved for release blockers. This records the execution plan. Completed work and measured results are tracked
in the [release evidence](evidence/README.md) and [load report](../benchmark/README.md).

## Outcome

A usable browser application works on the developer machine and the private
deployment server over the intended LAN/Tailscale routes. It uploads documents,
shows processing progress, and answers questions using OpenAI with inspectable
sources. Traces connect the services. Tests, load results, deployment instructions
and assignment evidence are complete. Publication follows successful local and
server acceptance, as requested.

Keep the existing Python services, PostgreSQL/pgvector, Redis, object storage and
CPU embeddings. Replace Mistral generation with OpenAI; there is no need to migrate
embeddings or re-index existing documents just to change the answer provider.
Use Docker Compose on the server. Kubernetes, a new vector database and a full
identity-management product are not needed to satisfy this delivery.

## Verified starting point

- Main is at `3ec103b`; the prior documentation review and Compose changes are
  uncommitted and must be preserved in the implementation branch/worktree.
- The last default run passed 463 tests with 93.93% coverage. HTTP services, RLS,
  asynchronous ingestion, model inference, image publication and local startup exist.
- The server is reachable through the configured SSH alias. Docker and Compose
  work; capacity observed was 16 logical CPUs, about 17 GiB available RAM and
  127 GiB free disk. It hosts other applications: shared default ports are occupied.
- No frontend or HTTP load-test report exists. Gateway trace propagation is
  incomplete. Mistral is still the only hosted answer adapter.
- Private hostnames, IP addresses, key paths and deployment secrets belong in
  untracked deployment configuration, not in public repository documentation.

## Kickoff decisions (resolved)

1. The supplied private credential authenticated successfully; keep it mounted only
   into query. Never put its value in chat, source or the browser.
2. Confirmed scope: **public repository, private app**. Private HTTPS over Tailscale;
   no internet-facing application, router exposure or Funnel.
3. Use `gpt-4.1-mini-2025-04-14`, verified against English/Croatian fixture answers
   and unsupported-question abstention. Keep CPU embeddings unchanged.
4. Cap smoke/evaluation spending at US$5; load tests use extractive mode. Tenant/day
   token reservations and usage accounting enforce a conservative runtime budget.
5. Serve small native JavaScript modules from `frontend/` through Caddy. This meets
   the upload/library/question workflow without an additional frontend build system.

## Schedule and acceptance gates

Times are execution budgets, not guaranteed completion estimates. Complete the
earlier gate before depending on it; use the final hour to resolve genuine failures.

| Warsaw time | Work | Exit condition |
| --- | --- | --- |
| 12:00–12:45 | Preserve current changes; establish implementation branch; freeze API additions; check key access, server ports, storage encryption and deployment permissions | Reproducible baseline, isolated server layout, credential source and test model established |
| 12:45–15:00 | OpenAI migration, usage limits/accounting, trace propagation, tenant relay correction | Provider/trace/tenant tests pass; a real OpenAI answer reports usage and citations |
| 15:00–17:00 | Browser frontend, document-list endpoint, browser/API E2E tests | Upload → progress → grounded answer can be completed in the browser without curl |
| 17:00–18:00 | Full local stack acceptance, integration/model tests and defect fixes | Local acceptance matrix passes; same release images ready for the server |
| 18:00–19:00 | Isolated private-server deployment, LAN/Tailscale access, persistence/recovery checks | Browser flow works from a second machine; existing server applications remain healthy |
| 19:00–20:30 | Load ramps, saturation analysis, targeted tuning, rerun final benchmark | Raw results, graphs and honest load-test report from the release candidate |
| 20:30–22:00 | Encryption/backup restore evidence, observability captures, final CI and security checks | All assignment evidence linked; no unresolved functional/security release blocker |
| 22:00–23:00 | User tryout, final corrections, release notes and gated publication | Same tagged version verified locally/server-side; publication only after acceptance |
| 23:00–23:59 | Contingency | Fix release blockers; do not substitute fabricated evidence or label failed gates complete |

## 1. OpenAI integration and cost control

**Touchpoints:** `apps/query`, `packages/contracts/.../query.py`, provider fakes,
query tests, `.env.example`, Compose, dependency lock, a new usage migration and docs.

- Implement an OpenAI Responses adapter behind the existing generator boundary.
  Use structured output for answer, supported flag and cited passage indexes.
  Validate indexes against retrieved passages and preserve explicit abstention.
- Handle refused/incomplete responses, malformed output, timeouts, 429s and server
  failures. Use bounded concurrency and timeouts with a concurrency-safe breaker;
  do not retain the current blanket single-call lock as a throughput bottleneck.
- Remove Mistral from active runtime wiring, provider literals, defaults, tests
  and operator instructions. Historical ADRs may retain its decision history with
  a superseded note. Keep local extractive mode as an explicit fallback.
- Keep the API key server-side. Proposed settings: `DI_OPENAI_API_KEY`,
  `DI_OPENAI_MODEL`, `DI_LLM_MAX_OUTPUT_TOKENS`, timeout/concurrency limits and
  token-budget settings. Map credentials only into query; support a protected
  secret file on the server. Never embed credentials in the frontend bundle.
- Capture input/output/cached token usage, provider/model, request ID and outcome.
  Store tenant-scoped usage events with RLS and expose only authorized summaries.
  Record usage before downstream citation/grounding rejection can discard a response.
- Reserve a conservative per-request token allowance atomically before dispatch;
  settle actual usage on completion. Do not release reservations blindly after an
  ambiguous timeout. Enforce output-token and daily token limits across processes.
  Report cost as an estimate with model-price/date metadata, not as an exact invoice.
- Use `store=false` for standalone requests and document that this is a response
  storage option, not a promise about all provider-side retention.
- Evaluate answers on fixed English/Croatian fixtures, including unsupported
  questions and conflicting/instruction-like document text. Inspect semantic answer
  quality as well as JSON/citation validity. Report fallback and abstention visibly.

OpenAI supports structured responses, usage fields and output-token limits; verify
the selected model's support before finalizing parameters. Sources:
[Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

**Gate:** one real hosted answer succeeds locally and on the server, usage is
recorded, a forced provider failure falls back visibly, and budget exhaustion
prevents another hosted call. Unit/contract tests run without paid requests.

## 2. Trace continuity, processing and tenant coverage

- Inject the active gateway span context into outbound headers instead of copying
  the incoming header. Test absent, valid and invalid incoming trace headers.
- Verify the full upload → ingest → outbox → relay → worker chain, including
  publication parentage, re-delivery and context cleanup between tenants/messages.
- Add an OpenAI client span under query generation with provider/model/status/usage
  metadata, excluding prompts, document text, API keys and sensitive headers.
- Capture real connected traces in Tempo and stage/request metrics in Grafana.
  Add low-cardinality error, queue/backlog, processing-duration and fallback signals.
- Replace the single-demo-tenant deployment limitation with supervised relays for
  a configured tenant allowlist. Provision the two acceptance-test tenants and
  reject unprovisioned tenants clearly; no accepted upload may silently wait forever.
- Exercise long OCR processing against heartbeat/reclaim timing. Correct premature
  unhealthiness or duplicate work; keep sequential native-library execution per worker.

**Gate:** a request without its own trace header produces connected gateway and
downstream spans; both provisioned tenants process independently; retry/restart
preserves ownership and one durable result.

## 3. Frontend the user can try

Build a compact native JavaScript UI, served as static assets behind the existing
HTTPS entry point. Keep browser/API requests on the same origin. Source lives in
`frontend/`; validate module syntax in CI and exercise the browser against real services.

Required views and behavior:

- A simple authenticated connection screen. For the private release, accept an
  operator-issued short-lived app token, keep it in memory, and support expiry/sign-out.
  This token is separate from the OpenAI key. Public internet access, if requested,
  requires a proper login/access policy before exposure.
- Drag/drop or select PDF/image files; validate size/type and show upload progress.
- Tenant-scoped document library with filename, processing state, page count and
  useful failure messages. Add paginated `GET /documents` through the gateway so
  the library survives page reloads rather than relying on browser-only IDs.
- Ask questions across all documents or a selected document, with language/top-k
  controls where useful. Show loading, answer, abstention and retry states.
- Expandable source cards with exact quotes and page numbers, extracted entities,
  provider/fallback status, elapsed time and available token usage. Explain that
  confidence is a heuristic; do not present it as a correctness probability.
- Responsive desktop/mobile layout, keyboard operation, accessible labels and
  escaped document/model content. Render no raw untrusted HTML.

**Gate:** a user completes upload → processed → question → source inspection in
the browser, locally and remotely. Browser tests cover session expiry, failed
uploads, empty results, and an API failure as well as the happy path.

## 4. Repeatable acceptance suite

Add `scripts/acceptance.py`, one command that tests the real composed services with
generated fixture data. Browser and API checks use the same release images and deterministic fixtures.

- Text PDF, scanned image/PDF, Croatian text and a valid file >=10 MiB.
- Duplicate upload, polling to completion, cited answer and unsupported-question abstention.
- Tenant A cannot list, read, query or obtain usage for tenant B's documents.
- Missing/expired token, spoofed identity headers, rate limiting and oversize rejection.
- Worker restart during processing, eventual recovery and no duplicate stored result.
- Provider timeout/429, dependency outage and explicit fallback behavior.
- Host/container restart retains documents, keys and usage records.

Run unit, integration, model, browser/E2E, formatting, typing, dependency/security
scans and image checks. Keep >=70% unit coverage. CI runs lint/tests/security on
every branch push, with guarded image publication on main; authenticated paid tests
remain explicit opt-in checks rather than exposing credentials to PRs.

## 5. Private-server deployment

- Use a dedicated checkout/release directory, Compose project, networks, credentials
  and volumes. Select unused ports after checking the host; remove infrastructure
  host-port publications in the server override wherever only containers need access.
- Expose the UI/gateway through a dedicated LAN/Tailscale route. Inspect existing
  HTTPS/proxy configuration before selecting a certificate and port. Do not replace
  the server's existing 443/8443 handlers or other application mappings.
- Provide verified HTTPS access over the selected private routes. Tailscale does
  not replace app authentication and does not encrypt a separate direct LAN path.
- Verify backing-storage encryption. If absent, provision an application-specific
  encrypted storage location with the required privileges, plus encrypted backups
  and protected key recovery. Named Docker volumes alone do not prove encryption.
- Document and secure every transport crossing a host boundary; configure TLS for
  storage links where needed. Record the single-host container-network trust boundary.
- Keep runtime/migration roles separate, use fresh secrets, resource limits, model
  caches, readiness checks and restart policies. Deploy the same immutable images
  tested locally; run migrations as a one-shot controlled job.
- Provide deploy, backup, restore and rollback commands. Validate a restore into
  disposable isolated storage without overwriting the running service. Rollback
  must account for schema compatibility, not only image tags.

**Gate:** reach the UI from the intended LAN and Tailscale clients; complete E2E;
restart the app stack; recover persisted documents; confirm other server services
remain healthy. Record private endpoint details outside tracked/public docs.

## 6. Load-test script and report

Deliver `benchmark/` with a reproducible load driver, fixtures/seed instructions,
machine-readable results, charts and a report in `benchmark/README.md`. Run the release candidate on
the private server and record CPU/RAM/disk, process counts, dataset/chunk counts,
cache state, model/provider, image SHA, duration and concurrent host activity.

Separate workloads so the report has an honest interpretation:

1. **Application/retrieval load:** real gateway authentication, database, embeddings
   and extractive answers; warm-up followed by 10/25/50/100 RPS stages, each long
   enough for stable measurements (target 2 minutes), then a 10-minute soak at the
   sustainable rate. Use multiple users so intentional per-user quotas do not
   masquerade as application capacity. Report 429s separately.
2. **Upload/worker throughput:** text/scanned/large-file cases with processing latency,
   queue depth, retry count and documents/pages per minute. Do not equate upload
   acceptance with completed OCR/indexing.
3. **OpenAI QA:** a small budgeted live sample at account-supported concurrency;
   report answer latency, success, usage, fallback, abstention and quality. Do not
   describe local or mocked answers as 100-RPS OpenAI performance.

Report offered/achieved RPS, p50/p95/p99 latency, errors/timeouts/429s, resource
saturation and retrieval/answer correctness. Save raw results and telemetry captures.
Investigate query plans, full-text indexing, worker/process counts and bounded
provider concurrency; change only demonstrated bottlenecks and rerun after changes.

**Gate:** the report demonstrates behavior at an offered ~100 RPS and identifies
the sustainable operating point. If 100 successful queries/s is not achieved, state
the measured limit and cause. The assignment asks for measured behavior, not an
invented throughput guarantee. Set operational limits from the results.

## 7. Evidence, handover and publication

- Update architecture, API, frontend, configuration, OpenAI, server deployment,
  operations and troubleshooting docs. Export a rendered architecture diagram.
- Keep the existing requirement review as dated history; add a final status matrix
  linking each requirement to code/tests/report/screenshots at the release SHA.
- Select three core ADRs for the evaluator's reading path; document the provider
  replacement without discarding earlier decisions. Update contribution ownership
  for frontend code and select a project license if the user supplies a preference.
- Capture one short browser walkthrough and metrics/trace screenshots using generated
  shareable fixtures. Exclude ignored assignment inputs, private documents, credentials,
  private endpoint details and personal infrastructure configuration from publication.
- Tag the tested release, verify clean-clone setup and green CI/image jobs, and hand
  over local/server URLs plus a short operator guide. User tryout occurs before publication.
- Make the repository public only after local/server acceptance. If public app
  exposure is also requested, verify domain, login, firewall, TLS and budgets first;
  that ambiguity must be resolved before opening an internet listener.

## Completion checklist

- [ ] OpenAI generation, citations, failure handling and usage/budget controls pass.
- [ ] Frontend works locally and over the server's intended private access routes.
- [ ] All provisioned tenants can upload/process/query; isolation tests pass.
- [ ] Connected HTTP/async traces and useful dashboards are captured.
- [ ] Unit/integration/model/browser/E2E checks pass with coverage evidence.
- [ ] Load-test script, raw data, charts and report describe the final release.
- [ ] Server deployment, encryption, backup/restore and restart/rollback are verified.
- [ ] Documentation, rendered architecture and assignment evidence are complete.
- [ ] User can try the final UI; release SHA matches both installations.
- [ ] Publication scope is confirmed and its preconditions pass before publication.

The API credential, server access and publication scope have been resolved. A same-day target does not
make an unverified deployment, missing permission or failed test a completed deliverable.
