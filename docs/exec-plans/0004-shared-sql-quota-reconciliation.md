---
title: "Versioned shared-SQL quota schema and reconciliation baseline"
status: completed
updated: 2026-07-22
owner: primary-agent
depends_on: docs/exec-plans/0003-barbican-kms-quota-poc.md
---

# Objective

Turn ADR 0009's local quota ledger into the smallest production-oriented shared-SQL and reconciliation vertical slice. Replace implicit quota-table creation with a versioned Alembic migration path, prove the ledger's locking and state transitions against disposable PostgreSQL and MariaDB instances, and add a bounded idempotent reconciliation service that probes exact private Distribution manifest digests and conservatively commits, releases, or retains quota state. This package does not deploy to production or claim multi-replica ingress/HA completion.

## Done Criteria

- [x] A checked-in Alembic baseline creates the quota ledger schema with explicit constraints and indexes on PostgreSQL, MariaDB, and SQLite; upgrades are idempotent and application startup does not silently create production quota tables.
- [x] Disposable PostgreSQL and MariaDB tests apply the migration from an empty database, exercise two independent SQL connections through the quota ledger, prove one-winner concurrent admission and valid retry/release transitions, and leave no container, volume, or credential residue.
- [x] A bounded reconciliation component lists deterministic candidates, resolves their immutable project/repository identity, probes the exact manifest digest through a private Distribution interface, verifies a successful content digest, and performs idempotent present/absent/indeterminate transitions without optimistic refunds.
- [x] Focused tests cover lost/duplicate/reordered observations, 200/404/401/5xx/transport outcomes, stale-candidate bounds, shared descriptors, deletion refund, and no state change on indeterminate evidence.
- [x] ADR 0009, architecture/research/runbook documents, this plan, and `HANDOFF.md` record the migration/reconciliation authority, verified evidence, remaining multi-worker lease/ingress gates, and exact next action.
- [x] The complete Python 3.11–3.13, static, Compose, migration, documentation, and secret/residue verification matrix passes.

## Non-goals

- Production database deployment, credentials, backups, online schema rollout against existing operator data, or a destructive migration.
- A Distribution notification consumer as quota authority; notifications remain advisory wake-up hints.
- Multi-worker reconciliation leasing, separate-host ingress/load-balancer HA, physical-byte billing, destructive GC, or automatic blob deletion.
- Changing the accepted project-logical accounting definition, proxying blob bodies, or forking Distribution.

## Context and Evidence

- Completed plan 0003 and accepted-for-PoC ADR 0009 prove the private manifest seam and SQLite state machine but explicitly leave production migrations, real row locks, and reconciliation open.
- `src/coffer/quota.py` currently owns five SQLAlchemy tables and calls `MetaData.create_all()` in `QuotaStore.__init__`; that is convenient for fixtures but is not an auditable production upgrade authority.
- Existing states are `pending`, `release_pending`, `committed`, and `released`. Capacity remains charged while evidence is ambiguous; exact manifest presence may commit a pending reservation and exact absence may release it.
- Reconciliation must use repository identity from the control authority and probe `HEAD /v2/<canonical-repository>/manifests/<digest>` over a private service path. A 200 is acceptable only when `Docker-Content-Digest` matches; 404 is absence; authorization, dependency, malformed, or transport results are indeterminate and retain charge.
- The user's 2026-07-22 instruction authorizes autonomous long-horizon local implementation and verification without human checkpoints. It does not authorize production deployment, external publication, credentials, or destructive operations.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Use Alembic as the sole production quota-schema upgrade authority | Alembic is already present through `oslo.db`, is standard in OpenStack services, and produces reviewable forward migrations | Runtime `create_all`; hand-written per-engine SQL; destructive schema recreation | 2026-07-22 |
| Keep fixture schema creation explicit and test-only | Local unit fixtures remain fast without allowing production startup to mutate schema silently | Dialect-based implicit creation; forcing every unit test to launch a database server | 2026-07-22 |
| Reconcile from the durable ledger with exact digest probes | The ledger records every admission ambiguity and digest identity; notifications can be lost, duplicated, or reordered | Notification-only truth; tag probes; bucket listing as logical authority | 2026-07-22 |
| Treat every outcome except verified matching 200 or exact 404 as indeterminate | Conservative charging prevents optimistic refunds during auth, dependency, proxy, or protocol failures | Release on timeout/5xx; trust an unverified 200; retry forever in one process | 2026-07-22 |

## Tasks

- [x] Add the Alembic environment/revision, explicit fixture bootstrap, schema constraints/indexes, and migration tests.
- [x] Add a disposable pinned PostgreSQL/MariaDB shared-SQL harness and prove migration plus concurrent ledger behavior.
- [x] Implement the bounded exact-digest reconciliation service and focused state/outcome tests.
- [x] Exercise reconciliation against an isolated Distribution fixture and verify cleanup/secret hygiene.
- [x] Reconcile durable architecture/ADR/runbook/HANDOFF, run the complete regression matrix, inspect the diff, and prepare the completed work package for publication.

## Progress Log

### 2026-07-22 — Work package activated

- Completed: Recovered completed plan 0003 and the clean `325fbf2` repository state, applied the long-horizon harness, and scoped the next package to versioned quota migrations plus conservative exact-digest reconciliation.
- Evidence: ADR 0009 and the handoff name production SQL migrations/reconciliation as the next gate; `QuotaStore` currently performs implicit `create_all`, and only `reconcile_absent` exists.
- Changed files: Added this plan and activated it in `.codex/state/HANDOFF.md`.
- Next exact action: Add an explicit schema bootstrap boundary to `src/coffer/quota.py`, then create `alembic.ini`, `migrations/env.py`, and the initial quota revision before changing reconciliation behavior.

### 2026-07-22 — Versioned quota schema boundary completed

- Completed: Added an explicit Alembic dependency and environment, revision `0001_quota_ledger`, named state/non-negative constraints, foreign keys, reconciliation indexes, and strict application-side revision validation. `QuotaStore` no longer calls `create_all()` unless a fixture explicitly requests `bootstrap_schema=True`.
- Evidence: A missing schema fails immediately; an explicit fixture schema cannot masquerade as migrated production state; empty SQLite upgrade and repeated upgrade succeed; the migrated store operates normally; bounded downgrade removes only the five quota tables and indexes. Focused migration/quota/admission verification reports 22 passed.
- Changed files: `pyproject.toml`, `uv.lock`, `alembic.ini`, `migrations/`, `src/coffer/quota.py`, quota fixtures, migration/quota tests, this plan, and the handoff.
- Next exact action: Pin disposable PostgreSQL and MariaDB images, add their Python SQLAlchemy drivers and `poc/quota-sql/` harness, then run revision upgrade plus independent-connection concurrency on each engine.

### 2026-07-22 — Shared PostgreSQL and MariaDB behavior verified

- Completed: Pinned the PostgreSQL 17.10 Alpine and MariaDB 11.4.12 Noble multi-architecture image indexes plus current SQLAlchemy drivers; added the disposable `poc/quota-sql/` Compose harness with file-mounted generated secrets and loopback-only ports; exercised empty/repeated upgrade, model drift detection, independent backend connections, database constraints, concurrent one-winner admission, idempotent retry/commit/release, and downgrade/re-upgrade on both engines.
- Evidence: PostgreSQL 17.10 and MariaDB 11.4.12 each reported exactly one admission and one quota denial, zero final used/reserved bytes, distinct backend connection IDs, no migration drift, and successful downgrade/re-upgrade. Cleanup reported zero labeled containers, volumes, networks, or generated credentials. An initial Podman `internal` network prevented Mac port-forward delivery and was removed while retaining loopback-only host bindings; MariaDB constraint code 4025 was normalized as the expected DBAPI-level rejection.
- Changed files: `pyproject.toml`, `uv.lock`, and new `poc/quota-sql/` Compose, verification, Make, and operator guidance files, plus this plan and the handoff.
- Next exact action: Add deterministic stale-candidate listing to `QuotaStore`, then implement the bounded present/absent/indeterminate exact-digest probe in `src/coffer/quota_reconciliation.py` with focused unit tests.

### 2026-07-22 — Exact-digest reconciliation baseline verified

- Completed: Added monotonic reservation versions and compare-and-set reconciliation, deterministic stale candidate pages with bounded cursors, periodic committed-manifest scans, control-authority repository resolution, and an HTTP(S) Distribution HEAD probe. Only one matching `Docker-Content-Digest` on HTTP 200 commits/refreshes; exact 404 releases; missing repository authority, mismatched/missing/duplicate digest headers, 401/403, 5xx, and transport failures remain indeterminate without ledger mutation.
- Evidence: Twenty-four focused migration/quota/reconciliation tests passed for stale bounds, cursor pagination, lost/duplicate/reordered observations, CAS conflicts, present/absent/indeterminate outcomes, 401/403/500/503/transport behavior, and shared-descriptor deletion refunds. `make -C poc/quota-reconciliation verify` passed against unmodified pinned Distribution v3.1.1 with exact present commit, absent pending release, stale observation rejection, committed deletion refund, last-reference accounting, final zero usage, and zero container/volume/network/state residue. The versioned schema then passed the PostgreSQL 17.10 and MariaDB 11.4.12 harness again.
- Changed files: `src/coffer/quota.py`, migration revision `0001_quota_ledger`, new `src/coffer/quota_reconciliation.py`, `tests/test_quota_reconciliation.py`, new `poc/quota-reconciliation/`, this plan, and the handoff.
- Next exact action: Reconcile ADR 0009, architecture and operator documentation with the verified migration/reconciliation authority, then run the complete repository regression and safety matrix.

### 2026-07-22 — Documentation and final regression completed

- Completed: Updated ADR 0009, the architecture baseline, quota research, real-lab runbook, README, and a new schema/reconciliation operator boundary with the Alembic, exact-probe, and multi-worker lease decisions. Reworked and visually inspected the component map after its first render exposed overlapping reconciliation labels.
- Regression discovered and corrected: Running Alembic before the token tests disabled existing application loggers because Python `fileConfig()` defaults to `disable_existing_loggers=True`. `migrations/env.py` now preserves existing loggers, and a focused regression proves migration execution cannot silence Coffer logging.
- Evidence: The complete suite reports 108 passed on each of Python 3.11, 3.12, and 3.13. Lock, compile, Alembic head, Bash, ShellCheck, Gunicorn, five Compose models, every PoC Make target dry-run, 45 Markdown files, 18 local links, all three rendered diagrams, diff checks, project-owned Gitleaks, and private-key/JWT scans pass. The PostgreSQL/MariaDB and Distribution harnesses passed again and left zero labeled runtime or credential/state residue.
- Changed files: ADR/architecture/research/runbook/README documentation, new operator runbook, Alembic logging regression, this completed plan, and the handoff, in addition to the implementation and fixtures recorded in earlier milestones.
- Exact next action: After explicit publication authorization, verify the `jaehanbyun` GitHub account and atomically commit and push this completed work package.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Baseline recovery | `git status --short`; `git log -5 --oneline --decorate`; source-of-truth documents | passed: clean `main` at `325fbf2` |
| Alembic schema | upgrade/repeat/downgrade on SQLite plus both disposable shared engines | passed: exact head validation, named constraints/indexes, drift check, and logging isolation |
| Shared-SQL ledger | `make -C poc/quota-sql verify` | passed: PostgreSQL 17.10 and MariaDB 11.4.12; distinct connections; one winner; retry/release; downgrade/re-upgrade; zero residue |
| Reconciliation | focused unit tests plus `make -C poc/quota-reconciliation verify` | passed: exact 200 digest/404; fail-closed indeterminate outcomes; CAS; shared deletion refund; zero residue |
| Repository regression | Python 3.11–3.13, compile, Bash/ShellCheck, Compose, docs | passed: 108 tests per Python version; all structural/runtime checks passed |
| Secret/residue | scoped Gitleaks plus container/volume/runtime cleanup | passed: no project-owned leaks; zero labeled runtime or generated credential/state residue |

## Failures, Blockers, and Risks

- A first revision must represent the already-implemented ledger without pretending an in-place production upgrade has been exercised; existing-data stamping/online rollout remains a non-goal until an operator dataset exists.
- Network probes must not hold SQL row locks. The first worker is bounded and idempotent; distributed claims/leases remain a later multi-worker gate unless required by real database evidence.
- PostgreSQL and MariaDB differ in constraint naming, time-zone handling, and row-lock behavior. Both disposable engines pass this bounded fixture, but production Galera/deadlock, TLS, backup, and connection-pool behavior remains unproven.
- Podman's Mac port forwarding accepts host TCP while an `internal` container network cannot deliver it to the database. The harness therefore relies on loopback-only published ports rather than claiming container-level egress isolation.

## Handoff

- Current state: Completed, fully verified, and published as one atomic `main` milestone after explicit user authorization.
- Exact next action: Create and activate plan 0005 for multi-worker reconciliation scheduling, bounded observability, and process-failure evidence.
- First file: `docs/exec-plans/0005-multi-worker-reconciliation.md` from `docs/exec-plans/TEMPLATE.md`.
- Questions requiring user input: none for local plan 0005 work; production deployment, credentials, separate-host infrastructure, and destructive operations remain outside authorization.
