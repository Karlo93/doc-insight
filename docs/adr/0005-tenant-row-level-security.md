# ADR-0005: FORCE row-level security with transaction-local tenant context

Status: accepted. Date: 2026-09-10.

## Decision

Keep shared documents, chunks and entities tables. Enable and FORCE RLS with one
FOR ALL policy per table. Both USING and WITH CHECK require `tenant_id` to equal
`NULLIF(current_setting('app.tenant_id', true), '')`. PostgreSQL can return an empty
string after resetting a custom setting; normalize it to NULL to deny empty tenant rows
too. Retain application filters and composite
foreign keys as independent checks. Missing context grants access to no tenant.

Bind the tenant through `set_config('app.tenant_id', :tenant, true)` before each
repository transaction's first data statement, including REPEATABLE READ reads.
This is parameterized SET LOCAL: commit or rollback clears it before connection-pool
reuse. Session-level SET would let the next request inherit the previous tenant.
Metadata reflection reads catalogs and needs no tenant context.

Use two credentials. `di_migrate` owns tables and has BYPASSRLS for migrations;
`di_app` has only schema USAGE and table SELECT/INSERT/UPDATE/DELETE. Runtime has no
superuser, BYPASSRLS, owner-role membership or ownership privileges. Development
Compose's existing `di` superuser fills the migration role only. Alembic reads
`DI_MIGRATION_DATABASE_URL`; runtime reads `DI_DATABASE_URL`. See the
[setup commands](../pipeline.md#storage-and-search).

## Consequences and alternatives

FORCE applies policies to ordinary table owners too; it cannot constrain superusers
or BYPASSRLS. Keeping runtime separate also prevents it altering or disabling policies.
Tests use a restricted login, and temporarily transfer ownership inside a rolled-back
transaction to prove FORCE itself. Tests exercise all four row operations, absent
context and pooled connection reuse after commits, rollbacks and exceptions.

RLS catches omitted or incorrect row filters. Trusted service code still chooses the
tenant; a caller able to execute arbitrary SQL can change this custom setting. RLS
does not authenticate tenants or replace the gateway's credential validation. Global
uniqueness/foreign-key checks can expose constraint failures, so API errors need care.

Per-tenant schemas multiply migrations and require safe schema routing. Per-tenant
databases offer stronger credential, backup and resource isolation, but multiply
connections and operations. Neither cost is justified by this shared-table workload.
Application filters alone leave a missing WHERE clause able to leak data. A single
owner login with FORCE still permits policy changes and mixes migration privileges
with runtime, so it was rejected.
