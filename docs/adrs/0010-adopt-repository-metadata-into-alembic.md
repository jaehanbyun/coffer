# ADR 0010: Adopt Repository Metadata into the Alembic Control Schema

- Status: accepted for PoC validation
- Date: 2026-07-23
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0007-unified-control-schema.md`
- Related runbook: `docs/runbooks/quota-schema-reconciliation.md`

## Context

Coffer introduced the `repositories` table before its quota schema and created it implicitly in every `RepositoryStore` constructor. Later quota revisions made Alembic the production schema authority, but repository identity remained outside that chain. Existing PoC databases can therefore contain durable project/repository mappings with no Alembic revision, or contain both repository metadata and quota revision `0002`.

Unconditionally adding `op.create_table("repositories")` would fail on those databases. Dropping or recreating the table would discard the immutable authority used by token reduction, admission, and reconciliation. Blindly accepting any table with the same name would let Alembic claim an incompatible schema.

## Decision

1. Revision `0003_repository_metadata` integrates repository metadata into the single Coffer control-schema chain and Alembic compares both repository and quota metadata. The later `0004_inventory_import` revision is now the current head and adds only the baseline-import marker.
2. The revision runs online. On a fresh database it creates `repositories`; on an existing database it validates the exact five-column contract, `id` primary key, string bounds, nullability, and named `(project_id, name)` uniqueness before adopting the table without rewriting rows.
3. Incompatible legacy structure aborts before Alembic records revision `0003`. Offline SQL generation is rejected because it cannot safely decide create versus adopt.
4. `RepositoryStore` and `QuotaStore` both require the exact current revision and their required tables during normal construction. `MetaData.create_all()` is available only behind explicit `bootstrap_schema=True` in unit and disposable fixtures.
5. Downgrade across revision `0003` retains `repositories`. The migration cannot reliably distinguish a table created by the revision from one it adopted, and deleting durable repository identity for downgrade symmetry is unsafe. Normal stores reject the downgraded revision until a re-upgrade validates and adopts the retained table again.
6. Repository metadata adoption does not inventory Distribution/RGW content or populate the quota ledger. Admission over a registry with pre-existing payloads remains blocked on a separate write-stopped inventory/import and backup/restore procedure.

## Consequences

- API, token, admission, and reconciliation processes fail closed instead of creating production repository tables during startup.
- Exact pre-migration repository rows can survive forward migration, bounded downgrade, and re-upgrade without a copy or identifier change.
- Operators must run the migration online through an owner-approved migration job before starting a new binary. This PoC evidence is not authorization to migrate a production database.
- A database at Alembic `base` can intentionally retain `repositories`, but that table alone is not a current or runnable Coffer schema.
- Existing OCI content and logical quota state remain a separate and larger migration problem.

## Evidence and Remaining Gates

SQLite tests cover fresh creation, exact legacy adoption, incompatible columns/primary-key/uniqueness rejection, offline rejection, repeat upgrade, non-destructive downgrade, and re-adoption. The pinned PostgreSQL 17.10 and MariaDB 11.4.12 harnesses preserve one legacy repository row through adoption and downgrade/re-upgrade while also rerunning quota concurrency, process abandonment, lease recovery, and fencing.

Production promotion still requires a restorable backup, least-privilege migration/runtime roles, maintenance and rollback ownership, real data-volume timing, Galera behavior where applicable, and a write-stopped OCI inventory/import rehearsal before quota admission becomes authoritative.
