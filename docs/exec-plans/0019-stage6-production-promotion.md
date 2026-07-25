---
title: "Stage 6 production promotion"
status: active
updated: 2026-07-25
owner: primary-agent
---

# Objective

Turn the completed Stage 5 HA pilot into a production-candidate operator
baseline without weakening any accepted security, storage, identity, data
protection, or operability gate. Stage 6 qualifies released upstream
Distribution and Ceph inputs, closes the maintenance-identity and existing-data
cutover contracts, proves restart-correct observability and controlled garbage
collection, exercises representative load and recovery, and finishes with one
repeatable Kolla companion-role pilot whose evidence can support an
operator-local release.

## Done Criteria

- [ ] A signed, supported CNCF Distribution release passes ADR 0006 on x86_64
      and aarch64: immutable provenance, Coffer runtime, OCI supported-profile
      conformance, malformed-reference behavior, Referrers disposition, SBOM,
      secret scanning, and zero unresolved reachable Critical/High findings.
- [ ] A released, supported Ceph/RGW combination passes verified-TLS
      Distribution storage behavior with Barbican SSE-KMS for positive-size and
      zero-byte moves, wrong-key/outage recovery, key rotation, restart
      persistence, multipart cleanup, and least-privilege access.
- [ ] Reconciliation and authenticated live inventory use an accepted,
      expiring, owner-controlled maintenance identity over private verified TLS;
      credential materialization, rotation, revocation, audit, and fail-closed
      behavior are repeatable without secret residue.
- [ ] A representative disposable copy completes writer exclusion, restorable
      SQL and RGW backup, exact-release inventory, transactional import,
      authenticated comparison, admission cutover, rollback, and recovery with
      deterministic evidence and no mutation of production data.
- [ ] API, edge, registry, reconciliation, database, RGW, KMS, and load-balancer
      signals have restart-correct metrics, bounded-cardinality labels, alerts,
      logs, and an operator-owned failure-budget/SLO baseline.
- [ ] Coordinated write-stopped Distribution garbage collection passes dry-run
      and approved destructive collection on a disposable shared-blob fixture;
      referenced content survives, reclaimed content is measured, restore is
      rehearsed, and RGW orphan/lifecycle cleanup remains separately owned.
- [ ] Representative private-TLS/shared-SQL/RGW load and soak tests cover the
      accepted client matrix, upload shapes, quota contention, Galera
      retry/deadlock behavior, reconciler fencing, replica and dependency
      faults, and resource saturation with recorded limits.
- [ ] A fresh Kolla multinode production-candidate pilot deploys immutable
      release artifacts, passes tenant isolation and all Stage 5 availability
      gates, rehearses upgrade/rollback/backup/restore, and is completely
      removed by an independently audited teardown.
- [ ] Operator documentation, accepted/rejected ADR decisions, release notes,
      supply-chain evidence, repository regression, secret checks, and
      `HANDOFF.md` accurately describe what is and is not production-ready.

## Non-goals

- Official OpenStack governance, Kolla/Kolla-Ansible upstream inclusion, or
  service-type authority registration. Those begin only after an
  operator-local production candidate exists.
- Deploying into a production OpenStack cloud or reading, modifying, deleting,
  backing up, or restoring production tenant data.
- Publishing commits, images, attestations, SBOMs, releases, issues, or pull
  requests without separate authorization.
- Carrying an unreleased Distribution or Ceph branch, silently introducing a
  private fork, or waiving a reachable Critical/High finding to satisfy a date.
- Creating credentials, rotating real keys, changing a security boundary, or
  executing destructive GC without the explicit approval required by
  `AGENTS.md`.
- Recreating the six-VM Stage 5 lab before the selected released dependencies
  and production-candidate inputs pass their cheaper qualification gates.

## Context and Evidence

- Plan 0018 completed the disposable three-controller Kolla/Galera/HAProxy and
  three-storage-node Ceph/RGW HA pilot, then removed every exact Stage 5
  identity, credential, bucket, object namespace, VM, volume, and network.
  Post-destroy repository regression passed 251 Python tests and 52 companion
  role contract checks.
- Plan 0017 left a deterministic `production_candidate=false` result:
  Coffer-owned ARM64 image findings were reduced to zero Critical/High, but the
  signed Distribution v3.1.1 binary retained reachable vulnerabilities. ADR
  0006 therefore still prohibits production promotion.
- Official GitHub release metadata checked on 2026-07-25 still reports signed
  Distribution v3.1.1 as the latest stable release. No newer released input is
  available for the existing production-image harness.
- Ceph Tentacle v20.2.2 is still the latest stable Tentacle point release.
  That release intentionally rejects ordinary `CopyObject` for an encrypted
  source, leaving Distribution's zero-byte SSE-KMS move incompatible.
- Ceph PR 69277 was merged to the protected `tentacle` branch on 2026-07-22.
  It backports encrypted `CopyObject` support and related fixes/tests, so the
  blocker now has a concrete upstream release path. It is not acceptable
  evidence until it appears in a signed stable point release and passes the
  exact Coffer/Distribution/Barbican matrix.
- Stage 5 already proves Galera/HAProxy, replica loss, worker fencing, signing
  key overlap, rolling update, and compatible rollback. Stage 6 reuses those
  contracts only after dependency, identity, and data-protection promotion
  inputs are ready.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Treat plan 0018 commit `610b576` as the Stage 5 atomic boundary and begin Stage 6 with a new plan | The worktree is clean and Stage 5 completion, teardown, and final verification are already committed | Empty checkpoint commit; rewriting the Stage 5 completion commit | 2026-07-25 |
| Run Stage 6 as gated workstreams that converge before a new multinode pilot | Distribution and Ceph releases are external dependencies, while identity, data protection, and observability design can progress independently without recreating infrastructure | Blocking every task on the next upstream release; recreating the full lab before candidate inputs exist | 2026-07-25 |
| Accept only signed stable upstream releases for executable promotion evidence | ADR 0006 and the unmodified-data-plane decision require reproducible supported inputs | Testing a branch build and labeling it production-ready; private dependency fork without a separate ADR | 2026-07-25 |
| Treat merged Ceph PR 69277 as a release candidate signal, not a closed gate | The backport is in `tentacle` but absent from released v20.2.2; exact zero-byte and failure-mode behavior still needs an official image and live test | Claiming source inspection or upstream tests as Coffer runtime acceptance | 2026-07-25 |
| Keep official Kolla upstream work outside Stage 6 | Companion-role contracts may still change as production identity, data protection, and operations gates close | Starting governance review around provisional deployment contracts | 2026-07-25 |

## Tasks

- [x] Recover the completed Stage 5 boundary and refresh current official
      Distribution/Ceph release and source-branch evidence.
- [ ] Add a deterministic upstream-release readiness check that distinguishes
      signed stable artifacts from merged-but-unreleased fixes and feeds the
      existing fail-closed production-image and RGW/KMS harnesses.
- [ ] Select and prove the production maintenance identity and owner-only
      secret-delivery lifecycle without creating a real credential.
- [ ] Package and qualify the exact-release RGW inventory helper and complete
      the disposable backup/import/comparison/cutover/rollback rehearsal.
- [ ] Implement restart-correct metrics, protected scrape/aggregation, alerts,
      operational dashboards, and failure-budget documentation.
- [ ] Implement and execute the approved coordinated GC/retention fixture and
      restore rehearsal.
- [ ] Implement and execute the representative client/load/soak/fault matrix.
- [ ] Build immutable production-candidate artifacts and rerun dependency,
      protocol, security, architecture, and runtime qualification on both
      supported architectures.
- [ ] Recreate a fresh isolated Kolla multinode pilot only after every
      pre-deployment gate passes; accept and tear it down.
- [ ] Close operator documentation, supply-chain evidence, ADRs, repository
      regression, and the Stage 6 handoff.

## Progress Log

### 2026-07-25 — Stage 6 activated at the existing Stage 5 commit boundary

- Completed: Recovered `AGENTS.md`, the complete plan 0018, the handoff,
  current Git state, ADRs 0003/0006/0011/0014, and the retained production
  image and Barbican/RGW evidence. Confirmed the clean worktree at
  `610b576`, 126 local commits ahead of `origin/main`, with no uncommitted
  Stage 5 work requiring another checkpoint.
- Upstream evidence: Official release metadata still identifies signed
  Distribution v3.1.1 and Ceph Tentacle v20.2.2 as the current stable inputs.
  The protected Ceph `tentacle` branch merged PR 69277 at
  `c6fc9801f55e24152f0e934b2ddc3e5cda33d63e`, replacing the released
  encrypted-source rejection with decrypt/re-encrypt copy support and related
  tests. No stable release contains that backport yet.
- Decision: Activate the Stage 6 promotion harness now, preserve the external
  release gates as fail-closed, and progress independent work instead of
  rebuilding the six-VM lab or adopting an unreleased branch.
- Changed files: This plan and `.codex/state/HANDOFF.md`.
- Next exact action: Add
  `poc/production-images/check_upstream_readiness.py` with fixture-driven unit
  tests. It must classify current Distribution/Ceph release metadata and the
  Ceph encrypted-copy backport as `blocked`, `candidate-released`, or
  `candidate-qualified` without downloading, building, mutating infrastructure,
  or treating a branch commit as a released artifact.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 5 atomic boundary | `git status --short --branch`; `git log -8 --oneline` | passed; clean at `610b576`, ahead of origin by 126 |
| Distribution release state | Official GitHub latest-release API and signed release page | passed; v3.1.1 remains latest stable |
| Ceph stable release state | Official Tentacle release notes and GitHub tags | passed; v20.2.2 remains latest stable |
| Ceph fix disposition | Official PR 69277 metadata and protected `tentacle` source | passed; merged on 2026-07-22, not released |
| Plan/HANDOFF structure | Markdown inspection and local-link check | pending |

## Failures, Blockers, and Risks

- Distribution v3.1.1 remains the latest signed stable release and fails ADR
  0006. Stage 6 can progress independent contracts but cannot produce a final
  production candidate until a release or reviewable VEX closes this gate.
- Ceph's encrypted-copy fix is merged but unreleased. Branch execution may be
  useful only as explicitly labelled anticipatory evidence; it cannot satisfy
  the stable-release gate.
- Identity selection and destructive GC change security/data boundaries. This
  plan may prepare designs and disposable harnesses, but execution still
  requires the approvals stated in `AGENTS.md`.
- The local branch is 126 commits ahead of `origin/main`. This is not a
  technical blocker, but remote publication remains a separately authorized
  action and must use the `jaehanbyun` GitHub account.

## Handoff

- Current state: Stage 5 is complete and committed. Stage 6 is active; current
  released dependencies remain fail-closed while Ceph's required fix has
  reached the protected stable branch.
- Exact next action: Implement and test the fixture-driven upstream release
  readiness classifier.
- First file or command:
  `poc/production-images/check_upstream_readiness.py`.
- Questions requiring user input: None for the local classifier. Ask before
  branch-based live qualification, real credentials/security-boundary changes,
  destructive GC, external publication, or production deployment.
