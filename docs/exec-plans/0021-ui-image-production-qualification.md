---
title: "Horizon and Skyline UI image production qualification"
status: completed
updated: 2026-07-26
owner: primary-agent
---

# Objective

Turn the completed Horizon and Skyline package/container contracts into actual
immutable image evidence without weakening Stage 6. Build the stock dashboard
parents from the pinned Kolla 2026.1 source instead of consuming Quay test
images, layer the exact Coffer wheels onto those parents, verify runtime and
provenance contracts, generate vulnerability/secret/SBOM evidence, classify
the result fail closed, and remove all exact local runtime artifacts. Native
ARM64 is the first executable milestone; x86_64, signing, publication, and
live Kolla acceptance remain separate gates.

## Done Criteria

- [x] One versioned harness builds only from the accepted Kolla, Horizon, and
      Skyline revisions plus pinned Ubuntu platform input and exact wheel
      hashes; mutable parent tags and Quay test images are rejected.
- [x] Stock Horizon and Skyline Console parents and their Coffer derivatives
      are built on the native architecture with immutable digests and required
      OCI/Coffer labels.
- [x] Runtime inspection proves the exact package versions and dashboard
      registration/bundle files, inherited Kolla users/entry points, absence
      of build wheels/installers, and no unexpected credential material.
- [x] SPDX SBOM, vulnerability, and secret evidence compares each custom image
      with its exact parent and rejects any newly introduced Critical/High
      finding or secret; unresolved parent findings remain an explicit
      production block rather than being waived.
- [x] A canonical non-secret qualification result binds architecture, source
      revisions, wheel hashes, parent/custom digests, scanner versions, and
      gate disposition; schema, evidence, cleanup, and repository checks pass.
- [x] Exact local images, containers, and temporary mounts are removed after
      the run. No image, SBOM, attestation, signature, or credential is
      published.

## Non-goals

- Treating a native ARM64 run as x86_64 or multi-architecture evidence.
- Signing, pushing, releasing, or deploying an image to an external registry
  or OpenStack cloud.
- Using `quay.io/openstack.kolla` test images as production parents.
- Recreating the six-VM pilot, bypassing plan 0019's Distribution/Ceph release
  gate, or calling local image evidence production promotion.
- Generating a persistent signing key or modifying an operator credential,
  registry, Kolla deployment, or remote host.

## Context and Evidence

- Plan 0020 completed the wheel, Containerfile, public digest-contract, Kolla
  lifecycle, and local UI regression boundaries but built no custom image.
- Kolla-Ansible `stable/2026.1` explicitly classifies
  `quay.io/openstack.kolla` as test-only. The accepted parent must therefore be
  assembled from Kolla commit
  `686c6d13dc1c31092b22c6c481e16a7329e935ea`.
- The retained production-image harness already pins Ubuntu Noble platform
  manifests, drives Kolla's Podman builder, and generates Docker Scout, Trivy,
  secret, SPDX, provenance, and cleanup evidence. The UI harness should reuse
  its accepted patterns rather than inventing another scanner boundary.
- The local Podman machine provided native ARM64 execution for this work
  package. It remained attached to the required persistent PTY during the
  transaction and was stopped after verification.
- Plan 0019 remains externally blocked because Distribution v3.1.1 has no
  newer stable release and Ceph Tentacle v20.2.2 lacks the released
  encrypted-copy fix.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Build both stock dashboard parents from the pinned Kolla source | Kolla itself marks the public Quay namespace as test-only, while production evidence must bind exact source and Ubuntu platform inputs | Quay test image; mutable operator image; unrelated distro image | 2026-07-26 |
| Compare every custom image to its exact stock parent and retain both absolute and introduced findings | The Coffer wheel must not introduce risk, but inherited parent findings cannot be hidden or relabeled as qualified | Scan only the custom image; subtract findings without retaining the parent result; waive parent findings | 2026-07-26 |
| Execute native ARM64 first and keep x86_64 as a separate required gate | The available local engine is ARM64 and cross-emulation would not prove native runtime behavior | Calling a manifest-only or emulated build x86_64 runtime evidence | 2026-07-26 |
| Produce local evidence only | The user authorized Git milestone publication, not image, signature, SBOM, or credential publication | Push to GitHub Container Registry; keyless external signing; persistent local signing key | 2026-07-26 |

## Tasks

- [x] Inventory and fix the exact Kolla parent build, wheel materialization,
      runtime, scanner, provenance, and cleanup contracts.
- [x] Implement fixture-driven evidence verification before running a
      container engine.
- [x] Run the native ARM64 build and qualification transaction, diagnose and
      correct bounded failures, and retain only ignored non-secret evidence.
- [x] Run focused and repository regression, update operator documentation and
      handoff, and publish the atomic source milestone.

## Progress Log

### 2026-07-26 — Work package activated

- Completed: Recovered the clean `main` boundary at `54368ec`, rechecked the
  Stage 6 release classifier, and selected actual UI image supply-chain
  qualification as the next independent production milestone.
- Evidence: The classifier still reports Distribution v3.1.1 and Ceph
  Tentacle v20.2.2 as `blocked`. Kolla-Ansible's pinned source marks Quay
  `openstack.kolla` images test-only. The retained local Podman engine is
  stopped and native ARM64.
- Changed files: This plan and `.codex/state/HANDOFF.md`.
- Next exact action: Create `poc/ui-images/README.md` and
  `poc/ui-images/qualification.py` with a fixture-first canonical evidence
  schema and fail-closed parent/custom comparison before starting Podman.

### 2026-07-26 — Fixture-first qualification contract completed

- Completed: Added the canonical manifest, image-inspection, runtime,
  SPDX, Trivy, Docker Scout SARIF, parent/custom delta, terminal result, and
  owner-controlled evidence contracts before starting a container engine.
- Fail-closed behavior: Exact source revisions and actual wheel hashes are
  mandatory. Custom images must preserve parent user/entrypoint/cmd and exact
  layer ancestry. Runtime file hashes must match wheel members. Parent
  Critical/High findings remain blockers; introduced findings, findings
  missing from the custom scan, secrets, source/wheel/runtime tamper, and
  different-result overwrite all fail.
- Evidence: Eight focused fixture tests, Python compilation, and E/F/I checks
  pass. The full repository regression passes 1,463 tests. All 106 tracked or
  newly added Markdown files have balanced fences and all 58 local
  links/images resolve; diff checks pass.
- Corrected failure: The first document scan incorrectly traversed the ignored
  Horizon virtual environment and found one unrelated third-party README
  asset. The repository gate now scopes itself to Git-tracked plus explicitly
  new project documents.
- Changed files: `poc/ui-images/`, the focused tests, this plan, and the
  handoff.
- Next exact action: Add `poc/ui-images/qualify.sh` and its pinned build
  inputs. Materialize current Horizon/Skyline wheels, build stock parents from
  Kolla commit `686c6d1`, then collect the exact evidence consumed by the
  completed verifier.

### 2026-07-26 — Native ARM64 transaction completed and blocked honestly

- Completed: Added the serialized Kolla/Podman build, exact runtime collector,
  Docker Scout SPDX/SARIF, pinned Trivy database acquisition plus networkless
  vuln/secret scan, canonical qualification, and exact-exit cleanup harness.
  Built both stock parents and both Coffer derivatives from the pinned source
  and Ubuntu ARM64 digest. No image, evidence, signature, credential, or
  deployment was published.
- Evidence: Horizon parent/custom contain 641/642 SPDX packages; Skyline
  parent/custom contain 569/570. The Coffer delta is zero introduced and zero
  missing Critical/High findings under both Docker Scout and Trivy, and all
  four images have zero detected secrets. The terminal result is nevertheless
  `blocked`: the Horizon parent and custom each have Trivy 1 Critical/83 High
  and Scout 0 Critical/75 High; Skyline each have Trivy 1 Critical/68 High and
  Scout 0 Critical/60 High. Exact local UI images, scan archives, and scanner
  cache were removed. Owner-only ignored evidence remains under
  `work/ui-image-qualification/evidence/`.
- Corrected failures: The bounded transaction exposed and corrected use of
  Horizon's system Python instead of its venv, invalid wheel renaming, native
  Podman image-ID normalization, Docker Scout archive path handling, archive
  cleanup on failure, separate Trivy and Java database acquisition, writable
  scanner cache isolation, and an unnecessary `USER root` declaration that
  changed Horizon's inherited Kolla runtime metadata. The first complete
  result also showed that Trivy's archive filename is not a stable finding
  identity; the verifier now uses finding class/type with package/version
  identity and a regression proves parent/custom archive names compare
  correctly.
- Changed files: `poc/ui-images/`, both UI Containerfiles, qualification and
  collector tests, this plan, and the handoff.
- Next exact action: Run the same pinned qualification contract on a native
  x86_64 isolated runner, then remediate or replace the stock dashboard
  parents until their absolute Critical/High gate reaches zero.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 6 upstream release boundary | `make -C poc/production-images check-upstream` | passed; valid `blocked` result |
| Git recovery | `git status --short --branch`; recent log | passed; clean at `54368ec`, equal to `origin/main` |
| Kolla parent provenance | Pinned source and Kolla-Ansible test-image precheck inspection | passed; local exact-source parent build required |
| UI image evidence verifier and collectors | `make -C poc/ui-images verify` | passed; 20 |
| Verifier source quality | Python compilation; Ruff E/F/I | passed |
| Post-verifier full regression | `uv run pytest -q` | passed; 1463 |
| Post-verifier document/link and diff gate | Tracked/new project Markdown validator; `git diff --check` | passed; 106 files, 58 links/images |
| Native ARM64 build/runtime/scan transaction | `make -C poc/ui-images qualify` | completed; terminal `blocked`, zero Coffer Critical/High delta and zero secrets |
| Exact runtime cleanup | bounded image/archive/cache inspection | passed; zero exact UI image, tar archive, or scanner-cache residue |
| Full repository regression and hygiene | compile; Ruff E/F/I; Horizon/Skyline builds; Kolla role; `uv run pytest -q`; shell/docs/secret/diff gates | passed; 1,475 Python tests, Horizon 36, Skyline 31, Kolla 108 |

## Failures, Blockers, and Risks

- Distribution and Ceph stable-release gates still prevent final Stage 6
  promotion and the fresh multinode pilot.
- Horizon and Skyline parents may themselves contain unresolved
  Critical/High findings. The ARM64 run confirmed that they do, so those
  findings remain visible and block production qualification even though the
  Coffer delta introduces none.
- The retained Podman VM has 3.7 GiB memory. The serialized transaction
  completed without resource exhaustion and removed exact runtime residue.
- A successful ARM64 transaction does not close the required native x86_64
  matrix or any live Kolla/browser acceptance criterion.

## Handoff

- Current state: Plan 0021 is complete for native ARM64 and terminates
  correctly as `blocked`. Runtime/provenance/cleanup pass, the Coffer security
  delta is zero, and inherited stock-parent Critical/High findings prevent
  production qualification. Plan 0019 remains externally blocked.
- Exact next action: Create the native x86_64 qualification work package and
  inventory a bounded isolated x86_64 runner without deploying or publishing.
- First file or command: Read-only preflight of the approved isolated runner,
  then create the next execution plan from `docs/exec-plans/TEMPLATE.md`.
- Questions requiring user input: None. Git milestone pushes are authorized;
  image publication, signing, remote deployment, and release gates remain
  excluded and fail closed.
