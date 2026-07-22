# ADR 0006 Candidate: Gate the Production Distribution Release

- Status: proposed
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0002-thin-vertical-poc.md`
- Evidence: `docs/research/m0-upstream-compatibility.md`

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
