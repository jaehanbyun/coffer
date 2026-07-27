---
title: "User-facing single HTTPS registry endpoint"
status: complete
updated: 2026-07-27
owner: primary-agent
---

# Objective

Turn the retained Coffer preview into a complete user-facing OpenStack registry
vertical slice through one TLS origin. The origin must expose the control API
under `/v1`, the Keystone application-credential token exchange under
`/auth/token`, and all OCI traffic under `/v2`; it must be discoverable from
Keystone, manageable from Horizon, Skyline, and OpenStackClient, and usable by
unmodified Docker, Podman, and ORAS clients without exposing Distribution or
another private backend.

## Done Criteria

- [x] One owner-accessible HTTPS origin routes `/v1/*` to Coffer API,
      `/auth/token` to the token broker, and `/v2/*` through Coffer Edge to
      private unmodified Distribution and RGW.
- [x] The proposed Keystone `oci-registry` public endpoint and an authenticated
      discovery response identify the exact control, registry, and token URLs
      without deriving them by string manipulation.
- [x] A packaged OpenStackClient extension supports endpoint discovery,
      repository create/list/show, quota show, and a non-secret registry login
      workflow; focused unit and packaging tests pass.
- [x] Horizon and Skyline continue to list and inspect the same live
      project-scoped repository through the catalog endpoint after
      reconfiguration.
- [x] Real Docker, Podman, and ORAS clients can push and pull through the public
      origin using finite project-scoped Keystone application credentials.
- [x] A second project cannot read or write the first project's repository,
      and neither direct API, Distribution, RGW, database, nor secret-bearing
      runtime ports are reachable from the client network.
- [x] TLS verification, redacted logs, restart persistence, reconfigure
      idempotency, and a two-edge/Distribution-replica HA exercise pass without
      weakening the existing production gates.
- [x] The execution plan, runbook, API reference, and durable handoff contain
      exact secret-free evidence; each material milestone is committed and
      pushed atomically.

## Non-goals

- Declaring the retained single-host preview production-ready, publishing
  images, applying for official OpenStack/Kolla governance, or clearing
  independent Distribution, RGW SSE-KMS, UI dependency, backup/restore,
  capacity, and multi-failure-domain production gates.
- Using a human or administrator password for registry login, returning an
  application-credential secret from an API, committing credentials, or
  putting credentials in command history, logs, plans, or evidence.
- Exposing the private Distribution listener, Coffer API listener, MariaDB,
  Keystone internals, RGW, or a debug/metrics listener through `bb00`.

## Context and Evidence

- Plan 0027 retained `coffer-ui-preview-1` on `bb00`. Horizon and Skyline are
  reachable through bounded system-HAProxy listeners, and the guest-internal
  Coffer origin is `https://192.168.122.221:8788`.
- The current Distribution challenge advertises that guest-internal token
  realm. Adding a host port alone would therefore produce a client-visible
  redirect to an unreachable address; the external origin, catalog endpoint,
  token realm, certificate, and proxy route must change together.
- The role already keeps API and Distribution private and makes Coffer Edge
  the sole service ingress. The missing product surfaces are an explicit
  discovery contract, a packaged OpenStackClient extension, and a verified
  owner-accessible registry origin.
- Existing production promotion plans remain fail-closed. This plan proves a
  complete functional user path on retained disposable infrastructure only.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Keep one external origin for control, token, and OCI paths | OCI clients follow an absolute token realm, while OpenStack users need one cataloged service boundary | Separate control and data FQDNs; expose Distribution directly | 2026-07-27 |
| Keep Coffer Edge as the only public backend | It preserves project authorization, bounded quota admission, observability, and a closed Distribution bypass | Route `/v2` from host HAProxy directly to Distribution | 2026-07-27 |
| Use finite application credentials and local client-side credential handling | It avoids human passwords and prevents Coffer from minting or returning reusable Keystone secrets | Admin password login; server-generated long-lived registry password | 2026-07-27 |
| Package the OpenStackClient extension as an optional Coffer client extra | Service images do not need client dependencies, while the command namespace remains installable from the same reviewed source | Shell-only examples; add OpenStackClient to every Coffer runtime | 2026-07-27 |
| Treat same-host replicas as functional HA evidence only | They can prove load-balancer routing and shared state, but not independent failure domains | Claim production HA from the retained AIO | 2026-07-27 |

## Tasks

- [x] Audit the live external DNS/TLS options, Kolla-rendered edge routing,
      catalog record, client availability, and direct-backend reachability.
- [x] Add versioned endpoint discovery and update the OpenAPI contract.
- [x] Implement and package the OpenStackClient command surface with tests and
      owner-safe login output.
- [x] Extend the retained preview harness and companion role for the selected
      external origin, TLS material, system-HAProxy route, and repeatable
      teardown.
- [x] Reconfigure the preview and verify catalog, UIs, real clients, isolation,
      backend closure, restart, idempotency, secret redaction, and same-host HA.
- [x] Run the full regression and completion audit, update durable documents,
      and push the final atomic milestone.

## Progress Log

### 2026-07-27 — Work package activated

- Completed: Recovered the clean repository at `bc9d95d`, reconciled plan 0027
  with the new persistent goal, and separated the already proven guest-internal
  OCI path from the still-missing owner-facing endpoint and CLI contract.
- Evidence: `main` equals `origin/main`; plan 0027 records live UI and
  guest-internal OCI evidence but leaves Coffer's data plane unexposed on
  `bb00`; `pyproject.toml` contains service process entry points and no
  OpenStackClient plugin.
- Changed files: This execution plan and the durable handoff.
- Next exact action: Inspect `bb00`'s available DNS and certificate identity,
  the existing system HAProxy marker block, and the guest's rendered Coffer
  catalog/challenge before freezing the owner-facing origin.

### 2026-07-27 — External origin and discovery contract frozen

- Completed: Selected
  `https://bb00.tail23b778.ts.net:18788` as the bounded owner-facing origin.
  The Tailscale DNS identity resolves to the exact host address, and port
  18788 is unused and does not disturb the existing host listener set.
  Tailscale-managed TLS was an initial hypothesis; the later bounded attempts
  proved this tailnet does not support it and selected the owner-local preview
  CA recorded below.
- Completed: Added an authenticated `GET /v1` discovery resource containing
  explicit control, registry, and token URLs. Added a dedicated
  `endpoint:get` project policy, `/v1/` compatibility, an exact OpenAPI 3.1
  schema, Kolla-rendered endpoint settings, and fail-closed validation that
  requires one credential-free HTTPS origin with exact `/v1`, `/v2/`, and
  `/auth/token` paths.
- Evidence: 45 focused repository, configuration, OpenAPI, and product
  application tests pass. JSON parsing, Python compilation, and diff checks
  pass. The local Ruff executable is absent, so Ruff is deferred to the
  repository's established final verification boundary.
- Changed files: Coffer API/config/policy/WSGI modules, Kolla Coffer template,
  OpenAPI document, focused tests, this plan, and the durable handoff.
- Next exact action: Implement the optional OpenStackClient extension and
  exercise its entry points from a built wheel.

### 2026-07-27 — OpenStackClient command surface completed

- Completed: Added a catalog-native `registry` OpenStackClient plugin and the
  six commands `endpoint show`, `repository create/list/show`, `quota show`,
  and `login`. The client validates the server discovery document, preserves
  project-scoped pagination, and returns bounded errors without reflecting a
  response body.
- Security: `registry login` accepts only a finite application credential ID,
  reads its secret from a hidden prompt or stdin, invokes Docker, Podman, or
  ORAS without a shell, and sends the secret only through the child process
  stdin. The human/admin password path is absent.
- Evidence: 56 focused tests and Ruff 0.12.1 pass. A clean wheel build contains
  the exact extension and six command entry points; OpenStackClient 9.0.0
  loads and lists all six commands. Generated build, egg-info, and temporary
  wheel state were moved to Trash after verification.
- Changed files: `pyproject.toml`, new `src/cofferclient/` package, focused
  client tests, this plan, and the durable handoff.
- Next exact action: Extend the preview lifecycle for the selected origin,
  acquire owner-only Tailscale TLS material, and reconfigure Coffer's public
  origin and Keystone catalog before installing the bounded host route.

### 2026-07-27 — Bounded public-route and replica lifecycle prepared

- Completed: Extended the marker-owned system-HAProxy contract with one
  `100.123.168.66:18788` TLS frontend, explicit private/operational path
  denials, verified-TLS primary and secondary Edge backends, exact Docker
  client trust, legacy-block migration, rollback, status, and cleanup.
- Completed: Added a Mac-owned local-CA lifecycle, a runtime-only Coffer image
  refresh, and exact same-host Edge/Distribution replica lifecycle. The
  selected external FQDN and port now enter Kolla through companion globals.
- TLS boundary: The root CA key remains mode 0600 on the Mac. Only the public
  CA, leaf key/certificate, and public guest backend CA are staged mode 0600
  under the owner's `bb00` directory; no private material entered Git or
  command output.
- Evidence: Bash syntax, strict ShellCheck, diff checks, and 61 focused Kolla,
  configuration, API, and client tests pass. Local leaf and CA validation
  passes exact hostname, expiry, chain, and key-pair checks.
- Changed files: Preview HAProxy, TLS, image-refresh, replica, globals, and
  runbook artifacts; focused Kolla contract tests; this plan and handoff.
- Next exact action: Copy the committed source into the guest, rebuild only
  the Coffer runtime image, run companion prechecks/reconfigure, and start the
  exact replicas before installing the host route.

### 2026-07-27 — Public route and real-client HA acceptance passed

- Completed: Rebuilt and reconfigured the retained runtime with the selected
  public origin, started an exact same-host Edge/Distribution replica pair,
  and installed the Tailscale-address-only system-HAProxy route with verified
  TLS on both hops. The primary pair was then stopped as one bounded fault and
  restored by a fail-closed Mac orchestrator.
- Evidence: Docker 28.0.4, pinned Podman 5.8.2, and pinned ORAS 1.3.3 each
  pushed and pulled through the public origin. Project B was denied project
  A's Docker content. A Docker push and pull continued while the primary Edge
  and Distribution containers were stopped. The primary and replica paths
  advertise the exact external token realm; the primary containers returned
  healthy after restoration.
- Security: TLS chain and hostname verification passed; client secrets crossed
  only stdin and owner-readable mode-0600 staging, and all staging files were
  removed. Secret-free owner evidence remains on `bb00` with SHA-256
  `e9b87ca4588bf959210634509645bb57c5d515782e258e6f29f8cd9613929874`.
- Failures resolved: Added a bounded HAProxy transition retry after an initial
  post-stop 503, and stopped requiring Docker and Podman to produce identical
  manifest digests because clients may normalize media types independently.
- Next exact action: Install the built Coffer wheel into the retained Kolla
  toolbox and run the six `openstack registry` commands against the live
  catalog without exposing an application-credential secret.

### 2026-07-27 — Catalog, UI, lifecycle, and completion audit passed

- Completed: Installed the universal Coffer wheel into Kolla toolbox without
  adding service dependencies. OpenStackClient 9.0.0 loaded all six registry
  commands. A finite project-A application credential then resolved the live
  Keystone `oci-registry` catalog, returned the exact three discovery URLs,
  read quota, and created, listed, and inspected `osc-proof`.
- Runtime defect resolved: The first live discovery command found that `/v1`
  and `/v1/` were absent from the bounded HTTP metric route set. That caused
  response middleware to convert a valid discovery response into HTTP 500.
  Commit `2c260e5` added only those two fixed labels and made the authenticated
  control fixture exercise metrics; 146 focused tests passed before runtime
  reconfiguration.
- UI evidence: The installed Horizon adapter listed `osc-proof` and
  `preview-proof`, inspected `preview-proof`, and read the project quota
  through its real request adapter. Skyline's live same-origin proxy returned
  the same two repositories. Its root, login, registry route, and exact
  `auth.bundle.1785131314.js` asset all returned verified HTTP 200. A new
  browser session had no retained login and reported one stale chunk-load
  event, so it was not accepted as new visual evidence; the live adapter,
  proxy, static assets, and earlier plan-0027 browser evidence are the
  authoritative UI proof.
- Isolation and HA evidence: Acceptance schema v2 proves project B cannot pull
  or push project A content through the public origin. Docker 28.0.4, pinned
  Podman 5.8.2, and pinned ORAS 1.3.3 all pushed and pulled. A Docker push/pull
  passed with the primary Edge/Distribution pair stopped. Owner-only,
  secret-free v2 evidence SHA-256 is
  `4c406c24c951280c645655270fafc48d34f5e46dc441785226050e2de7d6b121`.
- Lifecycle evidence: The accepted Docker digest
  `sha256:84a85f89e310cf9e42ac607ed7eef5da9e4ab4e6d51145933bc95c4b155f7329`
  was identical before and after restarting API, both Edge processes, and both
  Distribution processes. Private/operational paths returned 403; client
  ports 8787, 8788, 8789, 18888, and 18889 were closed; and credential,
  private-key, Authorization, and JWT scans of all five runtime logs passed.
  A second unchanged reconfigure completed with failed=0; its sole changed
  task was the intended repeat-safe one-shot schema bootstrap.
- Final verification: 1,666 repository tests, 37 Horizon tests, and 31 Skyline
  tests pass. Bash syntax, strict ShellCheck, Ruff 0.12.1, lock consistency,
  Python compilation through the component suites, and diff checks pass.
- Changed files: Bounded public-client and lifecycle acceptance harnesses,
  Kolla contract tests, preview runbook, this plan, and the durable handoff.
- Next exact action: Keep the retained preview available for owner inspection.
  Production promotion remains a separate fail-closed work package beginning
  with a generally trusted certificate and independent failure domains.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Repository recovery | AGENTS, HANDOFF, plan, Git status/log | passed; clean at `bc9d95d` |
| Requirement audit | plan 0027, role defaults, package entry points | passed; endpoint and client gaps confirmed |
| Discovery unit and API contract | focused pytest, JSON, compilation | passed; 45 tests |
| Client unit and package contract | focused pytest, Ruff, wheel entry-point inspection | passed; 56 focused tests and six commands |
| Live catalog and path routing | Keystone catalog, discovery, OpenStackClient | passed; public/internal/admin catalog plus six packaged commands |
| Real OCI clients and isolation | Docker, Podman, ORAS project A/B acceptance v2 | passed; project-B pull and push denied |
| Horizon and Skyline integration | live Horizon adapter, Skyline same-origin proxy and static routes | passed; both returned `osc-proof` and `preview-proof` |
| Security and lifecycle | direct-backend probes, restart, reconfigure, log scan | passed; only repeat-safe bootstrap reports changed |
| Functional HA | bounded primary Edge/Distribution stop and continued push/pull | passed; same-host only |
| Full regression | repository, Horizon, Skyline, Bash, ShellCheck, Ruff, lock, diff | passed; 1,666 + 37 + 31 tests |

## Failures, Blockers, and Risks

- The retained AIO can prove only same-host load-balancer and replica
  behavior. Separate-host HA remains a production gate.
- Two Tailscale-managed certificate attempts failed closed: the ordinary user
  lacks cert permission, and a root-scoped socket call proved that this
  tailnet does not support TLS certificates. The selected preview fallback is
  an explicit owner-local CA; a generally trusted production FQDN/certificate
  remains a production gate.

## Handoff

- Current state: Plan 0028 is complete. The retained preview exposes and
  verifies one external control/token/OCI origin, project-scoped
  OpenStackClient and dashboard management, three real OCI clients,
  read/write isolation, restart/reconfigure correctness, closed backends, and
  same-host primary-pair failover.
- Exact next action: Preserve the retained preview for owner inspection; when
  production work resumes, create a new execution plan that starts with a
  generally trusted certificate and separate-host HA.
- First file or command: `poc/ui-preview/README.md`; no command is required
  while the preview remains retained.
- Questions requiring user input: None.
