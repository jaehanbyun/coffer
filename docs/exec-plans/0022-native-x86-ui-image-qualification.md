---
title: "Native x86_64 UI image qualification"
status: blocked
updated: 2026-07-26
owner: primary-agent
---

# Objective

Run the completed Horizon and Skyline Console image supply-chain contract on a
native x86_64 Linux runner. Reproduce the exact pinned Kolla, upstream source,
wheel, runtime, SBOM, vulnerability, secret, and cleanup gates from plan 0021
without using emulation, test-only parent images, external image publication,
or a live OpenStack deployment. Compare the x86_64 result with the accepted
ARM64 evidence and leave the remote runner with zero Coffer-owned runtime
residue.

## Done Criteria

- [x] Read-only preflight proves a distinct native x86_64 runner, sufficient
      bounded CPU/memory/disk, an isolated working path, required container and
      scanner capabilities, and no need to reuse or mutate unrelated services.
- [x] The runner consumes the exact committed Coffer source, Kolla/Horizon/
      Skyline revisions, Ubuntu AMD64 digest, wheel versions, and scanner pins;
      mutable/test-only parents and cross-architecture emulation are refused.
- [x] Stock Horizon and Skyline Console parents plus both Coffer derivatives
      build natively and pass immutable provenance, inherited Kolla metadata,
      runtime package/file, build-input absence, and exact layer-prefix gates.
- [ ] SPDX, Docker Scout, and Trivy vuln/secret evidence yields a canonical
      native x86_64 qualification result with explicit absolute and
      parent/custom delta findings.
- [ ] The ARM64 and x86_64 dispositions are compared without waiving inherited
      findings. Any architecture-specific Coffer Critical/High delta or secret
      remains a production blocker.
- [x] Exact remote Coffer images, containers, archives, scanner cache, work
      state, and temporary source material are removed. No image, evidence,
      signature, credential, or deployment is published.
- [x] Focused and repository regression, documentation, secret, and diff gates
      pass; the atomic milestone is committed and pushed.

## Non-goals

- Creating or modifying a production OpenStack cloud, Kolla deployment,
  Keystone catalog, Horizon/Skyline service, registry, or tenant data.
- Reusing the shared virtualization host's unrelated ports, VMs, services,
  networks, volumes, or registry workloads.
- Treating native x86_64 image evidence as closure of plan 0019's Distribution
  and Ceph stable-release gates.
- Signing, pushing, publishing, deploying, or releasing any image or evidence.
- Installing a persistent system-wide credential or retaining an SSH target,
  token, key, certificate, or scanner secret in the repository.

## Context and Evidence

- Plan 0021 completed the same contract on native ARM64. The Coffer
  parent/custom delta is zero and no secrets were detected, but inherited
  stock-parent Critical/High findings correctly block production
  qualification.
- The user previously supplied an approved nested SSH route for an x86_64
  environment. The shared outer virtualization host is not itself an
  installation or workload target.
- The plan 0021 harness currently assumes a local macOS Podman machine and
  Docker Scout installation. The x86_64 adapter must preserve evidence
  semantics while making only the minimum platform-specific orchestration
  change.
- Plan 0019 remains externally blocked by the latest stable Distribution and
  Ceph/RGW release pair. This work can narrow the independent UI architecture
  matrix but cannot promote Stage 6.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Use only a distinct native x86_64 Linux runner reached through the approved route | Native runtime behavior and architecture-specific packages must be observed without touching the shared outer host | Cross-emulation; direct shared-host installation; claiming manifest metadata as runtime evidence | 2026-07-26 |
| Reuse plan 0021's evidence schema and fail-closed classifier | Cross-architecture comparison is meaningful only when source, artifact, scanner, and disposition contracts remain identical | A weaker remote-only checklist; scanner-count-only comparison | 2026-07-26 |
| Preflight read-only before selecting the execution adapter | The remote tool and capacity boundary is drift-prone, and unrelated workloads must remain outside scope | Assuming Podman/Docker/Scout availability or free capacity | 2026-07-26 |
| Refuse Docker Scout credentials not already authorized for this work package | The standalone Linux CLI requires Docker login for CVE data. Copying a host credential, creating an account, or retaining a token would cross the explicit secret and publication boundary | Copying Docker Desktop credentials; interactive device login; fabricating an empty Scout result; silently replacing Scout with Trivy | 2026-07-26 |
| Probe Scout CVE capability before any expensive image build and contain its cache under the disposable work root | The native build completed twice before the credential dependency became visible, and the default standalone cache escaped the harness cleanup boundary | Repeating image builds before capability discovery; relying on a persistent user cache | 2026-07-26 |

## Tasks

- [x] Inventory the approved nested runner read-only and select the smallest
      isolated execution adapter.
- [x] Implement and fixture-test only the platform boundary needed for native
      Linux execution.
- [ ] Run the x86_64 build/runtime/scan/qualification transaction and verify
      exact cleanup.
- [ ] Compare ARM64/x86_64 evidence, run final gates, update the handoff, and
      publish the atomic milestone.

## Progress Log

### 2026-07-26 — Work package activated

- Completed: Closed plan 0021 at pushed commit `031ac16` and opened a separate
  native x86_64 gate rather than extending ARM64 evidence beyond its scope.
- Evidence: ARM64 produced zero Coffer Critical/High delta and zero secrets,
  while inherited dashboard parent findings kept the result `blocked`.
- Changed files: This plan and `.codex/state/HANDOFF.md`.
- Next exact action: Use the approved nested SSH route for a read-only
  architecture, capacity, OS, container-engine, scanner, source, and workload
  preflight. Do not create or modify a VM, package, service, network, or file.

### 2026-07-26 — Shared-host boundary and disposable runner accepted

- Completed: The approved address resolves directly to the shared `bb00`
  libvirt host rather than a separate guest. Direct Docker execution was
  rejected because 18 unrelated containers and 18 active VMs are present.
  Read-only inventory proved native x86_64, 64 host CPUs, about 128 GiB
  available memory, an active default NAT network, and about 936 GiB available
  in the existing Coffer libvirt pool. The fixed candidate domain and its two
  exact volumes are absent.
- Adapter: Added a fixed-name 8-vCPU, 24-GiB, 120-GiB disposable VM lifecycle.
  It accepts only a bounded ephemeral Ed25519 public key, verifies the official
  Ubuntu Noble cloud-image checksum signature and exact accepted AMD64 digest,
  refuses existing state, disables autostart, and destroys only the exact
  domain/root/seed identities. No shared-host package, Docker workload, port,
  service, network, or unrelated volume is selected.
- Native harness: Added Linux Podman API service lifecycle and an exact
  two-wheel input contract, preserving the same plan 0021 collector,
  classifier, scanner, and cleanup semantics.
- Evidence: Bash syntax, ShellCheck, 22 focused tests, diff checks, and a live
  read-only lifecycle `status` pass with domain/root/seed all absent.
- Changed files: `poc/ui-images/qualify.sh`,
  `poc/ui-images/libvirt_x86_runner.sh`, focused tests, this plan, and the
  handoff.
- Next exact action: Commit and push the bounded runner adapter, generate one
  owner-only ephemeral local SSH key, then invoke only the versioned `create`
  action on the shared host.

### 2026-07-26 — Native build proved; Scout CVE gate blocked and runner removed

- Completed: Created only the fixed, non-autostart
  `coffer-ui-x86-qualification-1` VM with 8 vCPU, 24 GiB RAM, and a 120-GiB
  root volume. The official Ubuntu Noble checksum signature verified under the
  Ubuntu cloud-image keyring. The live signed manifest had advanced from the
  initially recorded digest, so the accepted AMD64 digest was corrected to
  `d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac`
  before the image was accepted.
- Inputs: The guest consumed Coffer `ad8a4fa`, Kolla `686c6d1`, Horizon
  `0a44395` with exact `25.7.3` tag metadata, Skyline `c9000cb`, the two
  previously qualified wheels, uv 0.11.32, Podman 4.9.3 with Python client
  5.6.0, Docker Scout 1.21.0, and the pinned Trivy image. Both wheel SHA-256
  values matched the ARM64 transaction.
- Native evidence: Stock Kolla Horizon and Skyline Console parents plus both
  Coffer derivatives built on Linux AMD64. The collector produced matching
  manifest, image/layer, and runtime evidence; the first Scout SPDX operation
  indexed 641 Horizon-parent packages.
- Failures: The first transaction exposed a missing rootless
  `slirp4netns` dependency only when Trivy attempted its database download.
  After adding that disposable-guest dependency, a clean repeat passed both
  Trivy database downloads and stopped at `docker scout cves`: the standalone
  Linux CLI requires Docker login even for a local archive or SPDX input.
  Official offline mode does not remove that authentication requirement.
  No Docker credential was copied, created, requested, or retained, and no
  empty Scout report was synthesized.
- Harness correction: Docker Scout CVE capability is now probed before Kolla
  builds and its cache is forced under the bounded work directory, where the
  existing failure cleanup removes it. A focused regression protects the
  ordering and cache boundary.
- Cleanup: Both failed transactions removed all bounded Podman images,
  containers, scan archives, and Trivy cache. Owner-only partial non-secret
  evidence was copied to ignored local `work/`; the fixed VM, root/seed
  volumes, host runner temp path, local private/public SSH key, and known-host
  state were then removed. Before/after hashes match for all 18 unrelated
  domains, three unrelated Coffer pool volumes, the default network XML, 18
  Docker container IDs, and all Docker image IDs.
- Next exact action: Run the complete local repository gates, update the
  durable handoff, and commit/push this honest blocked milestone. Do not retry
  Scout or handle a Docker credential inside this work package.

### 2026-07-26 — Blocked milestone regression complete

- Verification: Bash syntax and strict ShellCheck pass for both changed
  runners; 23 focused UI qualification/collector tests and all 1,478 Python
  tests pass. Horizon passes its pinned baseline, 36 tests, and compilation;
  the companion Kolla role passes 108 checks; Skyline source, production
  bundle, and wheel verification pass.
- Repository safety: Python compilation, focused Ruff E/F/I for the changed
  Python file, warning-or-higher ShellCheck for every tracked shell file,
  Gitleaks, diff checks, 107 balanced Markdown files, and all 58 local
  links/images pass. A non-baseline whole-repository Ruff style probe reported
  existing import/line-format findings and the known explicit secret-lifetime
  `del` flow in `token_api.py`; no unrelated formatting change was made.
- Completion boundary: The implementation and cleanup milestone is ready for
  atomic publication, but the plan remains `blocked` because canonical Docker
  Scout CVE evidence and ARM64/AMD64 comparison cannot be completed without
  separately authorized Docker authentication.
- Next exact action: Commit and push this file set under the verified
  `jaehanbyun` GitHub account, then activate an independent Stage 6 work
  package.

## Verification

| Check | Command or method | Result |
|---|---|---|
| ARM64 predecessor and Git boundary | plan 0021 result; local/remote SHA | passed; `031ac16`, terminal `blocked` |
| Native x86_64 runner preflight | approved direct read-only SSH route and libvirt inventory | passed; shared host rejected as workload target, isolated VM boundary available |
| Linux/libvirt adapter | Bash/ShellCheck, 22 focused tests, live read-only status | passed; exact candidate absent |
| Native x86_64 qualification | versioned harness | blocked after native build/runtime/SPDX; standalone Scout CVE requires Docker login |
| Exact remote cleanup | bounded before/after inventory | passed; fixed VM/volumes/key/temp state absent and unrelated hashes equal |
| Full repository gates | focused/full tests, docs, secret, diff | passed; 23 focused, 1,478 full, Horizon 36, Kolla 108, 107 Markdown, 58 local links |

## Failures, Blockers, and Risks

- Docker Scout 1.21.0 CVE evidence cannot be generated by the standalone Linux
  CLI without Docker login. This work package has no authorization to copy,
  create, or retain that credential, and Trivy cannot silently replace the
  accepted two-scanner contract.
- Stock parent Critical/High findings are expected to remain absolute blockers
  even if Coffer introduces none.
- A native x86_64 success still does not release, sign, deploy, or promote the
  UI images and cannot bypass plan 0019.

## Handoff

- Current state: Plan 0021 is complete and pushed. Plan 0022 proved the native
  AMD64 image/runtime path but is honestly blocked at the Docker Scout CVE
  credential boundary. The disposable guest and every key/runtime identity are
  absent, and unrelated host hashes equal the preflight.
- Exact next action: Publish the plan 0022 blocked result, then continue a
  Stage 6 task independent of Docker Scout credentials.
- First file or command: Inspect the final diff, stage exactly the five changed
  files, and run the staged secret check.
- Questions requiring user input: None. The user authorized autonomous
  milestone pushes and continuation; external image publication and live cloud
  deployment remain excluded. Docker credential handling is not authorized and
  is not required for the independent next package.
