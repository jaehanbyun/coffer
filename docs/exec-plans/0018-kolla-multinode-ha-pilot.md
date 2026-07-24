---
title: "Kolla multinode and HA pilot"
status: active
updated: 2026-07-24
owner: primary-agent
---

# Objective

Complete Stage 5 with a disposable x86_64 multinode Kolla-Ansible 2026.1
deployment that runs replicated Coffer API, edge, and unmodified Distribution
services through HAProxy and Galera, consumes an independently provisioned
external Ceph RGW HA endpoint, and remains correct through bounded replica,
database, worker, key-rotation, rolling-upgrade, and rollback failures. The
pilot must be reproducible, secret-safe, non-bypassable, and exactly removable.
It is HA evidence for the product and deployment contracts, not production
promotion while ADR 0006 remains blocked.

## Done Criteria

- [ ] A fresh read-only `bb00` inventory resolves aggregate CPU, memory,
      storage, domain, network, address, port, and retained-service state.
      The selected topology has an explicit resource budget and safety margin,
      and no existing domain, Harbor, host HAProxy, network, storage object, or
      retained RGW service is mutated.
- [ ] A fail-closed provision/deploy/verify/destroy harness creates only
      allowlisted, autostart-disabled Stage 5 domains and dedicated volumes,
      addresses, TLS material, identities, buckets, and client state. Kolla's
      bootstrap registry remains independent from the tenant Coffer registry.
- [ ] At least three Kolla controller nodes provide Galera quorum and
      HAProxy/VIP service. At least two healthy replicas each of Coffer API,
      edge, and Distribution are reachable only through the intended internal
      or external HAProxy routes; direct tenant access to API or Distribution
      fails.
- [ ] The storage dependency is a separately provisioned disposable Ceph/RGW
      HA topology with a stable verified-TLS endpoint and redundant data path.
      Using the retained one-node `coffer-rgw-poc` can support an intermediate
      functional check but cannot satisfy this criterion.
- [ ] Deterministic OCI push, pull, resumable upload, repository isolation,
      quota admission, catalog, health, and digest persistence pass while
      removing one API, edge, Distribution, HAProxy, and RGW replica at a time.
      Requests continue through surviving backends without exposing a bypass
      or silently weakening authorization.
- [ ] Galera-backed repository and quota writes survive one database-member
      loss, concurrent admission, deadlock or certification retry, and member
      recovery. Reconciliation workers prove disjoint claims, abandoned-claim
      recovery, and stale-fencing-token rejection across separate hosts.
- [ ] JWT signing keys rotate with an overlap window: existing bounded tokens
      remain valid while both public keys are advertised, newly issued tokens
      use the new key, and the old key is removed only after its maximum token
      lifetime. Private-key recipients and logs remain correct.
- [ ] A rolling Coffer image/configuration update preserves service and
      accepted digests, repeat migration remains safe, and a compatible image
      rollback is rehearsed. An incompatible-schema path stops and exercises
      the documented maintenance/restore decision instead of invoking a blind
      Alembic downgrade.
- [ ] Exact Stage 5 resources and credentials are removed after retained,
      redacted aggregate evidence passes. Repository-wide focused tests,
      Ansible/config/template checks, secret scans, local-link checks, diff
      checks, and remote residue audits pass.

## Non-goals

- Promoting either candidate image to production, waiving ADR 0006, carrying a
  private Distribution fork, or claiming closure of Stage 6 security,
  conformance, KMS, backup/cutover, load, observability, GC, or operations
  gates.
- Reusing the tenant registry as Kolla's bootstrap registry, installing Kolla
  or Coffer directly on `bb00`, or coupling the pilot to existing Harbor or
  host HAProxy.
- Mutating or repurposing `coffer-rgw-poc`, unrelated domains, networks,
  storage pools, DHCP reservations, host services, credentials, or data.
- Destructive object GC, production data access, production credential use,
  official Kolla/Kolla-Ansible upstream work, issue or PR creation, releases,
  or image publication.
- Treating a two-node database, a single RGW daemon, colocated storage without
  failure-domain evidence, or one successful failover as an HA result.

## Context and Evidence

- Stages 1 through 4 are published on `main` through commit `4f1ff7d`.
  Stage 4 proved a complete disposable Kolla AIO tenant path, but intentionally
  excluded multinode behavior, Galera, replica failure, key overlap, rolling
  upgrade, and rollback.
- Plan 0017 provides a reproducible image qualification harness. The Coffer
  image has zero Critical/High findings in its executed ARM64 baseline, but the
  signed Distribution v3.1.1 release retains reachable vulnerabilities.
  Stage 5 may use the pinned functional artifacts only as explicitly
  non-production pilot inputs.
- Accepted ADR 0014 fixes the sole-ingress edge, private API/Distribution
  backends, HAProxy origins, verified TLS boundaries, one-shot Alembic owner,
  per-process secret recipients, and external-RGW dependency.
- Plans 0004 through 0006 already prove shared-SQL quota transactions,
  claims, fencing, process abandonment, bounded deadlock retry, and the
  reconciler process in disposable single-host database fixtures. Stage 5 must
  exercise those contracts across real Galera members and separate workers.
- `bb00` is a shared KVM substrate. Earlier snapshots showed capacity for
  bounded disposable guests, but those values are time-sensitive and must be
  refreshed before selecting or creating any Stage 5 resource.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Keep Stage 5 active until both Coffer/Kolla and external RGW failure domains have HA evidence | A resilient edge over a single storage endpoint is not an end-to-end registry HA result | Closing Stage 5 with only replicated API/edge; relabeling the retained one-node RGW as HA | 2026-07-24 |
| Prefer three controller nodes and an independent three-node storage topology, subject to the refreshed safety budget | Three members provide Galera and storage quorum while permitting one bounded member loss | Two-node quorum designs; direct installation on the shared host; unreviewed controller/storage colocation | 2026-07-24 |
| Allow a non-HA RGW intermediate track only as partial evidence | It can de-risk Kolla multinode automation without overstating the completed failure domain | Blocking all controller work until storage exists; treating partial evidence as the exit gate | 2026-07-24 |
| Use production-shaped TLS, routing, and secret recipients but retain the functional image label | HA behavior should exercise the intended network contract, while image security provenance remains honestly blocked | Plaintext cross-host backends; weakening ADR 0006; publishing an unapproved candidate | 2026-07-24 |
| Define every disruptive test as a bounded, allowlisted fault with an explicit restore assertion | The host is shared and a generic kill/destroy command is too broad | Free-form chaos testing; host-level service disruption; implicit cleanup | 2026-07-24 |

## Tasks

- [x] Refresh the shared-host inventory read-only and select a topology,
      address plan, capacity budget, failure domains, and stop conditions.
- [x] Add the secret-safe Stage 5 host-audit and exact provision/destroy
      harnesses, then prove dry-run and negative-target behavior locally.
- [ ] Provision the isolated storage and controller guests, bootstrap external
      Ceph/RGW HA and Kolla multinode, and record only aggregate health facts.
- [ ] Build or resolve immutable functional pilot images through the
      independent bootstrap path and deploy the Coffer companion role with
      production-shaped TLS and private backends.
- [ ] Run baseline catalog, two-project OCI, resumable upload, quota,
      non-bypass, digest, replica distribution, and secret/log acceptance.
- [ ] Run allowlisted replica, Galera, RGW, reconciler fencing, signing-key
      overlap, rolling-upgrade, compatible rollback, and recovery rehearsals.
- [ ] Remove exact pilot resources, verify shared-host and credential residue,
      run final regressions, and close the plan and handoff.

## Progress Log

### 2026-07-24 — Stage 5 activated

- Completed: Published the completed Stage 4 AIO work and plan 0017 image
  qualification as scoped commits `ae82f32` and `4f1ff7d`; verified local and
  remote `main` match at `4f1ff7d`; activated this fresh Stage 5 plan.
- Evidence: The worktree was clean after the atomic push. The accepted stage
  table defines replica loss, rolling upgrade, Galera, key overlap, load
  balancing, fencing, and rollback as Stage 5 exit evidence.
- Decision: Require independent external RGW HA for completion, but permit a
  clearly labeled controller-only intermediate track if refreshed host
  capacity cannot safely support both topologies concurrently.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Add `poc/kolla-ha/inventory-host.sh` as a bounded
  read-only, secret-safe aggregate inventory command; validate its shell
  syntax and run it through the user-supplied direct SSH path without changing
  any remote state.

### 2026-07-24 — Host inventory and preferred topology selected

- Completed: Added and locally validated the secret-safe host inventory
  harness. It tolerates this host's older libvirt name/unit formats, uses the
  caller's unprivileged libvirt/docker access, restricts Docker evidence to
  name/image/status/ports, and retains output only under ignored `work/`.
- Evidence: `bb00` reports x86_64, 64 logical CPUs, 251.6 GiB total and
  123.8 GiB available RAM, no swap, and 876.5 GiB available under `/srv/nfs`.
  All 18 domains are running with 82 allocated vCPUs and 244 GiB configured
  maximum guest RAM. The `coffer-rgw` pool is running with about 896.6 GiB
  available and contains only the three retained `coffer-rgw-poc` volumes.
  There are no Stage 5 domains or volumes; `coffer-rgw-poc` remains running
  with autostart disabled.
- Network decision: The crowded default `192.168.122.0/24` network is not
  reused. Host operational state has no `192.168.252.0/24`,
  `192.168.253.0/24`, or `192.168.254.0/24` interface, so the declared
  management, storage, and external Stage 5 networks use those isolated
  ranges without binding shared-host ports.
- Capacity decision: Select three 8-vCPU/16-GiB/96-GiB controller guests and
  three 4-vCPU/8-GiB storage guests with 32-GiB roots and 64-GiB OSDs. The
  complete 36-vCPU, 72-GiB RAM, 576-GiB logical-disk budget leaves about
  51.8 GiB currently available RAM and 300 GiB filesystem capacity. Preflight
  must still abort if the live post-allocation margins would fall below
  40 GiB RAM or 250 GiB storage.
- Failure: The supplied direct Tailscale address was not a current local
  tailnet peer and timed out; the existing `bb00` LAN alias was reachable.
  The first two harness runs also exposed noninteractive-sudo and older-virsh
  formatting assumptions. All failed before state mutation and were corrected.
- Changed files: Added `poc/kolla-ha/inventory-host.sh`,
  `poc/kolla-ha/topology.yml`, and `poc/kolla-ha/README.md`; updated this plan,
  topology documentation, and `HANDOFF.md`.
- Next exact action: Add `poc/kolla-ha/provision.sh preflight` to validate the
  schema, live safety margins, image checksum, and exact absence of every
  declared domain, volume, network, bridge, MAC, IP, and host route. It must
  implement no create or destroy action yet.

### 2026-07-24 — Mutation-free provision preflight implemented

- Completed: Extended the inventory with host IPv4 state and domain-interface
  MAC evidence, then added `poc/kolla-ha/provision.sh` with only one accepted
  action: `preflight`. It recomputes the declared resource budget and rejects
  insufficient live margins, schema drift, unresolved image input, or any
  collision in the domain, volume, network, bridge, subnet, IP, MAC, pool, or
  architecture contract.
- Evidence: Bash syntax and ShellCheck pass for both Stage 5 scripts. Missing
  and option-shaped targets return 64 without SSH. Against the live read-only
  snapshot, every capacity and collision test passed and the command returned
  1 with exactly one expected reason:
  `image.sha256 must be a resolved lowercase SHA-256`.
- Safety: The harness has no create or destroy action and the remote command
  surface remains read-only. No VM, network, volume, route, service, identity,
  credential, or configuration changed.
- Changed files: `poc/kolla-ha/inventory-host.sh`,
  `poc/kolla-ha/provision.sh`, this plan, and `HANDOFF.md`.
- Next exact action: Resolve the official Ubuntu Noble current image and
  `SHA256SUMS` from `cloud-images.ubuntu.com`, pin the exact lowercase digest
  in `poc/kolla-ha/topology.yml`, and rerun `provision.sh preflight bb00`.
  Do not add create behavior until the pinned preflight passes.

### 2026-07-24 — Immutable image input and live preflight passed

- Completed: Resolved Ubuntu Noble daily build `20260705` from the official
  cloud-image index, verified the x86_64 QCOW2 digest against both the
  official `current/SHA256SUMS` and date-fixed
  `20260705/SHA256SUMS`, and replaced the mutable source path with the
  date-fixed URL plus SHA-256.
- Evidence: `provision.sh preflight bb00` now passes with six planned domains
  and 36 vCPUs. The live snapshot predicts 51.8 GiB memory, 300.5 GiB
  filesystem, and 320.6 GiB libvirt-pool capacity remaining after the complete
  declared budget, all above the configured 40/250/250 GiB stop thresholds.
- Safety: The passed command remained read-only. No create, destroy, upload,
  network definition, volume definition, or domain definition exists in the
  harness yet.
- Changed files: Pinned `poc/kolla-ha/topology.yml`; updated this plan and
  `HANDOFF.md`.
- Next exact action: Commit the completed Stage 5 plan/inventory/preflight
  baseline locally, then add paired exact-target `create`, `status`, and
  `destroy` implementations with partial-create rollback. Do not invoke
  `create` until those actions pass local syntax, schema, negative-target, and
  allowlist review.

### 2026-07-24 — Exact libvirt lifecycle harness validated

- Completed: Preserved the plan/inventory/preflight baseline in local commit
  `1a78bd7`. Extracted the preflight validator, added a standard-library remote
  libvirt helper, and extended the wrapper with explicit
  `preflight|status|create|destroy` actions.
- Safety contract: The remote helper independently hard-codes the six domain,
  three network/bridge, pool, base-volume, and MAC-prefix allowlists. Create
  rechecks absence, verifies the date-pinned image before upload, leaves
  networks/domains autostart-disabled, and rolls back only the resources
  appended by that invocation. Destroy names every resource exactly, removes
  domains before volumes and networks, and never uses globs,
  `--remove-all-storage`, or prefix-selected deletion.
- Evidence: Bash syntax, ShellCheck, Python compilation, good/bad allowlist,
  six-domain/16-volume derivation, NAT/isolated XML, controller/storage NIC
  rendering, exact destroy, and partial rollback contracts pass. The remote
  host has all four required tools and three usable public keys. A fresh
  preflight passes; read-only remote status reports all six domains, sixteen
  volumes, and three networks absent.
- Limitation: Ruff is not installed in the locked project environment, so that
  optional style command could not start. Python compilation and the executable
  harness verification passed; no dependency was added merely for this check.
- Safety: Neither create nor destroy has been invoked. No remote state changed.
- Changed files: Added `poc/kolla-ha/preflight.py`,
  `poc/kolla-ha/libvirt_remote.py`, and `poc/kolla-ha/verify.py`; updated the
  provision wrapper, README, this plan, and `HANDOFF.md`.
- Next exact action: Commit the paired lifecycle harness locally, rerun
  `provision.sh preflight bb00` and `provision.sh status bb00`, then invoke
  `provision.sh create bb00` once. On any failure, verify its automatic
  rollback with read-only status before making a correction.

### 2026-07-24 — Six isolated Stage 5 guests provisioned

- Completed: Preserved the lifecycle harness in local commit `5326093`, reran
  clean preflight/status, and invoked the exact create action once. It
  downloaded and verified the pinned Ubuntu image, defined three dedicated
  networks, created one shared base plus fifteen guest volumes, and started
  three controller and three storage guests.
- Evidence: All six domains are running with autostart disabled; all three
  networks are active with autostart disabled on the exact `virbr252` through
  `virbr254` bridges. Controllers report 8 vCPUs, about 16 GiB RAM, and one
  disk. Storage guests report 4 vCPUs, about 8 GiB RAM, and separate root/OSD
  disks. Every guest completed cloud-init, has the planned management/storage
  addresses, active qemu guest agent, correct external-NIC shape, and x86_64
  architecture.
- Host safety: After first boot the shared host still reported about 119 GiB
  available RAM and 876 GiB free under `/srv/nfs`; no shared-host port was
  bound. The retained `coffer-rgw-poc` and all unrelated resources were
  untouched.
- Correction: The first status JSON named the Boolean
  `autostart` while its value meant “disabled.” Renamed it to
  `autostart_disabled` and verified it is true for every domain.
- Changed files: Added `poc/kolla-ha/verify-guests.sh`; corrected the status
  schema field; updated README, this plan, and `HANDOFF.md`.
- Next exact action: Reuse the pinned Ceph Tentacle inputs and safe cephadm
  download pattern from `poc/rgw/`, then add a three-node storage preparation
  and Ceph/RGW HA bootstrap harness. Its first executable phase must only
  install prerequisites, establish planned hostname resolution, and verify
  that `/dev/vdb` is the sole empty OSD candidate on each storage guest.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Published Stage 4/image baseline | local and remote Git commit equality | passed at `4f1ff7d` |
| Host capacity and namespace | bounded read-only Stage 5 audit | passed |
| Mutation-free provision preflight | schema, budget, namespace, network, and image gates | passed |
| Libvirt lifecycle safety | allowlists, exact destroy, partial rollback, remote status | passed; exact create completed |
| Guest provisioning and readiness | exact status, autostart, cloud-init, NIC, disk, and resource checks | passed |
| Provision/destroy target safety | local allowlist, rollback, and negative-target tests | passed |
| Kolla/Galera/Coffer baseline | multinode deploy and health acceptance | pending |
| External RGW HA | quorum, TLS endpoint, object and replica-loss acceptance | pending |
| OCI and isolation | two-project clients through sole external edge | pending |
| Fault and recovery matrix | allowlisted per-replica failures and restore checks | pending |
| Upgrade, key rotation, rollback | bounded rolling rehearsals | pending |
| Cleanup and repository regression | exact remote/local residue and focused checks | pending |

## Failures, Blockers, and Risks

- The latest signed Distribution v3.1.1 binary remains production-blocked.
  Stage 5 HA evidence cannot override the image gate.
- Capacity and unrelated guest load on `bb00` are time-sensitive. No Stage 5
  topology is selected until the read-only audit demonstrates a conservative
  host margin.
- A six-guest preferred topology may exceed safe concurrent memory or storage.
  If so, execute independent storage and controller tracks only when their
  failure claims remain valid, or obtain a different isolated substrate;
  never silently collapse quorum or failure domains.
- Cross-host TLS, Galera recovery, Ceph quorum, and rolling changes can fail in
  long-running ways. Every harness phase needs bounded timeouts, persistent
  aggregate evidence, exact target allowlists, and recovery before continuing.
- The production reconciliation maintenance identity remains unresolved.
  Stage 5 may use a disposable, least-privilege pilot identity but cannot
  convert it into the production decision.

## Handoff

- Current state: Active; all six autostart-disabled guests are running and
  readiness-verified on three dedicated autostart-disabled networks.
- Exact next action: Add the bounded storage-node preparation phase and verify
  the three empty `/dev/vdb` OSD candidates before Ceph bootstrap.
- First file or command: `poc/kolla-ha/prepare-storage.sh`.
- Questions requiring user input: None for read-only inventory and local
  harness work. Ask before expanding to a different substrate, production
  credentials/data, a private Distribution fork, external publication, or an
  operation outside the exact disposable Stage 5 allowlist.
