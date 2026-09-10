# ADR-0009: A heartbeat per worker consumer

Status: accepted.

## Decision

Use the Redis consumer name, `{hostname}-{pid}`, in the readiness key:
`di:worker:{hostname}-{pid}`. Refresh it at loop and message boundaries with a
30-second TTL. This replaces the hostname-only worker heartbeat convention.

## Why

More than one worker can run on a host. Separate keys expose each consumer's
recent progress and cannot overwrite a sibling's heartbeat. The consumer name
also matches the pending-entry owner shown by Redis.

## Consequences and alternatives

A hostname-only key is simpler to probe but can conceal a stalled sibling.
Readiness probes must now identify the process or enumerate the host's consumers.
Expired keys disappear automatically; shutdown does not delete another process's key.

Refreshes occur between sequential operations. A stage lasting more than 30 seconds
can expire the key until the next boundary. The heartbeat alone must not trigger
termination of long OCR work. Redis reclaim uses its separate configured idle lease;
it does not use heartbeat absence as proof of process death.

Revisit refresh scheduling if probes must stay valid throughout long OCR jobs.
That requires an independent refresh and an explicit policy for stalled processing.
