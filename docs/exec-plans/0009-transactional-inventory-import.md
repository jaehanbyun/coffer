---
title: "Transactional existing-content inventory import baseline"
status: completed
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0008-existing-content-inventory.md
---

# Objective

Define and prove the smallest disposable, transactional path that imports one verified `coffer.inventory/v1` artifact into Coffer's existing project-logical quota ledger before admission is enabled. The import must validate the canonical artifact and its expected SHA-256, bind every project/repository to current control authority, create committed manifest/reservation/descriptor state atomically, preserve honest over-limit usage, make an exact replay a no-op, reject a different baseline or a non-empty ledger, and leave no partial marker or quota state after failure. Do not access production Distribution/RGW/SQL, handle credentials, or enable admission in this package.

## Done Criteria

- [x] A strict parser accepts only canonical `coffer.inventory/v1`, recomputes every redundant project/repository/manifest/descriptor aggregate, and binds the raw artifact to an operator-supplied SHA-256.
- [x] One Alembic revision owns an immutable singleton baseline-import marker; normal schema validation includes it on SQLite, PostgreSQL, and MariaDB.
- [x] One database transaction creates committed reservations, manifest rows, reservation graphs, project-unique descriptors/reference counts, exact used bytes, zero reserved bytes, and the marker, or creates none of them.
- [x] The same artifact replay reports an idempotent no-op; a different artifact, pre-existing ledger/claim state, missing or mismatched repository authority, or missing project quota fails closed without ledger mutation.
- [x] Focused unit/migration/concurrency/rollback/over-limit tests and disposable PostgreSQL/MariaDB verification pass; operator docs, ADR candidate, execution plan, and HANDOFF preserve the separate production cutover gates.

## Non-goals

- Reading a production registry, RGW bucket, control database, or credentials; running a maintenance window, backup, restore, or rollback.
- Enabling quota admission, changing registry ingress, reconciling against Distribution, deleting content, or running GC.
- Incremental/delta imports, merging into a live/non-empty quota ledger, re-baselining with a second artifact, or importing orphan authority by inference.
- Large-scale streaming/chunked transactions, Galera certification policy, production packaging, artifact signing infrastructure, or operator authorization workflow.

## Context and Evidence

- Completed plan 0008 produces canonical secret-free `coffer.inventory/v1` only after exact authority, digest/media/size, nested-index, page/hash, two-scan, and digest-only coverage checks.
- The current quota ledger represents one published manifest as a committed reservation, its unique descriptor graph, a committed manifest row, and project descriptor reference counts. `project_quotas.used_bytes` is derived from project-unique committed descriptors; `reserved_bytes` covers only pending work.
- `project_quotas` and exact `repositories` rows already belong to the unified Alembic schema. Import must not invent a quota limit or repository owner.
- The schema permits actual used bytes to exceed a configured limit. Recording that fact is safer than rejecting or undercounting pre-existing content; the existing admission calculation will reject new unique bytes while idempotent existing graphs add zero.
- A whole-artifact transaction is acceptable for the bounded disposable PoC. Production scale, timeout, backup, and chunking policy remain separate promotion gates.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Import only into an empty quota ledger with admission still disabled | Avoids ambiguous merges, reference-count races, and partial authority during the first baseline | Merge with live reservations; reconcile an incomplete import later | 2026-07-23 |
| Store one immutable singleton baseline marker keyed by canonical artifact SHA-256 | Makes exact replay observable and blocks silent re-baselining | Infer completion from row counts; allow multiple baselines; filesystem-only marker | 2026-07-23 |
| Commit the marker and every ledger row in one database transaction | A crash or constraint failure must leave neither a completion claim nor partial quota state | Per-project commits; compensating deletes; mark complete in a second transaction | 2026-07-23 |
| Require existing project quotas and exact repository ID/project bindings, but allow imported usage above the configured limit | Import records reality without inventing policy; admission can then deny new unique bytes | Auto-create limits; cap imported usage; reject an honest over-limit baseline | 2026-07-23 |
| Use deterministic reservation IDs and import request IDs derived from artifact and manifest identity | Makes disposable evidence and replay comparison stable without treating IDs as secrets | Random IDs; mutable sequence IDs; reuse registry request IDs that do not exist historically | 2026-07-23 |

## Tasks

- [x] Add strict inventory-artifact parsing and focused redundant-aggregate/canonical-hash tests.
- [x] Add the baseline marker migration/model and transactional import primitive with idempotency, authority, empty-ledger, rollback, concurrency, and over-limit tests.
- [x] Add a secret-safe installed CLI and extend the disposable shared-SQL harness across PostgreSQL and MariaDB.
- [x] Record proposed ADR 0012 and the production cutover/refusal boundary, run the complete matrix, inspect the diff, and publish atomically.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Published plan 0008 at `65bdace`, mapped `coffer.inventory/v1` facts to the current reservation/manifest/descriptor/reference-count model, and bounded the next package to a one-time empty-ledger import in disposable SQL.
- Evidence: Existing quota commits already define the target ledger semantics; the current schema has no durable import marker and no safe way to distinguish a completed baseline from partial/manual rows.
- Changed files: Added this plan and activated it in `HANDOFF.md`.
- Next exact action: Add strict canonical artifact parsing in `src/coffer/quota_import.py` and focused tests before introducing any schema or write path.

### 2026-07-23 — Canonical artifact parser verified

- Completed: Added immutable inventory dataclasses, exact field/type/order/media/digest/size validation, redundant project/repository/manifest/descriptor and summary recomputation, canonical compact-byte enforcement, and operator-supplied SHA-256 binding. Repository output now has an explicit immutable project/repository-ID sort order.
- Evidence: Nine focused import-parser tests plus the 17 inventory tests pass. Noncanonical bytes, expected-digest mismatch, aggregate/descriptor drift, index-child mismatch, missing project summaries, and unknown secret-shaped fields fail before any database path exists.
- Changed files: `src/coffer/quota_import.py`, `tests/test_quota_import.py`, `src/coffer/inventory.py`, this plan, and `HANDOFF.md`.
- Next exact action: Add Alembic revision `0004_inventory_import` and the matching singleton marker model, then implement the atomic empty-ledger import primitive behind the parsed artifact type.

### 2026-07-23 — Atomic SQLite import contract verified

- Completed: Added revision/model `0004_inventory_import`, a downgrade guard for a committed marker, deterministic reservation identities, exact repository/quota authority checks, global empty-ledger refusal, one-transaction marker/committed graph/reference-count/usage writes, exact replay, concurrent replay, and secret-free aggregate results.
- Evidence: Migration, inventory, parser, and import tests total 46 passes. The two-manifest graph creates two committed reservations, five reservation edges, four project-unique descriptors with reference counts 2/1/1/1, used bytes 220, and reserved bytes zero. A forced second-reservation trigger failure rolls back the marker and every ledger table; concurrent SQLite callers return exactly `imported` and `already_imported`; usage above a 10-byte limit remains 220 and a novel byte is denied.
- Failure and correction: The first implementation passed a descriptor mapping directly to `Counter.update()`, which interpreted descriptor objects as counts and failed before SQL completion. It now counts the graph's digest keys explicitly; the full focused set passes.
- Changed files: Revision 0004, `src/coffer/schema.py`, quota marker metadata, import implementation/tests, migration tests, this plan, and `HANDOFF.md`.
- Next exact action: Add installed `coffer-import-inventory` with environment-only database URL input and extend `poc/quota-sql` to prove import/idempotency/rollback on pinned PostgreSQL and MariaDB.

### 2026-07-23 — Installed CLI and shared-SQL import passed

- Completed: Added `coffer-import-inventory` with canonical artifact path/hash arguments, environment-only `COFFER_DATABASE_URL`, aggregate-only output, configuration/failure exits, and connection disposal. Extended the pinned shared-SQL harness with a forced second-manifest constraint failure, two concurrent exact importers, different-baseline rejection, exact replay, and over-limit evidence.
- Evidence: PostgreSQL 17.10 and MariaDB 11.4.12 both leave marker/reservation/edge/manifest/descriptor counts at zero after the forced failure, then converge concurrent import to one `imported` and one `already_imported`, create the exact 2/5/2/4 ledger shape, retain used/reserved 220/0 against limit 10, and reject a different digest. CLI/migration/inventory/import focused tests total 49 passes; the installed help and lock check pass; the fixture removes every labeled container, volume, network, generated password, and state directory; Podman is stopped.
- Failure and correction: The first MariaDB concurrent marker race returned deadlock 1213 after PostgreSQL passed. Import now retries only MySQL 1205/1213 and PostgreSQL 40001/40P01 transaction failures, at most three whole attempts, checking for a committed marker between attempts. The complete two-engine rerun passed.
- Changed files: Import CLI/entry point, shared-SQL verifier, schema/import implementation and tests, this plan, and `HANDOFF.md`.
- Next exact action: Add proposed ADR 0012 and update the inventory/quota runbooks, architecture, README, ADR 0009/0011, plan, and HANDOFF with the proven PoC boundary and remaining production cutover gates.

### 2026-07-23 — Work package complete and ready for atomic publication

- Completed: Added proposed ADR 0012 and updated README, architecture, ADRs 0009–0011, inventory/quota runbooks, the shared-SQL fixture guide, this plan, and `HANDOFF.md`. The documents separate the verified disposable importer from production backup, writer exclusion, representative-scale transaction, authenticated comparison, maintenance, rollback, and admission-cutover authorization.
- Evidence: Python 3.11.14, 3.12.2, and 3.13.14 each pass 174 tests; only the known WebOb `cgi` deprecation warning appears on 3.11/3.12. Lock, compile, Alembic head `0004`, all three installed CLIs, Go format/test/vet, 58 Bash/ShellCheck files, six Docker Compose models, 54 Make dry-runs, 54 Markdown files, 32 local links, 99 external links, and diff checks pass. The already-completed PostgreSQL 17.10/MariaDB 11.4.12 run ended with zero container, volume, network, credential, and state residue.
- Failure and correction: The first Python 3.11/3.12 reruns used disposable environments that did not contain the installed `coffer-reconcile` entry point, so two subprocess tests failed. Installing the current checkout editable into those ignored environments and placing their `bin` directories on `PATH` produced 174 passes on each version. During the final static pass, the local Podman 5.6.0/libkrun machine began reporting a successful boot and then immediately stopped; two clean non-destructive retries behaved the same. No machine or data was recreated. Compose validation therefore used Docker Compose v5.1.4 without a daemon, while the live inventory fixture remains covered by plan 0008's completed run and the current shared-SQL import code by this package's successful two-engine run.
- Changed files: Import parser/CLI, revision 0004 and schema metadata, inventory ordering, shared-SQL fixture, focused tests, proposed ADR 0012, architecture/operator documentation, README, this plan, and `HANDOFF.md`.
- Next exact action: Stage only the plan 0009 file set, run staged secret and cached-diff checks, commit once as `feat: add transactional inventory import`, verify the GitHub account, and atomically push guarded by the published `65bdace` remote head.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Published baseline recovery | clean local/remote `main` at `65bdace`; inventory/quota/schema call graph | passed |
| Strict canonical artifact parser | focused malformed/redundant aggregate/hash tests | passed: 9 import-parser and 17 inventory tests |
| Atomic import and idempotency | SQLite plus PostgreSQL/MariaDB failure/concurrency evidence | passed on SQLite, PostgreSQL 17.10, and MariaDB 11.4.12 |
| Complete regression | Python 3.11-3.13, migrations, Bash/ShellCheck, Compose, docs, diff, secret scans | passed: 174 tests per Python version and all structural/safety checks; live SQL passed earlier in this package |

## Failures, Blockers, and Risks

- The current artifact is intentionally compact but redundant. Import must recompute project descriptors and all summaries instead of trusting aggregate fields independently.
- Whole-artifact transactions can be too large for production data volumes and Galera certification. Passing this PoC cannot promote that transaction shape without measured representative evidence.
- A committed baseline marker intentionally prevents re-import after later reconciliation releases content. Re-baselining requires a distinct approved rollback/migration design; replay must never resurrect removed manifests.

## Handoff

- Current state: Plan 0009 is complete and ready for one atomic commit and guarded push. Proposed ADR 0012 remains proposed; no production access, credentials, maintenance, import, or admission change occurred.
- Exact next action: Stage the exact plan 0009 file set, run staged secret/cached-diff checks, commit once, verify the GitHub account, and atomically push from expected remote head `65bdace`.
- First command: `git add` with the explicit changed-file list recorded by `git status --short`.
- Questions requiring user input: none for local/disposable implementation; production credentials, data access, backup/restore, import execution, maintenance, and admission cutover remain outside authorization.
