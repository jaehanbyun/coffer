---
title: "Native x86_64 UI image qualification"
status: active
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
- [ ] The runner consumes the exact committed Coffer source, Kolla/Horizon/
      Skyline revisions, Ubuntu AMD64 digest, wheel versions, and scanner pins;
      mutable/test-only parents and cross-architecture emulation are refused.
- [ ] Stock Horizon and Skyline Console parents plus both Coffer derivatives
      build natively and pass immutable provenance, inherited Kolla metadata,
      runtime package/file, build-input absence, and exact layer-prefix gates.
- [ ] SPDX, Docker Scout, and Trivy vuln/secret evidence yields a canonical
      native x86_64 qualification result with explicit absolute and
      parent/custom delta findings.
- [ ] The ARM64 and x86_64 dispositions are compared without waiving inherited
      findings. Any architecture-specific Coffer Critical/High delta or secret
      remains a production blocker.
- [ ] Exact remote Coffer images, containers, archives, scanner cache, work
      state, and temporary source material are removed. No image, evidence,
      signature, credential, or deployment is published.
- [ ] Focused and repository regression, documentation, secret, and diff gates
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

## Verification

| Check | Command or method | Result |
|---|---|---|
| ARM64 predecessor and Git boundary | plan 0021 result; local/remote SHA | passed; `031ac16`, terminal `blocked` |
| Native x86_64 runner preflight | approved direct read-only SSH route and libvirt inventory | passed; shared host rejected as workload target, isolated VM boundary available |
| Linux/libvirt adapter | Bash/ShellCheck, 22 focused tests, live read-only status | passed; exact candidate absent |
| Native x86_64 qualification | versioned harness | pending |
| Exact remote cleanup | bounded before/after inventory | pending |
| Full repository gates | focused/full tests, docs, secret, diff | pending |

## Failures, Blockers, and Risks

- The runner may lack Docker Scout or enough disposable disk. Selection of a
  different scanner or an outer-host installation would change the evidence
  contract and is not implied.
- Stock parent Critical/High findings are expected to remain absolute blockers
  even if Coffer introduces none.
- A native x86_64 success still does not release, sign, deploy, or promote the
  UI images and cannot bypass plan 0019.

## Handoff

- Current state: Plan 0021 is complete and pushed. Plan 0022 has a verified
  shared-host exclusion and fixed disposable-VM lifecycle; no remote mutation
  has occurred.
- Exact next action: Publish the adapter milestone, then create only the fixed
  disposable candidate with one ephemeral owner-only SSH key.
- First file or command: Stage, secret-scan, commit, and push the plan 0022
  adapter file set.
- Questions requiring user input: None. The user authorized autonomous
  milestone pushes and continuation; external image publication and live cloud
  deployment remain excluded.
