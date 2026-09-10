# ADR-0012: OpenAI generation and private browser delivery

Status: accepted. Date: 2026-09-10. Supersedes the provider portion of ADR-0008.

## Context and decision

The application needs hosted answers while keeping document processing on a shared
CPU server. Public source must not expose the app, its documents or credentials.

Use Responses with pinned `gpt-4.1-mini-2025-04-14`, strict structured output,
`store: false`, explicit time/output limits, and no implicit retries. Keep local
embeddings and extractive fallback. A semaphore bounds concurrent calls; epoch
tickets prevent older calls from settling a newer circuit-breaker recovery probe.

Reserve a conservative token bound transactionally before provider I/O. Tenant/day
budgets and usage events use forced PostgreSQL RLS. Settle known usage exactly once,
including billed invalid output; charge the reservation when billing is unknown.
An interrupted reservation stays held for its UTC day. This sacrifices available
allowance rather than permitting overspend. Dollar estimates do not enforce limits.

Serve a dependency-free ES-module frontend from Caddy, using the existing gateway
plus document listing and usage endpoints. Keep workspace tokens in memory and
render document content as text. Tailscale HTTPS fronts loopback Caddy; infrastructure
stays within the Compose network. The provider key is mounted only into query.

## Alternatives and consequences

Chat Completions could work but preserves the older parsing contract. An alternative hosted provider would
require a separate adapter and quality evaluation. React was considered; the single-screen workflow
does not justify its build/runtime dependencies. No embedding re-index is needed.

Unknown usage can conservatively consume a full reservation; a reconciliation worker
is an option if this occurs often. The model's published prices are $0.40/M input,
$0.10/M cached input and $1.60/M output; verify changes in the
[official model reference](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
See [Responses](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs).

Revisit when real-corpus evaluation rejects answer quality, multiple replicas need
a global concurrency cap, or operator-issued tokens no longer meet account needs.
