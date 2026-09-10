# ADR-0010: RS256/JWKS identity and a Redis token bucket

Status: accepted. Date: 2026-09-10.

## Context

One public API forwards requests to ingest and query. Both services trust identity
headers only on the internal network. The demo has no external identity provider.
Gateway replicas must share quotas without sharing signing secrets.

## Decision

Verify RS256 JWTs against a configured JWKS URL using locked PyJWT with cryptography.
Require issuer, audience, subject, tenant, expiration and issued-at claims. Reject other
algorithms before fetching keys. Validate tenant grammar and header-safe user ids.
Cache keys for 300 seconds; refresh unknown key ids at most once per five seconds per
process. Serialize refreshes and apply the same backoff to failed fetches. Expired caches
fail authentication closed. The client cannot choose a JWKS URL.

Generate a development RSA pair locally. Mount only public JWKS in the gateway. The
optional endpoint reads it at startup; rotation requires a restart. Production uses
an issuer URL and leaves this endpoint off.

Use a Redis Lua token bucket per tenant/user pair. Redis server time avoids gateway
clock differences. One script refills, consumes, records state and sets expiry. Hash a
NUL-delimited identity pair for an unambiguous, bounded key. Share quotas across all
authenticated routes; every authenticated attempt costs one token, including failures.
Expire idle buckets after the time needed to refill capacity.

Default to **fail closed**: Redis failures return 503, protecting processing capacity.
`DI_RATE_LIMIT_FAIL_OPEN=true` trades quota enforcement for availability; authentication
still applies and readiness still reports the outage. Fail-open responses omit remaining
quota headers because the count is unknown.

Forward only approved request headers. Replace identity headers with token claims,
drop bearer tokens and cookies, and preserve request/trace ids. Stream request bodies
through one reused async client, checking declared and observed size. Reject upstream
redirects. Preserve documented client-error envelopes and normalize server failures.

## Alternatives and consequences

- Sessions require login, session lifecycle and shared storage. Revisit when browser
  login and immediate logout/revocation become requirements.
- API keys require provisioning, rotation and identity lookup. Revisit for external
  service accounts with long-lived integrations.
- Keycloak or another external IdP supplies accounts, refresh tokens and rotation.
  Adopt before exposing the demo to real users or requiring federation, revocation or
  managed identities. The local issuer is not a user-management system.
- In-memory quotas diverge across replicas and reset on restart. Redis adds an
  availability dependency but provides one atomic decision for every replica.
- Fail open by default allows unbounded processing during an outage. Operators can
  opt in when continued availability outweighs the capacity risk.

Known keys remain accepted until cache expiry; unknown keys may wait for the refresh
cooldown. There is no immediate token revocation. The bucket controls request count,
not in-flight work or document cost. A failed streamed upload can already have delivered
a prefix upstream; ingest must discard incomplete uploads independently.

References: [PyJWT verification API](https://pyjwt.readthedocs.io/en/stable/api.html),
[Redis Lua atomic execution](https://redis.io/docs/latest/develop/programmability/eval-intro/),
[HTTPX async streaming](https://www.python-httpx.org/async/).
