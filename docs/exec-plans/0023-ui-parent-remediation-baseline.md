---
title: "UI parent vulnerability remediation baseline"
status: active
updated: 2026-07-26
owner: primary-agent
---

# Objective

Turn the inherited Critical/High findings in the accepted native ARM64 Horizon
and Skyline Console parent images into a deterministic, non-waiving
remediation baseline. Bind every inherited finding to both scanner evidence,
the exact OpenStack requirements revision and upper-constraints payload used by
Kolla, then test only narrowly justified package cleanup or constraint changes
against the real dashboard build/runtime contracts. Keep production promotion
fail closed until both scanners and both architectures meet the existing
absolute gate.

## Done Criteria

- [x] A fixture-tested classifier refuses incomplete or divergent
      parent/custom evidence and records every inherited Critical/High package
      without treating a zero Coffer delta as qualification.
- [x] The result binds the exact Kolla/OpenStack requirements revision,
      archived upper-constraints member and SHA-256, qualification evidence
      SHA-256, architecture, scanner findings, installed versions, fixed-version
      signals, and constraint matches.
- [x] The accepted ARM64 evidence produces an owner-only deterministic report
      separating constraint-bound Python candidates, upstream-unfixed
      findings, and OS-package findings without a waiver or arbitrary private
      constraint override.
- [ ] A bounded experiment evaluates whether final-image OS build dependency
      cleanup and the smallest compatible Python fix candidates preserve the
      Horizon/Skyline package, runtime, and UI test contracts.
- [ ] Any remediation image is rescanned by both accepted scanners and remains
      blocked unless its absolute Critical/High count is zero; scanner
      replacement, reachability-only suppression, or undocumented VEX is
      refused.
- [ ] Focused and repository regression, documentation, secret, and diff gates
      pass; verified atomic milestones are committed and pushed.

## Non-goals

- Waiving, suppressing, or hiding inherited findings because Coffer introduced
  none.
- Forking OpenStack global constraints or removing Kolla runtime packages
  without build, runtime, and compatibility evidence.
- Handling Docker credentials, publishing/signing images, creating a live
  OpenStack cloud, or bypassing plans 0019 and 0022.
- Claiming that a package is unreachable or build-only from its name alone.

## Context and Evidence

- Plan 0021's native ARM64 result is valid and blocked: Horizon parent/custom
  have Trivy 1 Critical/83 High and Scout 0 Critical/75 High; Skyline
  parent/custom have Trivy 1 Critical/68 High and Scout 0 Critical/60 High.
  Both scanners report zero introduced and zero missing Coffer findings.
- Plan 0022 proved the same native AMD64 build/runtime path but cannot produce
  canonical Scout CVE evidence without an unauthorized Docker login. That
  external credential boundary remains separate.
- The accepted Kolla build archive contains the OpenStack requirements
  `stable/2026.1` upper constraints. Read-only inspection binds current
  revision `06cd4e8523cbade25fb93efc4f8ea77d6d97064f` and shows the vulnerable
  Horizon Python versions match those exact constraints.
- Examples with scanner-advertised fixes include Django 4.2.28, cryptography
  43.0.3, pyOpenSSL 24.2.1, PyJWT 2.11.0, ujson 5.11.0, Pillow 12.1.1, lxml
  6.0.2, Mako 1.3.10, urllib3 2.6.3, msgpack 1.1.2, and httplib2 0.31.2.
  This is candidate evidence, not permission to override global constraints.
- The OS finding set includes `linux-libc-dev`/kernel-family packages with no
  scanner fixed version. Kolla's final `openstack-base` includes build
  dependencies, but removal safety must be proven from package dependency and
  runtime evidence rather than assumed.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Preserve the existing two-scanner absolute gate | A zero Coffer delta proves inheritance, not production safety | Delta-only qualification; Trivy-only replacement; CVE waiver | 2026-07-26 |
| Bind classification to the actual archived upper-constraints payload and official requirements revision | Package remediation is meaningful only against the exact Kolla build input | Copying a hand-selected vulnerable package list; mutable latest constraints | 2026-07-26 |
| Treat fixed-version data as an experiment candidate, not an accepted upgrade | OpenStack global constraints encode cross-project compatibility and cannot be privately reversed without tests | Blind latest-version upgrade; broad constraints fork | 2026-07-26 |
| Refuse build-only or reachability claims without direct evidence | Package names and scanner classes do not prove runtime irrelevance | Automatic `linux-libc-dev` removal; undocumented VEX | 2026-07-26 |

## Tasks

- [x] Implement and fixture-test the inherited-finding/constraints classifier.
- [x] Generate and independently reproduce the ARM64 remediation baseline.
- [ ] Run bounded OS cleanup and Python constraint compatibility experiments.
- [ ] Rescan viable derivatives, update the durable handoff, and publish each
      verified atomic milestone.

## Progress Log

### 2026-07-26 — Work package activated

- Completed: Rechecked the live Stage 6 upstream classifier; Distribution
  v3.1.1 remains the latest stable accepted line and Ceph v20.2.2 still
  predates the merged Tentacle zero-byte SSE-KMS fix. Inspected the accepted
  ARM64 UI evidence and actual Kolla `openstack-base` source archive.
- Evidence: Parent/custom finding counts and sets remain equal. The installed
  vulnerable Python versions match the exact `stable/2026.1` upper constraints
  at requirements revision
  `06cd4e8523cbade25fb93efc4f8ea77d6d97064f`.
- Changed files: This plan and `.codex/state/HANDOFF.md`.
- Next exact action: Add `poc/ui-images/remediation.py` with strict fixture
  tests in `tests/test_ui_parent_remediation.py`; consume the Kolla source
  archive directly rather than copying a mutable constraints subset.

### 2026-07-26 — Deterministic inherited-finding baseline completed

- Completed: Added a dependency-free classifier that refuses linked/missing
  evidence, invalid schemas and revisions, divergent parent/custom finding
  sets, qualification count mismatches, ambiguous constraints members,
  conflicting constraints, and non-atomic output replacement. No finding is
  suppressed and the result is never a production candidate.
- Accepted result: The owner-only ARM64 report exits `3` and reproduces at
  SHA-256
  `9ecde6e3b6e2d484bd27fa05cf6c1b26e81077a3e3154a64ebf4902863fa0941`.
  It binds qualification SHA-256
  `883a8af9ae1bd9419caccd027943fbeb6352f5a4316608009e1fa4b0de2cb564`
  and exact constraints SHA-256
  `04a324d166aa983f79341fe0584e0dc0b1b81377403dc85e47605c43d58db167`.
- Classification: Horizon has 16 package/version groups, including 12
  constraint-bound all-fixed candidates, one constraint-bound no-fix group,
  two OS no-fix groups, and one unbound all-fixed group. Skyline has 14 groups
  split 10/1/2/1 respectively. `linux`/`linux-libc-dev` remain OS no-fix;
  `oslo.messaging` remains constraint-bound without a fixed version.
- Safety boundary: The candidate lists are test inputs only.
  `waivers_applied`, `private_constraint_override_accepted`,
  `os_cleanup_accepted`, and `production_candidate` are all false.
- Changed files: Classifier, five focused fixtures, Make target, UI image
  README, this plan, and the handoff. Canonical raw/report evidence stays
  owner-only under ignored `work/`.
- Next exact action: Add a bounded dependency/removal probe for the stock
  Horizon and Skyline parent filesystem before modifying an image or
  constraints.

### 2026-07-26 — Stock-parent OS dependency boundary completed

- Completed: Added a fixed-target package probe and bounded Kolla stock-parent
  runner. It builds exact ARM64 Horizon/Skyline parents from the accepted
  Ubuntu digest and Kolla revision, then executes only read-only/no-network/
  no-capability/no-new-privileges `dpkg`, `apt-mark`, and `apt-get -s`
  inspection. Exact probe images and build contexts are removed and a
  previously stopped Podman machine is restored to stopped.
- Evidence: Horizon and Skyline probe payloads are byte-identical at SHA-256
  `75dfaac579e19bece668f480cbffc1212b08e1496dc8533d489d31b7256d783a`.
  The owner-only summary is mode 0640 at SHA-256
  `e0b95fe54f4d083fc5507847b0e7ed31fa61ec99e3af138446fe62039f21e0bc`.
- Package boundary: `linux-libc-dev` 6.8.0-136.136 is automatic, not manual.
  It owns 1,015 paths: 1,007 headers, zero shared-object paths, and zero
  executable paths. Its installed direct reverse dependency is automatic
  `libc6-dev` 2.39-0ubuntu8.7.
- Purge boundary: The exact simulation removes 18 packages, including
  `linux-libc-dev`, `libc6-dev`, `build-essential`, the C++ toolchain, Python
  development headers, and XML/XSLT/zlib development packages. Both package
  database checks pass, but the report keeps `safe_to_apply=false`; inventory
  and simulation do not prove runtime, rebuild, upgrade, or rollback safety.
- Diagnosed failures: The first probe rejected Ubuntu's normal
  `/etc/os-release` link to `/usr/lib/os-release`; the fixed-path system link is
  now accepted. The second probe parsed apt `Remv` but not purge-mode `Purg`;
  both exact action records are now accepted. A lightweight disposable Ubuntu
  digest fixture reproduced and verified each correction before the final
  stock-parent run. Failed owner-only probe directories were moved to the
  user's Trash and can be recovered; no raw invalid result entered Git.
- Cleanup: Final probe images and generated contexts are absent; the retained
  Podman machine is stopped. Owner-only non-secret evidence remains under
  ignored `work/ui-parent-remediation-probe/evidence/`.
- Changed files: Package probe, bounded runner, seven focused fixtures, Make
  target, README, this plan, and the handoff.
- Next exact action: Build a disposable post-Coffer derivative that applies
  only the exact 18-package apt purge transaction, then require clean package
  DB, Horizon/Skyline import and runtime checks, image metadata preservation,
  rollback parent availability, and two-scanner comparison before accepting or
  rejecting the cleanup.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 6 upstream release gate | `make -C poc/production-images check-upstream` | blocked as expected |
| ARM64 parent evidence inventory | accepted ignored evidence plus `jq` | inspected; exact parent/custom counts retained |
| Kolla constraints binding | archived `openstack-base` source plus official requirements revision | inspected; exact vulnerable versions match |
| Classifier fixtures | focused pytest | passed; 28 UI classifier/qualification/collector tests |
| Accepted evidence classification | deterministic repeat and SHA-256 comparison | passed; exit 3, mode 0640, stable SHA-256 `9ecde6e...` |
| Stock-parent package probe | bounded native ARM64 build and read-only inspection | passed; identical surfaces, exact cleanup, summary `e0b95fe...` |
| Package-probe milestone gates | 35 focused tests, ShellCheck, Ruff E/F/I, compilation, full pytest | passed; 1,490 tests |
| Compatibility/remediation experiment | bounded image/package/UI tests | pending |
| Baseline milestone gates | full pytest, Ruff E/F/I, compilation, staged secret/diff | passed; 1,483 tests and no staged leak |
| Final repository gates | dashboard packages, Kolla role, docs/links, secret, diff | pending with remediation experiment |

## Failures, Blockers, and Risks

- Distribution and Ceph stable-release gates still block plan 0019.
- Docker Scout authentication still blocks canonical native AMD64 evidence in
  plan 0022; this package does not expand credential authority.
- OpenStack upper constraints may intentionally exclude scanner-advertised
  fixed releases. A private override could introduce API/runtime incompatibility
  and remains unaccepted until the exact test matrix passes.
- The OS purge simulation removes 18 development packages rather than only
  `linux-libc-dev`. It is not accepted until a post-Coffer derivative proves
  package integrity, dashboard runtime, rebuild, fallback, and scan behavior.
- A lower scanner count after deleting build packages is insufficient unless
  Kolla startup, package ownership, Horizon/Skyline runtime, and upgrade/
  rollback behavior also remain correct.

## Handoff

- Current state: Plan 0023 is active; plans 0019 and 0022 remain externally
  blocked. The inherited ARM64 classifier and deterministic baseline are
  complete locally with no waiver. The stock-parent dependency probe is also
  complete and proves an exact 18-package purge set, but explicitly does not
  accept it. Raw/report evidence is non-secret and remains owner-only under
  ignored `work/`.
- Exact next action: Implement the bounded post-Coffer OS cleanup derivative,
  runtime/rollback verifier, and two-scanner comparison.
- First file or command: Add an experimental Containerfile and a
  cleanup-specific disposable runner under `poc/ui-images/`; do not modify the
  production UI Containerfiles yet.
- Questions requiring user input: None. No credential, external publication,
  live deployment, or waiver is required for the next local milestone.
