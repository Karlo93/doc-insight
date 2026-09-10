# ADR-0011: Compose delivery, service images and Caddy TLS

Status: accepted. Date: 2026-09-10.

## Decision

Ship one image per application from one parameterized Dockerfile (`APP`). Shared
Python, uv, installation and user settings stay consistent. Each build installs
only the selected workspace package and its locked production dependencies as
wheels. Relay reuses ingest; migration reuses worker. A separate Dockerfile per
application would duplicate the same installation and security policy four times.

Build the worker's tokenizer and ONNX cache into its image using production
loaders and the revisions in ADR-0003. Query warms the same cache when it declares
its worker dependency. Disable Hub networking at runtime. A volume populated on
first startup would require network access and make startup less reproducible.

Use Compose profiles for local delivery. Applications wait for healthy storage
and a successful Alembic job. Run applications as UID/GID 10001 with a read-only
root and a bounded temporary directory. Keep the existing worker CLI available.
A one-shot issuer job generates the development key pair into its own volume and
publishes only the JWKS to the gateway; `make dev-token` mints tokens through that job,
so no private key or host Python is needed to exercise the public API.

Caddy terminates TLS with an internal CA for localhost. Persist its CA and
certificates separately from the read-only configuration. It proxies health
checks to the gateway; it does not synthesize application health. Production
requires a real domain and a publicly trusted certificate or managed TLS.

## Consequences and alternatives

Images publish with immutable commit tags plus `main`, attached SBOMs and
provenance after required CI checks. Registry write permission exists only in the
main-push image job. Pull requests, including forks, cannot publish.

Kubernetes manifests, ingress and autoscaling remain wave B. Starting there would
add cluster setup before the local reviewer path works. Compose proves image
entrypoints, dependency ordering and TLS; it does not supply production HA,
network policies, secret rotation or rolling deployment guarantees.
