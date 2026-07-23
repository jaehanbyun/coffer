---
title: "Data-preserving repository metadata adoption into the control schema"
status: completed
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0006-reconciliation-runner.md
---

# Objective

Move Coffer's `repositories` table from implicit `RepositoryStore` startup creation into the same auditable Alembic revision chain as quota state, while preserving repository rows created by the pre-migration PoC. A fresh database and an exact legacy table must both reach one current control-schema revision; a drifted legacy table must fail closed; normal API, token, admission, and reconciliation processes must never create production tables; and downgrade/re-upgrade evidence must retain repository metadata. Keep registry-content inventory and production rollout outside this package.

## Done Criteria

- [x] Alembic owns `repositories` at a new current schema revision and compares both repository and quota metadata without drift on SQLite, PostgreSQL, and MariaDB.
- [x] Upgrade creates `repositories` on a fresh database, adopts an exact pre-existing PoC table without rewriting or losing rows, and rejects incompatible columns, primary key, or project/name uniqueness before claiming the new revision.
- [x] Downgrade across the adoption revision never drops repository metadata; a later re-upgrade validates and re-adopts the retained table.
- [x] `RepositoryStore` validates the exact Alembic revision and required table by default. `create_all()` remains available only through an explicit fixture bootstrap used by unit and disposable lab code.
- [x] Focused migration/store tests, both pinned shared-SQL engines, the full Python 3.11–3.13 matrix, structural checks, docs, and secret/residue scans pass.

## Non-goals

- Inventorying or importing manifests/blobs from an existing Distribution/RGW deployment, enabling quota admission over pre-existing registry content, or mutating object storage.
- Running a production database migration, backup, restore, rollback, or maintenance window.
- Adding a repository foreign key to quota rows, changing repository API semantics, or introducing repository aliases/renames.
- Credential handling, authenticated reconciliation, Galera certification/deadlock policy, deployment packaging, or destructive GC.

## Context and Evidence

- Published revision `0002_reconciliation_claims` owns quota tables, while `src/coffer/db.py` still calls `metadata.create_all()` in every `RepositoryStore` construction.
- Existing PoC SQLite databases and current migrated development databases can already contain `repositories`, so an unconditional `op.create_table()` would fail or tempt operators to discard durable project/repository mappings.
- The current `repositories` contract is five columns, primary key `id`, and named uniqueness `uq_repository_project_name` over `(project_id, name)`. The application does not store registry payloads in this table.
- Alembic downgrade cannot infer whether a table was created by the new revision or adopted from a legacy database. Preserving the table in both cases is safer than a nominally symmetric downgrade that can delete control metadata.
- Existing-data OCI inventory remains a separate gate because adopting repository metadata does not prove or charge manifests already present in Distribution/RGW.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Add one linear Alembic revision that creates or strictly adopts `repositories` | Supports both fresh and already-used PoC databases while keeping one reviewable revision authority | Unconditional create; manual `stamp`; delete/recreate; a second migration tree | 2026-07-23 |
| Validate exact legacy columns, primary key, string bounds, and named project/name uniqueness before adoption | Prevents Alembic from claiming ownership of a structurally incompatible table without inspecting tenant row values | Blind `has_table`; silently alter unknown drift; copy rows into a replacement table | 2026-07-23 |
| Make downgrade over the adoption revision non-destructive for repository metadata | The revision cannot reliably distinguish created from adopted data, and repository identity is durable control state | Always drop `repositories`; store hidden provenance state solely for downgrade symmetry | 2026-07-23 |
| Require the current revision in `RepositoryStore` and retain explicit fixture bootstrap only | Aligns API/token/reconciliation startup with the quota fail-closed schema boundary | Runtime create in production; automatic migration during service startup | 2026-07-23 |
| Keep OCI content inventory outside this work package | Repository rows alone cannot establish manifest/reference/descriptor quota state | Infer content from control rows; enable quota with an empty ledger | 2026-07-23 |

## Tasks

- [x] Add the repository adoption revision, unified Alembic target metadata, and shared schema-revision validation.
- [x] Convert every unit/disposable caller that needs ephemeral schema creation to an explicit fixture bootstrap and preserve normal runtime fail-closed behavior.
- [x] Add fresh/adopt/drift/downgrade/re-upgrade tests and extend PostgreSQL/MariaDB evidence with retained repository rows.
- [x] Update architecture, ADR/runbook/README/HANDOFF, run the complete matrix, inspect the diff, and publish atomically.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Recovered clean published `main` at `5500e36`, mapped every `RepositoryStore` construction, migration target, fixture bootstrap, and shared-SQL downgrade path, and bounded plan 0007 to repository control metadata rather than OCI payload inventory.
- Evidence: `RepositoryStore.__init__` currently performs unconditional `metadata.create_all()`. Alembic targets only `quota_metadata`; revision `0002` can coexist with an unversioned repository table; the shared-SQL harness already exercises repeat upgrade and downgrade/re-upgrade on both selected engines.
- Changed files: Added this plan and activated it in `HANDOFF.md`.
- Next exact action: Add `src/coffer/schema.py` with the shared current revision/validator, then implement migration `0003_repository_metadata` with strict create-or-adopt tests in `tests/test_migrations.py`.

### 2026-07-23 — Unified schema and cross-engine adoption verified

- Completed: Added shared revision validation, online revision `0003_repository_metadata`, unified Alembic target metadata, strict normal `RepositoryStore` startup, explicit fixture bootstraps, SQLite migration tests, PostgreSQL/MariaDB legacy-row evidence, ADR 0010, and operator/architecture documentation.
- Evidence: Ten SQLite migration tests cover fresh creation, exact adoption, column/primary-key/uniqueness/Boolean-type drift, offline rejection, repeat upgrade, non-destructive downgrade, and re-adoption. PostgreSQL 17.10 and MariaDB 11.4.12 both adopted and retained the same legacy row through downgrade/re-upgrade; quota concurrency, independent connections, process exit 17, lease recovery, fencing, model drift, and cleanup also passed.
- Failure and correction: SQLite reflects `DateTime(timezone=True)` without timezone metadata, so a direct dataclass equality assertion differed after reload even though the stored timestamp was identical. The test now compares the existing normalized public dictionary representation. Cross-engine Boolean reflection was handled as a logical Boolean/integer family while exact column names, bounds, nullability, primary key, and uniqueness remain strict.
- Changed files: New shared schema helper and revision 0003; repository/quota/runner validation; migration metadata and tests; explicit unit/disposable bootstraps; shared-SQL verifier; ADR 0010, README, architecture, runbooks, this plan, and `HANDOFF.md`.
- Next exact action: Run the complete Python 3.11–3.13 and structural/safety matrix, inspect the final diff, complete this plan, and publish atomically.

### 2026-07-23 — Work package completed

- Completed: Tightened MySQL-compatible Boolean adoption to exact `TINYINT(1)`, reran both real database engines and Distribution reconciliation, completed all supported Python and structural checks, and reconciled durable documentation with the implemented control-schema contract.
- Evidence: Python 3.11, 3.12, and 3.13 each pass 134 tests. Lock, compile, Alembic head `0003`, installed runner help, migrated-schema Gunicorn loading, 57 Bash/ShellCheck files, five Compose models, every PoC Make target dry-run, 45 Markdown files, 25 local links, diff checks, private-key/JWT shape checks, and Gitleaks over 188 project-owned files pass. PostgreSQL/MariaDB and Distribution harnesses pass with zero labeled runtime, generated credential, or state residue; Podman is stopped.
- Failure and correction: Final review found that accepting every reflected integer for MySQL `BOOLEAN` would also admit `BIGINT` drift. The validator now accepts only native `Boolean` or MySQL-family `TINYINT(1)`, a new drift test rejects `BIGINT`, and both pinned engines passed again.
- Changed files: The complete file set recorded in the prior milestone; no production database, object storage, credential, or external deployment was changed.
- Next exact action: Publish the completed plan atomically, then scope a separate read-only OCI content inventory/import work package without enabling quota or touching object storage.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Baseline recovery | clean local/remote `main` at `5500e36`; repository/migration call graph | passed |
| SQLite fresh and legacy adoption | focused Alembic and `RepositoryStore` tests | passed: 10 tests including four drift classes and offline rejection |
| PostgreSQL/MariaDB adoption | pinned `poc/quota-sql` harness | passed: exact row adopted/retained/re-adopted; existing quota/claim evidence passed; zero residue |
| Complete regression | Python 3.11-3.13, compile, Alembic, Bash/ShellCheck, Compose, docs, diff, secret scan | passed: 134 tests per Python version and all structural/safety checks |

## Failures, Blockers, and Risks

- Cross-engine reflection represents booleans and timezone metadata differently. Adoption validation must enforce the durable logical contract without depending on dialect-specific display strings.
- A non-destructive downgrade intentionally leaves `repositories` outside an active Alembic revision at `base`; normal stores must still reject that state until re-upgrade.
- This migration can preserve control rows but cannot make quota authoritative for registry content that predates the ledger. Production admission remains blocked on a separate write-stopped inventory/import rehearsal and backup/restore plan.

## Handoff

- Current state: Completed and verified; ready for atomic publication.
- Exact next action: Publish this completed work package, then scope read-only OCI inventory/import discovery as a separate plan.
- First command: `gh auth status` followed by explicit staging and `git diff --cached --check`.
- Questions requiring user input: none for local migration implementation and disposable verification; production data access, backup/restore, and rollout remain outside authorization.
