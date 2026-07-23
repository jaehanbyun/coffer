---
title: "Read-only post-import ledger comparison baseline"
status: complete
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0009-transactional-inventory-import.md
---

# Objective

Define and prove a read-only comparison between one independently verified
`coffer.inventory/v1` artifact and the complete Coffer quota-ledger state created
by plan 0009. The comparison must detect any missing, extra, released, pending,
reassigned, or counter-drifted import state from one database snapshot and emit
only fixed aggregate evidence. It must not contact Distribution/RGW, accept
service credentials, mutate SQL, prove external writer exclusion, enable
admission, or declare a production cutover safe.

## Done Criteria

- [x] The comparator reuses the strict canonical artifact/hash parser and requires
  the exact immutable baseline marker and current control-schema authority.
- [x] Expected reservations, graphs, manifests, project-unique descriptors,
  reference counts, quota counters, zero claims, and import timestamps match the
  complete ledger with no missing or extra rows.
- [x] One read-only repeatable database snapshot produces a secret-safe aggregate
  result; any mismatch returns a fixed refusal class without tenant, repository,
  digest, URL, credential, or SQL detail.
- [x] An installed CLI receives the database URL only from
  `COFFER_DATABASE_URL`; focused mutation/extra-row/read-only/concurrency tests and
  disposable PostgreSQL/MariaDB verification pass.
- [x] README, architecture, proposed ADR 0012, operator runbooks, this plan, and
  `HANDOFF.md` state that database equality is evidence only: authenticated live
  digest comparison, writer exclusion, backup/restore, authorization, and
  admission cutover remain separate gates.

## Non-goals

- Connecting to production SQL, Distribution, RGW, Keystone, or Barbican; handling
  any credential, private CA, service token, or signed inventory.
- Enabling or changing manifest admission, ingress, reconciliation, GC, deletion,
  quota limits, repository authority, import markers, or ledger rows.
- Proving external writer exclusion, backup restorability, live manifest
  availability, physical object completeness, or production readiness.
- Designing the authenticated Distribution probe, cutover orchestration, rollback
  automation, Galera policy, or representative-scale transaction strategy.

## Context and Evidence

- Completed plan 0009 imports one canonical artifact into an empty ledger and
  records deterministic reservation IDs, a shared import request ID, committed
  graph/manifests, project descriptor reference counts, quota usage, and one
  immutable marker in a single transaction.
- Exact replay currently validates the marker and quota presence but deliberately
  does not prove the imported ledger still equals the artifact. Reconciliation or
  accidental mutation after import can therefore make the marker insufficient as
  cutover evidence.
- Control metadata may contain additional empty repositories and zero-usage quota
  configurations. Those are not imported ledger rows and must not be confused with
  extra content.
- A database snapshot can prove only SQL equality at one instant. The operator
  must separately establish that all registry/admission/reconciliation writers are
  excluded for the entire inventory/import/compare interval.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Compare the entire ledger, not only marker counts or quota totals | Aggregate equality cannot detect graph substitution, released manifests, reference-count drift, or extra rows | Trust marker; compare only counts; sample rows | 2026-07-23 |
| Permit unrelated control repositories and zero-usage quota configurations but no unrelated ledger state | Empty repositories and preconfigured limits are legitimate authority; content accounting must remain exact | Require an otherwise empty control database; ignore extra ledger rows | 2026-07-23 |
| Use a read-only repeatable snapshot and return fixed aggregate evidence | A comparator must not create a new mutation or leak immutable tenant/content identifiers | Repair drift; lock ledger rows; print mismatch rows | 2026-07-23 |
| Call the result `verified`, never `ready` or `cutover-approved` | SQL equality cannot prove external writer exclusion, live content availability, authentication, or operator authorization | Emit a cutover token; enable admission automatically | 2026-07-23 |

## Tasks

- [x] Build expected ledger facts from `InventoryArtifact` without duplicating import semantics silently.
- [x] Implement the read-only comparator and installed secret-safe CLI with focused SQLite tests.
- [x] Extend the disposable PostgreSQL/MariaDB harness with exact and drifted comparisons.
- [x] Update ADR/operator documentation, run the complete matrix, inspect the diff, and prepare atomic publication.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Published plan 0009 at `5e9b02e`, mapped the marker-only replay gap,
  bounded this package to read-only SQL equality, and explicitly excluded live
  registry access and admission changes.
- Evidence: The import writes deterministic row identities and complete graph
  facts, while `_marker_result()` currently checks only marker aggregates and
  project quota presence/over-limit counts.
- Changed files: Added this plan and activated it in README and `HANDOFF.md`.
- Next exact action: Add a failing focused test in
  `tests/test_quota_import_verification.py` for exact imported state and one
  post-import manifest-state mutation, then implement expected ledger facts in a
  separate verification module.

### 2026-07-23 — SQLite comparison seam complete

- Completed: Extracted deterministic ledger facts shared by import and
  verification, added a one-snapshot read-only exact comparator, and installed
  `coffer-verify-inventory-import`. The comparator accepts the database URL only
  through `COFFER_DATABASE_URL`, emits aggregate JSON, and uses one fixed mismatch
  class without row identifiers or connection details.
- Evidence: 38 focused import/comparison tests pass. They cover exact state,
  marker false positives, every ledger class including timestamp drift, extra
  claims/rows, allowed empty authority, absence of DML, one snapshot across a
  concurrent commit, CLI output, and environment-only database configuration.
- Failures corrected: The first test collection used the nonexistent
  `tests.test_quota_import` package path; the repository's flat test-module path
  fixed it. One CLI assertion initially included prior Alembic setup output;
  clearing captured setup output isolated the installed-command contract. The
  first concurrent SQLite mutation exposed Python sqlite3's deferred `BEGIN`,
  which allowed later SELECTs to observe the new commit; an explicit read-only
  `BEGIN` now fixes the snapshot before the first comparison query.
- Changed files: `src/coffer/quota_import.py`,
  `src/coffer/quota_import_verification.py`, `pyproject.toml`, and
  `tests/test_quota_import_verification.py`.
- Next exact action: Extend `poc/quota-sql/verify_shared_sql.py` with exact,
  drifted, and restored-ledger comparisons on both pinned engines.

### 2026-07-23 — Shared-SQL comparison complete

- Completed: Ran the exact comparator, mutated one imported manifest, proved the
  fixed refusal, restored it, and proved exact comparison again on PostgreSQL
  17.10 and MariaDB 11.4.12.
- Evidence: `make -C poc/quota-sql verify` passed both engines, including the
  existing transactional-import, concurrency, reconciliation, and adoption
  checks. Cleanup reported zero containers, volumes, networks, credentials, and
  labeled quota-SQL residue. The disposable Podman machine is stopped.
- Failure corrected: Podman/libkrun was not corrupt. The app's noninteractive
  command lifecycle terminated the VM child after startup; keeping the start and
  harness in one persistent PTY preserved the VM. No recreation or data reset was
  required.
- Changed files: `poc/quota-sql/verify_shared_sql.py` and this plan.
- Next exact action: Update proposed ADR 0012, `README.md`, architecture, both
  inventory/quota operator runbooks, and `poc/quota-sql/README.md` with the exact
  comparison boundary before running the complete verification matrix.

### 2026-07-23 — Work package complete and ready for atomic publication

- Completed: Updated proposed ADR 0012, README, architecture, both operator
  runbooks, and the shared-SQL guide. They distinguish exact SQL equality from
  writer exclusion, authenticated live Distribution availability, backup/
  rollback readiness, authorization, and admission cutover.
- Evidence: Python 3.11.14, 3.12.2, and 3.13.14 each pass 189 tests; only the
  known WebOb `cgi` deprecation warning appears on 3.11/3.12. Lock, compilation,
  Alembic head `0004`, four installed CLI helps, Go format/test/vet, 58 Bash/
  ShellCheck files, six Compose models, 54 Make dry-runs, 54 Markdown files, 33
  local links, 99 external links, private-key/JWT scans, and diff checks pass.
  The final PostgreSQL/MariaDB rerun passed after the SQLite snapshot fix and
  ended with zero container, volume, network, credential, and labeled residue;
  Podman is stopped.
- Failures corrected: A new concurrent-commit test proved SQLAlchemy/sqlite3 had
  deferred the physical `BEGIN`, allowing a mixed comparison; the comparator now
  explicitly begins the read-only SQLite snapshot. The first static commands
  assumed Bash 4 `mapfile`, parsed Make dependencies as target text, and required
  an H1 in the special compact prompt; portable loops, four-field parsing, and a
  prompt-specific structural exception corrected those verification commands.
- Changed files: Shared import facts, the new comparator/CLI, focused and
  shared-SQL tests, package entry point, ADR/architecture/operator documentation,
  README, this plan, and `HANDOFF.md`.
- Next exact action: Stage only the plan 0010 file set, run staged Gitleaks and
  cached-diff checks, commit once as `feat: verify imported quota ledger`, verify
  the GitHub account, and atomically push from remote head `5e9b02e`.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Published plan 0009 recovery | clean local/remote `main` at `5e9b02e`; schema/import call graph | passed |
| Focused comparator behavior | SQLite exact, mutation, extra-row, read-only, concurrent snapshot, CLI tests | passed (38) |
| Shared SQL | pinned PostgreSQL 17.10 and MariaDB 11.4.12 exact/drifted/restored comparison | passed; zero residue |
| Complete regression | Python 3.11–3.13, Go, Bash/ShellCheck, Compose, docs, diff, secret scans | passed: 189 tests per Python version and all structural/safety checks |

## Failures, Blockers, and Risks

- Comparing the marker alone is insufficient because later ledger changes do not
  update or remove the immutable baseline marker.
- A repeatable SQL snapshot cannot prove that a writer was stopped before it began
  or stayed stopped after it ended. Documentation and output must not overstate
  this bounded evidence.
- Podman 5.6.0/libkrun must remain attached to a persistent PTY in this app while
  the disposable harness runs. Noninteractive command completion terminates its
  child VM; this is a command-lifecycle constraint, not evidence of VM corruption.

## Handoff

- Current state: Plan 0010 implementation, documentation, disposable live
  evidence, and complete regression are finished and ready for atomic publication.
- Exact next action: Stage the exact file set and run staged secret/diff checks
  before the single publication commit.
- First command: `git add` with the explicit plan 0010 file list.
- Questions requiring user input: none for local/disposable read-only work;
  production data, credentials, maintenance, comparison, and admission cutover
  remain outside authorization.
