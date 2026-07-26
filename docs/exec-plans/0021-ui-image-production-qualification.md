---
title: "Horizon and Skyline UI image production qualification"
status: active
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

- [ ] One versioned harness builds only from the accepted Kolla, Horizon, and
      Skyline revisions plus pinned Ubuntu platform input and exact wheel
      hashes; mutable parent tags and Quay test images are rejected.
- [ ] Stock Horizon and Skyline Console parents and their Coffer derivatives
      are built on the native architecture with immutable digests and required
      OCI/Coffer labels.
- [ ] Runtime inspection proves the exact package versions and dashboard
      registration/bundle files, inherited Kolla users/entry points, absence
      of build wheels/installers, and no unexpected credential material.
- [ ] SPDX SBOM, vulnerability, and secret evidence compares each custom image
      with its exact parent and rejects any newly introduced Critical/High
      finding or secret; unresolved parent findings remain an explicit
      production block rather than being waived.
- [ ] A canonical non-secret qualification result binds architecture, source
      revisions, wheel hashes, parent/custom digests, scanner versions, and
      gate disposition; schema, evidence, cleanup, and repository checks pass.
- [ ] Exact local images, containers, and temporary mounts are removed after
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
- The local Podman machine is currently stopped and provides native ARM64
  execution only. Starting it is a reversible local build prerequisite, not
  deployment evidence.
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

- [ ] Inventory and fix the exact Kolla parent build, wheel materialization,
      runtime, scanner, provenance, and cleanup contracts.
- [x] Implement fixture-driven evidence verification before running a
      container engine.
- [ ] Run the native ARM64 build and qualification transaction, diagnose and
      correct bounded failures, and retain only ignored non-secret evidence.
- [ ] Run focused and repository regression, update operator documentation and
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

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 6 upstream release boundary | `make -C poc/production-images check-upstream` | passed; valid `blocked` result |
| Git recovery | `git status --short --branch`; recent log | passed; clean at `54368ec`, equal to `origin/main` |
| Kolla parent provenance | Pinned source and Kolla-Ansible test-image precheck inspection | passed; local exact-source parent build required |
| UI image evidence verifier | `uv run pytest -q tests/test_ui_image_qualification.py` | passed; 8 |
| Verifier source quality | Python compilation; Ruff E/F/I | passed |
| Post-verifier full regression | `uv run pytest -q` | passed; 1463 |
| Post-verifier document/link and diff gate | Tracked/new project Markdown validator; `git diff --check` | passed; 106 files, 58 links/images |
| Native ARM64 build/runtime/scan transaction | UI image qualification harness | pending |
| Full repository regression and hygiene | Project gates | pending |

## Failures, Blockers, and Risks

- Distribution and Ceph stable-release gates still prevent final Stage 6
  promotion and the fresh multinode pilot.
- Horizon and Skyline parents may themselves contain unresolved
  Critical/High findings. Those findings must remain visible and block
  production qualification even if the Coffer delta introduces none.
- The retained Podman VM has 3.7 GiB memory. The harness must serialize Kolla
  builds and scans and fail cleanly on resource exhaustion.
- A successful ARM64 transaction does not close the required native x86_64
  matrix or any live Kolla/browser acceptance criterion.

## Handoff

- Current state: Plan 0020 is complete locally. Plan 0019 is externally
  blocked. Plan 0021's pure evidence verifier is complete; no container engine
  has been started for this package.
- Exact next action: Add `poc/ui-images/qualify.sh` and pinned build inputs,
  then build the two stock Kolla parents and custom images serially.
- First file or command: Add the engine transaction beginning at
  `poc/ui-images/qualify.sh`.
- Questions requiring user input: None. Git milestone pushes are authorized;
  image publication, signing, remote deployment, and release gates remain
  excluded and fail closed.
