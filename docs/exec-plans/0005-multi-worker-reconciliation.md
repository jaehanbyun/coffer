---
title: "SQL-backed multi-worker reconciliation claims and observability"
status: completed
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0004-shared-sql-quota-reconciliation.md
---

# Objective

Turn plan 0004's single-worker exact-digest reconciler into the smallest safe multi-worker vertical slice. Add database-backed, expiring claims with fencing tokens so independent workers can divide a bounded stale-reservation batch without duplicate mutation, recover work abandoned by a failed process, and reject a late result from a superseded worker. Preserve conservative quota accounting, keep Distribution probes outside database transactions, and expose only fixed-cardinality aggregate outcomes suitable for the reference multi-worker process model.

## Done Criteria

- [x] Alembic revision `0002` adds an explicit reconciliation-claim schema with named constraints and indexes; strict application schema validation, upgrade, downgrade, and model-drift checks pass on SQLite, PostgreSQL, and MariaDB.
- [x] Independent workers atomically claim non-overlapping bounded candidate sets, each claim has a unique fencing token and expiry, and an abandoned claim becomes reclaimable after its lease without releasing quota.
- [x] A late or duplicated worker result cannot mutate a reservation after its claim expired, was released, or was reassigned; successful present/absent transitions consume the matching claim in the same transaction.
- [x] Distribution resolution and probing occur only after the claim transaction closes. Indeterminate observations retain accounting state and use the lease as bounded retry backoff.
- [x] Reconciliation exposes aggregate metrics with a fixed result-label vocabulary and no worker, project, repository, digest, request, claim-token, or credential labels.
- [x] Focused tests cover competing workers, disjoint batches, expiry/reclaim, stale fencing tokens, process abandonment, duplicate/reordered results, and metric cardinality.
- [x] Disposable PostgreSQL and MariaDB evidence proves cross-connection claim exclusion and lease recovery, then removes every labeled runtime resource and generated credential.
- [x] ADR/runbook/architecture documents, this plan, and `HANDOFF.md` record the accepted scheduling boundary, verified evidence, remaining production gates, and exact next action; the complete regression and safety matrix passes.

## Non-goals

- Production deployment, credentials, backups, existing-data rollout, Galera certification/deadlock tuning, or destructive operations.
- A distributed task queue, leader election service, notification authority, or exactly-once network delivery claim.
- Holding database locks while resolving repositories or probing Distribution.
- Separate-host ingress/load-balancer HA, production Prometheus deployment, cross-process metric aggregation selection, or tenant-level metric labels.
- Physical-byte accounting, blob deletion, destructive GC, changing project-logical quota semantics, or forking Distribution.

## Context and Evidence

- Completed plan 0004 established Alembic revision `0001_quota_ledger`, deterministic bounded candidate pages, reservation-version compare-and-set transitions, exact private Distribution digest probes, and shared PostgreSQL/MariaDB behavior.
- The current `QuotaReconciler` reads candidate pages without claiming them. Two workers may therefore probe and attempt the same candidate; version CAS prevents some incorrect mutations but does not provide work division, retry backoff, or protection when a lease is reassigned without a reservation-version change.
- The reference Gunicorn model has multiple processes. Process-local coordination cannot be the scheduling authority, so the already-required shared quota database is the simplest sufficient coordination boundary.
- Quota state must remain charged on missing authority, authentication errors, dependency failure, protocol ambiguity, and process death. A lease schedules work; it never proves manifest absence and never authorizes a refund.
- The user authorized autonomous long-horizon local implementation and verification. The 2026-07-23 publication authorization covered the completed plan 0004 milestone; production deployment, new credentials, destructive operations, and later publication remain separately gated.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Store short-lived reconciliation claims in a table separate from quota reservations | Scheduling lifecycle can expire or be abandoned without rewriting quota business state or incrementing reservation versions | Claim columns on reservations; in-process locks; external queue as the first implementation | 2026-07-23 |
| Fence every mutation with both reservation version and opaque claim token | Version CAS alone cannot reject an old worker after claim expiry and reassignment when the reservation itself did not change | Lease timestamp only; worker ID only; optimistic duplicate probes without ownership | 2026-07-23 |
| Select candidates under a short writer transaction using row locks and skip-locked semantics where supported | Independent database workers can divide a bounded batch, then release all locks before network I/O | Holding locks through Distribution probes; global advisory lock; unbounded scans | 2026-07-23 |
| Leave an indeterminate claim until lease expiry | The lease provides bounded backoff while quota remains conservatively charged; no separate retry queue is needed in this slice | Immediate hot-loop release; treating ambiguity as absence; permanent poison state | 2026-07-23 |
| Expose only a closed outcome vocabulary in metrics | Aggregate labels are operationally useful without tenant/worker/digest cardinality or identifier leakage | Per-project, per-repository, per-worker, per-digest, or per-claim labels | 2026-07-23 |

## Tasks

- [x] Add Alembic revision `0002`, SQLAlchemy claim metadata, strict schema validation, and migration tests.
- [x] Implement atomic bounded claim/release APIs and token-fenced present/absent transitions in `QuotaStore`.
- [x] Integrate claims, lease behavior, and fixed-cardinality outcome metrics into `QuotaReconciler` with focused unit tests.
- [x] Extend the disposable shared-SQL harness with independent-worker exclusion, process-abandonment, expiry/reclaim, and old-token rejection evidence.
- [x] Reconcile ADR/architecture/runbook/HANDOFF, run the full regression and safety matrix, inspect the diff, and prepare the completed work package for a separately authorized publication.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Verified clean published `main` at `b0c83b1`, recovered completed plan 0004, and bounded plan 0005 to shared-SQL claims/leases, fencing, aggregate metrics, and abandoned-worker recovery.
- Evidence: `QuotaReconciler.run_once()` currently calls the non-claiming candidate-page API; reservation-version CAS does not fence a worker whose expired claim is reassigned without a quota-state change.
- Changed files: Added this execution plan and activated it in `.codex/state/HANDOFF.md`.
- Next exact action: Define `quota_reconciliation_claims` in `src/coffer/quota.py`, add Alembic revision `migrations/versions/0002_reconciliation_claims.py`, and extend `tests/test_migrations.py` before changing reconciler behavior.

### 2026-07-23 — Multi-worker claims and failure recovery verified

- Completed: Added Alembic revision `0002`, a separate expiring claim table, bounded claim/release APIs, reservation-version plus claim-token fencing, lease-backed indeterminate retry, and fixed-cardinality reconciliation outcomes. Network probes run after the claim writer transaction closes. A spawned claimant process exits with status 17 after committing its claim; accounting stays charged until a second worker reclaims after expiry, the old token is rejected, and the new token completes the transition.
- Evidence: Thirty-six focused migration/quota/reconciliation/observability tests pass. PostgreSQL 17.10 splits three simultaneous candidates 2+1; MariaDB 11.4.12 safely returns 0+2 under its range-lock contention and a bounded post-contention retry claims the final candidate. Both engines pass migration drift/downgrade/re-upgrade, independent connection exclusion, abandoned-process recovery, stale-token fencing, final zero usage, and zero container/volume/network/credential residue. The Podman VM is stopped.
- Failure and correction: The first correlated `NOT EXISTS` candidate query widened MariaDB's locking range. Selecting through the claim outer join and locking only reservation rows preserves PostgreSQL behavior and makes the lock target explicit. MariaDB can still return an empty safe batch under concurrent range locking, so the scheduler contract permits a later bounded retry; it never assumes every non-empty backlog yields work to every simultaneous caller.
- Changed files: Migration `0002`, quota metadata/store/reconciler/metrics, focused tests, the PostgreSQL/MariaDB harness, the Distribution fixture constructor, this plan, and `HANDOFF.md`.
- Next exact action: Update ADR 0009, `docs/runbooks/quota-schema-reconciliation.md`, architecture/research/README operator boundaries, and the shared-SQL harness guide with the verified claim/fencing and MariaDB retry semantics; then run the complete regression matrix.

### 2026-07-23 — Documentation and final regression completed

- Completed: Updated ADR 0009, architecture, quota and observability research, both operator runbooks, README, and both reconciliation fixture guides with the implemented claim/fencing contract and remaining production scheduler/aggregation gates. Corrected the Distribution black box to assert stable reservation versions rather than depending on the removed spurious recompute increment.
- Evidence: Python 3.11, 3.12, and 3.13 each pass 114 tests. Lock, compile, Alembic head, Bash, ShellCheck, Gunicorn, five Compose models, every PoC Make target dry-run, 42 Markdown files, 19 local links, diff checks, and Gitleaks over all 180 project-owned tracked/untracked files pass. PostgreSQL/MariaDB and Distribution harnesses pass with zero labeled runtime, generated credential, or state residue; Podman is stopped.
- Failed verification attempts: Parallel Python matrix startup was abandoned because both `uv run` commands replace the same `.venv`; sequential runs passed. A broad whole-directory Gitleaks invocation found 98 ignored dependency/worktree artifacts, while the required project-owned file set passed with zero findings. The first Distribution rerun expected at least one stale result caused by the old spurious version increment; the corrected stable-version assertion passed on rerun.
- Changed files: Implementation, migration, tests, fixtures, ADR/architecture/research/runbook/README documents, this completed plan, and `HANDOFF.md`.
- Exact next action: Under the user's 2026-07-23 publication authorization, verify the `jaehanbyun` GitHub account, stage only the recorded plan 0005 files, create one atomic commit, and push `main` atomically; then create plan 0006 for an operator-runnable reconciliation scheduler and timing/retry contract.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Baseline recovery | `git status -sb`; `git log -5 --oneline --decorate`; source-of-truth documents | passed: clean `main` and `origin/main` at `b0c83b1` |
| Migration and model parity | focused SQLite tests plus disposable PostgreSQL/MariaDB harness | passed: revision `0002`, model drift, downgrade/re-upgrade on all three engines |
| Multi-worker fencing | focused unit/integration tests | passed: disjoint claims, process exit 17, expiry/reclaim, stale-token rejection |
| Metrics cardinality | observability tests and forbidden-label scan | passed: five fixed result classes and no worker/tenant/digest/claim identifiers |
| Complete regression | Python 3.11-3.13, static, Compose, migration, documentation, and secret/residue checks | passed: 114 tests per Python version and every recorded structural/safety check |

## Failures, Blockers, and Risks

- SQLAlchemy and the three supported engines differ in skip-locked compilation, timestamp normalization, and concurrent insert behavior. SQLite may serialize fixture writers, while PostgreSQL and MariaDB are the cross-connection evidence authorities.
- MariaDB 11.4.12 may return an empty claim batch to one concurrent caller while another range-locked caller claims part of the backlog. A subsequent bounded retry after the short transaction completes recovers the remaining work; no duplicate claim or accounting mutation was observed.
- A lease bounds duplicate work but cannot make an external probe exactly once. Correctness depends on token fencing and idempotent quota transitions, not on network delivery guarantees.
- Worker clocks can diverge. This PoC passes one explicit UTC boundary through claim selection and validates expiry transactionally; a production design may require database-server time after cross-host clock evidence.
- Process-local Prometheus counters remain insufficient for truthful fleet totals across restarts. This package fixes label cardinality and instrumentation semantics but does not select a production aggregation backend.
- `uv run --python` matrix jobs share and replace the repository `.venv`; run them sequentially or give them isolated project environments. Parallel startup is a tooling collision, not test evidence.

## Handoff

- Current state: Completed, fully verified, and published as one atomic `main` milestone under the user's 2026-07-23 authorization.
- Exact next action: Create plan 0006 for the operator-runnable reconciliation scheduler, including cadence, jitter, graceful shutdown, lease sizing, clock, and retry boundaries without production deployment.
- First file: `docs/exec-plans/0006-reconciliation-runner.md`.
- Questions requiring user input: none for safe local implementation and disposable verification; production deployment, credentials, destructive tests, and publication remain outside this package's current authorization.
