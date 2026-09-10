# Engineering journal

## M4 — persistent core

Kept extraction and inference outside the write transaction; the unique tenant/hash upsert
locks the document while all derived output is replaced. Migration SQL owns the schema;
SQLAlchemy reflects it to avoid duplicating column declarations. Shared fake/Postgres contracts
check replay and tenant boundaries; injected failures and concurrent writers exercise the real
transaction. Database tests use disposable databases, protecting local demo data.
