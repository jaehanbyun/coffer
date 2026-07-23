---
title: "Synthetic inventory scale characterization"
status: complete
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0011-authenticated-live-inventory-comparison.md
---

# Objective

Build a deterministic, disposable measurement harness that characterizes the
current inventory parse, empty-ledger import, exact SQL comparison, and serial
authenticated live-comparison core at increasing synthetic sizes. Preserve the
existing security and consistency contracts while identifying concrete time,
memory, SQL-statement, and probe-count scaling behavior. This package produces
engineering evidence, not a production capacity claim or an accepted target.

## Done Criteria

- [x] A deterministic generator creates valid `coffer.inventory/v1` artifacts,
  matching repository/quota authority, and unique manifest/descriptor graphs for
  bounded named profiles without using production content or identifiers.
- [x] The harness measures artifact build/parse, migration/authority preparation,
  transactional import, exact SQL snapshot comparison, and injected always-
  present live comparison separately with monotonic duration, peak traced memory,
  SQL statement counts, and exact probe counts.
- [x] Automated tests prove deterministic facts and aggregate-only output at a
  small scale; measurements themselves use no brittle wall-clock assertions.
- [x] At least three increasing profiles complete in disposable SQLite state,
  leave no database or credential residue, and record sufficient evidence to
  locate nonlinear behavior or hard bounds.
- [x] Documentation distinguishes local synthetic characterization from
  production RGW/Distribution/Keystone, shared-SQL, network, concurrency,
  credential fan-out, all-replica, writer-exclusion, and capacity qualification.

## Non-goals

- Selecting a production project/repository/manifest target, SLO, timeout,
  concurrency, retry, rate-limit, batching, or database tuning policy.
- Creating a Keystone identity, application credential, registry token, TLS
  endpoint, maintenance role, proxy, or secret-delivery format.
- Contacting production or retained lab services, measuring real tenant data,
  enabling admission, mutating a non-disposable ledger, or running GC.
- Optimizing the importer/comparators before a measured bottleneck and explicit
  correctness-preserving design are recorded.
- Treating CPython traced allocations as process RSS or local SQLite timings as
  PostgreSQL, MariaDB, Galera, RGW, Distribution, or network capacity.

## Context and Evidence

- Plan 0011 proves exact same-snapshot route resolution and an injected,
  authenticated, serial digest-probe contract. It deliberately leaves provider
  selection and production identity outside the implementation.
- The inventory loader currently accepts at most 64 MiB and structural counts up
  to ten million, but those parser bounds are validation ceilings rather than
  qualified operating capacity.
- The importer writes reservation and manifest rows per manifest, batches edge
  and project-descriptor rows, and updates quota once per project. The exact SQL
  comparator reads complete ledger classes into Python sets. The live comparator
  probes each manifest serially.
- No accepted product workload distribution exists. Named profiles in this plan
  are therefore synthetic comparison points only and must not be described as
  representative customer scale.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Measure the unmodified serial algorithms before optimizing | Establishes evidence and prevents speculative concurrency/batching changes | Add parallel HTTP or bulk SQL before measuring; infer capacity from complexity alone | 2026-07-23 |
| Use deterministic unique image-manifest graphs with two referenced descriptors per manifest | Exercises all imported ledger classes with predictable linear facts and no external content | Reuse one tiny artifact; random unrepeatable graphs; nested-index complexity in the first scale pass | 2026-07-23 |
| Keep timings observational and assert only structural/count invariants | Local timing thresholds are host-load-sensitive and cannot be a portable correctness gate | Fail CI on a narrow wall-clock or RSS threshold | 2026-07-23 |
| Use disposable SQLite plus an injected in-process authenticated probe | Isolates current algorithmic/statement/probe scaling without credentials or network variance | Production/lab access; anonymous HTTP; claim shared-SQL or network capacity from the result | 2026-07-23 |

## Tasks

- [x] Add the deterministic profile generator and phase measurement harness with
  fixed aggregate JSON output.
- [x] Add focused structural/count tests and a repeatable Make entry point.
- [x] Run increasing profiles, record evidence and bottlenecks, update operator
  boundaries, and complete the full regression/publication matrix.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Published plan 0011 at `b45fa32`, selected the next safe unresolved
  gate, and bounded it to local synthetic characterization with no production
  identity, credential, endpoint, or policy decision.
- Evidence: Current code has explicit 64-MiB/record validation ceilings, a
  per-manifest import loop, full-ledger set comparison, and serial live probes;
  none of those facts supplies a qualified operating target by itself.
- Changed files: Added this plan and activated it in README and `HANDOFF.md`.
- Next exact action: Add focused tests for a deterministic scale-profile generator
  beginning in `tests/test_inventory_scale.py`.

### 2026-07-23 — Deterministic harness and scale observations complete

- Completed: Added a non-installed PoC measurement module, fixed 100/1,000/5,000
  manifest profiles, a repeatable Make target, and focused tests for deterministic
  valid inventory facts, exact statement/probe counts, aggregate-only output, and
  temporary-state cleanup.
- Evidence: Two focused tests pass. All three profiles completed. At 100/1,000/
  5,000 manifests, artifacts were 95,480/944,053/4,711,096 bytes; import took
  0.082/0.728/3.642 seconds and 316/3,022/15,032 statements; exact comparison
  took 0.046/0.417/2.085 seconds with a constant 11 statements and peak traced
  allocation 0.65/4.89/24.87 MB; live-core comparison took 0.040/0.387/1.968
  seconds with exactly one in-process probe per manifest. No temporary database
  directory remains.
- Interpretation: Growth was approximately linear in this bounded unique-
  descriptor SQLite topology. Import statement count is `3 * manifests + 2 *
  projects + 12`; exact comparison keeps constant query count but materializes
  linearly larger Python sets. Serial private-TLS/auth/network cost is not
  represented and can dominate the live path.
- Failure corrected: `uv run pytest` does not place the repository root on the
  console script's import path. The focused test now loads the exact PoC module
  path directly instead of altering product packaging or global pytest settings.
- Changed files: `poc/inventory_scale/`, `tests/test_inventory_scale.py`, and this
  plan.
- Next exact action: Update both inventory/quota operator boundaries with the
  synthetic evidence and remaining production-scale gates, then run the complete
  regression matrix.

### 2026-07-23 — Work package complete and ready for atomic publication

- Completed: Updated README, architecture, inventory/quota operator boundaries,
  and the PoC guide with the measured behavior and explicit non-production
  interpretation. Completed the full language, packaging, documentation, diff,
  and secret-safety matrix.
- Evidence: Python 3.11.14, 3.12.2, and 3.13.14 each pass 201 tests; 3.11/3.12
  emit only WebOb's known `cgi` deprecation warning. Lock, compilation, Alembic
  head `0004`, four installed CLI helps, Go format/test/vet, 58 Bash/ShellCheck
  files, six Compose models, 55 Make dry-runs, 58 Markdown files, 33 local links,
  99 external links, 222-file project-owned Gitleaks, private-key/JWT scans, and
  diff checks pass. The actual three-profile Make target passed before the full
  matrix and left no temporary database directory.
- Boundary: This closes only deterministic local algorithm characterization.
  It neither selects an accepted workload/capacity target nor qualifies shared
  SQL, private TLS, an authenticated provider, network behavior, concurrency,
  writer exclusion, backup/rollback, or admission cutover.
- Next exact action: Stage only the plan 0012 file set, run cached-diff and staged
  Gitleaks checks, commit once as `test: characterize inventory scale`, verify the
  GitHub account, and atomically push from remote head `b45fa32`.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Published plan 0011 recovery | clean local/remote `main` at `b45fa32`; plan and handoff complete | passed |
| Deterministic generator and measurements | focused tests | passed (2) |
| Increasing local profiles | `make -C poc/inventory_scale verify` | passed: 100/1,000/5,000 manifests; no residue |
| Complete regression | Python 3.11–3.13, Go, Bash/ShellCheck, Compose, docs, diff, secret scans | passed: 201 tests per Python version and all structural/safety checks |

## Failures, Blockers, and Risks

- Synthetic manifest topology can bias descriptor sharing and statement/memory
  behavior. The first profile intentionally uses a simple unique graph and must
  state that limitation with every result.
- `tracemalloc` observes Python allocations only; native driver, SQLite, and OS
  cache memory are excluded.
- Local sequential probe duration excludes TLS, authentication exchange, registry
  latency, throttling, load balancing, and partial failure.

## Handoff

- Current state: Harness, focused tests, all three scale profiles, operator
  boundaries, interpretation, and full regression are complete and ready for
  atomic publication.
- Exact next action: Stage the exact plan 0012 file set and run staged secret and
  cached-diff checks before the single commit.
- First file or command: `git status --short`.
- Questions requiring user input: none for disposable synthetic measurement;
  production targets, providers, credentials, endpoints, optimization policy,
  and capacity acceptance require a separate decision or authorization.
