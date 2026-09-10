# Security policy

## Reporting privately

Do not publish vulnerability details in issues or pull requests. Use the repository's
**Security → Report a vulnerability** option when available. If private reporting is unavailable,
contact the maintainer, @Karlo93, to arrange a private channel. If no private contact channel is
available, open an issue asking for one without describing the vulnerability or including data.

In the private report, include the affected commit, impact, minimal reproduction using synthetic
input, and any mitigation. Do not send real documents, credentials or access tokens. Coordinate
disclosure with the maintainer; no response-time guarantee is currently defined.

## Supported versions

| Version | Security fixes |
| --- | --- |
| Current `main` (development) | Maintained |
| Earlier commits and unreleased snapshots | No separate backports; update to current `main` |

There is no stable-release support schedule yet. The deployed stack uses a JWT/JWKS
gateway, per-user quotas, tenant-scoped queries and forced PostgreSQL row-level
security. Internal services trust the isolated Compose network and must not be
exposed directly. The development issuer is for operator-managed workspaces;
self-service identity lifecycle and multi-node availability are not implemented.
See [security boundaries](docs/security-boundaries.md) for the encryption matrix.
See [private deployment](docs/private-deployment.md) for credentials, backups and
network boundaries. Hosted generation sends selected passages and questions to
the provider; local extraction and embeddings do not require a hosted API.

## Secrets and document data

- Keep secrets in environment variables or ignored local files. Never commit private keys,
  tokens, database credentials, real document samples or private infrastructure details.
- `.env`, `*.pem`, `*.key`, `inputs/`, `.cache/` and `.local/` are ignored; inspect the staged diff anyway.
  Generate unique local credentials with `python scripts/configure_local.py`.
- Logs and review attachments must exclude document text, questions, user filenames, vectors
  and credentials. Explicit CLI output is document data and must be handled accordingly.
- If a secret is exposed, revoke or rotate it promptly and notify the maintainer privately.
  Deleting a file does not remove previous commits, logs or artifacts containing it.
- Run `make audit`. Gitleaks scans all fetched Git history; inspect uncommitted files separately; pip-audit skips editable workspace packages
  and cannot audit the two spaCy model wheels outside PyPI. Passing these tools is limited evidence,
  not a guarantee that a deployment is secure.
