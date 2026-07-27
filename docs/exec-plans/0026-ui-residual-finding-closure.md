---
title: "UI residual finding closure"
status: active
updated: 2026-07-27
owner: primary-agent
---

# Objective

Resolve the three High findings that remain on both native ARM64 cumulative UI
derivatives without replacing vendor-patched packages merely to satisfy
version-only matching. Bind the result to Plan 0025's exact evidence, prove
whether Ubuntu's backported setuptools fixes justify a standards-based
machine-readable disposition, track the genuinely affected oslo.messaging
finding to an upstream fix and release, and keep the production gate
fail-closed for every finding that is not proven fixed or not affected.

## Done Criteria

- [ ] A checked-in residual-finding contract binds Plan 0025 result SHA-256,
      both exact after-scan report hashes, package identities and locations,
      affected/fixed status, vendor advisory sources, and expected disposition.
- [ ] Canonical's two Noble setuptools backports are verified against the
      installed `68.1.2-2ubuntu1.2` package and the vulnerable behaviors,
      without deleting dpkg metadata, upgrading a distro package with pip, or
      hiding raw scanner results.
- [ ] Any OpenVEX statement is generated only from proven vendor backport
      evidence, identifies the exact immutable product and subcomponent, uses
      `vulnerable_code_not_present`, and is independently accepted by Docker
      Scout while raw and VEX-aware results remain available together.
- [ ] The current oslo.messaging advisory, upstream patch state, release
      availability, compatibility boundary, and exact production blocker are
      recorded. No unreleased commit or private fork is promoted.
- [ ] Native ARM64 runtime, package, scanner, secret, cleanup, focused/full
      regression, documentation, diff, and residue gates pass; verified
      milestones are committed and pushed.

## Non-goals

- Suppressing or waiving a vulnerability, deleting scanner-recognized metadata,
  replacing Ubuntu packages with untracked pip installations, or accepting a
  risk because the vulnerable code path appears unlikely.
- Editing production Horizon/Skyline Containerfiles, OpenStack global
  constraints, Kolla configuration, or published image tags before the
  residual disposition is independently accepted.
- Handling Docker credentials, publishing or signing images, creating a live
  cloud, or claiming AMD64, Kolla startup, browser, upgrade, rollback, or
  production compatibility from an ARM64 experiment.
- Shipping an unreleased oslo.messaging source patch as a Coffer-owned
  security fork.

## Context and Evidence

- Plan 0025 accepted clean result SHA-256
  `a920ce2076908469c06103fbd0f19953cbf6e67a4dead964faaf85d20ed21e0a`.
  Both surfaces remain at Trivy 0 Critical/1 High and Scout 0 Critical/3
  High.
- Trivy and Scout agree that `oslo.messaging` 17.3.0 is affected by
  `CVE-2026-44393` and report no fixed version. The installed package lives in
  the Kolla virtual environment.
- Scout additionally treats
  `/usr/lib/python3/dist-packages/setuptools-68.1.2.egg-info` as
  `pkg:pypi/setuptools@68.1.2` and reports `CVE-2024-6345` plus
  `CVE-2025-47273` by upstream version range.
- The installed dpkg package is `python3-setuptools`
  `68.1.2-2ubuntu1.2`. Canonical USN-7002-1 records Noble fixed at
  `68.1.2-2ubuntu1.1`; USN-7544-1 records Noble fixed at
  `68.1.2-2ubuntu1.2`. The apparent conflict is therefore a package-ecosystem
  and backport-recognition issue, not evidence that a later upstream wheel is
  automatically safer for the Kolla base.
- Docker Scout supports OpenVEX input through `--vex-location`. A VEX
  disposition is acceptable here only if it represents proven absence of the
  vulnerable code and leaves the original scanner evidence auditable.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Reconcile vendor backports before mutating the image | Ubuntu's supported package version is newer than both stated fixed package revisions even though its upstream version remains 68.1.2 | Blind pip upgrade to 78.1.1; deleting egg-info; removing setuptools before dependency proof | 2026-07-27 |
| Preserve raw findings beside any VEX-aware view | Standards-based exploitability context must be auditable and must not erase scanner observations | `--ignore-suppressed` as the only retained output; custom severity downgrade; allowlist | 2026-07-27 |
| Keep oslo.messaging affected until an upstream release is available and qualified | Both scanners and the advisory agree that 17.3.0 is affected and no fixed release is currently identified in accepted evidence | Local monkey patch; private wheel; configuration-only waiver | 2026-07-27 |
| Keep production images unchanged during this plan | Residual classification and release qualification must precede immutable production image changes | Editing disabled production Containerfiles first | 2026-07-27 |

## Tasks

- [ ] Add the strict residual-finding and vendor-evidence contract with
      positive and fail-closed rejection tests.
- [ ] Verify exact Ubuntu backport content and security behavior; generate and
      validate product-bound OpenVEX only if the evidence closes both findings.
- [ ] Resolve current oslo.messaging upstream patch/release state and define
      the release qualification gate.
- [ ] Run the bounded native ARM64 transaction, repository gates, durable
      documentation, commit, and push.

## Progress Log

### 2026-07-27 — Work package activated

- Completed: Classified the three residual findings by package source and
  location and checked current primary vendor guidance.
- Evidence: Both scanners retain `CVE-2026-44393` for venv
  `oslo.messaging` 17.3.0 with no fixed version. Scout alone reports two
  upstream-version setuptools findings against a system egg-info whose dpkg
  package revision is the exact Canonical-fixed Noble revision.
- Changed files: This execution plan and durable handoff.
- Next exact action: Add `poc/ui-images/residual_findings.json` with exact
  Plan 0025/result/scanner/package/vendor bindings, then implement a strict
  loader and rejection fixtures before generating VEX or rebuilding images.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Plan 0025 residual inventory | exact after-scan JSON projection | passed; identical 1 Trivy/3 Scout High on both surfaces |
| Canonical package status | USN-7002-1 and USN-7544-1 | passed; installed Noble revision includes both fixes |
| Residual contract and fixtures | focused pytest, Ruff, format, JSON | pending |
| Vendor patch and negative behavior proof | exact source/package inspection and bounded runtime probes | pending |
| VEX-aware Scout result | raw plus `--vex-location` acquisition | pending |
| oslo.messaging release gate | official OpenStack changes/releases | pending |
| Final repository gates | focused/full pytest, static, secret, residue, diff | pending |

## Failures, Blockers, and Risks

- Version-only matching can misclassify a distro-backported package. Replacing
  it with an upstream wheel would cross dpkg ownership and can create a less
  supportable image even if the scanner count falls.
- VEX is security evidence, not permission to invent a disposition. Product,
  subcomponent, vendor revision, patch, and behavior must all match before a
  `not_affected` statement is accepted.
- `CVE-2026-44393` affects the OpenStack control-plane messaging TLS boundary.
  It cannot be waived based on Coffer's own registry request path.
- Canonical AMD64 Scout evidence, signed publication, Distribution/Ceph
  release blockers, and live Kolla/UI acceptance remain independent gates.

## Handoff

- Current state: Plan 0026 is active; research has separated the vendor-patched
  system package reports from the genuinely affected venv package.
- Exact next action: Implement the immutable residual-finding manifest and
  strict loader.
- First file or command: Add
  `poc/ui-images/residual_findings.json`, then
  `poc/ui-images/residual_finding.py` and focused tests.
- Questions requiring user input: None. No credential, publication, live
  deployment, waiver, or production image mutation is required.
