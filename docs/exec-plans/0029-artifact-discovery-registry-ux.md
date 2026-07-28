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

- [x] A versioned migration adds a durable, bounded artifact/tag projection
      that is updated by manifest admission and reconciliation without changing
      the accepted quota accounting model.
- [x] Existing repository `immutable_tags` is enforced atomically before a tag
      can move to another digest; digest pushes and idempotent same-digest tag
      pushes remain valid.
- [x] Project-scoped APIs list and show repository artifacts with stable JSON,
      keyset pagination, tag/digest search, media/artifact type, logical size,
      push time, tags, freshness, and safe 400/401/403/404/409/503 behavior.
- [x] The OpenAPI document, Python client, OpenStackClient commands, Horizon
      adapter, and Skyline client validate the exact same public contract.
- [x] Horizon and Skyline repository detail pages expose an `Images &
      Artifacts` surface with tag, pushed time, type, size, digest, copyable
      pull reference, search, loading, empty, permission, and dependency-error
      states.
- [x] Both dashboards expose a `How to connect` guide with Docker, Podman,
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
| Accept an omitted manifest JSON `mediaType` only when a supported request `Content-Type` supplies it | OCI image-spec defines the JSON field as SHOULD rather than REQUIRED, and Helm 4 emits a valid chart manifest without it; quota still needs one unambiguous supported type | Rejecting Helm 4; guessing from shape when both sources are absent; accepting a header/body mismatch | 2026-07-28 |

## Tasks

- [x] Specify and migrate the artifact/tag projection, including tag
      immutability and reconciliation behavior.
- [x] Add API resources, policies, OpenAPI schemas, client methods, CLI
      commands, bounded metrics, and tests.
- [x] Extend Horizon's server-side adapter and repository detail UI.
- [x] Extend Skyline's source overlay, stores, routes/components, locales, and
      tests.
- [x] Extend immutable UI images and Kolla artifact/config verification.
- [ ] Run local visual/interaction QA at desktop and narrow viewports and close
      all P0/P1/P2 findings.
- [x] Deploy to the retained preview, run the real-client and two-project
      acceptance matrix, and inspect both dashboards.
- [x] Run final regression and security checks; update this plan and
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

### 2026-07-28 — Horizon artifact browser and connection guide completed

- Completed: Extended the Horizon server-side adapter with strict
  project/repository artifact validation, bounded tag/digest search and
  pagination, artifact detail, and a credential-free catalog-derived registry
  host. The repository detail page now provides native `Images & Artifacts`
  and `Details` tabs, metadata rows, search, empty/dependency/permission states,
  long-value overflow, pull-reference and digest copy actions, and a responsive
  layout.
- Connection UX: Added one accessible native modal with Docker, Podman, Helm,
  and ORAS tabs. Every example is generated from the current catalog,
  project, and repository. Login uses the existing `openstack registry login`
  hidden-secret prompt and never renders a token, password, or application
  credential secret. Helm deliberately reuses Docker's registry credential
  store.
- Packaging: Registered the focused JS/SCSS assets through Horizon's standard
  pluggable-panel settings and included them in the independently installable
  wheel. Added artifact policy metadata and updated the plugin boundary
  documentation.
- Evidence: The exact Horizon 25.7.3 baseline and all 47 plugin tests pass;
  Python compilation, JS syntax, diff checks, a clean wheel build, and exact
  static/template wheel membership pass.
- Changed files: Horizon adapter, view/template, policy metadata, native
  JS/SCSS, package configuration, tests, README, this plan, and handoff.
- Next exact action: Extend
  `ui/skyline/overlay/src/client/coffer/index.js` with the exact artifact
  contract, then add Skyline store methods before changing the repository
  detail page.

### 2026-07-28 — Skyline artifact browser and connection guide completed

- Completed: Added exact artifact page/detail and endpoint-discovery validators,
  a race-safe artifact store, bounded keyset navigation, safe presentation
  helpers, and a native Skyline repository-detail tab. The table exposes
  tag/digest search, tags, pushed time, OCI type/media type, logical size,
  digest, and a copyable catalog-derived pull reference with explicit loading,
  empty, permission, dependency, and invalid-endpoint states.
- Connection UX: Added one native Ant Design dialog with Docker, Podman, Helm,
  and ORAS tabs. Commands are derived only after same-origin HTTPS endpoint
  validation, use `openstack registry login` instead of rendering credentials,
  and disable the guide when a safe host/reference cannot be constructed.
- Correctness: Request sequencing prevents stale responses from overwriting a
  newer repository/search page. Artifact and endpoint payloads reject unknown
  fields, invalid digests, unsafe tags, cross-origin service paths, malformed
  pagination markers, and inconsistent tag counts.
- Evidence: The exact pinned Skyline Console `stable/2026.1` source passes
  materialization, locale generation, focused ESLint, all 45 Coffer Jest
  tests, production Webpack bundle, versioned wheel construction, bundle/wheel
  content verification, Python compilation, and diff checks. The final test
  addition changed test source only after the successful production
  bundle/wheel verification.
- Changed files: Skyline client/store/resources, repository-detail route and
  native components/styles, tests, verifier, Makefile, README, this plan, and
  handoff.
- Next exact action: Extend and verify the immutable Horizon/Skyline image and
  Kolla companion-role contracts for the plan 0029 API migration and dashboard
  assets before changing the retained preview.

### 2026-07-28 — Immutable preview delivery contracts completed

- Completed: Rebuilt the exact Horizon and Skyline wheels, pinned their new
  SHA-256 values in the retained-preview bootstrap contract, and added an
  independent Horizon refresh transaction matching the existing Skyline
  transaction. Each refresh verifies its wheel, builds and pushes only its
  dashboard image, writes an immutable image contract, and atomically updates
  only its own companion global while preserving the other dashboard and all
  Coffer runtime images.
- Evidence: Both wheel digests were calculated from the locally verified
  outputs. Bash syntax, warning-or-higher ShellCheck, 40 focused Kolla runtime,
  image-contract, and runtime-collector tests, and diff checks pass.
- Changed files: Retained-preview image bootstrap and dashboard refresh
  scripts, preview runbook, Kolla runtime contract tests, this plan, and
  handoff.
- Next exact action: Synchronize commit `5ac6c90` plus the new delivery
  transaction to the retained guest, stage only the two verified wheels,
  rebuild Coffer/Horizon/Skyline images, run migration 0007 through companion
  `reconfigure`, and verify service health before pushing fresh OCI content.

### 2026-07-28 — Retained deployment activated; Helm 4 compatibility fixed

- Completed: Synchronized the reviewed source and only the two verified wheels,
  built new Coffer/Horizon/Skyline images, ran the Kolla companion
  `reconfigure`, restarted the bounded same-host replica, and verified healthy
  services, exact image digests, dashboard assets, public HTTP 200 responses,
  and Alembic revision `0007_artifact_projection`.
- Client evidence: Fresh Docker, Podman, and ORAS push/pull passed through the
  owner endpoint, including project-B read/write denial and primary-pair
  outage. The prior evidence was preserved in an owner-only history directory
  and the new result remains mode 0600.
- Failure found: Helm 4.2.3 sent the supported OCI manifest media type in the
  HTTP `Content-Type` while omitting the optional top-level JSON `mediaType`.
  Coffer returned a bounded 400 before Distribution. The OCI image
  specification defines this JSON field as SHOULD and requires the declared
  value only when it is present, so the admission parser was stricter than the
  standard.
- Correction: Resolve the manifest type from a supported `Content-Type` when
  the JSON field is absent, still rejecting absence from both sources,
  non-string JSON values, unsupported types, and header/body mismatches.
  Thirty-four focused parser/admission tests pass, including the exact
  Helm-shaped manifest.
- Changed files: Manifest parser, parser/admission tests, this plan, and
  handoff.
- Next exact action: Commit and redeploy the compatibility correction, repeat
  real Helm push/pull, then query the project-scoped artifact API before
  browser QA.

### 2026-07-28 — Real artifact discovery and executable guides accepted

- Completed: Redeployed the standards-compatible admission parser and passed
  real Helm 4.2.3 push and pull. Added a bounded owner-only acceptance command
  that acquires both project tokens through stdin, queries only the public
  project-scoped API, and retains a secret-free mode-0600 result.
- API evidence: The retained repository projects four digest rows and all
  Docker, Podman, ORAS, failover, and Helm tags. Tag search, artifact detail,
  keyset pagination, Helm media-type classification, and project-B 404 denial
  pass.
- Guide correction: Helm does not share the Docker command shape and appends
  the chart name to the push target. `openstack registry login` now supports
  `--client helm` through `helm registry login`; both dashboards create a chart
  named after the repository's final path segment and push it to the parent
  OCI namespace. This makes the displayed command resolve to the selected
  Coffer repository instead of an unauthorized nested repository.
- Packaging evidence: Horizon's exact 47-test baseline and wheel build pass.
  Skyline's exact 45-test, ESLint, locale, production bundle, and wheel
  verification pass. Both replacement wheels have new pinned SHA-256 inputs
  in the bounded refresh transactions.
- Next exact action: Commit and push the executable-guide milestone, stage only
  the two pinned wheels on the retained guest, refresh Horizon and Skyline,
  and verify the deployed bundles and artifact API before final regression.

### 2026-07-28 — Corrected dashboard images deployed

- Completed: Pushed commit `33ae727`, staged only the two hash-pinned wheels,
  independently refreshed Horizon and Skyline, and ran the Kolla companion
  reconfigure transaction. It completed with `ok=117`, `changed=9`, zero
  unreachable and zero failed.
- Runtime evidence: Horizon is healthy on
  `sha256:528c6fe5443624660297f0f7f160f307070ea3820aaa0f01adfd0da4a82b24a5`;
  Skyline is healthy on
  `sha256:5e2519a8ac51f9b301ba3c38c3c2bb4232a4bd549b34e4405eef96d5210b2082`.
  The public Horizon login redirect, Skyline page, and registry authentication
  challenge return their expected 302, 200, and 401 responses.
- Deployed-content evidence: The Horizon template and Skyline production
  bundle contain the dedicated Helm login and corrected chart commands. The
  project-scoped artifact acceptance reran after replacement and again passed
  with four rows and project-B denial.
- Boundary: No credential was moved into a browser automation session. Live
  authenticated visual comparison remains an owner-session QA item; exact
  adapters, interaction tests, packages, deployed assets, runtime health, and
  API data are verified.
- Next exact action: Have the owner inspect the retained authenticated desktop
  and narrow states against the supplied reference; record any visible P0/P1/P2
  discrepancy before closing plan 0029.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Repository recovery | `git status --short`; recent log; handoff and active-plan inspection | passed; clean at `a6330aa` |
| Current API inventory | OpenAPI path enumeration and source inspection | passed; no artifact/tag public API |
| Current dashboard boundary | Plan 0020 and Horizon/Skyline source inspection | passed; repository/quota only |
| Reference flow inventory | Supplied Nebius screenshots and accessibility tree | passed; images table, search, connection dialog, Docker/Helm examples |
| Artifact/API complete regression | `uv run --extra client pytest -q` | passed; 1,867 |
| Horizon exact baseline and plugin suite | `make -C ui/horizon verify` | passed; Horizon 25.7.3 and 47 tests |
| Horizon package assets | `uv build --project ui/horizon --out-dir work/horizon-dist`; wheel membership inspection | passed |
| Horizon focused JS/diff checks | `node --check .../registry-detail.js`; `git diff --check` | passed |
| Skyline exact source and focused suite | clean materialization; locale; ESLint; focused Jest | passed; 45 tests |
| Skyline production package | Webpack build; wheel build; `ui/skyline/verify_build.py` | passed |
| Preview image delivery contracts | Bash syntax; ShellCheck; focused Kolla/image tests | passed; 40 tests |
| Retained image/migration activation | Kolla reconfigure; image/asset/schema/HTTP checks | passed |
| Fresh Docker/Podman/ORAS acceptance | retained endpoint v2 acceptance | passed |
| Helm 4 compatibility regression | focused quota parser/admission suite | passed; 34 tests |
| Retained artifact API acceptance | public API with project A/B application credentials | passed; 4 artifact rows, search/detail/keyset/Helm classification, project B 404 |
| Executable connection guides | client unit tests; exact Horizon and Skyline package builds | passed; dedicated Helm login and correct repository path |
| Corrected complete repository regression | `uv run --extra client pytest -q` | passed; 1,872 |
| Corrected retained dashboard rollout | bounded wheel refresh; Kolla companion reconfigure; runtime and asset probes | passed; `ok=117`, `changed=9`, zero failed; both dashboards healthy |
| Authenticated desktop/narrow visual comparison | owner browser session | pending; no credential entered into automation |

## Failures, Blockers, and Risks

- The saved Product Design context is absent; the user-supplied screenshots and
  existing Coffer design systems are sufficient grounding for this work.
- Stage 6 remains blocked on signed upstream release inputs. No result from
  this plan may promote or relabel that gate.
- The artifact projection must remain repairable because Distribution accepts
  the manifest before Coffer can know the final commit outcome. Reconciliation
  must not present indeterminate writes as current content.
- The existing `immutable_tags` option is enforced by manifest admission in
  the retained preview.

## Handoff

- Current state: Active only for authenticated desktop/narrow visual
  comparison. Artifact projection, admission enforcement, public
  API/OpenAPI/client, both Horizon and Skyline artifact browsers and executable
  connection guides, exact image delivery, retained deployment, real-client
  acceptance, and final repository regression are complete.
- Exact next action: Inspect the retained repository detail and connection
  dialog in the owner's authenticated browser session at desktop and narrow
  widths, recording only actionable P0/P1/P2 discrepancies.
- First file or command: Open the retained Horizon or Skyline address and
  select **Project → Registry → Repositories → preview-proof**.
- Questions requiring user input: None.
