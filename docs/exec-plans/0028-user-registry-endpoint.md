---
title: "User-facing single HTTPS registry endpoint"
status: active
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

- [ ] One owner-accessible HTTPS origin routes `/v1/*` to Coffer API,
      `/auth/token` to the token broker, and `/v2/*` through Coffer Edge to
      private unmodified Distribution and RGW.
- [ ] The proposed Keystone `oci-registry` public endpoint and an authenticated
      discovery response identify the exact control, registry, and token URLs
      without deriving them by string manipulation.
- [ ] A packaged OpenStackClient extension supports endpoint discovery,
      repository create/list/show, quota show, and a non-secret registry login
      workflow; focused unit and packaging tests pass.
- [ ] Horizon and Skyline continue to list and inspect the same live
      project-scoped repository through the catalog endpoint after
      reconfiguration.
- [ ] Real Docker, Podman, and ORAS clients can push and pull through the public
      origin using finite project-scoped Keystone application credentials.
- [ ] A second project cannot read or write the first project's repository,
      and neither direct API, Distribution, RGW, database, nor secret-bearing
      runtime ports are reachable from the client network.
- [ ] TLS verification, redacted logs, restart persistence, reconfigure
      idempotency, and a two-edge/Distribution-replica HA exercise pass without
      weakening the existing production gates.
- [ ] The execution plan, runbook, API reference, and durable handoff contain
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
- [ ] Implement and package the OpenStackClient command surface with tests and
      owner-safe login output.
- [ ] Extend the retained preview harness and companion role for the selected
      external origin, TLS material, system-HAProxy route, and repeatable
      teardown.
- [ ] Reconfigure the preview and verify catalog, UIs, real clients, isolation,
      backend closure, restart, idempotency, secret redaction, and same-host HA.
- [ ] Run the full regression and completion audit, update durable documents,
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
  The Tailscale DNS identity resolves to the exact host address, Tailscale can
  issue its publicly trusted certificate, and port 18788 is unused and does
  not disturb the existing host listener set.
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

## Verification

| Check | Command or method | Result |
|---|---|---|
| Repository recovery | AGENTS, HANDOFF, plan, Git status/log | passed; clean at `bc9d95d` |
| Requirement audit | plan 0027, role defaults, package entry points | passed; endpoint and client gaps confirmed |
| Discovery unit and API contract | focused pytest, JSON, compilation | passed; 45 tests |
| Client unit and package contract | focused pytest and wheel entry-point inspection | pending |
| Live catalog and path routing | Keystone catalog plus HTTPS requests | pending |
| Real OCI clients and isolation | Docker, Podman, ORAS project A/B acceptance | pending |
| Security and lifecycle | direct-backend probes, restart, reconfigure, log scan | pending |
| Functional HA | bounded replica stop and continued push/pull | pending |
| Full regression | complete repository test and source checks | pending |

## Failures, Blockers, and Risks

- The local `ssh bb00` alias currently resolves to `192.168.35.8` and timed
  out. Direct SSH to `jh.byun@100.123.168.66` works, but privileged inspection
  requires the previously documented bounded host-control path.
- A certificate warning acceptable for dashboard inspection is not sufficient
  for Docker/Podman/ORAS acceptance. The selected public origin must have an
  explicit client trust procedure or a verifiable host certificate.
- The retained AIO can prove only same-host load-balancer and replica
  behavior. Separate-host HA remains a production gate.

## Handoff

- Current state: Plan 0028 is active. The public origin and API discovery
  contract are frozen and tested; the retained runtime has not yet been
  reconfigured.
- Exact next action: Implement the optional OpenStackClient extension and
  inspect its installed command entry points from a built wheel.
- First file or command: Add `src/cofferclient/` and the
  `openstack.cli.extension` plus `openstack.registry.v1` entry points in
  `pyproject.toml`.
- Questions requiring user input: None.
