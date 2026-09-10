# API and event contract

The internal [query service](query.md) implements `POST /query` on port 8002. Its guide
includes a captured offline response. The internal [ingest service](ingest.md) implements
`POST /ingest`, `GET /documents/{id}` and the outbox relay on port 8001. The public [gateway](gateway.md)
authenticates, rate-limits and forwards these routes. Examples below describe the public contract; they are not captured responses.
Run the stack with `make local-run` ([deployment](deploy.md)), or index documents for
query with the [working CLI](../README.md#local-cli-setup).

## Public HTTP contract

Authenticate with `Authorization: Bearer <JWT>` at the gateway. The development issuer,
key-generation and token-minting commands are in the [gateway runbook](gateway.md).
The gateway derives internal tenant/user headers from verified credentials.

| Request | Success | Other outcomes |
| --- | --- | --- |
| `POST /ingest`, multipart field `file` | 202 with `document_id`, `sha256`, `status` | 413 over limit; 415 unsupported magic bytes |
| `GET /documents/{id}` | 200 with document metadata | 404 if absent or owned by another tenant |
| `POST /query`, JSON | 200 with answer and cited evidence | 400 above 126 content tokens; 422 schema errors |

Duplicates return 202 with the existing document ID and `status: "duplicate"`, never 409.
Ingest accepts PDF, PNG, JPEG and TIFF by magic bytes and streams bytes with a default
50 MiB limit (`DI_MAX_UPLOAD_BYTES`). Stored states are `uploaded`, `processing`,
`processed` and `failed`; polling must stop on either terminal state.

Status response fields: `document_id`, `status`, `filename`, `page_count`, `language`,
`pipeline_version`, `created_at`, `processed_at`, `error`. Failed processing exposes a
sanitized error class/message. Nullability before processing will be checked against
the merged response model.

`top_k` is 1–20, default 5. The optional filter contains `document_ids` (UUID list or
null) and `language` (`en`, `hr` or null). The embedder rejects overlong questions
instead of truncating them; the HTTP 400 message must explain the 126-content-token cap.

The gateway adds 401 for authentication failure and 429 with `Retry-After` for throttling.
Errors use `{"error":{"code":"...","message":"..."}}`, without tracebacks or document text.
Internal ingest/query requests without `X-Tenant-Id` return 400; these services must not
be exposed as an alternative public authentication path.

## Curl sequence (Bash)

With `make local-run` finished, set `BASE_URL=https://localhost` (add `-k` for the local
certificate) and `TOKEN=$(make -s dev-token)`; against a deployment, use its public HTTPS
endpoint and a token from its issuer.

```sh
curl --fail-with-body -H "Authorization: Bearer $TOKEN" \
  -F file=@tests/fixtures/text_hr.pdf "$BASE_URL/ingest"
```

Illustrative upload response (UUID and digest stand-ins, not a fixture hash):

```json
{"document_id":"11111111-1111-4111-8111-111111111111","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"uploaded"}
```

Set `DOCUMENT_ID` from the actual upload response. Repeat this status request until
`processed` or `failed`; query only after successful processing:

```sh
curl --fail-with-body -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/documents/$DOCUMENT_ID"
curl --fail-with-body -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Gdje se nalazi Zagreb?","top_k":5,"filter":{"document_ids":null,"language":"hr"}}' \
  "$BASE_URL/query"
```

Query response contract:

| Field | Shape |
| --- | --- |
| `answer`, `confidence`, `abstained` | String, float 0–1, boolean |
| `sources` | List of `{document_id, page, chunk_ord, char_start, char_end, text, score}` |
| `entities` | List of `{text, label, count, document_id}` |
| `retrieval` | `{top_k, hits, hybrid}`; `hybrid` is boolean |
| `generation` | `{provider, model}`; provider is `mistral` or `extractive` |
| `latency_ms` | Integer |

Citation offsets refer to normalized extracted page text, not PDF byte offsets.
Recorded upload/status responses, development certificate handling and a five-minute demo
remain pending verification against the merged services.

## Object and stream contract

Originals use bucket `documents`, key `{tenant_id}/{sha256}`, with SSE-S3 on MinIO.
The document and outbox row commit together. Outbox columns are `id` (UUID primary key),
`tenant_id`, `aggregate_id` (UUID), `type`, `payload` (JSONB), `created_at`, and nullable
`published_at`. `di-ingest relay` is the planned relay entry point.

The relay publishes `document.uploaded` to Redis Stream `di:documents`. All message
values are strings: `event_id`, `type`, `tenant_id`, `document_id`, `sha256`, `object_key`,
`media_type`, `size_bytes`, `occurred_at` (RFC 3339), and optional `traceparent`.
Consumer group: `worker`. Dead-letter stream: `di:documents:dlq`, containing the original
fields plus `error` and `attempts`. Delivery is at least once; consumers must be idempotent.
See [reliability](architecture.md#reliability) for transaction and acknowledgment boundaries.
