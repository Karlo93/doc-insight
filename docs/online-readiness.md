# Online readiness and API credentials

The application now has a browser frontend and OpenAI generation, with per-tenant
token accounting and daily budgets. The eventual target is public source and a
private application. **Both remain private until the owner publishes manually.** Local and private-server HTTP acceptance have passed;
load and recovery evidence are separate release checks. The original
[assignment review](assignment-review.md) records the pre-change baseline.
Use the [private deployment runbook](private-deployment.md) for operation.

## API credentials and token usage

OCR, language detection, named entities and CPU embeddings run locally. Only answer
generation needs an OpenAI API key. A ChatGPT/Codex login is not an application API
credential. Use `DI_OPENAI_API_KEY`, or a mounted key via `deploy/compose.secret.yml`
and `OPENAI_SECRET_FILE`. The pinned model is `gpt-4.1-mini-2025-04-14`.

```sh
docker compose -f docker-compose.yml -f deploy/compose.secret.yml \
  --profile '*' up -d --no-deps --wait query
```

Add `-f deploy/compose.private.yml` on the private server. Recreate query after
changing configuration; a restart retains its existing environment. Without a key,
the app uses extractive answers. `generation.provider` reports the path actually
used. `generation.usage` includes input, output and cached input tokens;
`fallback_reason` identifies disabled generation, saturation, circuit, budget,
upstream and format failures.

`GET /usage` and the browser display the current tenant's UTC-day accounting.
Default limits are 250,000 daily tokens, 700 output tokens per call and four
concurrent hosted calls. PostgreSQL reservations protect the allowance across
concurrency and restarts. Unknown usage is charged conservatively. This is a token
allowance, not a provider invoice or exact dollar limit. Cached input is already
included in input tokens. See [query settings](query.md#settings).

Questions and retrieved text are sent to OpenAI with `store: false`. This option
is not a promise of zero provider retention; consult
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).
`HF_HUB_OFFLINE=1` only disables model downloads. Use an empty key/load profile to
also disable hosted answer calls.

## Beyond this delivery

Internet-facing app publication is intentionally out of scope. Broader multi-user
operation needs identity lifecycle/onboarding, hard processing deadlines,
larger-corpus evaluation and an off-host backup policy. A fixture-scale benchmark
does not establish those capabilities. Confidence is a lexical grounding heuristic,
not a calibrated probability; valid paraphrases can still cause abstention.
