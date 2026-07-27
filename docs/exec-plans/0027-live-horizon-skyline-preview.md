---
title: "Live Horizon and Skyline Coffer preview"
status: completed
updated: 2026-07-27
owner: primary-agent
---

# Objective

Deploy one retained, isolated, non-production Kolla 2026.1 AIO on `bb00` with
Keystone, Coffer's OCI Registry service, Horizon, and Skyline Console so the
user can log in through SSH tunnels and exercise the same repository and quota
surface in both dashboards. Keep the shared host and unrelated `dev11-*`
workloads unchanged, retain production security gates, and deliver access
without recording credentials in Git or exposing a new public listener.

## Done Criteria

- [x] A uniquely named, autostart-disabled x86_64 VM uses only a dedicated
      Coffer storage namespace, fixed non-conflicting address/MAC values, and
      sufficient CPU, memory, and disk on `bb00`.
- [x] Kolla-Ansible deploys Keystone, Horizon, Skyline, and their required
      services; Coffer deploys through its companion role with verified TLS,
      external disposable RGW storage, MariaDB, and proposed
      `oci-registry` catalog endpoints.
- [x] The project-scoped preview account can create, list, and inspect a
      repository and read quota through both the Horizon Registry dashboard
      and Skyline Registry Console.
- [x] OCI push/pull persists a digest and another project cannot access it.
- [x] Local SSH tunnels provide the user-facing URLs without changing shared
      host ports, DNS, firewall policy, or unrelated libvirt networks.
- [x] Browser acceptance records both live dashboards, catalog-gated Registry
      navigation, absence of secret-bearing output, and exact deployment
      limitations.
- [x] Deployment state, owner-only credential retrieval, stop/start, and exact
      teardown commands are documented; the retained preview is not described
      as production-ready.

## Non-goals

- Production promotion, HA, capacity or performance claims, public Internet
  exposure, official Kolla/OpenStack support, or bypassing the Distribution,
  Ceph, oslo.messaging, native AMD64, signing, and publication gates.
- Reusing or modifying `dev11-*`, host HAProxy/Harbor, host ports 80/443, or
  another user's VM, network, image, credential, registry, or bucket.
- Printing or checking in passwords, private keys, application credentials,
  Docker credentials, kubeconfigs, or complete token responses.

## Context and Evidence

- Plan 0016 proved a disposable Kolla 2026.1 AIO plus Coffer catalog and
  two-project OCI acceptance at `192.168.122.202` with external VIP
  `192.168.122.220`; that VM and its owned volumes were removed.
- Plan 0020 completed independently packaged Horizon and exact-revision
  Skyline integrations. Their live catalog, Keystone, Kolla, and browser
  acceptance was explicitly deferred.
- Plans 0021-0026 leave the UI image set fail-closed for production. This
  deployment is a retained preview using exact reviewed artifacts, not a
  production image promotion.
- Current read-only `bb00` evidence shows x86_64, about 124 GiB available
  memory, an 887-GiB-available `coffer-rgw` pool, the retained isolated
  `coffer-rgw-poc` VM at `192.168.122.200`, and no current Stage 4 domain or
  Stage 4 volumes. Unrelated `dev11-*` domains are running and excluded.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Create a new Coffer-owned AIO rather than mutate `dev11-*` | The existing environment is unrelated and shared-host safety requires an exact ownership boundary | Reconfigure the existing OpenStack controller; install directly on `bb00` | 2026-07-27 |
| Expose dashboards only through SSH local forwarding | The user can inspect both live UIs without public DNS, firewall, or host-port changes | Bind host 80/443; public reverse proxy; disable TLS | 2026-07-27 |
| Retain the preview until explicit teardown while disabling VM autostart | A user-visible preview must survive the build turn but remain bounded and recoverable | Destroy immediately after screenshots; enable host autostart | 2026-07-27 |
| Keep production gates visible in the UI preview handoff | Functional browser evidence cannot qualify vulnerable or unreleased dependencies | Label the preview production-ready; weaken scanners or release gates | 2026-07-27 |
| Map `oci-registry` to Skyline's `coffer` endpoint key through Kolla custom YAML | Skyline hides services absent from its configured Keystone service mapping | Hard-code a browser endpoint; expose the private API directly | 2026-07-27 |
| Let the companion role own Skyline's same-origin Coffer proxy | Kolla 2026.1 renders only its built-in Nginx service locations, while the browser must keep tokens on the Skyline origin | Add a host listener; fork all of Kolla's Nginx template | 2026-07-27 |
| Explicitly set Skyline's repository list envelope to `repositories` | Skyline's generic singular-plus-`s` rule produces the invalid `repositorys` key | Change the Coffer API contract; transform responses in Nginx | 2026-07-27 |

## Tasks

- [x] Freeze the preview VM, network, image, storage, and access contract with
      collision/capacity preflight.
- [x] Provision the AIO and deploy pinned Kolla core, Horizon, and Skyline.
- [x] Build/install exact Coffer service, Horizon, and Skyline images and run
      companion-role/catalog/storage bootstrap.
- [x] Create owner-only preview identities, exercise OCI and both UI flows,
      and retain no token or secret in evidence.
- [x] Verify SSH-tunnel access, browser behavior, restart/idempotency, residue,
      documentation, commit, and push.

## Progress Log

### 2026-07-27 — Work package activated

- Completed: Recovered the current repository and Stage 6 boundary, inspected
  `bb00` read-only, excluded unrelated `dev11-*` domains, and confirmed that a
  separately named non-autostart AIO is feasible.
- Evidence: `bb00` is x86_64 with about 124 GiB available memory; the
  `coffer-rgw` pool reports about 887 GiB available; `coffer-rgw-poc` is
  running at `192.168.122.200`; the old Stage 4 domain and volumes are absent.
- Changed files: This execution plan and durable handoff.
- Next exact action: Inspect the exact Kolla 2026.1 Horizon/Skyline service
  ports, image variables, and the companion role's live UI tasks before
  freezing the preview address and provisioner.

### 2026-07-27 — Preview ownership contract frozen

- Completed: Frozen a new `coffer-ui-preview-1` ownership boundary with
  management address `192.168.122.204`, internal VIP `192.168.122.205`,
  external VIP `192.168.122.221`, new MACs, 8 vCPUs, 40 GiB RAM, and a
  220-GiB sparse root in only the `coffer-rgw` pool. All three addresses were
  silent, both MACs were absent, and the exact domain and volume names were
  absent at preflight.
- Completed: Pinned the guest to Ubuntu Noble serial `20260725` at SHA-256
  `d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac`.
  The official signed manifest was verified with the installed Ubuntu cloud
  image keyring before recording the dated input.
- Completed: Enabled both parent UIs in the preview Kolla globals, enabled
  both opt-in Coffer integrations in separate companion globals, and recorded
  the local-only SSH forward contract for Horizon 443, Skyline Console 9999,
  and Coffer edge 8788.
- Evidence: Bash syntax, strict ShellCheck, YAML parsing, and diff checks pass.
  Skyline's Kolla Nginx template proxies Skyline API and service calls through
  the Console origin, so local forwarding does not require publishing the
  internal control plane.
- Changed files: Added `poc/ui-preview/provision.sh`, `globals.yml`,
  `coffer-globals.yml`, and `README.md`.
- Next exact action: Copy only the validated provisioner to `bb00`, rerun its
  collision checks there, create the autostart-disabled preview VM, and wait
  for cloud-init/SSH readiness.

### 2026-07-27 — Retained AIO, Coffer, and tenant proof deployed

- Completed: Created `coffer-ui-preview-1` with the frozen ownership contract,
  autostart disabled, and only its named root and seed storage. Pinned
  Kolla-Ansible deployed 37 parent containers, then the companion role
  deployed Coffer API, quota edge, CNCF Distribution, the exact Horizon
  derivative, and the exact Skyline derivative.
- Completed: Registered the proposed `oci-registry` service and internal,
  public, and admin endpoints in Keystone. Created the dedicated RGW identity
  and bucket without exposing its keys, two disposable Keystone projects, and
  owner-only project credentials.
- Evidence: Docker push and pull retained
  `sha256:7a3ebe5bfd1a4a19797d20b0c0bb39d44393e9a03fd852c0865b0f540d868df0`.
  Project A received 200 for tags; project B received 404 for the control
  resource and 401 for tags, and could neither pull nor push project A's
  repository. Direct backend bypass remained unavailable.
- Corrected: Shortened Alembic revision
  `0005_maintenance_comparison_sessions` to `0005_maintenance_sessions`
  because the former exceeded the stock MySQL `alembic_version` column.
  Corrected edge/reconciler backend CA delivery to honor
  `coffer_backend_cacert`, and packaged Horizon's policy defaults as oslo
  policy metadata rather than a raw rule dictionary.

### 2026-07-27 — Horizon and Skyline live browser integration completed

- Completed: Horizon displayed project A's quota, `preview-proof` list row,
  and repository detail through the tunneled Kolla deployment.
- Completed: Added Kolla's required Skyline `oci-registry: coffer` mapping,
  companion-owned same-origin Nginx proxy, and the explicit `repositories`
  response envelope. Skyline then displayed the same quota, list row, and
  detail for repository ID `92afcfef-0bb8-40dd-b295-b397e7494930`.
- Evidence: Horizon uses exact image
  `localhost:5000/coffer-horizon@sha256:1013fea974116b5f466c97cd9be8909edfe60d2231659f5171eaa09cf62d41be`.
  Skyline uses exact image
  `localhost:5000/coffer-skyline-console@sha256:f8d0bce1e2125507ebba0ccb6d3bbb4a619781d2446aaaa0c3da84f06f607dbd`.
- Corrected: Re-running the parent prepare phase had replaced the companion
  inventory groups. The harness now creates the pinned parent inventory only
  when absent, preserving its Coffer-owned extension on later prepares.

### 2026-07-27 — Restart, reconfigure, and retention gate passed

- Completed: Restarted Coffer API, edge, Distribution, Horizon, Skyline API,
  and Skyline Console. All six became healthy, both browser details remained
  usable, and the exact OCI digest was unchanged.
- Completed: A second companion reconfigure reported only the expected
  one-shot Alembic bootstrap task as changed; it completed without failure,
  preserved both exact UI images, and its owner-only lifecycle log passed
  generated-password, Coffer-secret, and disposable-identity secret scans.
- Evidence: The guest reports 41 running containers, zero non-running and
  zero unhealthy containers, both VIPs present, owner state at mode 0600,
  and no temporary browser password or restart evidence residue. Libvirt
  reports the retained preview running with autostart disabled. Unrelated
  `dev11-*` domains remain running.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Repository recovery | AGENTS, HANDOFF, Git status/log | passed; clean at `87016f6` |
| Shared-host capacity and ownership | read-only SSH, libvirt system inventory and pool info | passed; isolated target feasible |
| Preview harness | Bash syntax, strict ShellCheck, YAML parse, diff check | passed |
| Kolla/Coffer deployment | exact prechecks, deploy, catalog and container health | passed; 41 running, zero unhealthy |
| Horizon live browser acceptance | local SSH tunnel, project A login | passed; quota, list, detail |
| Skyline live browser acceptance | local SSH tunnel, project A login | passed; catalog menu, quota, list, detail |
| OCI and project isolation | real Docker push/pull and cross-project denial | passed; digest retained, A allowed, B denied |
| Restart, idempotency, secret, and residue | six-container restart, second reconfigure, exact secret scans | passed; only safe one-shot migration reports changed |
| Repository regression | `PATH="$PWD/.venv/bin:$PATH" ./.venv/bin/python -m pytest -q` | passed; 1,648 tests |
| Source and harness quality | Python compilation, Bash syntax, strict ShellCheck, YAML/JSON parse, diff check | passed |

## Failures, Blockers, and Risks

- `virsh` without `qemu:///system` showed an empty user session; the actual
  shared-host inventory is on `qemu:///system`.
- The shared root filesystem is 81% used, so the preview must use the
  high-capacity `coffer-rgw` pool and must not place image layers or guest
  volumes under the host root filesystem.
- The historical management address `192.168.122.202` is now used by an
  unrelated MAC. It is rejected; this preview uses the free `.204`, `.205`,
  and `.221` ownership set.
- The initial status path accidentally enabled libvirt autostart by invoking
  `virsh autostart` as a read. Autostart was immediately disabled, the
  mutating status call was removed, and the final libvirt check reports
  `Autostart: disable`.
- Distribution 3.1.1's unchanged upstream Alembic dependency was not involved;
  Coffer's original 36-character migration revision exceeded MySQL's standard
  `VARCHAR(32)`. The shortened revision and a length regression test now pass.
- Kolla's Skyline service mapping made the menu visible but its static Nginx
  template had no arbitrary-service location. The companion role now owns
  only the Coffer same-origin block instead of forking the complete template.
- Skyline initially displayed zero rows despite a correct one-repository API
  response because its generic pluralizer requested `repositorys`. The store
  now binds `repositories`, and the production-bundle verifier requires it.
- Production image release gates remain blocked. Preview deployment must carry
  an explicit non-production warning and cannot become an image publication
  path.

## Handoff

- Current state: Plan 0027 is complete. The retained
  `coffer-ui-preview-1` is running on `bb00`, autostart is disabled, all 41
  containers are running and healthy, both dashboards show the same live
  registry repository, and owner-only credentials remain on the guest.
- Exact next action: The owner can inspect Horizon and Skyline using the
  local-only SSH tunnel and credential retrieval commands in
  `poc/ui-preview/README.md`. No deployment action is required.
- First command when the preview is no longer needed: Run
  `poc/ui-preview/provision.sh destroy` on `bb00`; its ownership checks limit
  deletion to the exact preview domain and named volumes.
- Questions requiring user input: None. The current request authorizes a
  retained isolated preview deployment, disposable credentials, and
  owner-only access delivery.
