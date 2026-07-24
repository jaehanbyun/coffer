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
- [x] Provision the isolated storage and controller guests, bootstrap external
      Ceph/RGW HA and Kolla multinode, and record only aggregate health facts.
- [x] Build or resolve immutable functional pilot images through the
      independent bootstrap path and deploy the Coffer companion role with
      production-shaped TLS and private backends.
- [x] Run baseline catalog, two-project OCI, resumable upload, quota,
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

### 2026-07-24 — Three storage nodes prepared without Ceph mutation

- Completed: Reused the retained SHA-256-verified cephadm 20.2.2 artifact and
  pinned Ceph image digest. Added a storage-only preparation harness that
  copies the public artifact, installs chrony/LVM/Podman/Skopeo prerequisites,
  owns one marker-bounded hostname block, and verifies the sole OSD candidate
  without initializing it.
- Evidence: All three nodes report chrony active, the three storage names
  resolving to their `192.168.253.31` through `.33` addresses, `/dev/vdb`
  exactly 64 GiB with no partition, filesystem signature, mount, or LVM PV,
  the expected cephadm and image digests, no Ceph configuration, and zero
  containers.
- Failure and correction: The first run wrote the intended marker but failed
  before package installation because cloud-init's `127.0.1.1 <hostname>`
  entry won name resolution. The corrected script disables future cloud-init
  hosts rewriting and removes only a Stage 5 storage hostname's loopback alias
  before installing the exact storage map. The idempotent rerun passed.
- Safety: No `cephadm bootstrap`, disk wipe, LVM creation, OSD initialization,
  container start, RGW service, identity, or credential operation has occurred.
- Changed files: Added `poc/kolla-ha/prepare-storage.sh` and
  `poc/kolla-ha/guest-prepare-storage.sh`; updated this plan and `HANDOFF.md`.
- Next exact action: Add a three-node Ceph bootstrap harness that bootstraps
  only storage-1 on `192.168.253.31`, adopts storage-2/3 through cephadm's
  generated SSH key, applies three MONs and two MGRs, and stops before OSD or
  RGW creation. Validate the exact host and service allowlists locally before
  invoking it.

### 2026-07-24 — MON/MGR-only Ceph bootstrap harness validated

- Completed: Preserved storage preparation in local commit `56f6af2`. Added a
  four-part control-plane harness: pinned primary bootstrap, marker-bounded
  cephadm public-key authorization on the two secondary nodes, exact host
  adoption, and explicit three-MON/two-MGR placement and readiness.
- Safety contract: The bootstrap pins Ceph 20.2.2 and its image digest, uses
  storage-1 and `192.168.253.31` only as the initial monitor, sets default
  replica size 3/minimum 2, and requires zero OSDs before and after this phase.
  The secondary authorization script accepts only storage-2/3 and only one
  valid public key. Host adoption permits only the three declared hostnames and
  ends by proving RGW count zero.
- Evidence: Bash syntax, ShellCheck, missing/option-shaped target refusal, and
  a static negative scan for OSD create/zap/wipe/RGW commands pass. Read-only
  Tentacle CLI inspection confirms the selected bootstrap, placement, dry-run,
  format, host-label, and daemon-type options.
- Safety: The new bootstrap harness has not been invoked. The three OSD devices
  remain empty and no Ceph configuration or container exists.
- Changed files: Added `bootstrap-ceph-control.sh`,
  `guest-bootstrap-ceph-primary.sh`, `guest-authorize-cephadm.sh`, and
  `guest-adopt-ceph-hosts.sh`; updated this plan and `HANDOFF.md`.
- Next exact action: Commit the MON/MGR-only harness locally, rerun the storage
  empty-device assertions, then invoke `bootstrap-ceph-control.sh bb00` once.
  If it fails, inspect aggregate cluster/host/daemon state and do not proceed
  to OSD work.

### 2026-07-24 — First MON bootstrap failed safely

- Failure: The first control-plane invocation installed the exact
  `cephadm 20.2.2-1noble` package and pulled the digest-pinned Ceph image, but
  failed before creating the initial MON with
  `RuntimeError: Please call get_version first`.
- Root cause: Tentacle's `command_bootstrap` is excluded from the top-level
  container-engine check because normal bootstrap calls `prepare-host`, which
  initializes the Podman version. The harness passed `--skip-prepare-host`, so
  both paths were skipped and `supports_split_cgroups` read an uninitialized
  version.
- Safety evidence: cephadm's automatic non-OSD cleanup completed. All three
  `/dev/vdb` devices remain signature-free and absent from LVM; all three
  nodes have zero Ceph containers, FSID data directories, Ceph configuration,
  admin keyrings, and cephadm authorization markers.
- Correction: Removed only `--skip-prepare-host`. The nodes are already
  explicitly prepared, so normal bootstrap now performs the upstream
  prerequisite and container-engine checks while retaining the dashboard,
  monitoring, OSD, and RGW exclusions.
- Intermediate result: The corrected bootstrap created one healthy initial
  MON and MGR, but the wrapper returned before host adoption. Because the guest
  scripts are streamed to `bash -s`, the first interactive `cephadm shell`
  process consumed the remaining script lines from stdin. Read-only inspection
  found exactly one registered host, one running MON, one running MGR, zero
  OSDs, and zero RGW services. The three OSD devices remain empty.
- Second correction: Every `cephadm shell` call inside a streamed guest script
  now receives `/dev/null` explicitly. The public-key read also has closed
  stdin. This preserves the script stream and makes the partially completed
  state safe to resume idempotently.
- Intermediate result: The stdin-corrected resume registered both secondary
  hosts and applied all bounded labels, but the immediate MON placement
  dry-run raced the orchestrator host cache and rejected storage-3 as an
  unknown host. No MON/MGR placement change was applied. Subsequent aggregate
  inspection found all three registered hosts healthy, one MON, one MGR, zero
  OSDs, zero RGW services, and all three OSD devices still empty.
- Third correction: Added a bounded pre-placement poll that requires all three
  exact hostnames to appear with an empty orchestrator status before any
  service dry-run or apply.
- Next exact action: Validate and commit the host-readiness gate, then
  idempotently rerun the control bootstrap to reach three MONs/two MGRs.

### 2026-07-24 — Ceph control plane reached quorum

- Completed: Preserved the readiness correction in local commit `8950680` and
  idempotently resumed the harness. All three exact storage hosts are healthy;
  MONs run on storage-1/2/3 with quorum 3, and MGRs run on storage-1/2.
- Safety evidence: `ceph osd stat` remains zero and no RGW service exists.
  Every `/dev/vdb` remains signature-free and absent from LVM. Only storage-1
  has the owner-mode admin keyring; storage-2/3 have exactly one bounded
  cephadm public-key marker and no admin keyring.
- Configuration: The cluster config database retains
  `osd_pool_default_size=3`, `osd_pool_default_min_size=2`, and
  `mon_target_pg_per_osd=50`.
- HA check: A bounded failover promoted the ready storage-2 MGR while both MGR
  daemons remained running.
- Health resolution: `TOO_FEW_OSDS` is the sole expected warning before the
  next phase. Tentacle's source fixes stray evaluation to a 30-minute default
  interval, so warnings created before the service specs remained stale even
  after `orch ps --refresh` and MGR failover. A bounded temporary 30-second
  interval forced a fresh evaluation; both stray warnings cleared, and the
  option was removed to restore the effective 1800-second default. No warning
  was disabled or muted.
- Next exact action: Add an OSD-only harness that admits exactly `/dev/vdb` on
  the three allowlisted storage hosts, proves one `up`/`in` OSD per host and
  size/min-size 3/2, and leaves RGW absent.

### 2026-07-24 — Exact-device OSD harness validated

- Completed: Added a separate wrapper and streamed guest phase for OSD
  initialization. It requires the three-host MON quorum, two running MGRs,
  replica defaults 3/2, no RGW service, and an exact healthy storage-host set
  before any disk mutation.
- Safety contract: The only admitted path is `/dev/vdb` on the three hard-coded
  hostnames. The harness rejects unexpected or duplicate OSD metadata,
  verifies the selected device is available, rejection-free, and exactly
  64 GiB before creation, and never uses all-available-device selection,
  wildcard hosts, zap, wipe, remove, or raw LVM commands.
- Resume contract: Existing OSD metadata may contain zero through three
  allowlisted hosts with at most one OSD each. The harness creates only a
  missing host's exact device and waits for that OSD to become managed and
  running before considering the next host.
- Exit gate: Exactly three OSDs must be running, `up`, and `in`, with one
  metadata hostname per storage host, `HEALTH_OK`, and zero RGW services.
- Evidence: Bash syntax, ShellCheck, missing/option-shaped target refusal,
  exact-path/static destructive-command scans, Markdown diff checks, and
  Gitleaks pass. Live read-only inventory reports exactly one available,
  rejection-free 64-GiB `/dev/vdb` on each allowlisted host.
- Safety: The OSD harness has not been invoked; all three devices remain empty.
- Next exact action: Commit the OSD-only harness locally, recheck the live
  device inventory and sole expected `TOO_FEW_OSDS` health warning, then
  invoke `poc/kolla-ha/bootstrap-ceph-osds.sh bb00` once.

### 2026-07-24 — Three-host replicated OSD baseline complete

- Completed: Preserved the exact OSD harness in local commit `831b66b` and
  invoked it once. It created OSD 0, 1, and 2 sequentially on storage-1, -2,
  and -3, waiting for each managed daemon before touching the next host.
- Evidence: Independent aggregate verification reports exactly three OSDs,
  all running, `up`, and `in`; the metadata mapping is one OSD per exact host;
  the replicated CRUSH rule chooses the `host` failure domain; every pool is
  size 3/minimum 2; the single current PG is active and clean; cluster health
  is `HEALTH_OK`; and RGW count remains zero.
- Device evidence: Each host has exactly one `/dev/vdb` LVM PV and one running
  OSD container. No other data-device path was admitted.
- Idempotency: A second full harness invocation made no OSD addition and
  returned the same three-host, three-up/in, healthy, zero-RGW result.
- Next exact action: Add and validate a separate RGW/ingress phase with one RGW
  daemon per storage host, two ingress daemons, the reserved
  `192.168.253.30` VIP, verified TLS, and no S3 identity creation yet.

### 2026-07-24 — RGW HA service harness validated

- Completed: Added a dedicated RGW/ingress phase. It first requires healthy
  3-MON/2-MGR/3-OSD state, then places one RGW on each storage host over
  backend port 9443 and two HAProxy/Keepalived pairs on storage-1/2 with
  frontend VIP `192.168.253.30:8443`.
- TLS boundary: RGW backends use Ceph's generated service certificate and are
  independently checked with the public cephadm root CA. The ingress frontend
  uses a 14-day lab CA and leaf generated owner-only on storage-1, with only
  the public CA exported to ignored `work/kolla-ha/`. The leaf SAN is the
  stable lab DNS name plus the VIP. Untrusted TLS and plaintext on the TLS port
  must fail.
- Secret boundary: No private key enters the repository or command arguments.
  The ingress CA/server keys stay mode 0600 under `/etc/ceph` on storage-1;
  HAProxy receives only its required leaf key through the Ceph service spec.
  S3 user and bucket creation are excluded and final user count must remain
  zero.
- Exit gate: Three running RGWs, two running HAProxy, two running keepalived,
  exactly one live VIP owner, verified backend/frontend TLS, all PGs active
  and clean, pool size/minimum 3/2, zero S3 users, and `HEALTH_OK`.
- Evidence: Bash syntax, ShellCheck, missing/option-shaped target refusal,
  secret/destructive-command scans, Gitleaks, and diff checks pass. The exact
  RGW spec dry-run passes. Live preflight reports zero RGW/ingress daemons,
  zero users/VIP owners, and ports 9443/8443/1967 free on all three hosts.
- Safety: Neither RGW nor ingress apply has run.
- Next exact action: Commit the RGW HA harness locally and invoke
  `poc/kolla-ha/bootstrap-ceph-rgw.sh bb00` once. On failure, retain aggregate
  service/VIP/TLS/health evidence and do not create an S3 identity.

### 2026-07-24 — Three-RGW redundant TLS endpoint complete

- Completed: Preserved the RGW HA harness in local commit `1f0e6e9` and
  invoked it. RGW runs on storage-1/2/3 over verified backend TLS; HAProxy and
  Keepalived run on storage-1/2; exactly one host owns
  `192.168.253.30:8443`.
- TLS evidence: Each backend passed hostname verification with the cephadm
  public root CA. The VIP passed the owner-only lab CA from both storage-1 and
  an independent Mac-to-`bb00` tunnel, while an untrusted client and plaintext
  HTTP on the TLS port failed. The exported public CA contains no private key
  and remains ignored under `work/kolla-ha/`.
- Storage evidence: Five RGW/system pools retain size/minimum 3/2, all 129 PGs
  are active and clean, and cluster health is `HEALTH_OK`.
- Identity boundary: `radosgw-admin user list` remains empty. No S3 user,
  access key, bucket, or object was created by this phase.
- Idempotency: A second complete invocation retained three RGWs, two ingress
  pairs, one VIP owner, the same owner-only certificate set, zero users, and
  healthy storage without adding a service.
- Next exact action: Add a separate least-privilege S3 fixture phase. Create
  owner-only registry and denial identities with one bucket each, prove
  anonymous/cross-owner/extra-bucket denial, and retain a known-digest private
  sentinel for later replica-loss tests without printing credentials.

### 2026-07-24 — Isolated S3 fixture harness validated

- Completed: Added a separate wrapper, owner-only guest provisioner, and
  standard-library/boto3 acceptance helper for the disposable registry and
  denial identities. The phase creates exactly one bucket per identity,
  retains a deterministic 4-MiB private sentinel, and emits only aggregate
  status and its non-secret digest.
- Secret boundary: The two RGW user records and future Distribution S3
  environment are mode `0600` under `/etc/coffer-stage5-rgw` on storage-1.
  The wrapper removes its temporary helper and asserts that storage-2/3 have
  no fixture directory. Existing owned keys must retain their hashes on a
  rerun; a pre-existing unowned user or orphan credential file fails closed.
- Acceptance contract: Anonymous access, cross-owner access, and a second
  registry bucket must fail. A pre-existing sentinel must retain the expected
  size and SHA-256 metadata before it is read and verified; it is never
  silently replaced.
- Evidence: Bash syntax, ShellCheck, Python compilation, target refusals,
  source secret scans, AST fixture constants, Gitleaks, and diff checks pass.
  Live read-only preflight reports `HEALTH_OK`, boto3 present, zero S3 users,
  zero buckets, and no fixture state on any storage node.
- Safety: The S3 fixture harness has not been invoked. No identity, key,
  bucket, object, or credential file exists yet.
- Next exact action: Commit the validated fixture harness locally, recheck the
  zero-state preflight, then invoke
  `poc/kolla-ha/provision-ceph-s3.sh bb00` once and immediately rerun it to
  prove credential and sentinel idempotency.

### 2026-07-24 — Private S3 HA fixture complete

- Completed: Preserved the fixture harness in local commit `8d7c4bd`, passed a
  fresh zero-state preflight through `jh.byun@100.123.168.66`, and invoked the
  committed phase twice.
- Isolation evidence: Anonymous and registry-to-denial bucket requests both
  returned 403. A second bucket for the registry identity was rejected with
  400. The identities expose no admin caps, retain maximum one bucket and one
  key each, and own only their corresponding bucket.
- Persistence evidence: The retained private object is 4 MiB with SHA-256
  `543e845c8c7185da3bc04a566b068274825c837a740d029726b169481b919e50`.
  Both invocations read back that digest. The second invocation verified the
  existing credentials and object metadata instead of rotating or replacing
  them.
- Secret and health evidence: Independent inspection found the directory mode
  0700 and all three credential/config files root-owned mode 0600 on
  storage-1. The temporary helper is absent; storage-2/3 have no credential
  directory. Three RGWs and two HAProxy daemons remain running, all PGs are
  active and clean, and Ceph is `HEALTH_OK`.
- Next exact action: Implement the least disruptive bounded fault phase first:
  stop one exact RGW replica, verify the sentinel through the surviving VIP,
  restore it, then stop the exact active ingress pair, prove one VIP owner and
  sentinel access after failover, and restore the pair. Do not power off a
  storage VM until daemon-level recovery is complete.

### 2026-07-24 — Daemon-level RGW fault harness validated

- Completed: Added a read-only sentinel helper and a paired local/guest fault
  harness. Live Ceph inventory resolves exactly one allowlisted daemon name per
  expected host and type; no random suffix is accepted without matching its
  exact service, type, and hostname.
- Fault boundary: The first phase may stop only the RGW on storage-3. The
  second may stop only the Keepalived and HAProxy daemons on the current VIP
  owner among storage-1/2. MON, MGR, OSD, VM, network, and unrelated host
  service commands are absent. Five read-only sentinel downloads are required
  under each fault.
- Recovery boundary: The wrapper sets its mutation marker before the first
  stop. Any later error invokes an exact `restore-all` action through the EXIT
  trap. Normal restoration starts all three expected RGWs and both HAProxy
  pairs before both Keepalived daemons, then requires clean PGs and
  `HEALTH_OK`.
- Evidence: Bash syntax, ShellCheck, Python compilation, target/action
  refusals, forbidden-command scans, Gitleaks, and diff checks pass. A live
  preflight resolves the current randomized daemon names, reports 3/2/2
  running daemons and `HEALTH_OK`, reads the expected sentinel digest, and
  removes both temporary helpers.
- Failure corrected before mutation: The initial live preflight copied local
  basenames while expecting distinct remote names, so execution failed before
  daemon inventory. The wrapper now specifies each destination path and the
  two stray temporary files were removed. A traced rerun and the final clean
  preflight passed.
- Safety: No daemon stop/start action has been invoked by this harness.
- Next exact action: Commit the validated daemon-fault harness locally, rerun
  its healthy preflight implicitly, then invoke
  `poc/kolla-ha/test-ceph-rgw-failover.sh
  jh.byun@100.123.168.66` once. Independently verify full service, VIP, PG,
  health, sentinel, and temporary-file restoration before considering a whole
  storage-VM fault.

### 2026-07-24 — RGW and ingress daemon failures recovered

- Completed: Preserved the exact daemon-fault harness in local commit
  `094b597` and ran its complete sequence through the direct `bb00` address.
- RGW evidence: The storage-3 RGW stopped while exactly two RGWs remained
  running. Five consecutive read-only sentinel round trips passed through the
  VIP with the accepted digest. The exact replica restarted, the running count
  returned to three, and Ceph returned to `HEALTH_OK`.
- Ingress evidence: Storage-1 was the active VIP owner. Its exact Keepalived
  and HAProxy daemons stopped while one complete pair survived on storage-2.
  The VIP moved to storage-2 and five consecutive sentinel round trips passed.
  Both pairs then returned to service.
- Independent recovery audit: Three RGWs, two HAProxy, and two Keepalived
  daemons are running; exactly one node owns the VIP; all PGs are active and
  clean; Ceph is `HEALTH_OK`; and the sentinel retains its 4-MiB size and
  accepted digest. Fault and audit helpers are absent, and storage-2/3 retain
  no credential directory.
- Next exact action: Add a separate exact-target whole-VM fault harness for
  storage-3. It must verify the target is the declared autostart-disabled
  domain, shut down only that domain, prove two-MON quorum/two OSDs/two RGWs
  and sentinel reads through the unchanged VIP, start the same domain, and
  require full 3-MON/3-OSD/3-RGW/clean-PG recovery. Do not combine this with
  any controller or ingress-host failure.

### 2026-07-24 — Exact storage-3 VM fault harness validated

- Completed: Added an independent libvirt remote helper, primary-node Ceph
  audit, and local lifecycle wrapper for only
  `coffer-rgw-ha-stage5-storage-3`.
- Libvirt boundary: Before any action, the helper verifies the exact persistent
  domain name, disabled autostart, no managed save, 4 vCPUs, 8 GiB memory,
  root/OSD/seed filenames, two exact MAC/network pairs, and the running state
  of all other five Stage 5 domains. The fault is one exact `virsh destroy`
  power-off simulation; restoration is one exact `virsh start`. No undefine,
  storage, network, or other-domain mutation exists.
- Ceph boundary: During outage the audit requires only storage-1/2 in MON
  quorum, two of three OSDs up while all remain in, two RGWs, both ingress
  pairs, zero inactive PGs, `HEALTH_WARN`, one VIP owner, and five sentinel
  reads. Recovery requires quorum 3, three up/in OSDs, three RGWs, both
  ingress pairs, only clean PGs, `HEALTH_OK`, and the accepted sentinel.
- Recovery boundary: The wrapper marks the fault before power-off. Its EXIT
  trap starts the exact target, waits for its management SSH, attempts the
  complete healthy Ceph gate, and removes both temporary audit helpers.
- Evidence: Bash syntax, ShellCheck, Python compilation, target refusals,
  AST allowlist checks, forbidden-command scans, Gitleaks, and diff checks
  pass. Live mutation-free preflight validates the exact libvirt XML and five
  other running domains; the healthy Ceph and sentinel gates pass; helpers are
  absent afterward.
- Safety: `virsh destroy` and `virsh start` have not been invoked by this
  harness.
- Next exact action: Commit the VM-fault harness locally, then invoke
  `poc/kolla-ha/test-ceph-storage-vm-failover.sh
  jh.byun@100.123.168.66` once. Independently audit full recovery before any
  controller/Kolla mutation.

### 2026-07-24 — Storage-3 power-loss and recovery passed

- Completed: Preserved the exact VM-fault harness in local commit `9e9792d`
  and ran one complete storage-3 abrupt power-loss/recovery cycle.
- Outage evidence: Only storage-3 became `shut off`; all other five Stage 5
  domains remained running. Ceph converged to the exact two-node MON quorum,
  two of three OSDs up with all three still in, two RGWs, both ingress pairs,
  zero inactive PGs, 193 expected unclean PGs, and `HEALTH_WARN`. Exactly one
  VIP owner remained and five sentinel reads passed with the accepted digest.
- Recovery evidence: The exact domain restarted with autostart still disabled.
  It rejoined three-MON quorum; all three OSDs returned up/in; the third RGW
  returned after its host refresh; every PG became active and clean; and Ceph
  returned to `HEALTH_OK`. The sentinel retained its size and digest.
- Independent audit: The target and all other five domains are running; 3/3/3
  MON/OSD/RGW state, two HAProxy, two Keepalived, one VIP owner, clean PGs,
  `HEALTH_OK`, and helper cleanup all pass.
- Next exact action: Begin the controller track with a mutation-free inventory
  and Kolla 2026.1 multinode deployment plan for controller-1/2/3. Reuse the
  accepted Stage 4 pin and companion-role contracts, keep the external RGW
  endpoint unchanged, and do not deploy Coffer until three-controller
  Kolla/Galera/HAProxy health passes.

### 2026-07-24 — Three-controller Kolla preflight passed

- Completed: Added a pinned inventory renderer, minimal
  Keystone/Galera/HAProxy globals, and a mutation-free guest/controller
  preflight. The renderer keeps the official Kolla-Ansible 2026.1 group
  hierarchy after replacing only the initial host assignments.
- Inventory evidence: The ignored rendered inventory resolves controller-1/2/3
  as the exact control, network, MariaDB, RabbitMQ, and Keystone members;
  compute, monitoring, and Kolla storage groups are empty; deployment remains
  localhost. The source, role contract, and render marker all pin commit
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`.
- Guest evidence: Each controller is clean Ubuntu Noble x86_64 with 8 vCPUs,
  at least 15 GiB RAM and 70 GiB free root storage, synchronized time, the
  exact management/storage/external NICs, no assigned Kolla VIP, free reserved
  ports, no Kolla/container state, and working bootstrap and RGW paths.
- Configuration decision: Deploy only the shared infrastructure and Keystone
  baseline first: MariaDB/ProxySQL, RabbitMQ, Memcached, HAProxy/Keepalived,
  Fluentd, and Keystone. OpenStack core, Horizon, Cinder, Swift, and Prometheus
  stay disabled. Internal traffic uses the isolated management VIP; the
  separate external VIP uses TLS on ens5.
- Failures corrected before remote mutation: The project venv did not contain
  `ansible-inventory`, so the preflight now uses the already-pinned Stage 3
  Kolla venv. Child groups are validated by recursive effective membership,
  and a trailing space in `ip route` is ignored by comparing semantic route
  fields.
- Storage isolation: The external Ceph cluster remained at quorum 3, OSD
  3/3, RGW 3, two ingress pairs, clean PGs, and `HEALTH_OK`.
- Safety: No package, key, password, certificate, VIP, container, or service
  was created or changed.
- Next exact action: Commit the controller-preflight baseline locally. Then
  add a recoverable prepare/bootstrap harness that creates one owner-only
  deployment SSH key on controller-1, installs only its public key on the
  three exact controllers, checks out the pinned Kolla source and venv on
  controller-1, generates owner-only passwords/certificates, and stops before
  `kolla-ansible bootstrap-servers`.

### 2026-07-24 — Kolla deployment-host prepare harness validated

- Completed: Added separate controller authorization, controller-1
  preparation, and local orchestration helpers. The phase is idempotent only
  for its owner-marked state and refuses pre-existing unowned state, partial
  key/certificate sets, mismatched commits, or unknown actions.
- Recipient boundary: One Ed25519 private key remains mode 0600 and
  ubuntu-owned only on controller-1. The three controllers receive exactly one
  bounded public-key marker; transfer copies are removed. Controller-1 builds
  its own dedicated known-hosts file and must SSH to all three exact
  hostnames before installation continues.
- Tooling boundary: Controller-1 checks out exact Kolla commit
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`, creates a system-site-packages
  venv for the Ubuntu dbus binding, installs the Kolla package, Docker Python
  SDK, and pinned Galaxy dependencies, then installs only the rendered
  inventory and globals.
- Secret boundary: Root-only Kolla passwords and a 14-day lab CA/external-VIP
  certificate are generated on controller-1. The certificate covers only
  `192.168.254.10`; private CA and HAProxy material remain mode 0600. No
  secret or private key is copied to the local workspace or another host.
- Stop boundary: The final action is an Ansible ping to all three controllers.
  The harness contains no `bootstrap-servers`, precheck, pull, deploy, Docker
  run/start, VIP assignment, or container start.
- Evidence: Bash syntax, ShellCheck, missing/option/unknown action refusals,
  forbidden-command scans, Gitleaks, and diff checks pass. A live unknown
  action returned 64 before state creation; all three controllers still have
  zero owner directory, deployment key, `/etc/kolla`, or public-key marker.
- Safety: The prepare action has not been invoked.
- Next exact action: Commit the validated prepare harness locally, then invoke
  `poc/kolla-ha/prepare-kolla-controllers.sh
  jh.byun@100.123.168.66`. Verify only the declared key recipients, pinned
  source/venv, root-only config, TLS, three Ansible pings, zero containers/VIPs,
  and healthy external RGW before adding the Kolla lifecycle runner.

### 2026-07-24 — Kolla deployment-host preparation passed

- Completed: Preserved the preparation harness in local commit `1b4785f` and
  completed its final idempotent invocation. Controller-1 now owns the sole
  mode-0600 deployment private key, exact Kolla checkout and venv, root-only
  generated passwords, and the verified 14-day external-VIP certificate.
  Controllers 1 through 3 each retain exactly one bounded public-key marker.
- Recovery evidence: Four resumable attempts failed before Kolla runtime
  creation while exposing missing venv `PATH`, password-mode drift after
  generation, a missing dedicated-known-hosts inventory option, and a cleanup
  assertion ordered before cleanup. The scoped corrections are preserved in
  commits `50e48d`, `c5b166e`, `0d509e2`, and `d7cd2f6`; the final invocation
  passed all three Ansible pings.
- Independent evidence: A separate read-only audit confirmed source commit
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`, required generated password
  presence without printing values, root-only modes, TLS chain and external
  VIP SAN, removed transfer files, and exact private/public key recipients.
  Docker, `/var/lib/docker`, `/var/lib/kolla`, and both Kolla VIPs remain
  absent on all controllers. Controller-2/3 have no owner state or
  `/etc/kolla`.
- Storage boundary: The independent external audit still reports three-MON
  quorum, three of three OSDs up/in, three RGWs, two ingress pairs, zero
  inactive or unclean PGs, and `HEALTH_OK`.
- Next exact action: Implement and locally validate a phase-selectable
  `poc/kolla-ha/run-kolla-lifecycle.sh` plus a controller-1 guest helper. It
  must admit only `bootstrap`, `prechecks`, `pull`, `deploy`, and read-only
  `status`, retain owner-only phase logs, bound execution, and recheck the
  external RGW. Do not run `bootstrap-servers` before the harness is committed.

### 2026-07-24 — Resumable Kolla lifecycle harness validated

- Completed: Added separate `status`, `bootstrap`, `prechecks`, `pull`, and
  `deploy` actions. Mutating phases take one non-blocking lock, require the
  preceding root-only commit marker, run with hard phase timeouts, replace
  owner-only logs on controller-1, and create a marker only after their
  postconditions pass. Only `prechecks` receives `--use-test-images`.
- Storage boundary: The local wrapper runs the existing healthy Ceph/RGW
  audit before and after each phase. A failed Kolla phase retains its remote
  log without printing it and cannot suppress the post-phase storage audit.
- Failure and recovery: The first intended read-only status attempt used
  `ssh -n`, so the nested controller script produced an empty snapshot.
  Unsafe arithmetic then caused Bash to continue past the status branch and
  create only `lifecycle/status.complete` and two empty directories. Exact
  marker content/mode and sole-file state were verified before removing only
  that marker and the empty directories. Docker, Kolla runtime, images,
  containers, and VIPs remained absent; RGW was healthy on both boundaries.
- Correction: Nested snapshot stdin is now enabled; exact one-line host and
  numeric-field validation occurs before arithmetic; and marker paths admit
  only the four mutating phases, making a status marker structurally
  impossible. The corrected live status reports no completed phases, Docker
  `0/3`, and zero images, containers, or VIPs, then leaves no lifecycle/log
  directory.
- Evidence: Bash syntax, ShellCheck, missing/unknown/option-shaped local
  refusal, live remote unknown-action refusal, exact command/timeout checks,
  forbidden-mutation scans, Gitleaks, diff checks, corrected live status, and
  external RGW before/after audits pass.
- Bootstrap attempt: Preserved the harness in local commit `56632de` and
  invoked only `bootstrap`. It failed in about 20 seconds because the
  ubuntu-run Kolla CLI could not read the intentionally `root:root:0600`
  passwords file. No Docker binary, image, container, VIP, or success marker
  exists on any controller; RGW passed both boundary audits.
- Correction: Preserve the root-only password boundary and run Kolla plus its
  deploy check as root. Explicitly pin `ANSIBLE_COLLECTIONS_PATH` to the nine
  Galaxy collections installed under the deployment owner and the system
  collection path. Phase logs are now `root:root:0600`.
- Correction evidence: A root read-only preflight parses the exact inventory,
  loads the Kolla bootstrap command, sees all nine collections, retains the
  root-only passwords, and proves Docker and the bootstrap marker absent. Bash
  syntax, ShellCheck, Gitleaks, and diff checks pass.
- Next exact action: Commit the root-execution correction locally, then resume
  only `poc/kolla-ha/run-kolla-lifecycle.sh bootstrap
  jh.byun@100.123.168.66`.

### 2026-07-24 — Three-controller Kolla bootstrap passed

- Completed: Preserved the root-execution correction in local commit
  `bb34850` and resumed only `bootstrap`. All three controllers completed
  with `failed=0` and `unreachable=0`; controller-1 changed 16 tasks and
  controller-2/3 changed 17 each.
- Independent evidence: Docker is installed and active on all three
  controllers. There are zero containers, zero images, and no
  internal/external Kolla VIP owner. Controller-1 has the exact
  `root:root:0600` bootstrap marker and log; passwords remain root-only and
  prechecks/pull/deploy markers are absent.
- Storage boundary: The external audit still reports three-MON quorum, three
  up/in OSDs, three RGWs, two ingress pairs, zero inactive or unclean PGs,
  and `HEALTH_OK`.
- Next exact action: Invoke only
  `poc/kolla-ha/run-kolla-lifecycle.sh prechecks
  jh.byun@100.123.168.66`. Do not pull images unless the root-only prechecks
  marker and independent acceptance pass.

### 2026-07-24 — Three-controller Kolla prechecks passed

- Completed: The exact `prechecks --use-test-images` phase passed with
  `changed=0`, `failed=0`, and `unreachable=0` on all three controllers.
- Independent evidence: Lifecycle status reports only `bootstrap,prechecks`
  complete, Docker active `3/3`, and zero images, containers, or VIPs.
  Bootstrap/prechecks markers and logs are `root:root:0600`; passwords remain
  root-only and pull/deploy markers are absent.
- Storage boundary: External Ceph/RGW remains at three-MON quorum, three
  up/in OSDs, three RGWs, two ingress pairs, zero inactive/unclean PGs, and
  `HEALTH_OK`.
- Next exact action: Invoke only
  `poc/kolla-ha/run-kolla-lifecycle.sh pull
  jh.byun@100.123.168.66`. Do not deploy until all three nodes have images,
  the exact pull marker passes, and external RGW remains healthy.

### 2026-07-24 — Three-controller Kolla image pull passed

- Completed: The exact pull phase passed with `failed=0` and `unreachable=0`
  on all three controllers. Each node has 12 images.
- Immutable equality evidence: The sorted public image reference/digest set
  is identical across all three nodes with SHA-256
  `2db835fbf628fe2b747ad44c27f9c8685d72547876fb7f8e0cbaa9228c6fee27`;
  none is dangling or missing a digest.
- Independent evidence: Lifecycle status reports only
  `bootstrap,prechecks,pull` complete, Docker active `3/3`, and zero
  containers or VIPs. All three markers/logs are `root:root:0600`; the deploy
  marker is absent.
- Storage boundary: External Ceph/RGW remains at three-MON quorum, three
  up/in OSDs, three RGWs, two ingress pairs, zero inactive/unclean PGs, and
  `HEALTH_OK`.
- Next exact action: Invoke only
  `poc/kolla-ha/run-kolla-lifecycle.sh deploy
  jh.byun@100.123.168.66`. If it fails, retain its root-only log, keep the
  deploy marker absent, audit exact partial state, and recover Kolla before
  beginning any Coffer deployment.

### 2026-07-24 — Kolla deploy passed service gates but failed log-secret gate

- Service result: Kolla deploy completed with `failed=0` and `unreachable=0`.
  All 36 containers were running/healthy, internal and external VIPs each had
  exactly one owner, Kolla check and trusted Keystone probes passed, and
  external RGW remained fully healthy.
- Security failure: Independent log acceptance found the raw RabbitMQ cluster
  cookie and a derived Basic Authorization value in upstream Ansible item
  output under root-only `prechecks.log` and `deploy.log`. The cookie was not
  disclosed. A redacted-context diagnostic did expose the Basic token, so the
  disposable monitoring password is treated as compromised and requires
  rotation.
- Recovery: Verified and removed the exact deploy success marker, then
  atomically sanitized only the two affected root-only logs. A full scan now
  rejects every raw, URL-encoded, or base64-encoded generated value and all
  Basic/Bearer Authorization tokens across the lifecycle logs. Running
  services were unchanged.
- Correction: Every Kolla and deploy-check execution now sets
  `ANSIBLE_NO_LOG=True`. A mandatory post-run credential scan executes before
  recap or marker creation and fails closed on known or derived credential
  material.
- Evidence: Bash syntax, ShellCheck, Gitleaks, effective Ansible no-log
  configuration, sanitized existing-log scan, absent deploy marker, and diff
  checks pass.
- Next exact action: Commit the log guard, rotate only the disposable
  `rabbitmq_monitoring_password` without displaying or retaining either value,
  and rerun only `deploy`. Do not accept the Kolla baseline or begin Coffer
  deployment until the new root-only logs and full control plane pass.

### 2026-07-24 — Bounded monitoring-password rotation validated

- Completed: Preserved the no-log and post-run scan guard in local commit
  `d352870`. Added a dedicated recovery helper that accepts only the exact
  `rabbitmq_monitoring_password` rotation workflow.
- Safety contract: The helper requires the three preceding root-only lifecycle
  markers and an absent deploy marker. It generates the new value only in
  remote memory, creates no backup, atomically retains `root:root:0600`, and
  proves every unrelated parsed password value is unchanged. It never prints
  either credential.
- Evidence: Bash syntax, ShellCheck, Python compilation,
  missing/option-shaped target refusal, forbidden-operation scans, Gitleaks,
  and diff checks pass. Rotation has not run, so the current control plane
  remains internally consistent on the old disposable value.
- Next exact action: Commit the rotation helper, invoke it exactly once, and
  immediately rerun only `deploy` through the guarded lifecycle harness.

### 2026-07-24 — Credential rotation reconciled; VIP-owner probe corrected

- Rotation: Preserved the bounded helper in local commit `9d4be4a` and invoked
  it once. The target value changed without output or backup, the password file
  remained root-only, the deploy marker stayed absent, and RGW passed both
  boundary audits.
- Reconciliation: The guarded deploy applied the new credential and completed
  with `failed=0` and `unreachable=0`. All 36 containers were
  running/healthy; deploy and deploy-check logs passed the new raw,
  URL/base64-derived, and Authorization credential scan.
- Acceptance failure: Keepalived moved both VIPs from controller-1 to
  controller-2. Because nonowner external NICs are intentionally unnumbered,
  controller-1 has no route to the external VIP. A trusted probe from that
  wrong node failed and left the deploy marker absent; control-plane services
  and external RGW stayed healthy.
- Correction: External acceptance now identifies the sole owner from the
  exact snapshots, passes only the public CA in memory to that host, and runs
  trusted TLS plus untrusted and plaintext denial probes locally on the owner.
  A live read-only preflight passes on controller-2.
- Evidence: Bash syntax, ShellCheck, Gitleaks, owner-local TLS/denial probes,
  absent deploy marker, and diff checks pass.
- Next exact action: Commit the VIP-owner probe correction and rerun only
  `deploy`. The rotated credential has already reconciled and does not need a
  second rotation.

### 2026-07-24 — Three-controller Kolla HA baseline accepted

- Completed: Preserved the owner-local probe correction in commit `ea7e388`
  and reran only deploy. Controller-1 changed three tasks and controller-2/3
  changed zero; all hosts finished with `failed=0` and `unreachable=0`.
- Runtime evidence: Lifecycle status reports all four phases complete, Docker
  active `3/3`, and 12 running/healthy containers per controller. All three
  have the identical 12-name container set. Internal/external VIPs have one
  owner each; the owner-local external check returns trusted TLS 200 and
  denies untrusted TLS and plaintext.
- Quorum evidence: Galera reports three members, `Primary`, `Synced`, ready,
  and connected. RabbitMQ reports three running nodes and zero partitions.
  A real Keystone admin token is issued through the internal VIP with
  internal/public identity catalog interfaces.
- Secret evidence: All four exact markers and five lifecycle/check logs are
  `root:root:0600`. Raw, URL-encoded, and base64-encoded generated values plus
  Basic/Bearer Authorization patterns are absent after the credential
  rotation and guarded deploy.
- Storage boundary: External Ceph/RGW still reports three-MON quorum, three
  up/in OSDs, three RGWs, two ingress pairs, zero inactive/unclean PGs, and
  `HEALTH_OK`.
- Next exact action: Inspect the existing companion-role and Stage 4 image
  contracts read-only, then add a mutation-free Stage 5 Coffer HA preflight.
  It must resolve x86_64 functional image digests through the independent
  bootstrap path and prove exact service groups, ports, RGW inputs, database
  ownership, TLS recipients, and zero pre-existing Coffer state before deploy.

### 2026-07-24 — Coffer HA clean/ready preflight passed

- Completed: Added separate controller-node, controller-owner, and storage
  input checks behind `preflight-coffer-ha.sh clean|ready`. The harness first
  requires the accepted Kolla and Ceph/RGW baselines, then validates exact
  Coffer state and recipients without installing, copying, creating, or
  changing remote state.
- Clean evidence: All three controllers retain the same twelve running/healthy
  Kolla containers and have zero Coffer containers, reserved-port listeners,
  service configuration, HAProxy routes, or pilot images. Galera has neither
  a `coffer` schema nor user; Keystone has neither an `oci-registry` service
  nor `coffer` user; and companion inventory, source, inputs, internal TLS,
  and the single external frontend remain absent.
- Storage evidence: Three MONs, three up/in OSDs, three RGWs, two ingress
  pairs, clean PGs, and `HEALTH_OK` remain intact. Owner-only RGW inputs and
  its public CA exist only on storage-1, storage-2/3 retain no credential or
  CA directory, and the private 4-MiB sentinel still has SHA-256
  `543e845c8c7185da3bc04a566b068274825c837a740d029726b169481b919e50`.
- Ready contract: Before companion deploy, all controllers must have identical
  Stage 5 Coffer/Distribution image IDs; controller-1 must own source commit
  `4f1ff7ddfd89d21f17ab7cbb531c335e85d94542`, exact three-host Coffer groups,
  production globals, verified internal/external/backend certificates and
  exact owner-only inputs. Database/catalog/runtime must still be absent.
- Failure corrections: The first live run exposed that `openssl x509
  -checkhost` reports a mismatch with exit zero; identity checks now use
  chain-aware `openssl verify -verify_hostname/-verify_ip`. The second run
  corrected an overbroad secondary-storage CA requirement to the actual
  primary-only recipient model. Both stopped without remote mutation.
  A final `ready` invocation fails closed at the first missing pilot image, as
  expected before preparation.
- Verification: Bash syntax, ShellCheck, Python compilation, invalid
  action/target refusal, mutation-surface review, Coffer harness Gitleaks,
  diff checks, live `clean`, and live negative `ready` pass.
- Next exact action: Implement
  `poc/kolla-ha/prepare-kolla-production-profile.sh`. It must generate only
  the missing internal VIP certificate, replace the short-lived external
  certificate with one that also covers `registry.coffer.stage5`, enable
  internal TLS and Kolla's single external frontend, and stop before any Kolla
  reconfigure or Coffer/image/input mutation.

### 2026-07-24 — Kolla production profile inputs prepared

- Completed: Preserved the fail-closed profile harness in local commit
  `ebc08ff`, then invoked its exact `prepare` action through the direct jump
  target. It retained the existing Stage 5 CA, created one internal-VIP leaf,
  replaced the source external leaf with IP `192.168.254.10` plus DNS
  `registry.coffer.stage5`, and changed only the three allowlisted internal
  TLS/single-frontend/port globals.
- No-reconfigure evidence: The exact names, IDs, and start times of all twelve
  Kolla containers on controller-1 retained runtime snapshot SHA-256
  `c0041e9f3aa7236c3811f97e42f0afcd756372737b668e11ee45ee78250505a9`.
  All 36 Kolla containers remain running/healthy, both VIPs retain exactly
  one owner, and the new internal certificate is still absent from the
  rendered HAProxy service directory. Coffer runtime, images, inputs,
  database, and catalog remain absent.
- Recipient and cleanup evidence: The two source PEMs are `root:root:0600`,
  chain and exact IP/DNS verification pass, the root CA/key pair is unchanged,
  the root serial and temporary directory are absent, and no retained backup
  exists. A second `prepare` returned `idempotent=yes` with the same runtime
  snapshot and did not rotate either certificate.
- Storage boundary: External Ceph/RGW remained at three-MON quorum, three
  up/in OSDs, three RGWs, two ingress pairs, clean PGs, and `HEALTH_OK` before
  and after both invocations.
- Verification: Bash syntax, ShellCheck, action/target refusal, explicit
  no-reconfigure/container/VM mutation scan, rollback-path review, Gitleaks,
  live clean status, first prepare, repeated prepare, independent certificate/
  globals/runtime/residue audit, and diff checks pass.
- Next exact action: Extend the guarded Kolla lifecycle with one exact
  `reconfigure` phase. It must retain no-log/credential scanning, prove
  internal HTTPS and the external single frontend on 443 from their VIP
  owners, reject plaintext/untrusted paths and external port 5000, validate
  the updated Keystone catalog plus Galera/RabbitMQ quorums, and leave Coffer
  state absent.

### 2026-07-24 — Kolla production profile reconfigure accepted

- Completed: Preserved the guarded phase in local commit `dac7bf5` and ran
  the exact `reconfigure` lifecycle to convergence. The final idempotent run
  changed three tasks on controller-1 and zero on controller-2/3, with
  `failed=0` and `unreachable=0` everywhere. All 36 Kolla containers are
  running and healthy; Coffer containers, images, listeners, configuration,
  database objects, and catalog objects remain absent.
- TLS and routing evidence: Trusted internal HTTPS at
  `192.168.252.10:5000` and the single external frontend at
  `192.168.254.10:443` return 200. Untrusted TLS, plaintext, and the retired
  external port 5000 are denied. The external certificate validates both the
  VIP IP and `registry.coffer.stage5`.
- Catalog and quorum evidence: Keystone advertises the canonical internal URL
  `https://192.168.252.10:5000` and public URL
  `https://192.168.254.10`. Galera has three
  `Primary`/`Synced`/ready/connected members; RabbitMQ has exactly three
  running nodes and zero partitions.
- Secret and storage evidence: The `bootstrap`, `prechecks`, `pull`, `deploy`,
  and `reconfigure` markers plus seven lifecycle/check logs are
  `root:root:0600`. Every log passes raw, URL-encoded, and base64-encoded
  generated-password checks plus Basic/Bearer Authorization checks. External
  Ceph/RGW remains fully healthy.
- Failure correction 1: The first run stopped at the missing ProxySQL TLS
  certificate contract. Commit `a367f30` upgraded the prepared profile to
  owner-correct CA/certificate/key recipients.
- Failure correction 2: The next run reached Keystone registration but the
  toolbox lacked the internal CA trust path. Commit `2b29f2a` set only
  Kolla's documented Ubuntu CA bundle path.
- Acceptance correction: The successful service run exposed that Kolla emits
  catalog URLs without `/v3` and omits the default external `:443`. Commit
  `c37c014` corrected only those expected canonical URLs; the final rerun
  passed idempotently.
- Verification: Guarded failure markers, rollback-safe profile upgrades,
  Bash/ShellCheck, Gitleaks, log credential scans, Kolla check, owner-local
  TLS/denial probes, catalog, Galera/RabbitMQ, absent-Coffer, 36-container,
  and external RGW gates pass.
- Next exact action: Implement and locally validate
  `poc/kolla-ha/build-distribute-coffer-images.sh`. It must check out published
  commit `4f1ff7ddfd89d21f17ab7cbb531c335e85d94542` on controller-1, build the
  two x86_64 functional pilot images there, transfer them directly to
  controller-2/3, and require identical image IDs on all three controllers.
  Stop before companion inventory, owner-only input, database, catalog, or
  role mutation.

### 2026-07-24 — Coffer image build/distribution harness validated

- Completed: Added separate `status` and `build` actions with a controller-1
  guest helper. The build action requires the accepted Kolla reconfigure and
  production-profile markers, exact twelve-container runtime on every
  controller, and zero Coffer runtime/config/listeners before establishing its
  own root-only owner marker.
- Immutable inputs: The harness pins published Coffer commit
  `4f1ff7ddfd89d21f17ab7cbb531c335e85d94542`, Kolla image commit
  `686c6d13dc1c31092b22c6c481e16a7329e935ea`, Ubuntu 24.04 x86_64 base
  digest, and the repository's checksum-pinned Distribution v3.1.1 template.
- Bootstrap and recipient boundary: Controller-1 is the sole builder. It
  validates the non-root process entry points, streams both Docker archives
  directly through the existing deployment key to controller-2/3, and never
  logs in, pushes, publishes, or uses the tenant registry. No archive is
  retained on the Mac or secondary controllers.
- Resume and acceptance boundary: A failed build or transfer retains an
  owner-only log and partial owned state without a completion marker. Final
  acceptance requires exact source state and identical Coffer/Distribution
  image IDs on all three controllers while all 36 Kolla containers and the
  external RGW remain healthy. Companion inventory, owner-only inputs,
  database, catalog, and role execution are explicitly absent.
- Failure corrections: The first live status exposed the actual deployment
  known-hosts mode as 0644 rather than 0600. The second normalized Docker's
  blank output for a missing image. Both failed before creating an owner
  marker, source checkout, build directory, or image.
- Verification: Bash syntax, ShellCheck, missing/unknown/option-shaped target
  refusals, exact pin/tag/marker and no-publication scans, Gitleaks, diff
  checks, and the final mutation-free live `status` pass. It reports zero
  Coffer images/runtime, 36 healthy Kolla containers, accepted reconfigure,
  and healthy external RGW.
- Next exact action: Commit the validated image harness locally, then invoke
  only `poc/kolla-ha/build-distribute-coffer-images.sh build
  jh.byun@100.123.168.66`. On failure, retain the root-only log, verify the
  completion marker is absent, audit exact partial image/source state, and
  resume only this phase.

### 2026-07-24 — First image build stopped before image construction

- Failure: The committed build action created only its owner marker, exact
  Coffer/Kolla source checkouts, and isolated build venv, then stopped before
  Kolla image construction because Kolla's package does not depend on the
  Python Docker SDK required by its Docker engine.
- Safety evidence: The completion marker is absent; both final image tags are
  absent on all three controllers; Coffer runtime/config/listeners remain
  absent; all 36 Kolla containers and external Ceph/RGW remain healthy.
- Correction: Pin and install Python Docker SDK 7.2.0 in only the isolated
  image-build venv, matching the already working controller deployment venv.
  Require that exact installed version before invoking `kolla-build`.
- Next exact action: Commit the Docker SDK correction locally and resume only
  `poc/kolla-ha/build-distribute-coffer-images.sh build
  jh.byun@100.123.168.66`.

### 2026-07-24 — Functional x86_64 pilot images distributed

- Completed: Preserved the isolated Docker SDK correction in local commit
  `ea6995e` and resumed the same owned image phase. Controller-1 built the two
  Kolla-compatible x86_64 images from the pinned published source, validated
  their non-root entry points, and streamed them directly to controller-2/3.
- Immutable equality: All three controllers report Coffer image ID
  `sha256:336140d2d9b552b8635a3a742c5ca30a95173ccfb4459a46e2430b8ef0b007d4`
  and Distribution-wrapper image ID
  `sha256:d9c108f8879de50aef9b6641d56a5e3459bf2ced122f6c21431efe708b0b3e67`.
  Both report Linux `amd64` and the exact `coffer`/`registry` users.
- Idempotency: A second complete `build` invocation returned from the accepted
  marker without rebuilding or transferring. The three-host image
  ID/creation snapshot retained SHA-256
  `1bb91f677fb9e3d15dabb76c5abcea9a65110fa1b2fe617e0dfef8545575b762`.
- Security and runtime boundary: The owner/completion markers and every image
  build log are root-owned mode 0600. Credential URL, Authorization, and
  private-key patterns are absent. No image archive was retained outside the
  Docker stores; no image was published. All 36 Kolla containers remain
  healthy, Coffer runtime/config/listeners remain absent, and external RGW is
  healthy.
- Production limitation: Docker emitted a non-fatal local base-manifest
  signature-validation warning while continuing the build. The functional
  image result does not provide a signature/provenance promotion claim, and
  the signed Distribution v3.1.1 security gate remains blocked by ADR 0006.
- Preflight correction: The now-reachable control portion of `ready` exposed
  Python identity comparison against the string-valued `openstack_cacert`.
  Replacing it with value comparison passes the actual Kolla profile and makes
  the read-only gate stop at the expected first missing companion input,
  `/etc/kolla/coffer-globals.yml`.
- Verification: Exact image inspections on all three hosts, source/Kolla
  commit and clean-tree checks, marker/log modes, credential-pattern scan,
  unchanged runtime/listener checks, repeated build snapshot, expected
  negative `ready`, Python compilation, and external RGW boundary pass.
- Next exact action: Implement and locally validate
  `poc/kolla-ha/prepare-coffer-companion.sh`. It must render exact three-host
  Coffer groups, create owner-only controller inputs and backend TLS, transfer
  the existing RGW credential/CA directly from storage-1 without exposing
  them locally, and stop before database, Keystone, HAProxy, or Coffer
  container mutation.

### 2026-07-24 — Coffer companion preparation harness validated

- Completed: Added separate mutation-free `status` and transactional
  `prepare` actions with controller-1 and storage-1 guest helpers. The
  committed inputs are the four exact three-controller Coffer groups,
  production-profile globals, signing key/JWKS, backend CA/leaf, Distribution
  HTTP secret, database and Keystone passwords, and existing RGW registry
  credentials plus its public CA.
- Secret boundary: The RGW exporter validates the root-owned fixture and
  streams a deterministic three-member archive from storage-1 directly to
  controller-1 through SSH. The local workstation receives neither the
  archive nor credential values. Controller-1 is the sole secret recipient;
  public trust inputs are separated from root-only mode-0600 sources.
- Transaction and stop boundary: The guest phase keeps the original inventory
  in a root temporary directory, installs inputs atomically, and restores the
  inventory while removing partial globals/inputs on failure. The outer
  completion marker is written only after `preflight-coffer-ha.sh ready`
  accepts exact images, groups, TLS identities, storage inputs, and continued
  zero runtime/database/catalog state. No Ansible playbook, Kolla lifecycle,
  database, Keystone, HAProxy, or container mutation is in this phase.
- Read-only evidence: Live `status` reports companion state absent, identical
  image IDs on all controllers, 36 healthy Kolla containers, healthy external
  Ceph/RGW, zero Coffer runtime/database/catalog, and no temporary residue.
  `status` has no cleanup path and therefore performs no remote mutation.
- Verification: Bash syntax, ShellCheck, Python compilation, YAML parsing,
  missing/unknown/option-shaped target refusals, forbidden mutation and
  publication scans, Gitleaks, diff checks, and repeated live read-only status
  pass.
- Next exact action: Commit this validated preparation harness locally, then
  invoke only `poc/kolla-ha/prepare-coffer-companion.sh prepare
  jh.byun@100.123.168.66`. If it fails, preserve the owner marker, require
  inventory/input rollback and exact temporary-file cleanup, and resume only
  this phase.

### 2026-07-24 — First companion prepare stopped at missing custom-config parent

- Failure: The committed phase reached its final atomic install but
  `/etc/kolla/config` did not exist on the minimal controller-1 deployment, so
  moving the prepared Coffer tree to its final path failed. No database,
  catalog, HAProxy, or container action had started.
- Rollback evidence: Live mutation-free status reports state `owned` with no
  globals, inputs, companion groups, runtime, database, catalog, or temporary
  transfer residue. The original inventory is restored. Both image IDs, all
  36 Kolla containers, and the external Ceph/RGW boundary remain healthy.
- Correction: Treat `/etc/kolla/config` as an explicit transaction-owned
  prerequisite. Create only that root-owned mode-0755 parent when absent,
  track whether this phase created it, and remove it with exact `rmdir` during
  rollback after partial Coffer input cleanup. Refuse an existing parent with
  different owner, type, or mode.
- Next exact action: Run Bash/ShellCheck, rollback-path inspection, forbidden
  mutation scans, and live read-only status for this isolated correction;
  commit it locally, then resume only the same companion `prepare` action.

### 2026-07-24 — Resumed prepare exposed temporary secret-root mode

- Failure: After the parent-directory correction was committed, the resumed
  transaction installed its staged tree and then failed a silent mode
  assertion. The same transaction rollback again removed globals, inputs,
  groups, created custom-config parent, and fixed transfer files while
  retaining only the owner marker.
- Root cause: A bounded probe on controller-1 confirmed that
  `install -d -m 0700 <temporary>/coffer/secrets` creates the implicit
  intermediate `coffer` directory as mode 0755. The final validator correctly
  requires that secret-bearing input root to be mode 0700.
- Correction: Explicitly create the temporary `coffer` parent as
  root-owned mode 0700 before creating its mode-0700 secret and mode-0755
  public children. The final paths, secret recipients, input values, and stop
  boundary are unchanged.
- Next exact action: Validate and locally commit this one-line mode
  correction, prove the live owned/absent rollback state once more, and resume
  only the same companion `prepare` action.

### 2026-07-24 — Companion inputs prepared; repeat gate ordering corrected

- Completed: After commit `0400cca`, the resumed prepare passed. It installed
  four exact three-host groups, controller-1-only secret/public inputs, and
  the completion marker only after two independent `ready` gates accepted
  backend/RGW TLS, exact image IDs, sentinel access, and zero
  runtime/database/catalog state.
- Idempotency failure: The first repeat was refused before any transfer or
  generation because the wrapper still called the lower image-phase status,
  whose accepted terminal boundary requires companion inputs to be absent.
  A metadata-only before/after comparison of markers, inventory, globals,
  directories, and files remained identical.
- Correction: Select the gate from durable companion markers. Absent or owned
  state retains the completed-image check. Inputs-prepared and complete state
  use the stronger integrated `ready` check; a complete repeat performs no
  transfer, generation, inventory write, or lower-phase absence assertion.
- Next exact action: Validate and locally commit the marker-first gate order,
  then repeat the complete `prepare` with server-side metadata comparison and
  independently audit recipient, temporary-residue, runtime, database, and
  catalog boundaries.

### 2026-07-24 — Companion preparation accepted idempotently

- Completed: Preserved the marker-first gate correction in commit `3182f90`.
  A repeated complete `prepare` passed the integrated `ready` gate and
  returned `idempotent=yes` without invoking the image-phase absence contract.
- Idempotency evidence: A server-side metadata snapshot covering the three
  companion markers, inventory, globals, input directories, and every public
  and secret input was identical before and after the repeat. No credential
  content or content-derived digest was emitted.
- Independent acceptance: `status` validates the four exact groups, all
  owner/mode contracts, signing/JWKS and backend/RGW certificates,
  primary-only RGW credentials, identical images, the accepted sentinel, 36
  healthy Kolla containers, and no Coffer runtime, database, catalog, or
  fixed temporary transfer path. Controller-2/3 retain no private deployment
  key, owner state, or custom input tree.
- Verification: Bash syntax, ShellCheck, Python compilation, YAML parsing,
  refusal and forbidden-mutation scans, Gitleaks, two rollback rehearsals,
  paired `ready` gates, complete-repeat metadata comparison, and independent
  complete status pass.
- Next exact action: Add a bounded companion lifecycle wrapper admitting only
  `status`, `prechecks`, and `deploy`. It must run the pinned
  `ansible/kolla-ansible-coffer` entry point from controller-1 with exact
  inventory/globals, root-only no-log logs and markers, timeouts, independent
  pre/post acceptance, and no action invocation before the harness is
  committed.

### 2026-07-24 — Companion lifecycle harness validated before execution

- Completed: Added a `status|prechecks|deploy` outer wrapper and controller-1
  guest runner around the published `ansible/kolla-ansible-coffer` entry
  point. It fixes the Kolla venv, inventory, config/password paths, companion
  globals, source commit, recipient markers, phase ordering, non-blocking
  lock, timeouts, and root-only log/marker paths.
- Secret and failure boundary: Both Ansible phases set global no-log, replace
  only their owner-only log, and scan it against Kolla passwords plus every
  companion secret in raw, URL-encoded, and base64 forms before accepting the
  command result. A failed command, secret match, Kolla check, or acceptance
  probe cannot create its completion marker.
- Deploy gate: Acceptance requires three API, edge, and private Distribution
  replicas, all nine healthy and listening through verified TLS, twelve exact
  rendered config directories, no reconciler, schema head
  `0004_inventory_import`, one database user, one service user and
  `oci-registry` service with three canonical endpoints, public `/v2/`
  authentication challenge, external private-port denial, and external RGW
  health. Tenant/isolation and disruptive faults remain later phases.
- Failure correction: The first mutation-free status reached the correct
  controller-1 snapshot and then failed an over-escaped `sed` host parser.
  The corrected parser accepts all three nodes. Lifecycle/log directories,
  markers, rendered configs, listeners, containers, database, and catalog
  remain absent.
- Verification: Bash syntax, ShellCheck, missing/unknown/option-shaped target
  refusals, destructive/publication scans, Gitleaks, diff checks, and live
  read-only status pass with three zero-runtime nodes and healthy external
  Ceph/RGW.
- Next exact action: Commit the guarded lifecycle harness locally, then invoke
  only `run-coffer-companion-lifecycle.sh prechecks
  jh.byun@100.123.168.66`. Require the root-only prechecks marker/log,
  credential scan, second complete-ready gate, zero runtime/database/catalog,
  and healthy storage boundary before deploy.

### 2026-07-24 — Companion prechecks accepted idempotently

- Completed: Preserved the guarded lifecycle harness in commit `1f14cce` and
  invoked only `prechecks`. Controller-1 completed 19 tasks, controller-2/3
  completed 13 each, and localhost completed three; every recap has zero
  changed, unreachable, failed, rescued, or ignored tasks.
- Log and ordering evidence: The prechecks log and completion marker are
  root-only. The log passed raw/URL/base64 Kolla and companion credential
  checks plus private-key and Authorization checks. Deploy remains unmarked
  and uninvoked.
- Stop-boundary evidence: All three controllers still have zero Coffer
  containers, listeners, and rendered service configs. The independent
  complete-ready gate confirms database/user and Keystone service/user absent,
  exact images/inputs/TLS intact, 36 Kolla containers healthy, the private
  sentinel readable, and no temporary residue.
- Idempotency: A repeated prechecks invocation returned `idempotent=yes`.
  Server-side metadata for the existing marker and log was unchanged, and the
  same ready plus external-storage gates passed.
- Next exact action: Commit this accepted prechecks checkpoint locally, then
  invoke only `run-coffer-companion-lifecycle.sh deploy
  jh.byun@100.123.168.66`. On failure, keep the deploy marker absent, preserve
  the root-only log, audit exact database/catalog/config/container state, and
  correct only the first demonstrated cause.

### 2026-07-24 — First companion deploy stopped at bootstrap CA trust

- Failure: The committed deploy reached the one-shot schema bootstrap and
  stopped with `dependency_unavailable`; no deploy marker was written. The
  root-only Ansible and bootstrap logs passed Kolla/companion credential,
  private-key, and Authorization scans before their safe summaries were read.
- Root cause: API/edge/registry were members of Kolla's custom CA-copy service
  set, but the one-shot `coffer-bootstrap` process was not. Its config.json
  also omitted `/var/lib/kolla/share/ca-certificates`, so the database
  connection rejected ProxySQL's internal self-signed chain.
- Partial-state evidence: All controllers have zero Coffer containers but
  four rendered service/bootstrap directories and three HAProxy listeners.
  The Coffer database/user and Keystone service/user plus three endpoints
  exist, while `alembic_version` is absent. The prechecks marker remains,
  deploy marker is absent, and external Ceph/RGW is fully healthy.
- Correction: Include `coffer-bootstrap` through `coffer_processes` in
  `service-cert-copy`, add the conditional Kolla CA config.json contract, and
  cover enabled/disabled rendering plus service-set selection with focused
  tests. Preserve the immutable functional images and clean published source.
- Operator-source boundary: Added a separate transactional operator checkout
  based on published commit `4f1ff7d` with only the two SHA-256-pinned
  correction files. Its original source and image tags remain unchanged.
  Lifecycle validation requires the exact two-path Git diff, file hashes, no
  untracked state, and root-only marker before resume.
- Resume boundary: Lifecycle status/deploy now admits either the original
  zero-state predeploy boundary or exactly zero containers, twelve rendered
  configs, nine HAProxy listeners, one database/user and catalog set, and no
  migration table. Any other partial state fails closed.
- Verification: Six focused bootstrap/runtime tests, Bash syntax, ShellCheck,
  embedded Python compilation, diff checks, and live mutation-free
  operator-source `state=absent` status pass.
- Next exact action: Commit this isolated correction, invoke only
  `prepare-coffer-operator-source.sh prepare
  jh.byun@100.123.168.66`, require lifecycle status `deploy-partial`, then
  resume only the guarded companion deploy action.

### 2026-07-24 — Deploy recovered; listener acceptance corrected

- Completed: Preserved the bootstrap CA/operator-source repair in commit
  `fa99e3a`. The exact two-file overlay passed, lifecycle status classified
  the remote state as `deploy-partial`, and the resumed Ansible deploy plus
  Kolla check completed with zero failed or unreachable hosts.
- Runtime evidence: Three API, three edge, and three private Distribution
  containers are running and healthy. The migration/bootstrap step returned
  successfully, and no reconciler or bootstrap container remains running.
  External Ceph/RGW remains fully healthy.
- Acceptance failure: The deploy marker was correctly withheld because the
  harness expected nine listeners total. Production HAProxy uses nonlocal VIP
  binds on all three controllers in addition to each node's three service
  backends, yielding six sockets per node and an exact total of 18.
- Correction: Admit only the exact healthy candidate with nine containers,
  18 listeners, twelve configs, no unhealthy/reconciler process, migration
  head, and complete catalog/TLS/routing probes. For this candidate, rerun
  Kolla check and all acceptance probes without replaying the already
  successful deploy before writing the marker.
- Next exact action: Validate and locally commit this listener/candidate
  correction, run read-only lifecycle status to exercise the remaining
  schema/catalog/TLS/bypass probes, then resume deploy only to create its
  marker after the same full gate passes.

### 2026-07-24 — Edge upstream and external-owner probes corrected

- Failure: After commit `16be9bb`, read-only status accepted nine healthy
  containers, 18 listeners, twelve configs, migration head, one database/user,
  and the exact service/user/endpoints. Endpoint acceptance then found API
  200 and registry 401 on every backend, but edge returned 503 on every
  backend and internal VIP; all three edge HAProxy members were down.
- Edge root cause: `coffer_upstream_host` is the Kolla internal VIP. Its
  frontend certificate chains to the Kolla CA, while edge's explicit
  `backend-ca.crt` contained the separate CA used by Coffer process leaves.
  The registry upstream TLS connection failed before an HTTP 401 could be
  proxied.
- Correction: Copy the Kolla root CA into edge and the disabled reconciler's
  frontend-upstream CA path while retaining the Coffer backend CA for direct
  process leaves. A focused test requires both exact Kolla-CA copies.
- Probe correction: The external VIP owner is controller-2, while non-owners
  have no external-subnet source address and route the VIP through the
  management gateway. Acceptance now discovers exactly one owner, transfers
  only the public CA in memory, and runs DNS TLS, 401 challenge/service, and
  private-port TCP denial locally on that owner.
- Operator upgrade: Version 2 remains a two-file overlay. It transactionally
  validates and replaces v1, restoring the prior source/marker on any failure.
  A structural deploy candidate is replayed idempotently so the changed edge
  configs and handlers are applied before full acceptance.
- Verification: Seven focused bootstrap/runtime tests, Bash syntax,
  ShellCheck, three embedded Python blocks, diff checks, and the previously
  accepted replica/schema/catalog evidence pass.
- Next exact action: Commit these corrections, invoke only operator-source
  `prepare` to upgrade v1 to v2, require lifecycle status
  `deploy-candidate`, then replay only companion deploy and require the full
  endpoint plus marker gate.

### 2026-07-24 — Replicated Coffer companion baseline accepted

- Completed: Preserved the upstream-CA/operator-source-v2 correction in
  commit `88de660`, transactionally upgraded the exact two-file operator
  overlay, and classified the existing runtime as `deploy-candidate`. The
  idempotent companion deploy replay and Kolla check completed with zero
  failed or unreachable hosts and wrote the deploy marker only after every
  acceptance gate passed.
- Runtime evidence: Three API, three edge, and three private Distribution
  containers are healthy. The exact topology has eighteen HAProxy sockets and
  twelve rendered configurations; Alembic is at `0004_inventory_import`; the
  single database/user, Keystone service/user, and three canonical endpoints
  are present; and external Ceph/RGW remains at three-MON quorum, three of
  three OSDs up/in, three RGWs, clean PGs, and `HEALTH_OK`.
- Routing evidence: The API returns 200; edge and Distribution return the
  expected 401 challenge on all nine direct backends and the internal VIP.
  The unique external VIP owner returns the FQDN-verified 401 challenge with
  service `coffer-registry`, while external access to private port 8789 is
  denied.
- Idempotency and hygiene: Independent status passed, and a repeated deploy
  returned `idempotent=yes`. Completion-marker and lifecycle-log metadata plus
  controller-1 container IDs were unchanged. The deployed boundary now
  collects all nine runtime logs into root-only temporary files, scans them
  against Kolla and companion secrets plus private-key, Authorization, and
  JWT patterns, and removes the files before returning; the live audit passed.
- Verification: Bash syntax, ShellCheck, five focused runtime-contract tests,
  diff checks, independent live status, runtime log hygiene, and the repeated
  deploy boundary pass.
- Next exact action: Add and locally validate a bounded Stage 5 tenant
  acceptance harness that creates exactly two finite Keystone projects,
  users, and application credentials, runs its OCI client only on the unique
  external-VIP owner, proves project-A push/pull and project-B denial through
  port 443, and has exact identity/client cleanup. Do not invoke identity
  creation until the harness is committed and its mutation-free preflight
  passes.

### 2026-07-24 — Finite tenant identity fixture accepted

- Completed: Added and committed the guarded
  `preflight|prepare|status|cleanup` tenant fixture before invoking any
  identity mutation. It reuses `kolla_toolbox`, materializes the existing
  admin password only through an owner-only `/run` transfer, fixes every SDK
  connection to the internal Keystone VIP/interface, and creates exactly two
  projects, users, member assignments, and unrestricted-false application
  credentials with a twelve-hour expiry.
- Preflight evidence: The accepted companion and external RGW gates passed;
  all tenant names and fixture state were absent; all three controllers had
  zero client directory, Docker CA override, or tenant image residue; the
  external VIP owner was uniquely controller-2; and the intentionally
  unregistered FQDN was classified `dns=override-required`.
- Failure corrections: The first preflight found no host `clouds.yaml`; the
  deployed toolbox config is the supported source. The next two attempts
  showed that its generated auth/catalog defaults select the unreachable
  external VIP, so the helper now fixes the known internal Keystone URL and
  internal catalog interface. A later attempt correctly exposed absent
  external DNS; the preflight now admits only either the exact VIP mapping or
  a clean boundary for a later temporary owner-local override. Every failed
  attempt preceded identity creation and left no fixture or `/run` residue.
- Live evidence: Prepare and independent status report two projects, two
  users, and two valid credentials expiring at
  `2026-07-25T05:20:30`. State and marker are
  `root:root:0600` only on controller-1. Repeated prepare returned
  `idempotent=yes`; state/marker inode, size, timestamp, owner, and mode were
  unchanged, and all toolbox/admin transfer paths are absent.
- Verification: Bash syntax, ShellCheck, two embedded Python compilations,
  six focused runtime/fixture tests, refusal tests, changed/new-file Gitleaks,
  diff checks, clean preflight, prepare, independent status, and repeated
  prepare pass.
- Next exact action: Extend the committed fixture with a separately guarded
  `accept` phase. It must create one project-A repository through the control
  API, prove exact quota 429 then success, run Docker push/pull plus explicit
  resumable upload only on the unique external owner with a temporary DNS/CA
  override, deny project B, retain aggregate digest evidence, scan all client
  and service logs against tenant secrets, and remove all owner-client
  material before writing its marker.

### 2026-07-24 — Two-project tenant OCI acceptance accepted

- Completed: Added and committed the separately guarded
  `preflight|accept|status` tenant acceptance. It created one exact project-A
  control-plane repository, proved one-byte quota rejection with HTTP 429,
  raised the limit to 2 GiB, pushed and pulled the existing functional Coffer
  image with Docker through external port 443, denied project B, and committed
  a deterministic 2-MiB blob through two separate PATCH requests.
- Persistence and hygiene: Independent status returns manifest 200,
  resumable-blob 200, and project-B 401. Quota has positive used bytes,
  zero reserved bytes, and remains below its limit. The owner-local hosts,
  CA, auth, secret, and tenant-image state is absent after every attempt. All
  nine runtime logs pass the tenant password/application-secret,
  private-key, Authorization, and JWT scan.
- Failure corrections: The first probe used the wrong in-container Python
  path; the second tried to expose a host-only secret file to the container;
  both stopped before control/data mutation. A wrapper rc mask was closed
  with an explicit marker gate. Distribution required real descriptor blobs
  before quota admission could be distinguished from
  `MANIFEST_BLOB_UNKNOWN`. A streamed guest was then truncated by nested SSH
  stdin consumption, fixed with `ssh -n` only on input-free calls. The final
  status fixes preserve the repository object under an `acceptance` evidence
  namespace and send explicit manifest media-type negotiation. All owner
  cleanup gates passed after every bounded failure.
- Idempotency: Repeated `accept` returned `idempotent=yes`; repository,
  quota-denial marker, evidence, and accepted-marker inode, size, timestamp,
  owner, and mode were identical before and after. The same public digest,
  isolation, quota, log, owner-residue, companion, and external-RGW status
  gates passed twice.
- Verification: Bash syntax, ShellCheck, five embedded Python compilations,
  seven focused runtime/tenant tests, refusal tests, changed/new-file
  Gitleaks, diff checks, clean preflight, quota rejection, full acceptance,
  independent status, and repeated acceptance pass.
- Remaining in the baseline task: Prove authenticated data availability while
  one API, edge, and Distribution replica is stopped and restored; this also
  supplies the outstanding replica-distribution evidence.
- Next exact action: Add and locally validate an exact single-service replica
  fault harness for controller-3. It must stop only one allowlisted Coffer
  container at a time, run a fault-compatible tenant digest/isolation probe
  through the surviving external path, restore the same container to healthy,
  and retain an EXIT recovery trap. Do not stop HAProxy, Galera, or a whole
  controller in this phase.

### 2026-07-24 — Coffer service replica faults accepted

- Completed: Added a committed `data-status` tenant path and exact
  controller-3 fault harness before any container stop. API, edge, and
  unmodified Distribution were stopped one at a time. Each outage passed
  three authenticated manifest/blob plus project-B isolation probes through
  the surviving external route; all nine probes converged on their first
  attempt.
- Recovery evidence: Every target returned healthy before the next fault.
  Each post-fault full status restored all nine Coffer backends, eighteen
  listeners, twelve configs, catalog/schema state, private-port denial,
  tenant digest/quota/isolation, nine-container log hygiene, and the healthy
  three-RGW external storage boundary.
- Idempotency: Three root-owned mode-0600 completion markers remain only on
  controller-1. A repeated `run` reported `idempotent=yes` for all three
  faults, performed no additional stop, and retained identical marker inode,
  size, timestamp, owner, and mode.
- Failure correction: The first API cycle proved all three outage probes, but
  its restore wait used a pipe character in an SSH-rendered Docker format.
  The remote shell interpreted it as a pipeline, so the bounded wait failed
  despite the already healthy container. Independent inspection confirmed
  all three controller-3 services healthy; the exact local harness process
  was terminated after its recovery trap had restarted API. The parser now
  uses a shell-safe colon, and a fresh full preflight plus the complete matrix
  passed. No edge or Distribution fault ran before the correction.
- Verification: Bash syntax, ShellCheck, eight focused runtime-contract
  tests, refusal checks, Gitleaks, diff checks, committed preflight, the
  nine-probe fault matrix, complete recovery, and metadata-idempotent replay
  pass.
- Next exact action: Inspect the live Kolla Keepalived tracking and HAProxy
  restart contracts read-only, then add a separately guarded active external
  VIP-owner HAProxy fault. It must prove VIP movement, the same tenant
  digest/isolation path, exact HAProxy restoration, and one final VIP owner
  before any Galera fault.

### 2026-07-24 — Kolla HAProxy and VIP fault accepted

- Completed: Read-only inspection established the deployed Keepalived
  contract: both Kolla VIPs share one VRRP instance, HAProxy's UNIX socket is
  checked every two seconds with `fall 2` and `rise 10`, and `nopreempt`
  retains the surviving owner after recovery. A committed harness then
  dynamically targeted only the active owner's HAProxy container while
  leaving Keepalived running.
- Live evidence: The accepted cycle stopped controller-3 HAProxy. Internal
  and external VIPs moved together to controller-2. Three authenticated
  manifest/blob and project-B isolation probes passed through the survivor;
  their convergence attempts were 2, 2, and 1. Controller-3 HAProxy returned
  healthy, its Keepalived check passed, all nine Coffer backends recovered,
  and exactly controller-2 retained both VIPs.
- Failure corrections: The first mutation-free preflight exposed BSD awk's
  reserved `index` name and a masked VIP-owner return code; both were fixed
  before any stop. The first fault moved controller-2's VIPs to controller-3,
  but an immediate token request received transient HTTP 503. The EXIT trap
  restored HAProxy; all three controller-3 HAProxy backend sets remained
  `UP/L7OK`, and the identical tenant probe passed after convergence. The
  harness now permits only three bounded attempts per outage probe and records
  the successful attempt.
- Idempotency and hygiene: The completion marker is root-owned mode 0600 only
  on controller-1. A repeated run performed no stop, returned
  `idempotent=yes`, and retained identical marker metadata. Full tenant
  cleanup, log hygiene, external RGW health, and one-VIP ownership gates pass.
- Verification: Bash syntax, ShellCheck, nine focused runtime-contract tests,
  refusal and forbidden-command checks, Gitleaks, diff checks, committed
  preflight, dynamic VIP movement, three bounded outage probes, full recovery,
  and metadata-idempotent replay pass.
- Next exact action: Inspect the live Galera wsrep topology, container restart
  contract, and ProxySQL backend state read-only. Then add a committed
  controller-3 MariaDB member stop/write-read/restore harness with an EXIT
  recovery trap before exercising reconciler claims or signing keys.

### 2026-07-24 — Galera reader-member fault accepted

- Completed: Added a guarded `database-status` probe that verifies the
  accepted tenant boundary, raises the exact project quota from 2 GiB by one
  byte through the deployed database path, reads it back, and restores 2 GiB
  under an EXIT guard. A separate committed fault harness and secret-safe
  Galera/ProxySQL inspector then targeted only controller-3 MariaDB.
- Live evidence: While controller-3 was paused, the surviving Galera component
  reached size 2/Primary/Synced with exact incoming members controller-1/2.
  All three ProxySQL instances retained controller-1 as writer and
  controller-2 as reader while moving controller-3 to offline hostgroup 3.
  Three quota write/read/restore plus OCI digest/isolation probes passed on
  their first attempts.
- Recovery evidence: Exact unpause returned controller-3 healthy. Galera
  recovered size 3/Primary/Synced, all three ProxySQL instances returned
  controller-3 to the online reader group, the quota remained 2 GiB with zero
  reservation, and full Coffer/tenant/RGW acceptance passed.
- Failure corrections: A diagnostic Python exception accidentally included
  the disposable database root password in owner-visible tool output. It was
  not written to the repository or a remote evidence file, but is treated as
  compromised and must be rotated or destroyed before the final secret gate.
  Subsequent diagnostics transfer passwords only through stdin. The first
  stop-based fault was also restarted by an external Docker client despite
  restart policy `no`; no write probe ran. A deterministic pause/unpause
  fault replaced stop/start. Its first run exposed ProxySQL's real offline
  hostgroup 3 transition; it was recovered before writes, modeled exactly,
  and rerun.
- Idempotency: The root-owned mode-0600 marker remains only on controller-1.
  Repeated `run` performed no pause, returned `idempotent=yes`, and retained
  identical marker metadata.
- Verification: Bash syntax, ShellCheck, ten focused runtime-contract tests,
  embedded Python compilation, refusal and forbidden-command checks,
  Gitleaks, committed preflight, size-2 and three-write fault evidence, full
  recovery, and metadata-idempotent replay pass.
- Remaining Galera gate: Real concurrent quota transactions plus an observed
  bounded deadlock or serialization retry are not yet proven by the sequential
  member-loss probes.
- Next exact action: Inspect the existing quota transaction retry surface and
  add an exact real-Galera concurrent/deadlock probe that restores all rows
  and quota values before enabling separate-host reconciler workers.

### 2026-07-25 — Tenant credential renewal accepted

- Completed: Added and committed an exact, two-phase application-credential
  renewal path for the accepted tenant fixture. It preserves both Keystone project
  and user IDs, creates and authenticates two fresh twelve-hour credentials,
  atomically stages their owner-only state with the two retiring IDs, deletes
  only those retiring credentials, and atomically finalizes the state.
- Recovery and idempotency: A staged `pending_retire` state can resume exact
  finalization after interruption. Unknown additional credentials fail
  closed. A root-only mode-0600 renewal marker prevents an accepted rotation
  from replaying, while the normal status path continues to prove exactly two
  credentials.
- Verification: Bash syntax, ShellCheck, embedded Python compilation, ten
  focused runtime-contract tests, diff checks, and scoped Gitleaks pass. The
  live mutation-free `renew-preflight` confirms two projects, two users, two
  credentials expiring at `2026-07-25T05:20:30`, the accepted external owner,
  and zero transfer/client residue.
- Live evidence: The mutation-free preflight changed no state. The committed
  `renew` action then authenticated both replacements before the original
  credentials were retired. The final state has exactly two renewed
  credentials expiring at `2026-07-25T07:33:26`; project and user IDs,
  repository/quota state, and retained manifest/blob digests are unchanged,
  while project B remains denied with 401.
- Secret and residue gates: The renewed secrets pass all-nine-container log
  scans. The identity state and prepared/renewed markers remain mode 0600 only
  on controller-1; controller-2/3, all `/run` transfers, and client state are
  absent.
- Idempotency: Repeated `renew` performed no credential operation, returned
  `idempotent=yes`, and retained identical inode, size, timestamp, ownership,
  and mode across all three fixture files.
- Next exact action: Return to the deployed quota transaction retry surface
  and add the bounded real-Galera concurrent/deadlock probe with exact row and
  2-GiB quota restoration before separate-host reconciler workers.

### 2026-07-25 — Quota transaction retry surface implemented locally

- Completed locally: Centralized the existing known-conflict classifier and
  applied a three-attempt whole-transaction retry to all eight explicit
  `QuotaStore` write operations. Only MySQL lock-timeout/deadlock 1205/1213
  and SQLSTATE serialization/deadlock 40001/40P01 are admitted. The inventory
  importer reuses the same classifier and bound.
- Safety and observability: The transaction context rolls back and closes
  before the decorator retries the entire operation. Duplicate constraints,
  connection outages, and unknown failures pass through without retry. Retry
  logs contain only a fixed operation name and bounded attempt number, never
  exception text or tenant identifiers.
- Verification: Focused retry tests prove third-attempt success, exact
  three-attempt exhaustion, no retry for an unclassified database outage, and
  supported SQLSTATE recognition. All 246 repository tests pass with the
  installed entry-point directory on `PATH`; compile, `uv lock --check`, diff,
  and scoped Gitleaks pass. Ruff remains unavailable from the locked project
  environment.
- Boundary: This is not yet live Galera evidence. The running Stage 5
  containers still use the retained `localhost/coffer:stage5` image.
- Added next-phase harness: Preserved the product change in `a6f476e` and
  pinned its deterministic Git archive plus both installed quota-module
  digests. The harness can build only
  `localhost/coffer:stage5-quota-retry`, streams it directly to controller-2/3,
  and retains the original image/tag as the exact rollback input.
- Verification: Bash syntax, ShellCheck, eleven focused runtime-contract
  tests, diff checks, and scoped secret scans pass. The live mutation-free
  preflight proves the update tag and state root absent, all six API/edge
  containers on the recorded current image ID, all three registries on their
  recorded image ID, and all nine containers healthy.
- Safety: Preflight made no image, file, container, configuration, database,
  identity, or runtime change. The build phase has not run.
- Next exact action: Commit the update-image harness locally, then invoke its
  exact `build` action. Require the same new image ID and embedded retry-source
  hashes on all controllers, unchanged current runtime IDs/health, retained
  rollback image, owner-only evidence, and metadata-idempotent replay before
  rolling deployment.
- First build result: After `ad362bf` fixed the harness, Kolla successfully
  built the base and Coffer application layers and the same update image ID
  reached all three controllers. The source validator then used the wrong
  `/var/lib/coffer/venv/bin/python3` path instead of the image's
  `/var/lib/kolla/venv/bin/python3`.
- Partial-state correction: Command-substitution status also masked the failed
  validator, allowing a root-only four-line completion marker with an empty
  update ID. All nine running containers remain healthy on their recorded old
  image IDs, and the new image is unused. The corrected validator explicitly
  propagates remote failure and admits only this exact empty-ID marker for
  atomic repair; every other malformed marker fails closed.
- Verification: Bash syntax, ShellCheck, eleven focused runtime-contract
  tests, diff checks, scoped Gitleaks, exact three-node image inspection, and
  current-runtime health/ID checks pass.
- First corrected resume: `9dedfed` fixed the path and status propagation, but
  the remove-on-exit validation container lacked `-i`; Python received no
  embedded verifier and returned an empty snapshot. A direct read-only run
  proves both installed source hashes and the attempt bound are exact, and
  current runtime remains unchanged.
- Next exact action: Commit the isolated stdin-attachment correction, then
  resume only the update-image `build`. Validate the existing image and
  embedded source, replace the empty marker with its exact ID, prove no
  rebuild/runtime change, and replay status idempotently.

### 2026-07-25 — Quota-retry update image accepted

- Completed: Preserved the stdin correction in `cf40796` and resumed the exact
  partial phase. It reused the already built image rather than rebuilding.
  All three controllers now have identical update image ID
  `sha256:bf728bc1938d7f68a38fef16600d1c7a81bc0181863425736941fc0228bacb66`
  with exact embedded module hashes and the three-attempt retry bound.
- Rollback and runtime boundary: The original image remains on all nodes as
  ID `sha256:336140d2d9b552b8635a3a742c5ca30a95173ccfb4459a46e2430b8ef0b007d4`.
  Every running API/edge/registry retained its original recorded image ID and
  healthy state. No Kolla action or runtime replacement occurred.
- Security and residue: Owner/completion markers and the build log are
  root-owned mode 0600 on controller-1. The local/remote source archives are
  absent and no image was published.
- Idempotency: Repeated `build` returned from the accepted marker. Image
  ID/creation values on all three nodes plus owner/completion/build-log inode,
  size, timestamp, ownership, and mode remained identical; no rebuild or
  transfer occurred.
- Next exact action: Add and commit a serial-one rolling-upgrade harness with
  a temporary owner-only globals overlay selecting only the update Coffer
  image. Keep Distribution unchanged, continuously prove tenant digest and
  isolation, require one host at a time, and preserve the old image plus an
  exact compatible rollback path before the live Galera retry probe.

### 2026-07-25 — Serial rolling-upgrade harness validated

- Completed locally: Added guarded `preflight|status|upgrade|rollback`
  actions. Only recorded old/update Coffer image IDs are admitted; Distribution
  must retain its original image. An owner-only `/run` globals overlay changes
  only `coffer_image_full`, and the companion `upgrade` action receives
  `kolla_serial=1`; persistent globals remain unchanged.
- Availability and recovery: While Ansible is active, the outer harness
  repeatedly proves the accepted manifest/blob, project-B denial, and client
  cleanup. The complete post-change gate separately scans all nine runtime
  logs after containers converge. It requires at least one in-flight and
  three total probes. An exact old/new mixed state can resume, and the retained
  old image is wired to a separately marked serial rollback action.
- Verification: Bash syntax, ShellCheck, twelve focused runtime-contract
  tests, diff checks, and scoped Gitleaks pass. Live mutation-free preflight
  returns current=3/updated=0, retains tenant digest/isolation, finds no
  rolling root or temporary overlay, and passes all service/RGW health gates.
- Safety: No Ansible action, image replacement, container restart,
  configuration, database, identity, or object mutation has run.
- Next exact action: Commit the rolling harness locally, then invoke only its
  exact `upgrade` action. Require serial transitions, successful in-flight
  tenant probes, final current=0/updated=3, unchanged Distribution/persistent
  globals, owner-only logs/markers, and zero temporary residue before the live
  Galera transaction probe.

### 2026-07-25 — First rolling upgrade converged; postcheck race corrected

- Live result: Kolla-Ansible completed with zero failed or unreachable hosts
  and serially replaced all six API/edge containers. All three controllers
  now report the recorded update image for API/edge, the unchanged
  Distribution image, and nine healthy containers. The accepted manifest,
  blob, project-B denial, external RGW, and full runtime-log hygiene gates pass
  after convergence.
- Harness failure: During replacement, the former `data-status` probe tried to
  collect logs from a container name while Kolla had intentionally removed
  that container, producing bounded `no such object` failures. Immediately
  after Ansible, the guest also made a single health snapshot before Docker
  healthchecks had converged. Ansible succeeded, but those two races prevented
  the upgrade completion marker from being written.
- Correction: Added a `path-status` action that proves only the external
  manifest/blob and project-isolation path during the mutation and still
  removes all client residue. Full control/quota/log acceptance remains the
  final gate. The guest now waits up to 180 seconds for exact healthy image
  convergence and recognizes an exact 0-current/3-updated state as a
  postcheck-only resume, so it does not rerun Ansible.
- Verification: Bash syntax passes; ShellCheck passes with only the existing
  indirect trap-function informational diagnostic excluded. Eight focused
  race/resume contracts, diff checks, and a live `path-status` probe pass.
  Read-only status reports `partial current=0 updated=3`, exactly matching the
  resumable postcheck state; the owner and upgrade log are root-only, the
  temporary globals overlay is absent, and no completion marker exists yet.
- Next exact action: Commit this bounded race correction, rerun only the
  rolling `upgrade` action to finish postchecks and write the exact completion
  marker without invoking Ansible, then repeat status and full tenant/service
  acceptance before implementing the real-Galera concurrency probe.

### 2026-07-25 — Serial rolling upgrade accepted

- Completed: Preserved the bounded correction in `772b23f` and resumed the
  exact upgrade. The guest reported `resume=postcheck`, performed no second
  Ansible invocation, accepted current=0/updated=3 on its first convergence
  attempt, and atomically wrote the upgrade completion marker.
- Availability: The outer harness passed one probe while the guest was active
  and three total external path probes. Every probe retained the accepted
  manifest and blob with project-B returning 401, and every disposable client
  artifact was removed. The complete final tenant gate retained the quota,
  repository digest, isolation, and all-node runtime-log hygiene.
- Final state: All three API/edge pairs are healthy on the recorded update
  image, all three Distribution replicas are healthy on the unchanged image,
  all eighteen HAProxy sockets and the external RGW HA boundary pass, and the
  persistent `coffer-globals.yml` still selects the original deployment tag.
  The temporary overlay is absent. The rolling directory, owner marker,
  upgrade log, and upgrade completion marker have exact root-only ownership
  and modes.
- Verification: The resumed command exited zero with probes=3, during=1,
  serial=1. An independent aggregate audit reconfirmed the three healthy
  controller states, unchanged persistent globals, absent temporary overlay,
  and owner-only evidence. No image was removed, retagged, or published.
- Next exact action: Inspect the accepted shared-SQL concurrency fixtures and
  real deployed database configuration, then add a bounded real-Galera
  transaction harness. It must prove one-winner concurrent reservation,
  exercise the installed three-attempt retry on an actual retryable Galera
  conflict, restore exact quota/row state, retain tenant service, and leave no
  helper or credential residue before compatible rollback.

### 2026-07-25 — Real-Galera transaction harness validated

- Completed locally: Added a guarded `preflight|run` harness that executes the
  installed updated `QuotaStore` inside `coffer_api`, reads its existing
  owner-only configuration in-process, and reaches the deployed ProxySQL and
  Galera topology. The helper and database connection never become host files,
  command arguments, environment metadata, or retained output.
- Concurrency contract: Two independent stores synchronize on one project
  quota and submit two 150-byte logical reservations against a 150-byte limit.
  Exact success requires one admitted pending reservation, one
  `QuotaExceeded`, and reserved/used state 150/0 before cleanup.
- Retry contract: A separate connection locks an allowlisted temporary project
  row. The installed store sets a one-second session lock timeout, observes
  its real MySQL 1205 error, and must emit exactly one fixed retry record for
  `set_limit` attempt 2 before committing the second attempt. The test does
  not monkeypatch or inject an exception.
- Recovery and hygiene: Only two fixed temporary project IDs and two fixed
  repository IDs are admitted. A root-only owner marker makes interrupted
  executions resumable. The helper removes claims, manifests, descriptor
  edges, reservations, descriptors, and project quotas in child-first order
  both before an owned resume and in `finally`; completion requires aggregate
  residue zero and healthy tenant/Galera checks.
- Verification: Twenty-five focused Python tests, Bash syntax, ShellCheck,
  Python compilation, four refusal/forbidden-command contracts, and diff
  checks pass. Live mutation-free preflight reports three-node Primary/Synced
  Galera, all ProxySQL routes healthy, retry bound 3, exact row residue zero,
  and no marker/helper state.
- Safety: No synthetic row, lock, limit change, marker, helper file, service
  restart, container mutation, identity change, or object change occurred in
  preflight.
- Next exact action: Commit the guarded transaction harness locally, invoke
  only its `run` action once, and require one-winner admission, actual 1205
  followed by attempt 2 success, exact row cleanup, retained tenant digest and
  isolation, three-node Galera health, owner-only evidence, and idempotent
  replay before compatible rollback.

### 2026-07-25 — Real-Galera quota concurrency and retry accepted

- Completed: Preserved the guarded harness in `8cb9a22` and ran it once
  through the deployed update image. Two independent `QuotaStore` instances
  reached the same Galera-backed quota row concurrently; the exact result was
  one admitted reservation and one quota denial with no over-admission.
- Real retry evidence: A separate transaction retained the allowlisted quota
  row lock long enough for the deployed writer's one-second session timeout.
  SQLAlchemy observed MySQL error 1205 from the actual database path, the
  installed Coffer decorator emitted exactly one `set_limit` attempt-2 record,
  and that second whole transaction committed after the lock was released.
  No exception was patched, wrapped, or synthesized.
- Recovery: Child-first cleanup removed every allowlisted claim, manifest,
  descriptor edge, reservation, descriptor, and project quota. An independent
  helper preflight reported aggregate residue zero. The ordinary tenant
  database write/read/restore probe then passed with its original limit, and
  the accepted manifest/blob, project-B denial, log hygiene, external RGW,
  three-node Primary/Synced Galera, and all ProxySQL routes remained healthy.
- Evidence and replay: Root-only owner/completion markers were written only
  after the final gates. Repeating `run` executed no transaction probe,
  reported `idempotent=yes`, reconfirmed residue zero and full tenant/Galera
  health, and retained identical inode, size, timestamp, owner, group, and
  mode metadata for both markers.
- Next exact action: Inspect the deployed reconciler topology and the accepted
  multi-worker claim/fencing fixtures. Then add a bounded separate-worker
  Galera harness that creates only allowlisted stale reservations, proves
  disjoint claims and fencing/lease recovery across controller replicas,
  restores all rows, and retains tenant service before signing-key overlap or
  rollback.

### 2026-07-25 — Separate-worker reconciler fencing harness validated

- Completed locally: Added a guarded `preflight|run` harness that executes the
  installed claim/fencing implementation as separate stdin-only processes in
  the controller-1 and controller-2 `coffer_api` containers. The deployed
  periodic reconciler remains intentionally disabled because its production
  maintenance identity is unresolved; this phase isolates the shared-Galera
  worker/lease contract without inventing that identity.
- Candidate boundary: The claim API is intentionally global, so the setup
  records a timezone-aware cursor immediately before its three synthetic
  reservations. Both workers pass that cursor to `after`, excluding every
  older tenant or system reservation. Only two fixed project IDs and four fixed
  repository IDs may be created or cleaned.
- Multi-worker contract: Both controller processes claim concurrently with
  bounded batches of two. A bounded retry by the initially smaller worker
  tolerates MariaDB's safe empty-batch behavior. Final acceptance requires
  three unique reservations, three unique claim tokens, no overlap, and both
  exact worker IDs before every claim is consumed and usage returns to zero.
- Lease/fence contract: Controller-2 acquires one separate two-second lease and
  exits cleanly. Controller-1 proves that a logical time immediately before
  expiry cannot reclaim it, waits for actual wall-clock expiry, replaces the
  token, rejects the old token with `StaleReconciliationClaim`, and consumes
  the replacement claim.
- Recovery: A root-only owner marker authorizes child-first cleanup on an
  interrupted resume. The EXIT trap removes only the allowlisted rows and
  owner-only local worker outputs; completion requires aggregate residue zero,
  both nodes' installed retry bound, tenant acceptance, and healthy
  Galera/ProxySQL.
- Verification: Thirty-two focused tests, Bash syntax, ShellCheck, Python
  compilation, four refusal/forbidden-command contracts, scoped Gitleaks, and
  diff checks pass. Live mutation-free preflight reports both controller
  helpers ready, retry bound 3, aggregate residue zero, absent marker/helper
  state, and full tenant/Galera health.
- Next exact action: Commit the guarded reconciler fencing harness, invoke only
  its `run` action once, and require disjoint cross-controller claims, actual
  lease expiry and stale-token denial, exact cleanup, retained tenant service,
  owner-only evidence, and metadata-idempotent replay before signing-key
  overlap.

### 2026-07-25 — First reconciler run failed safely on cursor precision

- Failure: Preserved the initial harness in `b5b954a`. Its first `run` created
  the root-only owner marker and three allowlisted reservations, but both
  workers returned empty claim batches. The bounded retry also remained empty,
  so the harness stopped before lease/fence work or completion-marker creation.
- Root cause: The application cursor retained microseconds while the migrated
  MariaDB `updated_at` column stores whole seconds. Reservations created in the
  same database second were therefore truncated to a value earlier than the
  cursor and correctly excluded by `after`.
- Recovery evidence: The EXIT trap removed every allowlisted row and local
  worker output. Independent preflight reports aggregate residue zero; the
  owner marker alone records an exact resumable partial state. No tenant row,
  service, identity, credential, object, or container changed.
- Correction: The helper now records a whole-second cursor, crosses the next
  wall-clock second before inserting any candidate, and then creates the
  reservations. A bounded owned diagnostic returned claims 2+1 across
  controller-1 and controller-2 and removed all rows afterward.
- Verification: Python compilation, fourteen focused runtime-contract tests,
  diff checks, and the exact two-controller diagnostic pass.
- Next exact action: Commit the cursor-precision correction, rerun only the
  owned-partial `run`, and require cleanup-before-resume, disjoint 2+1 or
  bounded-equivalent claims, actual lease recovery/fencing, final residue
  zero, complete acceptance, and idempotent replay.

### 2026-07-25 — Separate-worker Galera fencing accepted

- Completed: Preserved the cursor correction in `83c223d` and resumed the
  owner-only partial run. It performed allowlisted cleanup before recreating
  candidates. Controller-1 and controller-2 ultimately claimed 1+2 unique
  rows with one bounded retry after MariaDB returned a safe transient empty
  batch; both worker IDs, all three reservation IDs, and all three claim tokens
  were unique with no overlap.
- Lease/fence evidence: Controller-2 acquired the separate two-second lease
  and exited. Controller-1 proved a pre-expiry logical claim remained blocked,
  waited through real wall-clock expiry, acquired a different token, and
  received `StaleReconciliationClaim` when it attempted the abandoned token.
  The replacement token released the reservation and restored quota.
- Recovery and service evidence: Child-first cleanup plus both controller
  helpers reported aggregate residue zero and retry bound 3. The ordinary
  tenant database write/read/restore, manifest/blob, project-B denial,
  runtime-log hygiene, three-node Galera/ProxySQL, HAProxy, and external RGW
  gates all passed before completion.
- Replay: The root-only completion marker was written after final acceptance.
  Repeated `run` executed no setup, claim, wait, or mutation; both controller
  preflights reconfirmed residue zero and marker inode, size, timestamp,
  ownership, group, and mode remained identical.
- Scope statement: This proves real shared-Galera claims, lease expiry, and
  fencing from separate controller processes. It does not enable the periodic
  reconciler or decide its production maintenance identity.
- Next exact action: Inspect the current signing-key/JWKS materialization and
  token-validation contracts, then add a bounded overlapping-key rotation
  harness. It must retain old-token validity during overlap across all edge
  and Distribution replicas, switch the signer to a new key, retire the old
  public key only after its maximum token lifetime, prove old-token rejection
  and new-token success, and keep an exact rollback path.

### 2026-07-25 — Overlapping signing-key rotation harness validated

- Completed locally: Added guarded `preflight|status|run|rollback` actions.
  Controller-1 retains root-only original/new RSA material and phase markers;
  only public old+new or new-only JWKS reaches edge and Distribution. Every
  Kolla phase uses `kolla_serial=1`, the already accepted update image, an
  owner-only temporary globals overlay, and secret-scanned owner-only logs.
- Forward phases: Deploy the overlapping JWKS while the old signer remains,
  mint an old-key tenant token, switch all API signers to the new key, and
  prove old/new tokens across every direct edge and Distribution replica.
  After the recorded old token's full 300-second lifetime plus a two-second
  guard, deploy new-only JWKS and prove a fresh live new token succeeds while a
  still-time-valid synthetic old-key token is rejected.
- Non-mutating edge proof: Each edge verifier receives an authenticated
  intentionally malformed manifest. A trusted key reaches bounded manifest
  validation and returns 400; an unknown retired key returns 401 before any
  quota or upstream mutation. Distribution receives only HEAD against the
  retained accepted digest.
- Durable and rollback boundary: Persistent globals change only
  `coffer_token_key_id`; the temporary overlay may additionally retain the
  accepted update image. Original private/public material stays root-only.
  The reverse action restores overlap, switches the signer back, waits out the
  new-token lifetime, retires the new public key, and restores old-only trust.
- Availability and hygiene: The outer harness continuously runs accepted
  manifest/blob/project-B path probes throughout Kolla changes and the bounded
  lifetime wait. Token responses, bearer configs, and expiry metadata are
  owner-only and deleted before completion. Final gates include all nine
  containers, tenant/quota/log hygiene, HAProxy, and external RGW.
- Verification: Sixty-one focused token/runtime tests, Bash syntax, ShellCheck,
  four refusal/forbidden-command contracts, scoped Gitleaks, and diff checks
  pass. Live mutation-free preflight reports all three API signers and six
  verifier recipients on old-only `stage5-20260724`, full tenant service, and
  no rotation state.
- Next exact action: Commit the guarded key-rotation harness, invoke only its
  `run` action, and require overlap, signer transition, old-token continuity,
  full-lifetime retirement, per-replica new/old outcomes, zero token residue,
  owner-only evidence, and metadata-idempotent replay before image rollback.

### 2026-07-25 — First key-rotation run failed safely before deployment

- Failure: Preserved the harness in `e5b713d`. Its first run created the
  root-only owner directory and copied the original rollback inputs, then the
  new-material generator failed because the Kolla control venv does not install
  the Coffer package and could not import `coffer.tokens`.
- Safety evidence: No prepared/phase/completion marker exists. The source and
  all three runtime replicas remain old-key/old-only JWKS, all nine containers
  are healthy, the temporary globals file is absent, and no Kolla/Ansible
  action or token issuance occurred. Only the exact owner plus empty
  new/token/log directories and owner-only original backups exist.
- Correction: Replaced the project import with a local RFC-compatible RSA JWK
  encoding using the already present cryptography dependency. The state
  machine now re-enters `prepare_material` whenever the prepared marker is
  absent, while first requiring the exact owner marker; unknown partial state
  still fails closed.
- Verification: Bash syntax, ShellCheck, focused runtime contracts, diff
  checks, and an independent live aggregate audit of the exact pre-deployment
  partial state pass.
- Next exact action: Commit the preparation-resume correction and rerun only
  key-rotation `run`. It must finish new material, deploy overlap serially,
  switch the signer, preserve old-token service, wait the full lifetime, retire
  old trust, and pass all replica/residue/final gates.

### 2026-07-25 — Overlap deployment converged before its marker

- Failure: The corrected run generated valid owner-only material and completed
  the serial overlap Kolla phase with zero failed or unreachable Ansible
  hosts. Its immediate post-deploy runtime assertion nevertheless exited
  before writing the overlap marker while container health was still
  converging.
- Safety evidence: An independent aggregate audit found the exact recoverable
  boundary: the source and all six edge/Distribution recipients have only the
  expected old+new JWKS, all three API signers remain on the old key, all nine
  containers are healthy, the persistent key ID remains old, no token exists,
  and the temporary globals overlay is absent. Tenant manifest/blob reads and
  project isolation continued to pass throughout and after the run.
- Correction: Mutation phases now wait a bounded two minutes for all three
  replicas to converge. An unmarked overlap phase may adopt only the exact
  old-signer/old+new-verifier state; an unknown JWKS state fails closed. The
  resumed phase still mints and verifies the old token before it records the
  marker.
- Next exact action: Validate and commit this convergence/adoption correction,
  then rerun only key-rotation `run` from the audited exact overlap state.
  Require the remaining signer, lifetime, retirement, residue, and final
  acceptance gates before compatible image rollback.

### 2026-07-25 — Token client boundary corrected

- Failure: Exact overlap adoption and all-node convergence passed, but the
  controller-1 orchestration process could not connect directly to the
  external VIP currently owned by controller-2. It failed before receiving or
  storing a registry token; the independently placed tenant client on the VIP
  owner continued to pass.
- Evidence: Three bounded unauthenticated controller-1 attempts returned
  connection refusal, while the same verified-TLS request executed on the
  discovered controller-2 VIP owner returned the expected 401 challenge.
  Only one owner-only Basic-auth curl config remained, with no response,
  bearer, expiry, overlap marker, or later phase marker.
- Correction: Token exchange now discovers the sole external VIP owner and
  streams the owner-only curl configuration to a bounded remote curl over the
  existing controller SSH trust. It writes no credential on the owner,
  retries only the external request for at most 30 seconds, and removes every
  exact label file on a failed exchange.
- Follow-up correction: The first owner-routed attempt used the unprivileged
  SSH user for curl. Although the selected CA file itself is public, its Kolla
  parent directory is root-restricted, so curl returned error 77. The remote
  request now uses only the existing passwordless root curl boundary. An
  independent audit confirms the failed attempt removed all token files,
  retained only the prepared marker, and left no temporary globals overlay.
- Next exact action: Validate and commit the owner-client correction, then
  resume only key-rotation `run`. Require no token residue, complete overlap
  and signer markers, full old-token lifetime, old-key retirement, and all
  final tenant/service/storage gates.

### 2026-07-25 — Signer deployment converged before its marker

- Failure: Owner-routed old-token exchange passed and the overlap marker was
  written. The serial signer Kolla phase then completed with zero failed or
  unreachable hosts, but its bounded post-deploy state wait ended before
  writing the persistent key ID or signer marker. One tenant request returned
  503 during the serial change and passed on the admitted second attempt.
- Safety evidence: All three API replicas now use the new signer and all six
  verifiers retain old+new trust. The source private key matches only the new
  JWK, persistent globals still name the old key, the temporary overlay is
  absent, and only the four owner-only old-token artifacts exist. Both Kolla
  phase logs have zero failed or unreachable hosts and all nine containers
  are healthy.
- Correction: The signer and retirement phases may now adopt only their exact
  unmarked applied states, using private/public key matching plus all-replica
  runtime assertions. Unknown states fail closed. Runtime convergence remains
  bounded but allows six minutes for slow serial container health transitions.
- Next exact action: Validate and commit this phase-resume correction, then
  resume only key-rotation `run`. It must adopt the exact new-signer/overlap
  state, update the persistent key ID, prove the retained old token and a new
  token, wait out the old token, retire old trust, and clear all residue.

### 2026-07-25 — Direct manifest probe corrected

- Failure: Exact signer adoption and persistent key-ID update passed. The
  issued old and new tokens both reached authenticated manifest validation on
  all three edge replicas with the expected 400, but direct Distribution HEAD
  returned 404 because the key-rotation probe omitted the OCI/Docker manifest
  `Accept` headers already used by the accepted tenant probe.
- Evidence: Both tokens returned the same 404/400 matrix on all three
  registry/edge pairs; unknown-key behavior is 401, so this was not a signer
  or trust failure. The retained actual old token was still unexpired during
  that audit. The signer marker was not written, source/runtime remain exact
  new-signer/overlap trust, persistent globals now name the new key, and the
  temporary overlay is absent.
- Correction: Direct registry HEAD now sends the accepted OCI and Docker
  manifest media types. Because the actual old token expired while this
  harness defect was corrected, the resume preserves its already observed
  API-issued kid and pre-expiry edge acceptance, then uses a fresh
  time-valid old-key token during overlap to complete registry 200/edge 400 on
  every replica. Retirement still creates a separate time-valid old-key token
  and requires 401/401 after old trust is removed.
- Next exact action: Validate and commit the manifest-probe correction, then
  resume only key-rotation `run`; require complete signer/retirement markers,
  new-key 200/400, retired-old 401/401, zero token residue, and final service
  gates.

### 2026-07-25 — Forward key rotation completed; outer replay gate pending

- Completed remotely: The corrected overlap proof returned registry 200 and
  edge 400 on all three replicas for both a time-valid old-key token and a
  fresh API-issued new-key token. After the original issued old token's full
  lifetime had elapsed, serial retirement converged to new-only trust. A
  fresh new token returned 200/400 on all replicas and a time-valid old-key
  token returned 401/401 on all replicas.
- Availability and residue: Continuous tenant probes passed except for one
  admitted second-attempt recovery during signer change and one admitted
  third-attempt recovery during retirement. The complete marker is root-only,
  all token files and the temporary globals overlay are absent, all nine
  containers are healthy with new signer/new-only JWKS, and the independent
  read-only key-rotation status passed.
- Wrapper failure: The final resumed guest phase completed during the first
  in-flight tenant probe. The outer wrapper then returned 1 only because it
  required three in-flight probes and did not fill the minimum after a fast
  idempotent/resume completion.
- Correction: The outer wrapper now performs at most three bounded
  post-completion tenant probes until the same minimum is met; any failed
  probe still fails the action. It does not rerun or mutate the guest phase.
- Next exact action: Validate and commit this post-completion probe correction,
  capture completion-marker metadata, rerun `run` idempotently, and require
  metadata identity plus all final companion, tenant, and key status gates
  before accepting key rotation.

### 2026-07-25 — Overlapping signing-key rotation accepted

- Completed: Preserved the post-completion probe correction in `7533307`.
  The idempotent replay executed no Kolla phase, passed exactly three tenant
  path probes, and completed the full companion, tenant, storage, and
  new-signer/new-only-JWKS status gates.
- Cryptographic evidence: Before retirement, a time-valid old-key token and a
  fresh API-issued new-key token each returned registry 200 and edge 400 on
  all three replicas. Retirement occurred after the original API-issued old
  token's recorded 300-second lifetime. Afterwards, a fresh new-key token
  returned 200/400 and a still-time-valid old-key token returned 401/401 on
  all replicas.
- Availability and hygiene: All serial phases had zero failed/unreachable
  Ansible hosts. Transient tenant 503s recovered within the admitted bounded
  attempts, and every other continuous probe passed. Final state has nine
  healthy containers, three new-key signers, six new-only verifiers, no token
  file, no temporary globals overlay, root-only phase logs/markers, and a
  healthy external RGW boundary.
- Replay: The completion marker retained the same inode, size, modification
  time, owner, group, and mode across the successful replay. The command
  exited zero with `probes=3`, `serial=1`, and `idempotent=yes`.
- Scope: This accepts forward overlapping rotation and old-key retirement.
  The separately guarded reverse key action remains available but is not
  required for the image compatibility rollback gate.
- Next exact action: Run mutation-free rolling-update status and inspect the
  rollback overlay against the now-persistent new signing key. Then invoke
  only `run-coffer-rolling-update.sh rollback`, preserving tenant service and
  new-key trust while restoring the original compatible Coffer image.

### 2026-07-25 — First compatible image rollback failed before Kolla

- Failure: Mutation-free rolling status passed at exactly three updated
  API/edge pairs. The rollback then failed before creating a log or invoking
  Kolla because its overlay builder matched one exact quoted YAML line.
  Key-rotation's safe YAML rewrite retained the same image value without
  quotes, so the textual match wrote a partial overlay and rejected it.
- Safety evidence: Both surrounding tenant probes passed. The upgrade marker
  remains valid, no rollback marker/log exists, all three API/edge pairs
  remain on the update image, new signer/new-only JWKS state is unchanged,
  and all services are healthy. The only residue is the exact owner-only
  `/run/coffer-stage5-rolling-globals.yml`; it contains the same parsed
  configuration as persistent globals and was never passed to Kolla.
- Correction: Overlay creation now parses YAML, changes only
  `coffer_image_full`, verifies the exact changed-key set, writes an
  owner-only staged path, and atomically renames it. A failed build removes
  only its uniquely named staged path and cannot leave the admitted overlay.
- Next exact action: Validate and commit the structured overlay correction.
  Verify the failed overlay's owner, mode, and parsed equality to persistent
  globals, remove only that exact disposable residue, rerun rolling status,
  then invoke only compatible image `rollback`.

### 2026-07-25 — Rollback applied but availability acceptance failed

- Applied state: After exact overlay cleanup, mutation-free status again
  reported three updated pairs. The structured overlay passed and serial
  rollback completed with zero failed or unreachable Ansible hosts. All three
  API/edge pairs now run the original compatible image while retaining the
  new signer and new-only JWKS; all nine containers are healthy and the
  temporary overlay is absent.
- Log-guard root cause: The guest stopped before convergence/marker output
  because its broad `private key` scan matched only the public Ansible task
  name `Copy backend TLS private keys to listener processes`. Counts for
  authorization, application-credential secret, and password assignment were
  zero. The key-rotation Kolla phases encountered the same false positive,
  explaining their exact applied-but-unmarked boundaries; their later strict
  adoption checks remain valid.
- Availability failure: Most continuous path probes passed, but one probe
  exhausted all three bounded attempts with 503 during the rollback. Later
  probes and the final aggregate audit recovered. This is retained as a real
  failed availability rehearsal even though image convergence succeeded; it
  is not waived or relabeled as success.
- Correction: Log hygiene now rejects an actual PEM private-key header rather
  than a benign task label. Rollback becomes a two-phase acceptance:
  `rollback-rehearse` performs the image transition but cannot write the final
  marker; the outer observer writes it through `rollback-finalize` only after
  every availability probe passes. On probe failure, `rollback-reset` removes
  only the exact rehearsal marker so a complete update-then-rollback cycle can
  be repeated. Re-upgrade and rollback remain serial-one and use the two
  already pinned image IDs.
- Next exact action: Validate and commit the corrected log guard and
  two-phase rollback acceptance. From the audited original-image/unaccepted
  state, invoke public `rollback`; it must restore the update image, perform a
  second compatible rollback under continuous probes, preserve the new
  signing key, and finalize only with zero probe failures.

### 2026-07-25 — Play serial did not serialize Coffer handlers

- Reproduction: The two-phase retry correctly withheld finalization, but one
  three-attempt 503 window recurred during the re-upgrade and another during
  rollback. Both Ansible phases otherwise converged with zero failed or
  unreachable hosts, and `rollback-reset` removed only the rehearsal marker.
  Current state is again the healthy original-image/new-key boundary with no
  final rollback marker.
- Root cause evidence: The Ansible log shows one handler flush restarting
  `coffer-api` on all three controllers and then `coffer-edge` on all three.
  Docker start timestamps confirm two API replicas restarted in the same
  second and all three edge replicas restarted within one second. The
  play-level `kolla_serial=1` did not constrain the notified handler flush, so
  the supposed rolling operation had all-replica outage windows.
- Correction: A rolling image phase now executes three separately limited
  Kolla invocations, one exact controller at a time. After each invocation it
  requires that host's API and edge to be healthy on the desired pinned image
  before the next controller is admitted. The existing cluster-wide
  convergence, continuous tenant probes, two-phase finalization, and exact
  reset remain in force.
- Next exact action: Validate and commit the per-controller `--limit`
  correction, then invoke public `rollback` from the same unaccepted boundary.
  Require update and rollback to show three ordered host convergence records,
  zero fully failed tenant probe windows, final marker creation, and complete
  service/key/storage acceptance.

### 2026-07-25 — Limited load-balancer render failed before mutation

- Failure: The first per-controller re-upgrade invocation stopped with Kolla
  rc 2 before any container change. HAProxy's shared template iterates every
  backend host and requires gathered `hostname` facts, while `--limit` had
  intentionally gathered facts for only controller-1.
- Safety evidence: Both tenant probes passed, the update/rollback images and
  key state did not change, no rehearsal marker or temporary overlay exists,
  and the owner-only diagnostic log contains only the expected censored
  template failure.
- Correction: Image-only per-controller invocations now skip the unchanged
  HAProxy/loadbalancer, Fluentd, cron, and Prometheus plays. Only the Coffer
  role is admitted on the one limited host; load-balancer and observability
  configuration were already accepted and are not image-dependent.
- Next exact action: Validate and commit the scoped skip-tag correction, then
  rerun only public `rollback` from the unchanged original-image/unaccepted
  boundary.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Published Stage 4/image baseline | local and remote Git commit equality | passed at `4f1ff7d` |
| Host capacity and namespace | bounded read-only Stage 5 audit | passed |
| Mutation-free provision preflight | schema, budget, namespace, network, and image gates | passed |
| Libvirt lifecycle safety | allowlists, exact destroy, partial rollback, remote status | passed; exact create completed |
| Guest provisioning and readiness | exact status, autostart, cloud-init, NIC, disk, and resource checks | passed |
| Provision/destroy target safety | local allowlist, rollback, and negative-target tests | passed |
| Storage preparation | pinned inputs, hostname map, chrony, empty OSD devices | passed |
| Ceph control plane | exact hosts, 3-MON quorum, 2 MGRs, key recipients, zero OSD/RGW | passed at the zero-OSD checkpoint |
| Ceph replicated OSDs | exact devices, 3 up/in OSDs, host CRUSH domain, size/min 3/2, idempotency | passed; `HEALTH_OK` |
| RGW HA endpoint | 3 RGWs, 2 ingress pairs, one VIP owner, backend/frontend TLS, idempotency | passed; 5 pools/129 clean PGs, zero users |
| S3 fixture | owner-only identities, denials, persistent sentinel, idempotency | passed twice; digest retained, no secondary residue |
| RGW daemon faults | storage-3 RGW and active ingress pair, reads, restoration | passed; 10 fault-window reads and full independent recovery |
| Storage VM fault | exact storage-3 power loss, degraded reads, full recovery | passed; 5 outage reads and independent 3-node recovery |
| Kolla controller preflight | pinned inventory/globals and three clean controller guests | passed mutation-free; external RGW remains healthy |
| Kolla prepare harness | owner/recipient boundaries, pinned tooling, secrets, stop gate | passed live and independently audited; runtime/VIPs remain absent |
| Kolla lifecycle harness | phase allowlist, ordering, timeouts, logs, markers, status, storage boundary | passed after no-log guard, credential rotation, and owner-local VIP probe |
| Kolla/Galera baseline | multinode deploy, quorums, identity, TLS, and secret acceptance | passed; 36 healthy containers, Galera/RabbitMQ three-node quorums |
| Coffer HA pre-deploy boundary | clean/ready controller, DB, catalog, TLS, image, and RGW recipient gates | clean passed live; ready fails closed before preparation |
| Kolla production profile preparation | exact certificate/globals mutation, rollback, idempotency, no runtime reload | passed; source prepared and runtime unchanged |
| Kolla production profile reconfigure | internal/external TLS, single frontend, catalog, quorums, logs, absent Coffer | passed idempotently; 36 healthy containers |
| Coffer image build/distribution | pins, owner/resume boundary, direct transfer, identical IDs, idempotency | passed; two exact images on three controllers, runtime absent |
| Coffer quota-retry update image | pinned archive/source, identical IDs, retained rollback, runtime unchanged | passed; update image on 3 controllers, metadata-idempotent replay |
| Coffer companion preparation | inventory, inputs, direct RGW transfer, rollback, idempotency, absent runtime | passed; complete marker and integrated ready gate accepted |
| Coffer HA baseline | companion deploy and replicated service acceptance | passed; 9 healthy replicas, 18 sockets, full TLS/routing and log-hygiene gates |
| External RGW HA | quorum, TLS endpoint, object and replica-loss acceptance | passed for daemon and storage-VM loss |
| OCI and isolation | two-project clients through sole external edge | passed; quota 429/success, Docker push/pull, two-part upload, project-B denial, digest/log/residue gates |
| Coffer replica faults | controller-3 API, edge, and Distribution stop/probe/restore | passed; 9/9 authenticated outage probes, complete recovery, idempotent replay |
| Kolla HAProxy fault | active-owner stop, paired VIP movement, tenant probes, restore | passed; VIP moved controller-3 to controller-2, 3/3 bounded probes, idempotent replay |
| Galera member fault | controller-3 pause, size-2 writes, exact unpause/rejoin | passed; 3/3 quota write/read/restore probes, size-3 recovery, idempotent replay |
| Tenant credential renewal | two-phase finite replacement, data continuity, residue, replay | passed; 2 credentials, digest/isolation retained, owner-only metadata stable |
| Fault and recovery matrix | Galera concurrency/retry and reconciler faults plus restore checks | passed; periodic maintenance identity remains a production decision |
| Upgrade, key rotation, rollback | bounded rolling rehearsals | upgrade and forward key rotation passed; compatible image rollback pending |
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

- Current state: Active; the Ceph control plane and exact three-host replicated
  OSD baseline plus three-RGW/two-ingress TLS endpoint are healthy. The two
  owner-limited S3 identities and buckets are provisioned; the deterministic
  private sentinel passed two identical baseline round trips and ten reads
  across one RGW and one active-ingress fault. All services are restored. The
  exact storage-3 VM power-loss cycle and full recovery passed. All services
  are healthy and all six domains are running. The three-controller Kolla
  inventory and lifecycle are deployed with three-node Galera/RabbitMQ
  quorums, 36 healthy containers, and one owner for each Kolla VIP. The
  mutation-free Coffer `clean` boundary passes across controller runtime,
  Galera, Keystone, companion inputs, and the external RGW fixture. The Kolla
  production profile and its guarded reconfigure are accepted: internal and
  external certificate identities, ProxySQL TLS recipients, four production
  globals, internal HTTPS, the sole external port 443 frontend, catalog URLs,
  three-member Galera/RabbitMQ quorums, seven protected logs, and zero Coffer
  state all pass. The companion inputs are now complete: four exact
  three-host groups, production globals, controller-1-only secret/public
  inputs, verified backend/RGW TLS, and durable owner/input/completion markers
  pass both integrated ready and repeated metadata-idempotency checks. The
  accepted deploy has nine healthy service containers, twelve configs,
  eighteen backend/frontend listeners, migration head, exact catalog,
  verified internal and external routing, denied private-port bypass, and a
  root-only deploy marker. Repeated deploy is metadata-idempotent, and the
  nine-container runtime log hygiene gate passes without retained audit
  residue. The controller-3 API, edge, and Distribution single-replica matrix
  also passes: nine authenticated outage probes retained both project-A
  digests and project-B denial, every container recovered healthy, and a
  metadata-stable replay skipped all completed faults. The active-owner
  HAProxy cycle also passes: paired VIPs moved together, all three bounded
  tenant probes passed, the exact HAProxy recovered, and replay was
  metadata-idempotent.
- Exact next action: Inspect the real deployed quota transaction retry
  surface, then implement a bounded concurrent/deadlock Galera probe with
  exact row and quota restoration.
- First file or command: Read `src/coffer/quota.py` transaction/retry helpers
  and the accepted shared-SQL deadlock tests before adding the Stage 5
  concurrent database phase.
- Questions requiring user input: None for read-only inventory and local
  harness work. Ask before expanding to a different substrate, production
  credentials/data, a private Distribution fork, external publication, or an
  operation outside the exact disposable Stage 5 allowlist.
