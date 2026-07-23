---
title: "Operator-runnable reconciliation process and scheduling contract"
status: completed
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0005-multi-worker-reconciliation.md
---

# Objective

Turn the plan 0005 reconciliation library into the smallest operator-runnable process without introducing a new queue, leader election service, or production deployment. Add a dedicated console entry point that composes the migrated quota store, control repository authority, exact-digest probe, and fixed outcome metrics; supports deterministic one-shot execution and a non-overlapping periodic loop; exits gracefully on process signals; and applies bounded backoff, jitter, and lease-versus-probe validation. Preserve fail-closed quota behavior and keep production credentials, Galera policy, packaging, and fleet metric aggregation outside this work package.

## Done Criteria

- [x] A checked-in `coffer-reconcile` console entry point uses the common oslo.config/logging path and a dedicated `[reconciliation]` group with bounded worker, batch, stale, lease, timeout, cadence, jitter, and retry settings.
- [x] Startup validates the exact Alembic quota revision, rejects missing upstream configuration, rejects unsafe lease/batch/timeout combinations, and allows plaintext HTTP only through an explicit fixture-only switch with loopback as the documented development boundary.
- [x] One-shot mode builds `QuotaStore`, `RepositoryStoreResolver`, `HTTPDistributionManifestProbe`, and `QuotaReconciler`; emits only a fixed aggregate summary; returns success for completed present/absent/indeterminate/stale outcomes and a stable temporary-failure exit for unexpected dependency errors.
- [x] Periodic mode never overlaps runs, uses a monotonic wait, handles SIGTERM/SIGINT through a stop event, adds bounded jitter to healthy cadence, and uses capped bounded backoff after unexpected failures without hot-looping.
- [x] Lease validation covers the configured worst-case sequential batch probe budget plus a fixed mutation grace. Runtime fencing remains the correctness authority if a probe still exceeds its lease.
- [x] Focused deterministic tests use injected clocks, waits, random values, stores, resolvers, and probes; they cover one-shot exit semantics, config rejection, healthy cadence, jitter bounds, backoff growth/reset, graceful stop, no overlapping execution, and identifier/secret-free summaries.
- [x] Operator/architecture/ADR documents, this plan, and `HANDOFF.md` record the runnable-process boundary, timing assumptions, verified evidence, and remaining production gates; the full Python 3.11–3.13 and structural/safety matrix passes.

## Non-goals

- Production deployment, systemd/Kubernetes/Helm/Kolla packaging, credentials, service-token provisioning, mTLS client keys, or a public reconciliation endpoint.
- A distributed queue, leader election, notification authority, overlapping in-process jobs, or exactly-once probe delivery.
- Galera certification/deadlock tuning, database-server-time migration, cross-host clock-failure proof, or production connection-pool sizing.
- Prometheus multiprocess/fleet aggregation, dashboards, alerts, SLOs, or admission/state/lag metric expansion.
- Existing-data import, destructive GC, blob deletion, physical-byte accounting, or changes to project-logical quota semantics.

## Context and Evidence

- Published plan 0005 provides Alembic revision `0002`, shared-SQL claims, reservation-version plus token fencing, one-hour maximum leases, conservative indeterminate behavior, and real PostgreSQL/MariaDB process-abandonment evidence.
- `QuotaReconciler` is currently a library invoked only by tests and fixtures. No installed command loads operator configuration, constructs its dependencies, owns process signals, or defines success versus temporary-failure exit behavior.
- The reconciler claims one bounded page and probes candidates sequentially. Correctness remains fenced if the lease expires, but useful work requires a configured lease at least as large as `batch_limit * probe_timeout + mutation_grace`.
- The reference WSGI API intentionally rejects Eventlet and `oslo_service.wsgi.Server`. A separate native Python process with a small synchronous loop follows the same threading-removal baseline and is independently scalable through the shared claim table.
- The user's 2026-07-23 instruction authorizes continued safe local implementation, atomic publication of completed milestones, and disposable verification. It does not authorize production deployment, credentials, destructive actions, or security-boundary expansion.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Ship a dedicated `coffer-reconcile` process with one-shot and periodic modes | Operators can choose CronJob/systemd timer or a long-running worker while both paths share one tested execution core | Embed scheduling in Gunicorn; add Celery/RabbitMQ; use deprecated Eventlet service loops | 2026-07-23 |
| Keep runs serial within each process and scale only through shared-SQL claims | Avoids overlapping local work and makes shutdown/backoff deterministic; plan 0005 already coordinates independent processes | Thread pool inside one runner; per-process leader election; global singleton | 2026-07-23 |
| Validate lease against the worst-case sequential batch timeout plus fixed grace | The current implementation claims a page before sequential probes; an undersized lease guarantees wasted stale work | Silent unsafe defaults; automatic unbounded lease extension; hold DB locks through probes | 2026-07-23 |
| Treat indeterminate probe results as completed business outcomes, but unexpected construction/DB/runtime errors as retryable process failures | Protocol ambiguity already retains quota and claim backoff; infrastructure exceptions need visible exit/backoff semantics | Exit on every 401/5xx/timeout; swallow unexpected exceptions; optimistic refund | 2026-07-23 |
| Use a stop event, monotonic waiting, capped exponential backoff, and bounded symmetric jitter | Supports prompt graceful shutdown and avoids synchronized fleets or hot loops without an async framework | `time.sleep()` without interruption; unbounded exponential delay; randomized lease expiry | 2026-07-23 |
| Do not add static service-auth secrets to oslo.config in this package | Credential delivery changes the security boundary and needs separate owner-approved design; private TLS/network identity can be configured without repository secrets | Bearer token in config; credentials in URL; command-line secret flags | 2026-07-23 |

## Tasks

- [x] Add reconciliation oslo.config options, console entry point, dependency construction, and startup validation.
- [x] Implement one-shot result/exit behavior plus deterministic periodic cadence, jitter, backoff, and signal handling.
- [x] Add focused runner/config tests and an isolated subprocess/fixture proof without real credentials.
- [x] Update architecture/ADR/runbook/README/HANDOFF, run the complete regression/safety matrix, inspect the diff, and publish the completed milestone atomically.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Verified plan 0005 commit `d4a230c` is published on clean `main`, recovered the configuration/process baselines, and bounded plan 0006 to one runnable reconciliation process plus timing/retry semantics.
- Evidence: The current package has no console entry point; `QuotaReconciler` is constructed only by focused and disposable fixtures. Its page-wide lease must account for sequential probe timeout across the configured batch.
- Changed files: Added this plan and activated it in `.codex/state/HANDOFF.md`.
- Next exact action: Add bounded `[reconciliation]` options in `src/coffer/config.py`, register `coffer-reconcile` in `pyproject.toml`, and create the dependency-free scheduling core in `src/coffer/reconciliation_runner.py` with validation tests.

### 2026-07-23 — Runnable process and scheduling core verified

- Completed: Added the installed `coffer-reconcile` entry point, bounded reconciliation configuration, strict origin and migrated-schema startup validation, fixed 0/75/78 exit semantics, page-wide lease budget checks, bounded cursor-preserving cycles, serial periodic execution, monotonic interruptible waits, symmetric jitter, capped exponential failure backoff, and SIGTERM/SIGINT restoration.
- Evidence: Fourteen runner tests and 67 combined runner/token/reconciliation tests pass. The installed subprocess loads an actual migrated SQLite database and control repository, probes an exact loopback manifest path returning 404, releases the pending reservation, and emits only aggregate counts without the project ID, digest, or database path. Missing quota schema fails before `RepositoryStore` can create its table. Cursor tests prove a cycle continues from its bound instead of restarting behind permanently indeterminate rows.
- Failure and correction: Reusing global oslo.config group and option objects let an override on one `ConfigOpts` instance affect a later instance. `new_config()` now registers independent copies, and a regression proves the default lease is restored without help from the test fixture. The runner review also found that a single-page stateless loop could starve later candidates, so cycles drain bounded pages and persist a remaining cursor and scan snapshot across periodic runs. The stop event is checked after the active page so a signal cannot begin another page.
- Changed files: `pyproject.toml`, `src/coffer/config.py`, new `src/coffer/reconciliation_runner.py`, new focused runner tests, this plan, and `HANDOFF.md`; the existing lock remained current.
- Next exact action: Run the complete Python 3.11–3.13 and structural/safety matrix, inspect the final diff, and publish the completed plan atomically.

### 2026-07-23 — Work package completed

- Completed: Documented the operator process boundary, closed config parsing and cross-instance isolation gaps found by final review, and completed the repository-wide regression and safety matrix.
- Evidence: Python 3.11, 3.12, and 3.13 each pass 128 tests. Lock, compile, Alembic head, installed entry point/help, Gunicorn, 57 Bash/ShellCheck files, five Compose models, every PoC Make target dry-run, 43 Markdown files, 21 local links, diff checks, private-key/JWT shape checks, and Gitleaks over 184 project-owned files pass. A missing config file now emits only the neutral invalid-configuration result and exits 78 without a traceback or path disclosure.
- Failed verification attempts and corrections: The first Gunicorn check named nonexistent `coffer.app` instead of the documented `coffer.wsgi` factory. Initial zsh list expansion joined Bash/Make targets into one argument, and a Gitleaks loop temporarily reused zsh's special `path` variable. Corrected commands passed and changed no repository or lab state. More importantly, the missing-config subprocess initially exposed an oslo.config traceback with exit 1; `main()` now normalizes parser and logging configuration failures to the documented secret-free exit 78, with an installed-console regression.
- Changed files: Runner/config/quota code and tests; console metadata and sample config; README, architecture, ADR 0009, quota and observability research, quota and real-lab runbooks, this plan, and `HANDOFF.md`.
- Next exact action: Publish this completed work package atomically, then scope the existing-data and unified control-schema migration gate as the next safe execution plan.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Baseline recovery | clean `main`/`origin/main` at `d4a230c`; plan 0005 and handoff | passed |
| Runner/config contract | focused unit and subprocess tests | passed: 14 tests, 67 combined focused tests, config-isolation and parser-exit regressions, and installed exact-404 subprocess proof |
| Timing/failure behavior | injected wait/random/clock tests | passed: serial cycles, cursor continuation, jitter, capped resettable backoff, interruptible signals |
| Complete regression | Python 3.11-3.13, compile, lock, entry point, Bash/ShellCheck, Compose, docs, diff, secret scan | passed: 128 tests per Python version and all structural/safety checks |

## Failures, Blockers, and Risks

- Application wall-clock timestamps still determine claim expiry. Token fencing preserves correctness under drift, but production cross-host clock and database-server-time policy remain unproven.
- Page-wide leases trade recovery time against the maximum sequential batch duration. This package validates configuration rather than implementing lease renewal; a later design may choose claim-one/probe-one or safe renewal after load evidence.
- Repository metadata still uses its earlier runtime `create_all()` boundary while quota tables require Alembic. Existing-data and unified control-schema migration remain a separate production gate.
- Process-local metrics can verify result vocabulary but cannot represent a multi-process or multi-replica fleet across restarts.

## Handoff

- Current state: Completed and verified; ready for atomic publication.
- Exact next action: Publish this completed work package, then create the next plan for existing-data and unified control-schema migration discovery.
- First command: `gh auth status` followed by explicit staging and `git diff --cached --check`.
- Questions requiring user input: none for safe local implementation; credentials, production deployment, security-boundary changes, and destructive testing remain outside authorization.
