# Security boundaries

The Compose deployment trusts one host and its private container network. Tenant
isolation and encryption solve different problems: PostgreSQL row-level security
restricts access through the runtime role; it does not encrypt records or protect
against a database administrator or a compromised host.

| Data path or store | Current protection | Limit |
| --- | --- | --- |
| Browser to private ingress | HTTPS; private network access in the server runbook | Loopback HTTP is allowed for development. The UI rejects token entry and API calls over network HTTP. |
| Query service to OpenAI | HTTPS | Questions and selected source text leave the host when hosted generation is enabled. |
| Ingress to gateway and internal HTTP services | Private Docker network; HTTP | No TLS between these services. A same-host proxy may also use loopback HTTP. |
| PostgreSQL, Redis, MinIO and telemetry connections | Private Docker network | Default Compose connections are plaintext. Network isolation is not encryption. |
| Original objects | MinIO SSE-S3; initialization requires bucket encryption | The local key volume must be protected and backed up separately. Host compromise can expose the key. |
| Database, queue and telemetry volumes | Operator-provided disk encryption | Compose does not enable or verify host encryption. Verify the actual Docker data filesystem and backups. |
| Backups | See the encrypted backup/restore procedure in the private deployment runbook | Encryption and restore testing are operator responsibilities. |

This is **not complete encryption in transit across every hop**. Before distributing
services across hosts, configure HTTPS/mTLS for service and telemetry traffic,
PostgreSQL TLS with certificate and hostname verification, Redis TLS, and an HTTPS
object-store endpoint. Test rejection of plaintext and untrusted certificates as
part of that deployment. An HTTPS browser address alone does not establish these
properties. See [PostgreSQL TLS](https://www.postgresql.org/docs/current/ssl-tcp.html).

Generate local credentials with `python scripts/configure_local.py`. Existing `.env`
files are preserved; editing an environment password does not rotate an initialized
database or its stored credentials. Production rotation needs a coordinated database,
object-store and application update. Gateway containers receive no database or
object-store credentials; query receives its database and provider configuration
but no object-store credentials.

Internal APIs trust gateway-authenticated tenant headers and must not be exposed
directly. Keep the development issuer private, use restricted database roles,
retain per-user quotas and tenant token budgets, and protect telemetry endpoints.
Treat document text as untrusted input. Grounding and citation checks reduce answer
errors; they are not a guarantee against prompt injection or unsupported statements.

Remaining operational limits include a single-host failure domain, no application
PII-redaction service, no tamper-resistant audit trail, and no hard process deadline
for every document-processing stage. Security scans and tests provide evidence for
their checks, not a claim that all vulnerabilities have been eliminated.
