---
title: "UI cumulative Python remediation matrix"
status: active
updated: 2026-07-27
owner: primary-agent
---

# Objective

Prove that every native ARM64 Python package remediation accepted by plans
0023 and 0024 remains dependency-valid, runtime-compatible, and
scanner-effective when combined in one Horizon derivative and one Skyline
Console derivative. Introduce a strict surface-aware matrix contract that
references the existing immutable targets, installs only their exact official
wheels without a network, runs every accepted compatibility probe, and
classifies the aggregate package and finding deltas without changing a
production Containerfile or weakening the absolute production gate.

## Done Criteria

- [ ] A checked-in matrix contract selects exactly the accepted target keys
      for each surface and refuses unknown, duplicate, unsorted,
      surface-incompatible, component-overlapping, or mutable input.
- [ ] The cumulative offline build and evidence contracts bind all 12 Horizon
      and 10 Skyline package components, their exact wheels, individual
      compatibility probes, surface membership, dependency metadata, and
      source hashes.
- [ ] Both cumulative derivatives preserve the accepted OS cleanup inventory,
      change only the declared Python distributions, pass `pip check`, every
      accepted probe, Coffer UI runtime, lineage, and build-input cleanup.
- [ ] Trivy and Docker Scout remove exactly the declared aggregate findings
      for each surface, introduce no Critical/High finding, find no secret,
      and leave the absolute production gate blocked if any inherited
      Critical/High finding remains.
- [ ] Focused and full regression, static, documentation, secret, residue, and
      diff gates pass; verified milestones are committed and pushed.

## Non-goals

- Editing production Horizon/Skyline Containerfiles, OpenStack global
  constraints, Kolla configuration, or image tags before cumulative evidence
  is accepted.
- Handling Docker credentials, replacing a scanner, suppressing findings,
  publishing or signing images, creating a live cloud, or bypassing plans 0019
  and 0022.
- Claiming AMD64, Kolla startup, browser, upgrade, rollback, or production
  compatibility from the local ARM64 derivatives.
- Adding a package or release that has not already passed an isolated native
  ARM64 trial.

## Context and Evidence

- Plan 0023 accepted isolated ARM64 trials for Click, Django, httplib2, lxml,
  Mako, msgpack, Pillow, PyJWT, ujson, and urllib3. Plan 0024 accepted
  cryptography and pyOpenSSL only as one dependency-coupled pair.
- Horizon contains all 11 accepted targets and 12 package components. Skyline
  contains nine targets and ten components because Django and Pillow are
  Horizon-only.
- The aggregate declared scanner sets contain 30 Trivy and 31 Scout finding
  identities for Horizon, and 15 Trivy and 16 Scout identities for Skyline.
  Click's `CVE-2026-7246` is Scout-only; scanner-specific identity must remain
  explicit.
- Existing target schema v4 already binds exact wheels, releases, finding
  identities, dependency metadata, probes, and surfaces. A matrix should
  reference these targets rather than duplicate their package metadata.
- All accepted isolated results remain `production_candidate=false`. Their
  combination is a compatibility experiment, not permission to override
  upstream constraints.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Add a separate immutable matrix manifest that references accepted target keys per surface | It reuses exact target identities and keeps surface-specific composition auditable without duplicating wheel or finding metadata | Copying 22 component records into two aggregate targets; a free-form wheel list; mutable latest resolution | 2026-07-27 |
| Use one clean cumulative image per surface | This directly tests dependency and runtime interaction while preserving exact before/after classification | Treating isolated successes as cumulative proof; layering previously generated unretained trial images | 2026-07-27 |
| Run every selected target's accepted probe after the single offline install | An aggregate import smoke test would not preserve the security and native-extension behaviors already proven independently | One generic import-only probe; skipping baseline controls; network-enabled resolver tests | 2026-07-27 |
| Keep the absolute production gate fail-closed | Removing selected findings does not qualify remaining inherited findings, AMD64, signed publication, or live deployment | Zero introduced-findings-only acceptance; waiver; Trivy-only promotion | 2026-07-27 |

## Tasks

- [x] Add strict matrix model, checked-in surface selections, and positive and
      rejection fixtures.
- [ ] Extend the offline build, runtime collector, evidence manifest, and
      classifier for exact surface-specific target and wheel sets.
- [ ] Add a bounded cumulative runner and Make target while preserving all
      isolated target commands.
- [ ] Run and independently inspect the two-surface native ARM64 transaction.
- [ ] Complete repository gates, update this plan and handoff, commit, and
      push.

## Progress Log

### 2026-07-27 — Immutable matrix contract complete

- Completed: Added a v1 matrix manifest bound to the exact target-manifest
  SHA-256 and a strict loader that derives package, wheel, probe, and
  scanner-finding sets from existing accepted targets.
- Evidence: Thirteen focused tests prove the checked-in 11-target/12-component
  Horizon and nine-target/ten-component Skyline selections and reject schema,
  hash, surface, unknown, duplicate, unsorted, incomplete, incompatible,
  overlapping, mutable-field, label, symlink, and unknown-key failures.
- Changed files: `python_matrices.json`, `python_matrix.py`, focused tests,
  Make verification membership, this plan, and durable handoff.
- Next exact action: Extend the runtime collector with an explicit matrix and
  surface mode that runs every selected probe and records all exact component
  files without changing the isolated target mode.

### 2026-07-27 — Work package activated

- Completed: Reconciled all isolated accepted targets and plan 0024's coupled
  target into exact per-surface sets. Selected 11 targets and 12 components
  for Horizon, and nine targets and ten components for Skyline.
- Evidence: The existing loader reports 30/31 aggregate Trivy/Scout finding
  identities for Horizon and 15/16 for Skyline. Every target is bound to an
  accepted surface and immutable official wheel.
- Changed files: This execution plan and durable handoff.
- Next exact action: Add `poc/ui-images/python_matrices.json` and a strict
  loader in `poc/ui-images/python_matrix.py`, then cover exact selection and
  rejection behavior before changing the build runner.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Accepted target inventory | target schema v4 loader | passed; Horizon 11 targets/12 components, Skyline 9/10 |
| Matrix contract fixtures | focused pytest, Ruff, formatting, compilation, JSON | passed; 13 tests |
| Cumulative native ARM64 transaction | bounded two-surface harness | pending |
| Runtime and scanner delta | exact inventories and two scanners | pending |
| Final repository gates | static, focused/full pytest, secret, residue, diff | pending |

## Failures, Blockers, and Risks

- The existing target model represents one probe and one surface set. Treating
  all packages as companions of one synthetic target would lose
  surface-specific composition and accepted probe identity.
- `pip --no-deps` intentionally prevents a resolver from silently changing
  packages. The cumulative target set must therefore be complete enough for
  `pip check` and must fail rather than retrieve an undeclared dependency.
- Scanner findings may overlap across package targets or differ by scanner.
  Aggregate comparison must use set identity per scanner and reject missing,
  extra, or introduced Critical/High findings.
- Production remains independently blocked by Distribution/Ceph release
  gates, canonical AMD64 Scout evidence, signed publication, and live
  Kolla/UI acceptance.

## Handoff

- Current state: Plan 0025 is active; the immutable matrix model is complete.
- Exact next action: Add explicit cumulative mode to the runtime collector.
- First file or command: Extend
  `poc/ui-images/collect_python_runtime.py` without changing isolated mode.
- Questions requiring user input: None. No credential, external publication,
  live deployment, waiver, or security-boundary change is required.
