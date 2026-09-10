# CI and repository controls

Every push and pull request runs three independent jobs. Newer runs on the same
ref cancel superseded runs. Default workflow permissions are read-only.

| Job | Required verification |
| --- | --- |
| `quality` | Ruff, strict mypy, Compose configuration, JavaScript syntax and browser transport unit tests |
| `test` | Offline tests with 70% coverage floor, then PostgreSQL/Redis/MinIO integration tests |
| `security` | Bandit, pip-audit and pinned gitleaks |

The test job installs Tesseract with English/Croatian data and uploads coverage
for seven days. It creates its own service databases. Pinned tokenizer/embedding
downloads run separately with `make test-models`; they are not part of default CI.

## Local checks and hooks

Run `make setup`, then `make check`. Start infrastructure with `make db-up` before
`make test-integration`. Install both hooks with `uv run --locked pre-commit install`:

- Commit: Ruff lint/format checks on changed Python files and Bandit.
- Push: the full security audit, including dependency and secret scanning.

Hooks use the locked uv environment. The push audit additionally needs GNU Make
and Go 1.24.11+. CI runs independently of local hooks, including when hooks are skipped.
Use [CONTRIBUTING](../CONTRIBUTING.md) for commands and migration requirements.

Gitleaks in `make audit` scans all fetched Git history; the security job fetches
full history. Inspect uncommitted and ignored files separately.
pip-audit skips editable workspace stubs and cannot check model wheels outside its
advisory database. Passing these checks does not replace a manual security review.
Dependabot proposes weekly Actions and uv dependency updates with grouped
minor/patch releases.

## Main protection

CODEOWNERS identifies the responsible maintainer; a file alone does not enforce
reviews. Configure these repository rules when supported by the repository's plan:

- Require pull requests and passing `quality`, `test` and `security` checks.
- Require resolved review conversations and linear history.
- Disallow force pushes and branch deletion on main.
- Apply rules to administrators instead of relying on bypasses.
- Require independent approval when another maintainer is available.

Use squash merging with a concise title describing the final change. A solo
maintainer cannot provide independent approval of their own work; do not present
a bot review or CODEOWNERS entry as that approval. Keep CI mandatory even when
human review must be arranged separately.

Protection was unavailable on the current private repository plan when checked.
These are setup instructions, not a claim that enforcement is active.
Changing repository visibility is an owner action.

## Container images

After all three jobs pass, upstream main pushes build gateway, ingest, query and
worker Linux amd64 images. Pull requests and forks skip publication. The image job
alone has `packages: write`; it publishes immutable commit tags plus `main` to GHCR
and attaches SBOM/provenance attestations. Relay reuses ingest; migration reuses worker.

Publication to GHCR does not deploy the application. Repository visibility and
package visibility are separate settings. No workflow exposes an application URL.
For local verification use `scripts/smoke_images.sh`, `scripts/smoke_tls.sh` and
`make local-run`; see [deployment](deploy.md).
