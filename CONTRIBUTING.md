# Contributing

Keep each PR focused on one behavior or documentation change. Read [the pipeline](docs/pipeline.md),
[CI gates](docs/ci.md) and the [three existing ADRs](docs/README.md)
before changing the processing/storage boundaries. Read the contracts, worker settings and the
default/integration test harness before introducing an adapter.

## Branches and commits

Start a separate worktree from current `origin/main`:

```sh
git fetch origin
git worktree add ../doc-insight-change -b feat/short-description origin/main
cd ../doc-insight-change
make setup
```

Use `feat/`, `fix/`, `docs/` or `chore/` followed by a short topic. Use Conventional Commits:
`type(scope): summary`, with the scope optional. Existing history uses `feat` and `chore`;
use `fix` for defects, `docs` for documentation, `test` for tests, `refactor` for behavior-preserving
changes and `perf` for measured performance work. Use `!` and a `BREAKING CHANGE:` footer when needed.
Prefer one logical commit per PR; keep review fixes in follow-up commits. Do not add authorship
trailers or generator attribution. Commit messages explain the resulting behavior.

Rebase onto `origin/main` before opening a PR and after a dependency merges. Do not merge your
own PR. Do not force-push a branch someone else may use. If rebase would rewrite a shared branch,
coordinate first or publish the rebased work on a new branch.

## Implementation standards

- Put Pydantic contracts and provider Protocols in `packages/contracts`, deterministic fakes in
  `packages/testing`, and real I/O adapters at service boundaries. Keep core transformations pure.
- Give every Protocol a shared contract test over fake and real implementations. Mark tests
  that require services as `integration`; mark runtime model-download tests as `models`.
- Create clients, model instances and pools once per process/configuration and reuse them.
- Use one cached Pydantic-settings object per service, with `env_prefix="DI_"` and startup
  validation. Document each variable's default and purpose and add it to `.env.example`.
- Add a dependency to its owning app/package with a lower bound and major cap. Run `uv lock`
  and commit `uv.lock`. Pin container images to exact tags and keep Compose/CI versions aligned.
- Keep functions at most 40 lines and modules at most 250 lines; tests are exempt. State the
  changed application-line count in the PR, including zero for documentation-only changes.
- Tenant-scope every persistent table, repository method, endpoint and storage CLI command.
  The current `extract`/`analyze` commands are stateless and do not take tenants. Only the gateway
  may derive a tenant from credentials; internal headers are trusted only on the internal network.
- Never log document text, questions, user-supplied filenames, vectors, tokens or credentials.
  Log IDs, counts, durations, statuses and error classes. Explicit CLI previews are document data;
  keep redirected output in ignored `inputs/` or `.cache/` and out of review attachments.
- Reuse extract → analyze → embed → store. Bump `PIPELINE_VERSION` only when stored output
  changes, including model/tokenizer/chunking changes; explain re-indexing needs.
- Comments explain intent. Remove dead code, banners and speculative stubs.

## Test tiers and gates

Install uv, Python 3.12, GNU Make, Go 1.24.11+, Docker/Compose and Tesseract with `eng`/`hrv`.
[Pipeline setup](docs/pipeline.md#run-it-wsl2linux) covers shell-specific installation and ports.

| Command | Scope and prerequisites |
| --- | --- |
| `make setup` | `uv sync --locked --all-packages`; requires dependency-download access |
| `make lint` | Ruff check and format check |
| `make typecheck` | mypy strict on `apps` and `packages` |
| `make test` | Default tests, offline socket/psycopg guard; installed OCR and language packages; coverage ≥70% |
| `make test-models` | Real tokenizer/embedding tests; may download pinned snapshots; no coverage report |
| `make db-up` | Start and wait for local Postgres/pgvector |
| `make migrate` | Apply schema to the development database |
| `make test-integration` | Service-backed tests; temporary databases; no coverage report |
| `make audit` | Bandit, pip-audit and pinned gitleaks via Go |
| `make check` | Lint, types, default tests/coverage and audit |
| `make db-down` | Stop Compose; preserve the named volume |

When changing the host port, export both `POSTGRES_PORT` and the matching `DI_DATABASE_URL`.
Integration tests need database-creation permission; the harness migrates its own disposable
databases and refuses nonlocal hosts unless explicitly enabled. Never target a shared database
casually. Default tests must not reach services or use sleeps for synchronization.

CI has `quality`, `test` and `security` jobs. The test job includes Postgres integration tests;
runtime model downloads are a separate local tier. Run relevant tiers and record exact results.
Passing a subset does not mean `make check` passed. See [CI](docs/ci.md) for coverage artifacts,
audit limitations and branch-protection setup. Install hooks with
`uv run --locked pre-commit install`.

## Migrations and decisions

Use Alembic revisions at `migrations/versions/NNNN_name.py`, with raw SQL as the schema source.
Take the next unused number, coordinate it with open PRs and provide a working `downgrade()`.
Test upgrade, downgrade and re-upgrade on a disposable database. Preserve tenant constraints
and transaction boundaries; document data-loss/re-indexing implications. Do not modify a
released migration to change an existing deployment.

Write an ADR for a decision with real alternatives: one page, context, decision, consequences,
alternatives and a concrete revisit criterion. Use the next free `docs/adr/NNNN-*.md` number
and state the reservation in the PR. Do not add an ADR merely to describe routine code or docs.
Update the pipeline or service runbook, add an Unreleased changelog entry and a short engineering
journal entry with the change.

## Pull requests

Use the [PR template](.github/pull_request_template.md), with these sections in order:

1. **What:** resulting behavior, scope and changed application-line count.
2. **Why:** concrete problem and any design trade-off; link the ADR if needed.
3. **How tested:** exact commands and numbers, plus full `make check` output in a details block.
   Redact credentials, document content and machine-specific paths; say what was redacted.
   If a command cannot run, record the blocker and the checks actually performed.
4. **Try it yourself:** commands a reviewer can run from a clean clone with prerequisites stated.
5. **Checklist:** all eleven items below; tick only what is demonstrated. Leave an unmet or
   inapplicable item unticked and explain why.

- [ ] Provider seam: every external dependency is behind a Protocol with a fake and a shared contract test.
- [ ] Pure core, thin edges: I/O (HTTP, DB, queue, object storage, models) stays at the boundary.
- [ ] Reproducible: pinned versions, locked dependencies, generated fixtures, pipeline version bumped if output changed.
- [ ] Load once: clients, models and pools are created once per process and reused.
- [ ] Deterministic tests: default suite offline; service-backed tests under `integration`; no sleeps for synchronization.
- [ ] Idempotent persistence: replaying the same input leaves exactly one complete output.
- [ ] Tenant on every table, repository method, endpoint and CLI command; cross-tenant access proven impossible by a test.
- [ ] No raw document text in logs.
- [ ] One `DI_`-prefixed settings object per service; nothing hard-coded.
- [ ] Budget: functions ≤ 40 lines, modules ≤ 250, application-line count stated.
- [ ] Comments explain intent; no banners, dead code or speculative infrastructure.

Before pushing, inspect the staged diff for credentials, private infrastructure names and personal
paths. Never commit `inputs/` or `.cache/`. Run the security gate; scanning current files does not
erase a secret from history. See [security reporting](SECURITY.md) for accidental disclosures.

For every automated review comment: reproduce it; if valid, fix it in a follow-up commit;
reply in plain prose naming the commit and test; then resolve the thread. If it is not valid,
explain the evidence before resolving. Do not dismiss a comment solely because a bot posted it.
