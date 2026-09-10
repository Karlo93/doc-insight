# Contributing

Discuss substantial changes in an issue before implementation. Keep each PR focused
on one behavior or operational concern, and use generated documents in examples.
See [support](SUPPORT.md) for questions and [SECURITY.md](SECURITY.md) for private reports.

## Development workflow

Start a branch in a separate worktree from current main:

```sh
git fetch origin
git worktree add ../doc-insight-change -b feat/short-description origin/main
cd ../doc-insight-change
make setup
uv run --locked pre-commit install
```

Use `feat/`, `fix/`, `docs/` or `chore/` branches and Conventional Commit messages:
`type(scope): summary`. Describe the resulting behavior. Use `BREAKING CHANGE:`
for incompatible changes and document the migration path.

Prefer small commits that can be reviewed independently. Keep review corrections
in follow-up commits; squash the PR at merge to leave a clear main history.
Rebase before review when practical. Never force-push shared branches without
coordination. If a change depends on an open PR, state the dependency and retarget
after it merges. Do not merge your own PR; the maintainer performs integration.

## Validation

Prerequisites: uv, Python 3.12, GNU Make, Go 1.24.11+, Docker Compose and Tesseract
with `eng`/`hrv` data. [Platform setup](docs/pipeline.md#run-it-wsl2linux)
covers Windows and Linux installation.

| Command | Scope |
| --- | --- |
| `make lint` / `make typecheck` | Ruff and strict mypy |
| `make test` | Offline default suite; coverage floor 70% |
| `make test-integration` | Real services and disposable databases; start `make db-up` first |
| `make test-models` | Opt-in pinned model downloads and adapter checks |
| `make audit` | Bandit, dependency audit and secret scanning |
| `make check` | Lint, types, default tests and audit |

Commit hooks check changed Python files with Ruff and run Bandit. Push hooks run
the security audit. Hooks require the installed tools; CI independently runs the
full gates. Run `uv run --locked pre-commit run --all-files` and
`uv run --locked pre-commit run --all-files --hook-stage pre-push` to check both.
For documentation-only edits, validate links and examples; do not invent test
results or require unrelated runtime tests.

Run the test tiers affected by a change and record exact commands and outcomes.
Integration tests create temporary databases and need a privileged migration login;
never aim them at shared production storage. See [CI](docs/ci.md) for details.

## Code and data boundaries

- Keep transformations pure and external I/O behind typed Protocols. Add deterministic
  fakes and shared adapter contract tests for new external dependencies.
- Reuse clients, pools and models. Use validated, cached `DI_` settings and document
  defaults in the owning runbook and `.env.example`.
- Keep functions within 40 lines and modules within 250 lines where practical;
  tests are exempt. Explain exceptions when splitting would obscure the behavior.
- Explain non-obvious intent and failure boundaries in comments and docstrings.
- Tenant-scope persistence and prove cross-tenant denial with tests. Only the
  gateway may derive identity from credentials.
- Never log document text, questions, filenames, vectors, tokens or credentials.
  Keep real inputs and local output in ignored directories.
- Add dependencies to their owning workspace package and commit the updated lockfile.
  Keep runtime versions reproducible.

## Migrations and documentation

Use the next unused Alembic revision and coordinate with open PRs. Test upgrade,
downgrade and re-upgrade on a disposable database. Do not edit released migrations.
State data-loss and rollback implications explicitly.

Bump `PIPELINE_VERSION` when stored processing output changes, including tokenizer
or chunking changes; explain re-indexing requirements. Keep the service runbook and
changelog current. Write an ADR only for a consequential choice with alternatives,
trade-offs and a concrete reason to revisit it.

## Review and merge

Use the [PR template](.github/pull_request_template.md). State the problem, resulting
behavior, validation and material risks. Link an issue or ADR when relevant; attach
sanitized evidence only when it helps review. Test output belongs in CI artifacts,
not a compulsory transcript in every description.

Resolve valid review findings with code and a regression check. Explain the evidence
when disagreeing. Automated comments are input to review; they are not independent
human approval. CODEOWNERS requests review from the maintainer; enforcement depends
on repository protection settings, documented in [CI](docs/ci.md).

## Contribution licensing

The project uses [PolyForm Noncommercial 1.0.0](LICENSE.md). Before accepting an
external contribution, the maintainer and contributor must separately agree on
permission for the maintainer to use and license that contribution commercially.
Submitting a PR alone does not transfer copyright or grant those additional rights.
Do not contribute code you lack permission to license, and preserve third-party notices.
