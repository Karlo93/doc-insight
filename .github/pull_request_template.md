## What

Describe the resulting behavior and scope.

Changed application lines: <!-- additions + deletions in apps/ and packages/; 0 for docs-only -->

## Why

Explain the problem and any trade-off. Link an ADR if applicable.

## How tested

List exact commands, counts and coverage. Record any blocked or omitted checks.

<details>
<summary>Full make check output</summary>

```text
Paste the complete output here. Redact secrets, document content and machine-specific paths;
state any redactions. If blocked, paste the failure and explain the missing prerequisite.
```

</details>

## Try it yourself

Give commands from a clean clone, with required tools, environment and services.

## Checklist

Leave unmet or inapplicable items unticked and explain why.

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
