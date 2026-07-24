---
title: "Kolla deployment topology and operating contract"
status: complete
updated: 2026-07-23
owner: primary-agent
---

# Objective

Complete the first Kolla integration work package by fixing Coffer's deployable
process boundaries, endpoint and port model, TLS trust boundaries, secret
delivery responsibilities, database migration ownership, and rollback
authority. Base the decision on the implemented Coffer seams, current
Kolla-Ansible contracts, and a secret-safe read-only inventory of the user's
reachable `bb00` KVM host. This package produces an accepted deployment
topology and a sequenced long-horizon roadmap; it does not build images, install
roles, create identities, or deploy Coffer.

## Done Criteria

- [x] A secret-safe read-only inventory of `bb00` records the
      relevant host, Kolla/OpenStack, network, database, load-balancer, and RGW
      facts without copying credentials or configuration secrets.
- [x] An accepted ADR fixes the API/token, edge, Distribution, reconciler, and
      one-shot migration boundaries and explains rejected alternatives.
- [x] The external and internal endpoint, port, TLS, routing, health, and
      non-bypassable quota-admission contracts are explicit and internally
      consistent.
- [x] Signing key/JWKS, Distribution HTTP secret, RGW credential, CA material,
      and database credential delivery ownership is fixed without creating or
      exposing any secret.
- [x] Migration, upgrade, rollback, backup, and failure ownership is explicit,
      including which actions are deliberately deferred.
- [x] The remaining Kolla journey is divided into independently verifiable
      work packages with one exact next action, and architecture, README, this
      plan, and `HANDOFF.md` agree.
- [x] Markdown structure, local links, secret scans, and the final Git diff pass
      focused verification.

## Non-goals

- Building or publishing production/Kolla container images.
- Modifying, installing, or deploying Kolla-Ansible, OpenStack, HAProxy,
  MariaDB/Galera, Ceph, RGW, Barbican, or Coffer on a remote host.
- Reading, printing, copying, rotating, or creating credentials, keys,
  certificates, kubeconfigs, or secret-bearing configuration.
- Registering the proposed `oci-registry` service type in Keystone.
- Selecting a production Distribution/Ceph release, closing the SSE-KMS
  zero-byte gate, or claiming production readiness.
- Committing, pushing, opening reviews, or publishing externally.

## Context and Evidence

- `docs/architecture/mvp-baseline.md` already separates Coffer control/token,
  manifest admission, reconciliation, unmodified Distribution, shared SQL, and
  RGW responsibilities but explicitly defers deployment-system packaging.
- `src/coffer/wsgi.py` installs the control API, token endpoint, and operational
  endpoints in one WSGI application. The quota edge is implemented separately
  in `src/coffer/registry_proxy.py` and currently assembled only by the
  disposable quota fixture.
- `coffer-reconcile` is an installed independent process. Alembic is the sole
  production schema authority and must run before normal processes.
- Accepted ADR 0009 requires every registry write path to make Distribution
  private behind a non-bypassable manifest-admission edge.
- The user supplied a direct Tailscale SSH target as the replacement for the
  stale `ssh bb00` alias and authorized secret-safe access for completing this
  topology package. The user/address pair is intentionally not retained in
  project documentation.

### Read-only target evidence

- The legacy `ssh bb00` alias resolves to an unavailable LAN address; direct
  Tailscale SSH reaches the same host, which identifies itself as `bb00`.
- `bb00` is Ubuntu 24.04.2 LTS on x86_64 with 64 logical CPUs, approximately
  124 GiB available memory during the probe, KVM/libvirt available, and
  approximately 881 GiB free under `/srv/nfs`.
- It is a shared virtualization host with 17 running domains. The existing
  `coffer-rgw-poc` domain remains running with 8 vCPUs, 24 GiB memory, and
  autostart disabled; it is external RGW PoC evidence, not a Kolla controller.
- Kolla-Ansible, Kolla build, Ansible, and OpenStack CLI are absent from the
  host. Docker, libvirt, and a host HAProxy are active; host ports 80 and 443
  are already occupied.
- A separate Harbor 2.14 deployment and unrelated workloads run on the host.
  Harbor can be evaluated later as an external bootstrap image registry but is
  not selected, modified, or coupled to the tenant registry by this plan.
- Therefore no Coffer/Kolla process may be installed directly on `bb00`.
  Stage 2 and later disposable Kolla validation must use a separately named VM,
  its own virtual NICs/VIP and storage allocation, and must not reuse or mutate
  the existing `dev11-*`, Harbor, HAProxy, or other domains without a separate
  plan and explicit target resolution.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Treat this as topology-only work package 0013 and assign image, role, AIO, HA, production-gate, and upstream work to later packages | Each package remains independently verifiable and recoverable across compaction | One plan covering all production and upstream work; starting Kolla role edits before fixing the runtime contract | 2026-07-23 |
| Accept ADR 0014's five-role topology: API, sole-ingress edge, unmodified private Distribution, reconciler, and one-shot bootstrap | It preserves the implemented privilege seams, makes quota admission non-bypassable, and maps cleanly to Kolla process and bootstrap contracts | Public direct-to-Distribution routing, a Distribution fork, one all-secret container, or a separate token service without evidence | 2026-07-23 |
| Route the single Coffer origin through `coffer-edge`; keep shared HAProxy responsible for FQDN/VIP/TLS/load balancing rather than Coffer-specific path ACLs | One FQDN can use Kolla's single external frontend while the product edge owns closed path dispatch and avoids global HAProxy customization | Dedicated Coffer VIP, public high ports as the production profile, or service-specific path rules in Kolla's shared frontend | 2026-07-23 |
| Materialize preferred Barbican-backed secrets before start and run Alembic only in `coffer-bootstrap` | Runtime hot paths do not depend on secret retrieval and replicas cannot race schema ownership | Per-request Barbican fetch, secret values in ordinary inventory, and application auto-migration | 2026-07-23 |

## Sequenced Long-Horizon Work Packages

| Stage | Work package | Observable exit |
|---|---|---|
| 1 | Deployment topology and operating contract | Accepted topology ADR, endpoint/secret/migration contracts, verified environment evidence |
| 2 | Product runtime entry points and Kolla-compatible images | API/edge/reconciler/migration images start through the Kolla container contract and pass focused image checks |
| 3 | Operator-local Kolla-Ansible integration | Companion role passes deploy, reconfigure, pull, upgrade, stop, Keystone registration, DB bootstrap, and config validation |
| 4 | Kolla AIO end-to-end | Two-project OCI push/pull, restart, migration repeat, edge non-bypass, and residue checks pass through the Kolla VIP |
| 5 | Multinode and HA pilot | Replica loss, rolling upgrade, Galera, key overlap, load balancing, and rollback rehearsals pass |
| 6 | Production promotion gates | Release security/conformance, RGW/KMS, identity, backup/cutover, observability, load, and GC gates close |
| 7 | Upstream Kolla/OpenStack path | Kolla image and Kolla-Ansible role changes have integrated Zuul coverage and an agreed governance path |

Each later stage requires a fresh numbered execution plan before implementation.
Completing an earlier stage does not authorize or imply completion of a later
stage.

## Tasks

- [x] Run the documented secret-safe read-only remote inventory on `bb00`
      and retain only non-sensitive aggregate facts in this plan.
- [x] Reconcile remote facts with current Kolla 2026.1 deployment contracts and
      the implemented Coffer process/configuration seams.
- [x] Add and accept ADR 0014 for the deployable topology and operating
      ownership boundaries.
- [x] Update the architecture and operator-facing overview with the fixed
      topology and sequenced work packages.
- [x] Run focused documentation, link, diff, and secret verification and close
      this plan and the handoff.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Recovered `AGENTS.md`, the long-horizon prompt, handoff, plan
  template, clean Git state, and published plan 0012 commit `1111cc5`; activated
  a topology-only plan rather than expanding directly into image or role work.
- Evidence: `main` and `origin/main` both resolve to `1111cc5`; no active plan
  or uncommitted file existed before this plan.
- Changed files: This plan.
- Next exact action: Run a bounded, non-interactive, read-only connectivity and
  host inventory command with the user-supplied direct Tailscale SSH address,
  excluding environment values and configuration contents.

### 2026-07-23 — Read-only deployment target inventory completed

- Completed: Replaced the stale LAN SSH alias with the user-supplied direct
  Tailscale address, confirmed it reaches `bb00`, and inventoried only aggregate
  OS, capacity, tool, service, port, container, libvirt domain, pool, and
  network facts.
- Evidence: `bb00` is a well-provisioned but shared KVM host; it has no Kolla
  installation, already owns host HAProxy ports 80/443, runs a separate Harbor
  deployment and 17 VM domains, and retains the dedicated external
  `coffer-rgw-poc` VM. No credential, environment value, configuration content,
  certificate, key, token, or remote file was read or changed.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Reconcile the five implemented Coffer process seams with
  Kolla 2026.1 service, container configuration, TLS, and external-Ceph
  contracts, then write ADR 0014.

### 2026-07-23 — Deployment topology and operating contract accepted

- Completed: Accepted ADR 0014, added the operator-facing Kolla topology, and
  aligned the MVP architecture and README. The contract fixes the five runtime
  roles, default backend ports `8787`–`8789`, sole public edge, proposed
  catalog endpoints, TLS hops, per-process secret recipients, owner-controlled
  Barbican materialization, one-shot Alembic ownership, restore-oriented
  rollback, bootstrap-registry independence, and isolated future lab placement.
- Evidence: The implemented WSGI, edge, reconciler, and Alembic seams were
  reconciled with the Kolla 2026.1 service, image-configuration, TLS, HAProxy
  single-external-frontend, and external-Ceph contracts. No exact
  `8787`/`8788`/`8789` use appeared across 166 inspected stable-branch port
  declarations at commit `4d39a81d392f608a04b69cfae9afaa92d65ea388`.
- Changed files: ADR 0014, `docs/architecture/kolla-deployment-topology.md`,
  the MVP architecture, README, this plan, and `HANDOFF.md`.
- Failure: One combined documentation patch did not match an existing
  line-wrapped paragraph and was rejected atomically; it made no partial
  change. The additions and updates were then applied as scoped patches.
- Next exact action: Run the repository Markdown/local-link checks, Mermaid
  rendering, secret scans, `git diff --check`, and a manual scoped diff review.

### 2026-07-23 — Stage 1 verified and completed

- Completed: Reconciled the final endpoint and secret-recipient language,
  changed the authentication sequence to show the non-bypassable edge, removed
  the supplied SSH user/address from durable documentation, visually inspected
  all affected architecture diagrams, and closed every Stage 1 criterion.
- Evidence: 61 Markdown files and 40 local links passed structural checks; all
  four new/revised diagrams rendered and were visually readable; the four
  Kolla primary-source URLs returned HTTP 200; changed files passed Gitleaks
  and private-key/JWT/access-key/SSH-target pattern scans; `git diff --check`
  and manual scoped review passed.
- Changed files: `.codex/state/HANDOFF.md`, `README.md`, ADR 0014, the Kolla
  deployment topology, the MVP architecture baseline, and this plan.
- Corrected verification failures: An initial `rg` pattern beginning with
  hyphens was parsed as an option until `--` was added; the corrected scan then
  found and prompted removal of the supplied SSH target. A Mermaid sequence
  label containing a semicolon failed parsing; replacing it with plain
  conjunction text rendered successfully. Neither failure changed remote or
  runtime state.
- Next exact action: Create
  `docs/exec-plans/0014-kolla-runtime-images.md` from the execution-plan
  template before making any Stage 2 code, image, VM, or deployment change.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Remote inventory | Bounded read-only SSH probes with no secret-bearing file or environment output | passed |
| Markdown structure and local links | Repository-local checker over 61 files and 40 links | passed |
| Mermaid | Render and visual inspection of four affected diagrams | passed |
| Primary links | Four Kolla 2026.1 documentation URLs | passed, HTTP 200 |
| Secret safety | Gitleaks plus private-key/JWT/access-key/SSH-target scans on changed files | passed |
| Diff review | `git diff --check` and manual scoped diff inspection | passed |

## Failures, Blockers, and Risks

- `bb00` is a shared KVM host, not a Kolla target. Installing on the host would
  conflict with existing HAProxy/Harbor/workloads; use a new isolated VM in a
  separately authorized later plan.
- The original alias timed out because it resolves to a stale LAN address. The
  supplied Tailscale address reaches the same host; future automation must
  parameterize the remote instead of committing either address.
- `oci-registry` remains a proposed service type, so topology documentation can
  use it as the project contract but cannot claim service-types authority
  registration.
- Remote access authorizes inventory for this work package, not deployment,
  credential inspection, or security-boundary changes.

## Handoff

- Current state: Complete; all Stage 1 decisions and verification criteria
  passed. No image, role, VM, identity, credential, or deployment was created.
- Exact next action: Create
  `docs/exec-plans/0014-kolla-runtime-images.md` before Stage 2 implementation.
- First file or command: Copy the decision and exit gates from ADR 0014 and
  `docs/architecture/kolla-deployment-topology.md` into a new plan based on
  `docs/exec-plans/TEMPLATE.md`.
- Questions requiring user input: None for secret-safe read-only inventory and
  local topology documentation.
