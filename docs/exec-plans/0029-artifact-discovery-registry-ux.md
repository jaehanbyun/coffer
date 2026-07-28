---
title: "Artifact discovery and registry UX"
status: active
updated: 2026-07-28
owner: primary-agent
---

# Objective

Extend Coffer's project-scoped repository control surface into a useful OCI
content browser. A user who opens a repository in Horizon or Skyline must be
able to discover pushed images and other admitted OCI manifests by tag or
digest, inspect safe immutable metadata, copy pull references, and open a
credential-safe connection guide for Docker, Podman, Helm, and ORAS. The two
dashboards consume one Keystone-authorized Coffer API and never query
Distribution, SQL, or the selected object-storage backend directly.

## Done Criteria

- [ ] A versioned migration adds a durable, bounded artifact/tag projection
      that is updated by manifest admission and reconciliation without changing
      the accepted quota accounting model.
- [ ] Existing repository `immutable_tags` is enforced atomically before a tag
      can move to another digest; digest pushes and idempotent same-digest tag
      pushes remain valid.
- [ ] Project-scoped APIs list and show repository artifacts with stable JSON,
      keyset pagination, tag/digest search, media/artifact type, logical size,
      push time, tags, freshness, and safe 400/401/403/404/409/503 behavior.
- [ ] The OpenAPI document, Python client, OpenStackClient commands, Horizon
      adapter, and Skyline client validate the exact same public contract.
- [ ] Horizon and Skyline repository detail pages expose an `Images &
      Artifacts` surface with tag, pushed time, type, size, digest, copyable
      pull reference, search, loading, empty, permission, and dependency-error
      states.
- [ ] Both dashboards expose a `How to connect` guide with Docker, Podman,
      Helm, and ORAS tabs. Commands are generated from the catalog endpoint,
      current project and selected repository, use application credentials
      through stdin or the existing `openstack registry login` command, and
      never render a secret.
- [ ] Desktop and narrow layouts, keyboard focus, dialog semantics, copy
      feedback, non-color-only status, and long digest/repository overflow pass
      visual and interaction QA against the supplied Nebius reference flow.
- [ ] Docker, Podman, Helm, and ORAS content pushed through the retained
      preview appears in both dashboards; project isolation, immutable-tag
      conflict, restart persistence, pagination/search, pull-by-tag, and
      pull-by-digest pass.
- [ ] Focused checks, complete repository regression, Kolla companion-role
      verification, secret scan, diff inspection, and durable handoff pass.

## Non-goals

- Vulnerability scanning, signing verification, retention/lifecycle mutation,
  replication, public repositories, repository or artifact deletion, tag
  creation/deletion outside an OCI manifest push, and administrator quota
  mutation.
- Direct browser access to Distribution, RGW/S3, Swift, SQL, registry JWTs, or
  application-credential material.
- Claiming Stage 6 production promotion, weakening plan 0019 release gates, or
  treating the retained same-host preview as production evidence.
- Cloning Nebius branding, navigation, resource hierarchy, or cloud-specific
  credential helper. Its screenshots are a product-flow reference only.

## Context and Evidence

- Plan 0020 completed repository create/list/detail and quota in both
  dashboards and explicitly deferred tag/manifest browsing.
- Plan 0028 completed a same-origin `/v1`, `/auth/token`, and `/v2` endpoint,
  OpenStackClient endpoint discovery/login, and a retained non-production
  preview.
- The current public OpenAPI exposes only endpoint discovery, repositories,
  and quota. The quota ledger records committed manifest digests and descriptor
  graphs, but does not retain tag, media type, user-facing artifact metadata,
  or an artifact-list contract.
- The supplied Nebius reference shows the required minimum interaction:
  repository contents grouped by repository name, tag-or-digest search, a
  table with tags, created/pushed time, type, size, and digest, plus a copyable
  Docker/Helm connection dialog.
- OCI tags are mutable pointers to a manifest digest. One digest may have zero,
  one, or many tags; the UI therefore uses digest-addressed artifacts as its
  stable row identity and treats tags as attributes.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Keep plan 0019 fail-closed and run this as independent plan 0029 | UI discovery is useful and locally testable while signed Distribution/Ceph release inputs remain external blockers | Marking UI work as Stage 6 production evidence; waiting for release inputs before any product work | 2026-07-28 |
| Use a Coffer-owned SQL projection updated from non-bypassable manifest admission and repaired by reconciliation | Both dashboards need bounded, project-authorized queries independent of storage backend and registry implementation details | Horizon/Skyline calling `/v2` directly; listing RGW/S3 or Swift objects; parsing Distribution storage layout in the browser | 2026-07-28 |
| Model one row per manifest digest and zero-or-more tags | This matches OCI identity and supports untagged manifests, tag movement, and multi-tag digests | Treating `name:tag` as an immutable image identity; showing raw blobs/layers as top-level images | 2026-07-28 |
| Reuse the existing single-origin catalog endpoint and finite application-credential login contract | Commands stay deployer-correct and do not invent a second authentication mechanism | Hard-coded registry hosts; rendering a secret; a Nebius-specific credential helper | 2026-07-28 |
| Match the reference information hierarchy while retaining Horizon and Skyline design systems | Users get a familiar flow without creating a third visual system or copying another provider's branding | Pixel-cloning Nebius; replacing native dashboard navigation and components | 2026-07-28 |

## Tasks

- [ ] Specify and migrate the artifact/tag projection, including tag
      immutability and reconciliation behavior.
- [x] Add API resources, policies, OpenAPI schemas, client methods, CLI
      commands, bounded metrics, and tests.
- [ ] Extend Horizon's server-side adapter and repository detail UI.
- [ ] Extend Skyline's source overlay, stores, routes/components, locales, and
      tests.
- [ ] Extend immutable UI images and Kolla artifact/config verification.
- [ ] Run local visual/interaction QA at desktop and narrow viewports and close
      all P0/P1/P2 findings.
- [ ] Deploy to the retained preview, run the real-client and two-project
      acceptance matrix, and inspect both dashboards.
- [ ] Run final regression and security checks; update this plan and
      `HANDOFF.md`; commit and push atomic milestones.

## Progress Log

### 2026-07-28 — Work package activated from the supplied reference flow

- Completed: Recovered the clean `a6330aa` repository, plan 0019's external
  release boundary, completed UI and endpoint plans, current API/schema, both
  dashboard implementations, and the supplied Nebius Images and connection
  dialog states.
- Evidence: Current OpenAPI paths are `/`, `/repositories`,
  `/repositories/{repository_id}`, and `/quota`; plan 0020 explicitly excluded
  tag/manifest browsing; the admission path sees the exact manifest reference
  and body before the sole Distribution write.
- Decision: Add one storage-independent Coffer projection and public API, then
  consume it from both existing dashboard integrations. Preserve plan 0019 and
  all secret and production boundaries.
- Changed files: This plan and `.codex/state/HANDOFF.md`.
- Next exact action: Add migration
  `src/coffer/migrations/versions/0007_artifact_projection.py` and the matching
  SQLAlchemy tables/dataclasses in `src/coffer/artifacts.py`, beginning with
  fixture-driven store tests before changing manifest admission.

### 2026-07-28 — Artifact projection, admission, and public API completed

- Completed: Added migration 0007, the bounded digest-addressed artifact/tag
  projection, expiring tag claims, atomic immutable-tag enforcement, manifest
  kind/artifact-type classification, logical-size recording, project-scoped
  list/search/show APIs, OpenAPI, OpenStackClient methods and commands, and
  bounded observability routes.
- Correctness: A tag is claimed before the only Distribution manifest write.
  Conflicting concurrent writes retry; immutable movement returns a stable
  Distribution error before forwarding; accepted content commits quota then
  projection; failed or indeterminate writes cannot appear as committed
  artifact rows.
- Evidence: Migration/store/admission/API/OpenAPI/client and observability
  focused suites pass 107 checks. The first complete repository run found one
  intentionally versioned observability route allowlist that still described
  the pre-artifact API; the matching contract was extended and its focused
  regression passes. The corrected complete repository run passes 1,867 tests.
- Changed files: Migration/schema, `src/coffer/artifacts.py`, manifest
  admission, control API/policy/metrics, OpenAPI, client/OSC, tests, runbook,
  this plan, and `.codex/state/HANDOFF.md`.
- Remaining repair boundary: A separately authenticated repository
  reconciliation pass must rebuild projection rows for content that predates
  migration 0007 or remains indeterminate after an accepted upstream write.
- Next exact action: Extend `ui/horizon/cofferdashboard/api/coffer.py` with
  exact artifact page/detail and endpoint validation, then add adapter tests
  before changing views or templates.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Repository recovery | `git status --short`; recent log; handoff and active-plan inspection | passed; clean at `a6330aa` |
| Current API inventory | OpenAPI path enumeration and source inspection | passed; no artifact/tag public API |
| Current dashboard boundary | Plan 0020 and Horizon/Skyline source inspection | passed; repository/quota only |
| Reference flow inventory | Supplied Nebius screenshots and accessibility tree | passed; images table, search, connection dialog, Docker/Helm examples |
| Artifact/API complete regression | `uv run --extra client pytest -q` | passed; 1,867 |
| Full implementation and visual QA | pending | pending |

## Failures, Blockers, and Risks

- The saved Product Design context is absent; the user-supplied screenshots and
  existing Coffer design systems are sufficient grounding for this work.
- Stage 6 remains blocked on signed upstream release inputs. No result from
  this plan may promote or relabel that gate.
- The artifact projection must remain repairable because Distribution accepts
  the manifest before Coffer can know the final commit outcome. Reconciliation
  must not present indeterminate writes as current content.
- The existing `immutable_tags` option is now enforced by manifest admission.
  The retained preview still runs the earlier image until plan 0029 deployment.

## Handoff

- Current state: Active; artifact projection, admission enforcement, public
  API, OpenAPI, client, and focused verification complete locally.
- Exact next action: Implement and test the Horizon artifact adapter contract.
- First file or command: `ui/horizon/cofferdashboard/api/coffer.py`
- Questions requiring user input: None.
