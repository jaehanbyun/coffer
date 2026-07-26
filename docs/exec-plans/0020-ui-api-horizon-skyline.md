---
title: "Product API, Horizon, and Skyline integration"
status: active
updated: 2026-07-26
owner: primary-agent
---

# Objective

Make Coffer visible and useful from both supported OpenStack web interfaces
without coupling either UI to Coffer SQL, the private Distribution service, or
deployment-specific URLs. First freeze a project-scoped REST/OpenAPI contract,
then ship an independently installable Horizon dashboard and a reviewable
Skyline Console integration. Prove each surface against deterministic local
API fixtures and the supported upstream framework shape. Do not call either
surface deployed until a qualified Kolla environment supplies live service
catalog, Keystone, API, and browser evidence.

## Done Criteria

- [ ] A versioned OpenAPI contract describes every public Coffer control
      endpoint, response, error, authentication, policy, and service-catalog
      assumption consumed by a UI, and automated tests reject drift from the
      Falcon routes and oslo.policy declarations.
- [ ] The project API supports repository create/list/detail and a read-only
      project quota summary with stable JSON, request IDs, bounded list
      behavior, deterministic error classes, and project isolation.
- [ ] An independently installable Horizon plugin discovers the
      `oci-registry` endpoint from the scoped Keystone catalog, forwards the
      current token server-side, lists and creates repositories, shows quota
      usage, handles 401/403/404/409/503 safely, and passes focused Django/UI
      tests without hard-coded endpoints or stored credentials.
- [ ] A Skyline Console integration discovers the same catalog service,
      implements the equivalent repository list/create/detail and quota view,
      carries the current scoped token through Skyline's supported client
      boundary, and passes lint/unit/build checks against a pinned upstream
      source baseline.
- [ ] Kolla companion-role contracts can opt in to the Horizon and Skyline
      artifacts and configuration without changing either dashboard by
      default; enable, reconfigure, disable, and residue checks are
      deterministic and secret-safe.
- [ ] Repository regression, dependency locks, generated-artifact checks,
      documentation, screenshots or rendered fixture evidence, release
      boundary, and `HANDOFF.md` accurately distinguish local integration from
      a deployed cloud result.

## Non-goals

- Unblocking, weakening, or declaring completion of plan 0019 while the exact
  stable Distribution/Ceph pair remains externally blocked.
- Direct UI access to Coffer SQL, RGW, Barbican, the registry signer, the
  private Distribution backend, or maintenance endpoints.
- Repository deletion, tag/manifest browsing, scanning, signing policy,
  lifecycle automation, public registries, or admin quota mutation in this
  work package.
- Official Horizon, Skyline, Kolla, or OpenStack governance publication.
- A production-cloud deployment or a claim that local mocks, source overlays,
  screenshots, or fixture browsers prove a deployed service.

## Context and Evidence

- The current control API exposes only `POST/GET /v1/repositories` and
  `GET /v1/repositories/{repository_id}` behind
  `keystonemiddleware.auth_token`. It has no OpenAPI document and no public
  quota usage endpoint.
- Coffer already proposes Keystone service type `oci-registry`; both UIs must
  resolve this endpoint from the current project-scoped catalog rather than a
  configured or hard-coded URL.
- Current Horizon documentation recommends an independently packaged plugin
  with an enabled file, panel, service adapter, views/templates, and tests.
  Server-side Django integration avoids adding CORS and browser token-storage
  boundaries.
- Current Skyline Console documentation describes first-party source modules:
  clients/stores, resource containers, routes, menus, and locales. It does not
  document a Horizon-style external plugin loader. The exact supported
  integration form must therefore be established against a pinned current
  upstream revision before code is accepted.
- Plan 0019 is `blocked-external`. UI development may continue independently,
  but final live catalog and browser acceptance remains conditional on a
  qualified disposable Kolla environment.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Freeze one product REST/OpenAPI contract before either UI | Horizon and Skyline must expose the same project behavior and error semantics without reading implementation internals | UI-specific APIs; direct SQL/RGW access; duplicated endpoint assumptions | 2026-07-26 |
| Keep the first UI surface deliberately small: repository create/list/detail plus quota summary | These are the implemented MVP control concepts needed to make the service useful without inventing destructive or deferred product features | Repository deletion; tag/manifest browser; scanning/signing/lifecycle features | 2026-07-26 |
| Resolve `oci-registry` from the scoped Keystone catalog and keep tokens in each UI's supported request layer | This matches OpenStack service discovery and avoids deployment-specific URLs or browser credential persistence | Hard-coded endpoint; local settings URL as primary discovery; direct browser token storage | 2026-07-26 |
| Package Horizon independently from Coffer's API runtime | Horizon explicitly supports out-of-tree plugins and deployers can enable or remove the dashboard independently | Patching Horizon core; embedding Django/Horizon dependencies in `coffer-api` | 2026-07-26 |
| Determine Skyline integration form from current upstream source before choosing overlay or maintained fork | Skyline documentation shows first-party modules but no confirmed external loader; the packaging boundary is an architectural fact, not a naming choice | Pretending Horizon's plugin model exists in Skyline; creating an unverified standalone bundle | 2026-07-26 |

## Tasks

- [ ] Inventory the exact public routes, policies, stores, response shapes,
      errors, metrics, and request-ID behavior; record and implement the stable
      REST/OpenAPI baseline.
- [ ] Add project quota summary and bounded repository listing where required
      by the frozen contract, with authorization and isolation tests.
- [ ] Build and test the independently packaged Horizon dashboard against the
      frozen contract and a pinned supported Horizon baseline.
- [ ] Inspect and pin current Skyline Console extension seams; record the
      overlay/fork decision and build/test the equivalent Console surface.
- [ ] Add disabled-by-default Kolla companion-role UI artifact/configuration
      contracts and lifecycle validation.
- [ ] Run focused and full verification, render and inspect both UIs with
      fixture data, document the live-deployment boundary, and close the
      handoff.

## Progress Log

### 2026-07-26 — UI work package activated behind the blocked promotion gate

- Completed: Recovered the clean repository and current public API boundary,
  refreshed the live Stage 6 upstream classifier, and separated the external
  production-promotion block from locally independent product/UI work.
- Evidence: Distribution v3.1.1 and Ceph Tentacle v20.2.2 still classify
  `blocked`; the API inventory finds three repository operations, no OpenAPI
  document, no quota read endpoint, and no existing Horizon or Skyline code.
  Official current Horizon documentation confirms an out-of-tree plugin
  model. Official Skyline Console development documentation describes
  first-party clients/stores/routes/menus/locales and requires current source
  inspection before selecting an integration package boundary.
- Changed files: Plan 0019, this plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Create `docs/research/ui-api-contract.md` by mapping
  `src/coffer/api.py`, `src/coffer/wsgi.py`, `src/coffer/policy.py`,
  `src/coffer/db.py`, `src/coffer/quota.py`, middleware errors, and current
  route tests to the minimum stable UI contract. Do not add an endpoint until
  this inventory fixes its policy, response, pagination, and failure
  semantics.

### 2026-07-26 — Project UI API contract inventoried and accepted

- Completed: Mapped the exact Falcon repository resources, Keystone identity
  middleware, oslo.policy rules, repository/quota stores, bounded metrics, API
  tests, and Kolla service-catalog endpoint. Fixed a version-relative OpenAPI
  contract for repository create/list/detail plus read-only current-project
  quota.
- Decisions: Keep the catalog endpoint ending in `/v1`; add bounded
  `(name, id)` pagination with a project-visible repository marker; preserve
  existing repository representation; add `GET /quota` without admin mutation
  or derived fields; emit request IDs for requests reaching Falcon; and keep
  auth middleware errors outer-layer owned.
- Security: Both UIs must use the current project-scoped token and
  `oci-registry` catalog endpoint. Cross-project markers and IDs remain
  indistinguishable from malformed/absent current-project resources. No UI
  receives SQL, RGW, signer, Distribution, maintenance, or secret access.
- Changed files: `docs/research/ui-api-contract.md`, this plan, and
  `.codex/state/HANDOFF.md`.
- Next exact action: In `src/coffer/db.py`, add the bounded keyset
  `RepositoryPage`/`RepositoryStore.list_page` contract and focused store/API
  tests before adding quota or OpenAPI files.

### 2026-07-26 — Project-scoped repository pagination completed

- Completed: Added immutable `RepositoryPage` and bounded keyset listing to
  the repository authority. The collection API defaults to 100 rows, permits
  1 through 1,000, orders by `(name, id)`, and returns `next_marker` only when
  another row exists.
- Isolation: A marker must resolve inside the authenticated project. Unknown,
  malformed, empty, or another project's marker returns the same 400 class
  without revealing cross-project existence.
- Compatibility: Existing unpaged store consumers remain unchanged. The
  existing `repositories` response array is preserved and only
  `next_marker` is added.
- Evidence: Repository, token, control-dispatch, and observability focused
  tests pass 70 cases; the full Python regression passes 1438 tests; Python
  compilation and diff checks pass.
- Changed files: `src/coffer/db.py`, `src/coffer/api.py`,
  `tests/test_repositories.py`, this plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Add `QuotaResource` in `src/coffer/api.py`, register
  `quota:get` in `src/coffer/policy.py`, construct `QuotaStore` in
  `src/coffer/wsgi.py`, and prove project-scoped quota read behavior before
  adding the OpenAPI document.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 6 release boundary | `make -C poc/production-images check-upstream` | passed; valid `blocked` result |
| Current API source inventory | Focused Falcon, policy, store, middleware, and test inspection | passed; gaps recorded |
| Horizon extension shape | Official current Horizon plugin and dashboard documentation | passed; out-of-tree plugin supported |
| Skyline extension shape | Official current Skyline Console development/source documentation | partial; first-party seams identified, packaging boundary pending source pin |
| Plan/HANDOFF structure | Markdown and exact-next-action inspection | passed |
| Project UI API contract inventory | Exact API/policy/store/middleware/test and Kolla endpoint inspection | passed; implementation boundary fixed |
| Repository keyset pagination | `uv run pytest -q tests/test_repositories.py tests/test_tokens.py tests/test_token_api.py tests/test_observability.py` | passed; 70 |
| Full regression after repository pagination | `uv run pytest -q` | passed; 1438 |

## Failures, Blockers, and Risks

- Live UI deployment evidence cannot be produced while plan 0019 prevents
  creation of the fresh Kolla pilot. Local API/framework/browser evidence must
  remain explicitly labelled.
- Skyline Console does not currently document a Horizon-equivalent external
  plugin loader. The accepted implementation may require a small maintained
  source overlay and image build rather than a separately installed runtime
  plugin; current upstream inspection decides this before implementation.
- Adding UI convenience endpoints can accidentally expand the product or
  authorization model. Only existing repository authority and a read-only
  current-project quota view are in scope.

## Handoff

- Current state: Plan 0019 is externally blocked, its local pilot harness is
  complete but uninvoked, and no six-VM pilot exists. Plan 0020 is active for
  API/Horizon/Skyline work that can be locally proven independently.
- Exact next action: Add `QuotaResource` in `src/coffer/api.py`, register
  `quota:get` in `src/coffer/policy.py`, construct `QuotaStore` in
  `src/coffer/wsgi.py`, and add focused current-project read tests.
- First file or command: `sed -n '1,190p' src/coffer/api.py`.
- Questions requiring user input: None. The user authorized autonomous
  milestone commits and pushes through Horizon and Skyline; accepted security,
  release, and deployment gates remain fail closed.
