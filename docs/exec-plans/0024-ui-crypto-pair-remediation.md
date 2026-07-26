---
title: "UI coupled crypto package remediation"
status: completed
updated: 2026-07-27
owner: primary-agent
---

# Objective

Prove the smallest dependency-valid remediation for the inherited
cryptography and pyOpenSSL High findings in the accepted native ARM64 Horizon
and Skyline Console images. Extend the plan 0023 single-package harness only
enough to represent one exact multi-package target, bind the official
cryptography 49.0.0 and pyOpenSSL 26.3.0 wheels and dependency metadata, and
require exact runtime and two-scanner deltas without changing a production
Containerfile or weakening the absolute production gate.

## Done Criteria

- [x] The checked-in target contract represents one or more exact package
      components while preserving strict wheel, architecture, finding,
      surface, dependency, and path validation for all existing targets.
- [x] Runner, build, runtime collector, evidence manifest, and classifier bind
      every component and refuse missing, extra, duplicate, wrong-platform, or
      wrong-hash wheels and package deltas.
- [x] Both native ARM64 surfaces change exactly cryptography 43.0.3 to 49.0.0
      and pyOpenSSL 24.2.1 to 26.3.0, pass `pip check`, native cryptographic
      operations, OpenSSL TLS-context compatibility, UI runtime, lineage, and
      build-input cleanup.
- [x] Trivy and Docker Scout remove exactly `CVE-2026-26007`,
      `GHSA-537c-gmf6-5ccf`, and `CVE-2026-27459`, introduce no
      Critical/High finding, report zero secrets, and retain the absolute
      nonzero gate as blocked.
- [x] Focused and full regression, static, documentation, secret, residue, and
      diff gates pass; the verified milestone is committed and pushed.

## Non-goals

- Combining any of plan 0023's other independently accepted upgrades.
- Editing production Horizon/Skyline Containerfiles or OpenStack global
  constraints before the complete cumulative matrix exists.
- Handling Docker credentials, replacing a scanner, suppressing a finding,
  publishing/signing images, creating a live cloud, or bypassing plans 0019
  and 0022.
- Claiming AMD64, Kolla startup, browser, upgrade, rollback, or production
  compatibility from the ARM64 local derivative.

## Context and Evidence

- The accepted Horizon and Skyline runtimes each contain cryptography 43.0.3,
  pyOpenSSL 24.2.1, and cffi 2.0.0.
- Both scanners report `CVE-2026-26007` and
  `GHSA-537c-gmf6-5ccf` against cryptography plus
  `CVE-2026-27459` against pyOpenSSL.
- Installed pyOpenSSL 24.2.1 declares
  `cryptography>=41.0.5,<44`, so cryptography cannot be upgraded alone while
  retaining a clean dependency graph.
- Official pyOpenSSL 26.3.0 declares `cryptography>=49,<50`; official
  cryptography 49.0.0 is the current compatible release and exceeds the
  scanner fix floors 46.0.5 and 48.0.1. pyOpenSSL 26.3.0 exceeds its 26.0.0
  fix floor.
- The selected official ARM64 cryptography wheel SHA-256 is
  `36d1709f992593689b45bda411498d62c6e365f2ca00b84657d4dadd24de16db`.
  The selected official pure pyOpenSSL wheel SHA-256 is
  `46367f8f66b92271e6d218da9c87607e1ef5a0bc5c8dea5bb3db82f395c385a3`.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Test cryptography and pyOpenSSL as one exact pair | Neither package has a dependency-valid independent upgrade path from the accepted baseline | Broken intermediate `pip check`; ignoring declared bounds; waiving one finding | 2026-07-27 |
| Select cryptography 49.0.0 and pyOpenSSL 26.3.0 | This is the current official dependency-compatible pair and both releases exceed every accepted scanner fix floor | cryptography 46.0.5 plus pyOpenSSL 26.0.0, which leaves the GHSA; cryptography 48.0.1 with an incompatible pyOpenSSL bound; mutable unpinned latest | 2026-07-27 |
| Generalize the evidence contract instead of creating a combined wheel | Each installed distribution, source wheel, file boundary, version delta, and vulnerability identity must remain independently auditable | Vendoring both packages into one artifact; duplicating the full runner; allowing free-form extra wheels | 2026-07-27 |

## Tasks

- [x] Add a strict package-component model with positive and rejection
      fixtures while preserving every plan 0023 target.
- [x] Carry exact component wheels through the offline build, runtime
      collector, manifest, and classifier.
- [x] Add native cryptography and pyOpenSSL compatibility probes.
- [x] Run and independently inspect the two-surface native ARM64 transaction.
- [x] Complete repository gates, update this plan and handoff, commit, and
      push.

## Progress Log

### 2026-07-27 — Coupled native ARM64 trial accepted

- Completed: Reran the complete transaction from a clean work boundary. Both
  UI surfaces changed exactly cryptography 43.0.3 to 49.0.0 and pyOpenSSL
  24.2.1 to 26.3.0. `pip check`, native `_rust`, AES-GCM, TLS context,
  Coffer UI runtimes, exact wheel files, lineage, OS invariance, and build
  input cleanup passed.
- Scanner evidence: Trivy and Scout each removed exactly
  `CVE-2026-26007`, `CVE-2026-27459`, and
  `GHSA-537c-gmf6-5ccf` on both surfaces with zero introduced Critical/High
  and zero Trivy secrets. Horizon High changed 31 to 28 in Trivy and 34 to
  31 in Scout; Skyline changed 16 to 13 and 19 to 16.
- Decision: The isolated coupled derivative is accepted with
  `production_candidate=false`. It changes no production Containerfile or
  constraints policy and applies no waiver. The owner-only result SHA-256 is
  `1195c893ca4d634652a5d0b77517d3e8b45536883d577e1585d4129cfda4dfbe`.
- Cleanup and gates: Generated images, contexts, wheels, archives, and scanner
  caches are absent; the pre-existing Podman machine is stopped. JSON, Bash,
  strict ShellCheck, Ruff, compilation, 86 focused UI image tests, and all
  1,541 repository tests pass.
- Next exact action: Create plan 0025 for a cumulative ARM64 remediation
  matrix that combines only the independently accepted targets and proves
  dependency, runtime, and exact scanner deltas before any production
  Containerfile change.

### 2026-07-27 — First native trial stopped at the TLS probe

- Completed: Implemented the v4 exact component target/evidence contract,
  v3 multi-component runtime contract, repeatable wheel input, offline
  multi-wheel build, exact two-package delta classifier, AES-GCM and
  pyOpenSSL TLS-context probes, Make target, documentation, and rejection
  fixtures. Forty-five focused tests pass.
- Failure: The first native ARM64 transaction installed cryptography 49.0.0
  and pyOpenSSL 26.3.0 and passed `pip check`, then stopped because
  pyOpenSSL's `Context` supports `set_min_proto_version()` but not the assumed
  `get_min_proto_version()` method. No scanner evidence was accepted.
- Cleanup: All bounded images, contexts, wheels, caches, archives, and empty
  work directories are absent; the pre-existing Podman machine is stopped.
  The probe now uses supported minimum-version, cipher-list, and option
  setters without claiming a nonexistent getter.
- Next exact action: Rerun
  `make -C poc/ui-images trial-python-cryptography-pyopenssl` from a clean
  bounded work directory.

### 2026-07-27 — Work package activated

- Completed: Inspected official current PyPI metadata and the accepted
  Horizon/Skyline runtime and scanner evidence. Confirmed that a
  dependency-valid remediation must change both packages atomically.
- Evidence: cryptography 49.0.0 requires cffi 2.0.0 on the accepted Python
  runtime; pyOpenSSL 26.3.0 requires cryptography 49.x. Both official wheels
  are non-yanked and their exact filenames, URLs, and SHA-256 values are
  recorded above.
- Changed files: This execution plan, completed plan 0023, and durable handoff.
- Next exact action: Introduce an immutable package-component model in
  `poc/ui-images/python_target.py`, migrate existing single-package targets in
  memory without changing their checked-in semantics, and add rejection
  fixtures before touching the runner.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Official metadata and wheel identity | PyPI JSON plus SHA-256 fields | passed read-only |
| Existing and coupled target regression | UI image focused pytest | passed; 86 tests |
| Coupled runtime and scanner transaction | native ARM64 harness | passed; accepted blocked result |
| Runtime and scanner delta | exact inventories and two scanners | passed; three High IDs removed on both surfaces |
| Final repository gates | JSON, Bash, ShellCheck, Ruff, compilation, focused/full pytest, secret, residue, diff | passed; 1,541 tests |

## Failures, Blockers, and Risks

- A single-package cryptography overlay necessarily violates pyOpenSSL
  24.2.1's `<44` bound; a single-package pyOpenSSL overlay necessarily
  violates pyOpenSSL 26.3.0's `>=49` lower bound. Both are refused before an
  image trial.
- Multi-package support expands the evidence schema. Existing single-package
  targets must retain exact behavior and rejection coverage; a schema bump
  cannot silently reinterpret accepted evidence.
- The first live trial exposed and removed one unsupported pyOpenSSL getter
  assumption. That stopped before evidence collection and is not accepted
  trial evidence.
- Production remains independently blocked by Distribution/Ceph release gates,
  canonical AMD64 Scout evidence, nonzero findings outside this pair,
  cumulative compatibility, signed publication, and live Kolla/UI acceptance.

## Handoff

- Current state: Plan 0024 is complete; no production file or image changed.
- Exact next action: Create plan 0025 for the cumulative accepted remediation
  matrix.
- First file or command: Create
  `docs/exec-plans/0025-ui-cumulative-remediation-matrix.md` from the
  execution-plan template.
- Questions requiring user input: None. No credential, external publication,
  live deployment, waiver, or security-boundary change is required.
