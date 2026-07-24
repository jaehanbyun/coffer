# ADR 0006 Candidate: Gate the Production Distribution Release

- Status: proposed
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plans: `docs/exec-plans/0002-thin-vertical-poc.md`,
  `docs/exec-plans/0017-production-image-remediation.md`
- Evidence: `docs/research/m0-upstream-compatibility.md`,
  `poc/production-images/`

## Context

ADR 0001 selects an unmodified Distribution v3 data plane but leaves the exact production release to empirical compatibility and security review. M0 proved the v3.1.1 functional path and also found unresolved image vulnerabilities, one core OCI conformance failure, and no native OCI 1.1 Referrers API.

Using a known-bad production pin would turn a temporary PoC convenience into an implicit architecture decision. Forking Distribution to repair these gaps would contradict the accepted composition baseline and transfer a large security maintenance burden to Coffer.

## Proposed Decision

Keep Distribution v3.1.1 pinned only for isolated local PoC work. Do not promote it to a production baseline.

A production candidate must satisfy all of these gates:

1. Pin the multi-platform image and each deployed platform manifest by digest, and map them to a signed upstream release/source commit.
2. Pass the Coffer functional image, artifact, persistence, and object-store tests.
3. Pass the OCI supported-capability conformance profile without a core protocol failure. Optional capabilities may be disabled only when Coffer does not advertise or depend on them.
4. Have no unresolved reachable Critical or High vulnerability under the project's policy. A documented, independently reviewable VEX disposition may satisfy a finding; scanner counts alone cannot.
5. Support native OCI 1.1 Referrers, or obtain an explicit product/security acceptance for client fallback concurrency and lifecycle limitations.
6. Pass the real Ceph RGW TLS, least-privilege, SSE-KMS, persistence, and coordinated GC gates before production use.

M1 and M2 development may continue against the loopback v3.1.1 fixture because those milestones validate Coffer control and auth contracts rather than approve a production image.

## 2026-07-24 Qualification Result

Plan 0017 rebuilt both product artifacts on the digest-pinned Ubuntu Noble
platform image through exact Kolla `stable/2026.1` commit
`686c6d13dc1c31092b22c6c481e16a7329e935ea`. The build verifies the signed
Distribution v3.1.1 release tar and its provenance subject, creates SPDX
package inventories, requires dedicated non-root users, runs two vulnerability
scanners plus a secret scan, and exercises the full local runtime contract
before deciding promotion.

The ARM64 Coffer image passes Docker Scout and Trivy at zero Critical and zero
High, reports zero detected secrets, and passes the API, edge, token,
repository, quota admission, OCI push/pull, restart-persistence,
reconciliation, and repeat-bootstrap contracts. Its locked application venv
remains intact while unused system `pip`, `setuptools`, `wheel`, and venv
build packages are removed from the final image.

The equally minimized registry wrapper remains blocked:

| Evidence | Coffer | Distribution wrapper |
|---|---:|---:|
| Docker Scout | 0 Critical / 0 High | 8 Critical / 10 High |
| Trivy 0.72.0 | 0 Critical / 0 High | 0 Critical / 22 High |
| Trivy secret scan | 0 | 0 |
| SPDX package inventory | 331 | 363 |

The residual registry findings belong to the signed upstream Go 1.25.9
release binary, including `golang.org/x/crypto` v0.49.0,
`golang.org/x/net` v0.52.0, and gRPC v1.80.0. `govulncheck` v1.6.0 reports
three source-reachable call paths and 37 vulnerable release-binary symbol
groups. Replacing the surrounding base cannot remediate them, and rebuilding
v3.1.1 with different dependencies would no longer be the signed upstream
release artifact.

The resulting `qualification.json` therefore sets `production_candidate` to
false. This is the intended fail-closed outcome: Coffer-owned and base-image
findings were remediated without suppressions, while the upstream release
dependency remains visible. The next eligible action is to rerun the same
harness against a newer signed, supported Distribution release and repeat the
protocol gates. A private fork or unreleased dependency rebuild still requires
a new ADR.

## Rejected Alternatives

- **Declare v3.1.1 production-ready because push/pull works:** rejects security and protocol evidence.
- **Fork or hot-patch Distribution now:** creates premature long-term ownership before upstream release selection and issue resolution are exhausted.
- **Hide conformance failures by changing the harness:** loses the evidence needed to make capability and release decisions.
- **Implement a Coffer Referrers sidecar:** duplicates registry semantics and risks divergence from standard clients and upstream storage.

## Consequences

- Production image selection remains open and is re-evaluated on each supported Distribution release.
- The PoC can continue without pretending that its fixture is deployable.
- Native Referrers and malformed-reference handling become explicit acceptance evidence rather than late surprises.
- If no upstream release satisfies the gates, maintainers must return with evidence for a new ADR rather than silently introduce a fork.
- The reproducible ARM64 qualification is positive image-construction
  evidence, not x86_64, multi-distribution, RGW/SSE-KMS, HA, backup, upgrade,
  or production deployment approval.
