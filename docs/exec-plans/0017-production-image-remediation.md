---
title: "Production image remediation baseline"
status: completed
updated: 2026-07-24
owner: primary-agent
---

# Objective

Turn the Stage 4 functional Coffer and Distribution images into a reproducible,
fail-closed production-candidate build and security-qualification baseline.
Use only supported Kolla 2026.1 bases and signed upstream Distribution release
inputs, eliminate avoidable image findings, classify remaining Critical/High
findings by exact component and reachability, and refuse production promotion
unless every proposed ADR 0006 gate is supported by retained evidence.

## Done Criteria

- [x] Resolve the current official Distribution stable release, signed source
      commit, release artifacts/checksums/provenance, published image manifests,
      security advisories, and Kolla 2026.1 supported base distributions from
      primary sources.
- [x] Produce both Coffer and Distribution candidate images from immutable,
      reviewable inputs without using Kolla test images or the tenant registry
      as their bootstrap source; support at least x86_64 and aarch64 build
      contracts and run the locally available architecture.
- [x] Generate SBOM, vulnerability, secret, provenance/input, non-root, package
      inventory, and configuration-contract evidence. The build fails closed
      on unresolved Critical/High findings rather than hiding scanner output.
- [x] Pass the existing image/runtime, OCI push/pull, restart, token, edge,
      schema/bootstrap, and focused regression contracts on the candidate
      artifacts. Record native Referrers and malformed-reference behavior
      honestly.
- [x] Decide whether a production candidate can be accepted. If no supported
      upstream release can satisfy ADR 0006, retain a reproducible blocked
      baseline, exact residual findings, and an explicit upstream dependency;
      do not introduce a private Distribution fork.
- [x] Update ADR 0006, image documentation, this plan, and `HANDOFF.md`; run
      focused and repository-wide code, template, shell, Markdown, secret,
      residue, and diff checks with no credential or runtime residue.

## Non-goals

- Publishing images, SBOMs, attestations, commits, branches, issues, pull
  requests, or releases without separate authorization.
- Claiming Kolla, Ceph RGW, Galera, multinode/HA, rolling-upgrade, backup,
  restore, GC, or SSE-KMS production readiness from local image evidence.
- Forking Distribution, carrying an unreviewed dependency patch set, accepting
  an unreleased branch as a stable production artifact, or suppressing scanner
  findings solely to reach a numeric gate.
- Recreating the destroyed Stage 4 AIO or mutating `bb00`, retained VMs,
  identities, credentials, storage, or external services.

## Context and Evidence

- Plan 0016 proved the Kolla AIO product path but used Kolla's explicitly
  test-only Quay images. Trivy 0.72.0 reported 6 Critical/34 High for Coffer
  and 6 Critical/54 High for the Distribution wrapper.
- Proposed ADR 0006 requires a signed supported upstream release, immutable
  platform pins, functional and OCI conformance, no unresolved reachable
  Critical/High findings, an explicit Referrers disposition, and real RGW
  gates before production promotion.
- At activation, the templates installed the official Distribution v3.1.1
  release binary into a Kolla `base` image and installed Coffer into Kolla
  `openstack-base`. The completed baseline keeps the unmodified release binary
  but moves Coffer to a constrained venv directly on `base`.
- Official upstream research at activation still identifies Distribution
  v3.1.1 as the latest signed stable release. Kolla-Ansible 2026.1 supports
  Ubuntu Noble, Debian Trixie, Rocky Linux 10, and CentOS Stream 10 hosts; its
  image support includes `ubuntu`, `debian`, `rocky`, and `centos`.
- Stage 4 implementation changes are intentionally uncommitted and must remain
  preserved. This plan extends them without publishing or rewriting their
  evidence.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Start with Ubuntu Noble for executable candidate evidence while keeping Debian/Rocky and both architecture contracts visible | Stage 4 used Ubuntu Noble and Kolla recommends matching host and image distributions; one executable baseline avoids claiming an untested matrix | Claiming all supported distributions from template rendering; changing the deployment OS during remediation | 2026-07-24 |
| Keep the production gate fail-closed when no supported upstream Distribution release satisfies it | Latest-release status and functional success do not resolve reachable vulnerabilities or protocol defects | Relabeling v3.1.1 as production-ready; using an unreleased branch; suppressing findings | 2026-07-24 |
| Prefer rebuilding supported base images and qualifying the signed release before considering any source rebuild | It separates avoidable OS/package findings from the immutable upstream binary and preserves ADR 0001's composition boundary | Immediate private fork or dependency patch train | 2026-07-24 |
| Build Coffer directly on Kolla `base` with an exact generated runtime constraint set | Coffer does not need the broad OpenStack build/runtime inventory; comparing the constraints to `uv.lock` before build prevents pip from silently resolving newer transitive packages | Retaining `openstack-base`; relying on a lock file that pip does not consume; manually maintaining partial pins | 2026-07-24 |
| Remove system packaging tools after final artifacts exist | The Kolla base's system `setuptools` and `wheel` accounted for avoidable High findings, while Kolla runtime only requires system Python and the Coffer commands use their private venv | Upgrading unused system build tools; removing system Python; suppressing scanner findings | 2026-07-24 |
| Complete this plan with a reproducible upstream-blocked baseline | Coffer-owned and wrapper-base findings are remediated, but the signed Distribution release still has reachable vulnerabilities and therefore cannot satisfy ADR 0006 | Private fork; rebranding a dependency rebuild as signed v3.1.1; numerical waiver without VEX | 2026-07-24 |

## Tasks

- [x] Inventory primary-source release/base support and exact retained
      Stage 2/4 scanner evidence; classify image versus embedded-binary risk.
- [x] Implement immutable production-candidate build inputs and a fail-closed
      SBOM/vulnerability/provenance qualification harness.
- [x] Build and exercise the locally available candidate architecture; fix
      avoidable packaging and runtime-contract findings.
- [x] Run protocol/runtime/regression gates and record the production
      acceptance or explicit upstream-blocked result.
- [x] Remove exact runtime artifacts, close documentation and handoff, and run
      the final repository verification matrix.

## Progress Log

### 2026-07-24 — Plan activated

- Completed: Recovered the completed Stage 4 plan, handoff, dirty worktree,
  current Kolla templates, local contract harness, Distribution version pins,
  ADR 0006 gates, and recent Git publication boundary.
- Evidence: Local and remote `main` remain at Stage 3 commit `dc145ff`; all
  completed Stage 4 files are preserved locally. Primary upstream pages still
  identify signed Distribution v3.1.1 as latest stable and document Kolla
  2026.1 supported bases.
- Decision: Remediate and qualify images without recreating AIO
  infrastructure, publishing artifacts, accepting unreleased Distribution
  code, or weakening the production gate.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Inspect retained Stage 2/4 SBOM and vulnerability evidence
  and query the signed v3.1.1 release metadata/source dependency graph to
  separate base-image findings from embedded Distribution binary findings.

### 2026-07-24 — Vulnerability ownership classified

- Completed: Verified signed Distribution v3.1.1 commit
  `9a8d98b679740cd514aa7e7d84d23d442a5ef54c`, release date, release asset
  digests, x86_64/aarch64 tar and provenance digests, module graph, official
  Ubuntu Noble multi-platform digest, and exact Kolla `stable/2026.1` commit
  `686c6d13dc1c31092b22c6c481e16a7329e935ea`.
- Retained evidence: The Stage 2 Coffer image had one Critical/4 High: the two
  Python High findings are fixed by upgrading `cryptography` 43.0.3 to the
  trusted-published 49.0.0 release; the remaining Perl findings belonged to
  the disposable Debian Bookworm contract base. The registry wrapper's 9
  Critical/12 High were dominated by the signed v3.1.1 Go binary:
  `x/crypto` 0.49.0, `x/net` 0.52.0, Go 1.25.9, and gRPC 1.80.0.
- Reachability evidence: `govulncheck` v1.6.0 source mode reports three actual
  call paths in v3.1.1: GO-2026-5970 through `x/text` normalization and
  GO-2026-5026/GO-2026-4918 through IDNA/HTTP2 paths. Binary mode finds
  vulnerable symbols for 37 Go/module advisories, including the Go 1.25.9
  standard library. This is an upstream binary gate; changing the surrounding
  base image cannot close it.
- Completed: Updated Coffer's direct `cryptography` pin to 49.0.0, refreshed
  the lock, and passed 51 focused token, Keystone, edge, and proxy tests.
- Decision: Build the candidate from the official pinned Kolla Ubuntu Noble
  base path to remove disposable contract-base noise, but retain a blocked
  production result while the latest signed Distribution release has
  reachable unresolved vulnerabilities. Do not rebuild an unofficial patched
  Distribution binary under the v3.1.1 identity.
- Changed files: `pyproject.toml`, `uv.lock`, this plan, and `HANDOFF.md`.
- Next exact action: Add `poc/production-images/` with pinned Kolla, Ubuntu,
  Distribution release/provenance and scanner inputs; make its qualification
  command emit SBOMs and exact findings, exercise runtime contracts, and
  return a deterministic blocked result while the upstream binary gate fails.

### 2026-07-24 — Reproducible candidate qualification completed

- Completed: Added exact Kolla, Ubuntu multi-platform/child-manifest,
  Distribution release/provenance, Trivy, Podman client, and `govulncheck`
  pins. The harness snapshots only tracked and intentional untracked source,
  rejects `uv.lock`/production-constraint drift, builds through the official
  Kolla Podman builder, and consumes neither Kolla test images nor Coffer's
  tenant registry.
- Packaging: Replaced `openstack-base` with Kolla `base`, installed Coffer
  into a root-owned dedicated venv from 64 exact constraints, validated it
  with `pip check`, and removed temporary system packaging/venv tools. The
  registry wrapper verifies the upstream tar digest and provenance before
  installing the release binary, then removes its unused system packaging
  tools.
- Runtime: The ARM64 candidate images run as `coffer` and `registry` and pass
  the complete Stage 2 contract: all installed commands, configuration copy
  and permissions, repeated Alembic bootstrap, API/token/JWKS, private quota
  edge, OCI push/pull, restart digest preservation, reconciliation, logging,
  secret checks, and exact container/network/volume cleanup.
- Security evidence: Coffer is 0 Critical/0 High in both Docker Scout and
  Trivy, with zero Trivy secret findings and 331 SPDX packages. The registry
  wrapper is 8 Critical/10 High in Scout, 0 Critical/22 High in Trivy, zero
  secret findings, and 363 SPDX packages. Base-tool removal reduced Scout
  registry High findings from 13 to 10 without suppressions.
- Upstream gate: `govulncheck` v1.6.0 reports three reachable source call
  paths and 37 vulnerable symbol groups in the signed Distribution v3.1.1
  release binary. The exact remaining Go 1.25.9, `x/crypto` 0.49.0,
  `x/net` 0.52.0, and gRPC 1.80.0 findings cannot be changed by rebuilding
  the wrapper base.
- Decision: `qualification.json` correctly sets `production_candidate=false`.
  Plan 0017 is complete with an explicit upstream dependency; no image,
  evidence, commit, branch, or release was published, and no private fork was
  introduced.
- Final regression: 232 tests pass on each of Python 3.11, 3.12, and 3.13;
  52 companion-role contract checks and production-profile Ansible lint over
  53 files pass; Go format/test/vet, lock/constraint drift, compilation, 67
  Bash/ShellCheck files, all Compose models and PoC Make defaults, 41 YAML and
  12 Jinja parses, 69 Markdown files and 44 local links, project-owned
  Gitleaks, diff, qualification-consistency, runtime-residue, and Podman
  shutdown checks pass.
- Changed files: Kolla image/runtime entry points and focused tests;
  `pyproject.toml`, `uv.lock`, generated production constraints;
  `poc/production-images/`; ADR 0006; Kolla topology/image documentation;
  this plan; and `HANDOFF.md`.
- Next recommended work package: monitor for a newer signed supported
  Distribution release, then update immutable release pins and rerun this
  qualification plus the malformed-reference and native Referrers protocol
  gates before considering Stage 5 or production promotion.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Primary-source release/base inventory | Signed upstream release metadata and official Kolla 2026.1 documentation | passed |
| Candidate input immutability | Digests, checksums, provenance, exact Kolla/source pins, 64-package constraint drift check | passed |
| Security qualification | SPDX, Docker Scout, Trivy vulnerability/secret, `govulncheck`, exact fail-closed decision | passed; production blocked |
| Runtime and OCI compatibility | Candidate image/CLI/config, token/JWKS, edge/quota, push/pull, restart, bootstrap/reconcile | passed on ARM64 |
| Full regression and hygiene | Python 3.11/3.12/3.13, Go, Ansible, templates, shell, Markdown, secrets, residue, diff | passed |

## Failures, Blockers, and Risks

- Distribution v3.1.1 is still the latest supported stable release. Its
  embedded Go/module findings remain unresolved, so this work package
  correctly finishes with a reproducible production block rather than an
  accepted production image.
- Scanner counts are not interchangeable across Scout and Trivy. Decisions
  require exact package/CVE/fixed-version/reachability evidence, not comparison
  of aggregate totals alone.
- A current base rebuild can remove stale OS packages but cannot repair an
  immutable vulnerable upstream binary. Rebuilding or replacing that binary
  changes provenance and requires a separately reviewable decision.
- Local Apple ARM64 execution does not establish x86_64 or multi-distro runtime
  evidence. Template/checksum contracts may cover the matrix, but claims must
  remain bounded to executed platforms.
- The earlier registry purge attempt named uninstalled wheel packages after
  apt indexes were removed and failed closed. The final template removes only
  the three installed system packages and the complete qualification passes.
- Final source review found a host-specific Homebrew `go` path and a
  macOS-only checksum assumption. The completed harness resolves `go` from
  `PATH` and selects either `sha256sum` or `shasum`; Bash, ShellCheck, and an
  exact retained release-digest check pass after the correction.

## Handoff

- Current state: Completed locally with a reproducible
  `production_candidate=false` result. The Coffer image is clean at the
  Critical/High gate; the signed upstream Distribution binary is the explicit
  blocker.
- Exact next action: None in plan 0017. For the recommended successor, first
  resolve a newer signed supported Distribution release, update
  `poc/production-images/pins.env`, and rerun the unchanged fail-closed
  qualification before any deployment or publication.
- First file or command: `poc/production-images/pins.env`, only after a newer
  supported release exists.
- Questions requiring user input: None within local, non-publishing image
  remediation. Ask before a private fork, unreleased source baseline,
  external publication, or production deployment.
