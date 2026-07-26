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

- [x] A versioned OpenAPI contract describes every public Coffer control
      endpoint, response, error, authentication, policy, and service-catalog
      assumption consumed by a UI, and automated tests reject drift from the
      Falcon routes and oslo.policy declarations.
- [x] The project API supports repository create/list/detail and a read-only
      project quota summary with stable JSON, request IDs, bounded list
      behavior, deterministic error classes, and project isolation.
- [x] An independently installable Horizon plugin discovers the
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
| Maintain an exact-revision Skyline source overlay and custom immutable Console image | Skyline has no external loader; Kolla builds its Console from a branch source archive, while the catalog/profile and token request seams are first-party source contracts | Runtime asset mutation; unrelated second SPA; unconstrained full fork | 2026-07-26 |
| Map `oci-registry` to `coffer` in Skyline and append `v1` in the Console client | Skyline exposes mapped same-origin paths and its Nginx generator deliberately removes terminal service API versions from catalog URLs | Hard-coded Coffer URL; raw catalog URL in the browser; duplicate `/v1/v1` | 2026-07-26 |

## Tasks

- [x] Inventory the exact public routes, policies, stores, response shapes,
      errors, metrics, and request-ID behavior; record and implement the stable
      REST/OpenAPI baseline.
- [x] Add project quota summary and bounded repository listing where required
      by the frozen contract, with authorization and isolation tests.
- [x] Build and test the independently packaged Horizon dashboard against the
      frozen contract and a pinned supported Horizon baseline.
- [x] Inspect and pin current Skyline Console extension seams; record the
      overlay/fork decision.
- [ ] Build/test the equivalent Console surface from the accepted exact-source
      overlay.
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

### 2026-07-26 — Read-only current-project quota API completed

- Completed: Added `GET /v1/quota`, `quota:get`, and the stable quota
  representation. The production application constructs one migrated
  `QuotaStore` and reuses it for both public quota reads and the optional
  maintenance authority.
- Isolation and absence: The resource resolves only the authenticated project.
  Reader/member/admin may read; invalid or non-project scopes retain 401/403;
  an unconfigured project returns fixed 404 without creating or borrowing a
  limit.
- Observability: `/v1/quota` is a bounded API metric route and participates in
  the same control-plane SLO numerator/denominator as token and repository
  operations.
- Evidence: API/quota/token/maintenance/observability focused tests pass 127
  cases, the Kolla companion role passes 96 lifecycle checks, and the full
  Python regression passes 1442 tests. Compilation and diff checks pass.
- Changed files: `src/coffer/api.py`, `src/coffer/quota.py`,
  `src/coffer/policy.py`, `src/coffer/wsgi.py`,
  `src/coffer/observability.py`, observability contract/rules, tests, this
  plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Add a bounded control request-ID middleware in
  `src/coffer/api.py`, prove valid incoming preservation and generated
  fallback without changing Keystone-owned outer 401 responses, then write
  `api-ref/openapi.json`.

### 2026-07-26 — Control request correlation completed

- Completed: Added a Falcon request-ID middleware ahead of public control
  resources. It preserves only bounded `req-` identifiers and otherwise emits
  a UUID-backed value on success and Falcon resource errors.
- Boundary: Keystone authentication still wraps Falcon. Missing/invalid token
  401 challenges remain middleware-owned and are not reclassified or claimed
  as Coffer request-correlation evidence.
- Evidence: Repository, token, maintenance, observability, and API runner
  focused tests pass 64 cases, including valid preservation, invalid fallback,
  quota 404 correlation, and unchanged Keystone challenge. Compilation and
  diff checks pass.
- Changed files: `src/coffer/api.py`, `src/coffer/wsgi.py`,
  `tests/test_repositories.py`, this plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Create `api-ref/openapi.json` and
  `tests/test_openapi_contract.py`. Bind the four version-relative UI
  operations, exact schemas/policies/security/status/request-ID contracts, and
  the implemented Falcon route set.

### 2026-07-26 — REST/OpenAPI baseline completed

- Completed: Added the source-controlled OpenAPI 3.1 JSON contract for four
  version-relative operations and a drift suite binding it to Falcon resource
  callbacks, registered oslo.policy operations, runtime representations,
  limits, status classes, Keystone security, and request correlation.
- Runtime hardening: Repository names now fail at the declared 255-character
  API boundary instead of reaching the database. Known repository/quota
  database failures return one fixed secret-safe 503 with request correlation.
- Scope: The document intentionally excludes OCI token/data-plane,
  maintenance, health, readiness, metrics, SQL, RGW, and private backend
  surfaces. Keystone-owned pre-Falcon 401 responses document only the
  challenge and do not falsely promise a Coffer request ID.
- Evidence: OpenAPI/API/policy/token/maintenance/observability focused tests
  pass 123 cases; JSON parsing, Python compilation, and diff checks pass. The
  full Python regression passes 1450 tests.
- Changed files: `api-ref/openapi.json`,
  `tests/test_openapi_contract.py`, API validation/failure mapping, tests,
  this plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Pin the current supported Horizon source/release and
  create `docs/research/horizon-integration-baseline.md` by inspecting a
  maintained out-of-tree service dashboard such as Designate. Fix package,
  catalog discovery, token forwarding, panel, table/form, and test seams
  before creating `ui/horizon/`.

### 2026-07-26 — Horizon 2026.1 integration baseline accepted

- Source pin: Inspected official Horizon 25.7.3 at
  `0a4439556517cf67be0aa949b6551a14e409af75` and Designate Dashboard 21.0.0 at
  `5ae88cbc9c0d728ce94acc568b7c9394ad49f175`, matching the Kolla/OpenStack
  2026.1 line.
- Decision: Build `coffer-horizon` as an out-of-tree, server-rendered Django
  plugin on the Project dashboard. Use Horizon's catalog selection and a
  server-side `keystoneauth1` token session; do not add AngularJS, CORS,
  browser token storage, a hard-coded endpoint, or a Horizon core patch.
- Surface: Registry/Repositories panel with bounded forward list, quota card,
  create modal, and detail view only. A local Horizon policy mirror controls
  visibility while the Coffer API remains authoritative.
- Security/failure contract: Preserve the `/v1` catalog endpoint, honor the
  dashboard TLS settings, use finite timeouts and bounded request IDs, validate
  remote JSON, and never interpolate raw remote failures into messages.
- Changed files: `docs/research/horizon-integration-baseline.md`, this plan,
  and `.codex/state/HANDOFF.md`. Upstream source clones remain ignored under
  `work/`.
- Next exact action: Create `ui/horizon/pyproject.toml` and the
  `cofferdashboard.api.coffer` adapter with isolated unit tests for catalog,
  token-session, TLS, timeout, endpoint joining, response validation, and
  secret-safe failures before adding panel views.

### 2026-07-26 — Horizon server-side API adapter completed

- Package: Added locked `coffer-horizon` packaging with the Kolla/OpenStack
  2026.1 test matrix: Horizon 25.7.3, Django 4.2.28,
  keystoneauth1 5.13.1, and pytest 9.0.2. The verifier additionally requires
  the exact clean Horizon source revision and imports it from that checkout.
- Adapter: Resolves `oci-registry` through Horizon's selected catalog,
  requires a safe versioned `/v1` HTTP(S) endpoint, uses a token-endpoint
  server-side session, honors Horizon CA/no-verify settings, and applies
  finite timeouts with zero automatic retries.
- Validation: Repository/page/quota envelopes are exact-field, current-project,
  UUID, timestamp, size, name, and continuation validated. Unsafe endpoint,
  input, cross-project response, oversized page, malformed JSON, transport,
  and HTTP failures collapse to bounded result classes.
- Secret safety: The token is not placed in URL, document, manual header,
  output, or error. Transport/JSON/HTTP exception context is discarded before
  the bounded dashboard exception is raised.
- Evidence: Exact baseline verification passes; 22 adapter tests pass;
  compilation and wheel/sdist build pass. Generated artifacts remain ignored
  under `work/`.
- Changed files: `ui/horizon/` package, lock, verifier, adapter and tests; this
  plan; `.codex/state/HANDOFF.md`.
- Next exact action: Add the Registry panel group, Repositories panel,
  local policy mirror, enabled settings, Django table/form/views/routes, and
  templates, then test service-catalog hiding and list/quota/create/detail
  flows against mocked adapter results.

### 2026-07-26 — Horizon project dashboard completed locally

- Surface: Added the Project dashboard Registry group and Repositories panel,
  forward-paged table, quota usage card, create modal, and five-field detail
  view. No destructive, data-plane, storage, signer, scanner, maintenance, or
  administrator action is exposed.
- Access and security: Panel visibility requires the current scoped catalog's
  `openstack.services.oci-registry` permission. Repository policy is mirrored
  locally while the API remains authoritative. The views never handle a token
  or configured endpoint directly and display only fixed failures for
  401/403/404/409/503 classes.
- Packaging: The wheel includes both enabled files, local policy settings,
  policy YAML, panel modules, and templates. Installation remains opt-in and
  requires deployer-controlled file placement, Horizon static/compression
  steps, and web restart.
- Evidence: The exact 2026.1 baseline verifier passes; 36 adapter and Django
  flow tests pass; Python compilation and E/F/I style checks pass; the wheel
  contract includes every deployable artifact. These are local framework and
  fixture results, not a deployed Horizon/cloud result.
- Changed files: `ui/horizon/`, this plan, and
  `.codex/state/HANDOFF.md`.
- Next exact action: Pin the Skyline Console revision matching Kolla
  `stable/2026.1` in `docs/research/skyline-integration-baseline.md`. Inspect
  its package manager, service-catalog client, request/token boundary, stores,
  routes, menus, locales, tests, and build before selecting a maintained
  source overlay or another supported extension seam.

### 2026-07-26 — Skyline 2026.1 integration baseline accepted

- Source pins: Inspected official Skyline Console `stable/2026.1` at
  `c9000cb1be332a213009793598f17a80ce59671e`, Skyline API Server at
  `1902699cbf1b01f4d8d4c65a43a21b06a3a5e077`, Kolla at
  `686c6d13dc1c31092b22c6c481e16a7329e935ea`, and Kolla-Ansible at
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`.
- Decision: Skyline has no external plugin loader. Maintain a small
  exact-revision source overlay and build it into a custom immutable Console
  image; do not patch runtime assets or claim an independent plugin package.
- Discovery: Skyline API Server maps `oci-registry` to same-origin alias
  `coffer`. Its Nginx generator removes the terminal `/v1` from the catalog
  endpoint, so the Console client appends `v1` through the existing endpoint
  version map.
- Security: The client subclasses Skyline's existing request boundary, which
  owns current scoped-token forwarding, expiry, request ID, and 401 behavior.
  Coffer code does not read token storage or a configured endpoint. Catalog
  presence gates the menu and Coffer API policy remains authoritative.
- Changed files: `docs/research/skyline-integration-baseline.md`, this plan,
  and `.codex/state/HANDOFF.md`.
- Next exact action: Create `ui/skyline/baseline.json`, an exact-revision
  overlay verifier, and the Coffer client/store source with focused Jest tests.
  Apply them to a disposable clean Console copy before editing routes, menu,
  pages, or locales.

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
| Read-only project quota API and observability | API, quota, token, maintenance, observability, contract, and runner focused tests | passed; 127 |
| Kolla role after quota SLO expansion | `make -C poc/kolla-ansible-role verify` | passed; 96 |
| Full regression after project quota API | `uv run pytest -q` | passed; 1442 |
| Control request correlation | Repository, token, maintenance, observability, and runner focused tests | passed; 64 |
| OpenAPI/runtime drift contract | OpenAPI, API, policy, token, maintenance, observability, and runner focused tests | passed; 123 |
| Full regression after REST/OpenAPI baseline | `uv run pytest -q` | passed; 1450 |
| Horizon source/package baseline | Official Horizon 25.7.3, Designate Dashboard 21.0.0, and OpenStack 2026.1 constraints | passed; exact revisions and dependency versions pinned |
| Horizon server-side adapter | `make -C ui/horizon verify-adapter` | passed; exact baseline and 22 tests |
| Horizon adapter package build | `uv build --project ui/horizon` | passed; wheel and sdist generated under ignored work |
| Horizon panel and adapter | `make -C ui/horizon verify` | passed; exact baseline, 36 tests, compilation |
| Horizon source style | `ruff check --select E,F,I ui/horizon/cofferdashboard ui/horizon/verify.py` | passed |
| Horizon deployable wheel contents | Built wheel archive inspection | passed; enabled, policy, modules, and templates present |

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
- The first Horizon research pass selected latest tag 26.0.0 before checking
  the already accepted Kolla-Ansible `stable/2026.1` deployment line.
  Official 2026.1 constraints instead select Horizon 25.7.3. The baseline and
  uncommitted package were corrected before accepting any adapter evidence;
  latest-tag compatibility remains a later matrix expansion.

## Handoff

- Current state: Plan 0019 is externally blocked, its local pilot harness is
  complete but uninvoked, and no six-VM pilot exists. Plan 0020 is active for
  API/Horizon/Skyline work that can be locally proven independently.
- Exact next action: Pin the Skyline Console revision matching Kolla
  `stable/2026.1` and record its supported integration boundary before
  implementation.
- First file or command: Create
  `docs/research/skyline-integration-baseline.md` after inspecting the exact
  Kolla image/source mapping and matching `skyline-console` revision.
- Questions requiring user input: None. The user authorized autonomous
  milestone commits and pushes through Horizon and Skyline; accepted security,
  release, and deployment gates remain fail closed.
