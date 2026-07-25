# Stage 6 Load, Soak, and Fault Baseline

- Date: 2026-07-25
- Status: implementation contract
- Scope: public registry data plane, control/token plane, quota admission,
  shared Galera, external RGW/SSE-KMS, reconciliation, HAProxy, observability,
  accepted OCI clients, and bounded failure injection
- External operations: none; this result comes from source/config inspection
  and official project documentation

## Outcome

Stage 5 proves functional HA slices, not a representative capacity or soak
envelope. It used Docker for authenticated tenant push/pull, a two-part raw
resumable upload, one quota denial, cross-project isolation, one-replica
service faults, HAProxy and Galera failover, concurrent quota transactions,
reconciler claim fencing, and signing-key rotation. Those tests were serial
acceptance transactions. They did not maintain load while faults occurred,
measure latency distributions, find saturation, run ORAS or containerd, or
correlate Coffer, HAProxy, Galera, RGW, and KMS signals.

The Stage 6 baseline will use two layers:

1. a deterministic protocol load driver owns high-concurrency raw OCI
   Distribution operations and emits bounded versioned evidence; and
2. real Docker, Podman, Skopeo, ORAS, and containerd/nerdctl commands prove
   client compatibility at bounded concurrency before and after the load
   window.

The driver must not simulate Coffer policy or issue its own signing key. It
obtains finite credentials through the public accepted flow, follows the
registry Bearer challenge, uses the external private-TLS FQDN, and sends all
blob bytes through Coffer edge to unmodified Distribution. Client and driver
state is disposable, owner-only, and removed after evidence collection.

No load execution is authorized against a production endpoint. The only
permitted target is the fresh Stage 6 disposable Kolla/RGW pilot whose exact
inventory, FQDN, CA, credential IDs, bucket, database, and teardown ownership
have passed preflight.

## Current Capacity Boundary

The accepted observability topology fixes one API worker with four threads and
one edge worker with eight threads per replica. Stage 5 uses three controller
replicas behind HAProxy, three Distribution replicas over one shared RGW
bucket, a three-member Galera cluster, three RGW daemons behind two ingress
daemons, and SQL-fenced reconciler workers. Blob streaming does not consume an
API worker, while every edge request and manifest admission consumes edge
capacity. Manifest publication also creates a short Galera transaction.

This is the first capacity boundary. The load gate may tune thread counts and
timeouts only after a measured saturation ramp; it may not silently add API or
edge workers because that would invalidate the direct per-process metric
contract in ADR 0016.

## Accepted Client Matrix

| Client | Required proof | Concurrency ownership |
|---|---|---|
| Docker Engine | login, push, pull by tag and digest, five-layer concurrent upload, restart-safe credential cleanup | Docker daemon default five concurrent layer uploads is recorded |
| Podman | login, push, pull by digest, temporary root/runroot cleanup | one process per bounded client slot |
| Skopeo | authenticated registry-to-registry copy and digest inspection | two copies in parallel, no local daemon |
| ORAS | OCI artifact push/pull, subject plus fallback referrers tag, explicit concurrency | driver records the requested ORAS concurrency |
| containerd/nerdctl | login, image push/pull through verified registry host configuration | one namespace and disposable content root |
| Raw OCI API driver | monolithic, chunked/resumed, cross-mount, manifest/index/artifact, HEAD/GET/DELETE, retry and exact digest checks | primary controlled concurrency source |

Docker, Podman, and Skopeo already have earlier local or Stage 4/5 functional
evidence. ORAS and containerd/nerdctl are still open and must pass on both
supported host architectures. Insecure-registry flags are forbidden in the
production-candidate profile; all clients consume the operator CA and the
exact registry hostname.

## Request and Content Matrix

Every qualification run uses deterministic pseudorandom bytes whose seed,
size, media type, and digest are recorded without retaining payload data.

| Shape | Size or count | Purpose |
|---|---:|---|
| control/token list/create/get | 1,000 operations | Keystone cache, API/SQL pool, token issuer, bounded latency |
| manifest HEAD/GET | 10,000 operations | pull control path and HAProxy/edge/registry latency |
| blob range/full GET | 1 MiB, 32 MiB, 256 MiB | streaming throughput, cancellation, digest integrity |
| monolithic upload | 0 B, 1 B, 1 MiB, 32 MiB | zero-byte KMS gate and normal finalize behavior |
| chunked/resumed upload | 256 MiB in 16 MiB chunks | upload UUID/location continuity across replicas |
| parallel layers | five 32 MiB layers | Docker-compatible concurrent upload shape |
| shared blob cross-mount | 32 MiB into 32 repositories | deduplication, authorization, project accounting |
| manifest contention | 32 concurrent finalizes | one-winner quota reservation and idempotent replay |
| image index | two platform children | recursive references and digest-only child retention |
| OCI artifact | subject, referrer, fallback index | ORAS compatibility and pinned Referrers disposition |
| abandoned upload | two partial 64 MiB uploads | purge metrics and physical staging guardrail |

The released Ceph/RGW candidate must pass both zero-byte and positive-size
SSE-KMS finalize before the zero-byte row can be enabled. A blocked released
candidate causes the whole production profile to remain blocked; it is not
converted into an expected failure.

## Profiles and Saturation Ramp

The harness has three immutable profiles:

| Profile | Duration | Virtual clients | Transfer ceiling | Use |
|---|---:|---:|---:|---|
| smoke | 2 minutes | 4 | 2 GiB | deploy/reconfigure sanity |
| qualification | 30 minutes plus faults | 16 steady, 32 burst | 40 GiB | Stage 6 acceptance |
| soak | 2 hours | 8 steady, 32 for each 5-minute burst | 160 GiB | production-candidate evidence |

Before qualification, a disposable 10-minute ramp runs 1, 2, 4, 8, 16, 32,
and 64 virtual clients. Each level stops early on an availability breach,
resource guard, growing queue, or p95 latency above its ceiling. The accepted
operating point is the highest completed level for which:

- API, edge, registry, Galera, RGW, and HAProxy have at least 30% CPU and
  memory headroom;
- file descriptors, connection pools, Galera receive/send queues, RGW request
  queues, and disk capacity remain below 70% of their configured limits;
- no backlog or active-upload count grows for two consecutive observation
  windows after offered load becomes steady; and
- one higher level either completes with the same guarantees or records the
  first measured bottleneck. An untested maximum is not a capacity claim.

The qualification and soak profiles run at no more than 80% of the accepted
virtual-client point. Transfer ceilings are hard stop conditions, not targets.

## Latency and Availability Gates

ADR 0016 already fixes monthly availability objectives. The pilot adds these
initial latency objectives for successful, non-fault-window requests:

| SLI | p95 gate | p99 guard |
|---|---:|---:|
| valid control or token request | 1 s | 2 s |
| manifest HEAD/GET | 500 ms | 2 s |
| manifest publication/admission | 2 s | 5 s |
| blob upload start/status/finalize excluding body transfer | 1 s | 5 s |
| blob first byte | 1 s | 3 s |

The load driver separately reports transferred bytes and wall-clock
throughput; it does not fold a 256 MiB body duration into a request-latency
histogram. No absolute network throughput SLO is portable across the lab and
production. The pilot records median, p95, p99, and minimum sustained
throughput for each content size and treats that result as the release
baseline.

Outside declared fault windows there may be no unexpected 5xx, digest
mismatch, lost successful finalize, duplicate quota charge, stale claim
application, or client retry exhaustion. Policy 401/403/404/429 outcomes are
counted separately and must match their injected request class.

## Fault Matrix

Faults are serial, bounded, and injected only after ten steady minutes. The
same offered load continues during each window.

| Fault | Maximum window | Required outcome |
|---|---:|---|
| one API replica stopped | 60 s | control/token recovers within 30 s; no cross-project result |
| one edge replica stopped | 60 s | client retries succeed; no direct Distribution bypass |
| one Distribution replica stopped mid-upload | 60 s | upload status resumes or safe retry restarts; digest exact |
| HAProxy external VIP owner failure | 60 s | VIP recovers within 15 s; hostname/TLS unchanged |
| Galera writer/primary failure | 90 s | bounded retry, no double reservation, cluster returns Primary |
| one RGW daemon failure | 90 s | ingress routes around it; completed content remains exact |
| one RGW ingress failure | 60 s | storage request recovery within 30 s |
| Barbican/KMS unavailable | 60 s | fixed dependency failure, no plaintext fallback, later retry exact |
| reconciler exits after claim | lease plus two cycles | old token fenced, replacement completes once |
| registry and edge rolling restart | one replica at a time | direct metrics reset/stale correctly; availability preserved |

Simultaneous unrelated faults, network partitions, disk corruption, and
physical-host loss are later chaos/DR work. Stage 6 does not infer them from
single-fault results.

## Galera and Quota Correctness

Galera certifies optimistic write sets at commit, so conflict and deadlock
retries are expected under multi-primary contention. The installed Coffer
transaction retry bound remains exactly three. The driver records attempt
counts and fixed outcomes but never treats an automatic retry as a separate
logical operation.

For every contention window:

- the sum of used and reserved bytes never exceeds the configured logical
  limit after committed admission;
- one exact request ID and manifest digest converge idempotently;
- different manifests compete independently without an accidental global
  lock;
- every active claim has one worker, token, version, and finite expiry;
- abandoned claims recover only after expiry and old tokens remain fenced;
- all three Galera nodes converge to the same rows and Primary component; and
- `wsrep_local_recv_queue`, `wsrep_local_send_queue`, certification failures,
  deadlocks, connection-pool waits, and Coffer retries are retained as bounded
  aggregates.

## Evidence Contract

The load driver writes `coffer.load-soak-evidence/v1` with:

- exact profile/topology/release/image/configuration digests;
- start/end monotonic duration and declared fault windows;
- client, operation, content-size, status, result, retry, and latency buckets
  from fixed allowlists;
- transferred bytes, completed logical operations, and digest-check counts;
- pre/ramp/steady/fault/recovery resource and dependency aggregates;
- quota/claim/Galera invariants and final inventory comparison;
- Prometheus target, recording-rule, alert, reset, and stale-series checks;
- secret and identifier leak scan results; and
- exact owned-resource cleanup plus unrelated-state signatures.

Repository names, project IDs, credential IDs, upload UUIDs, tokens,
application secrets, private keys, payload bytes, object keys, SQL connection
strings, and raw URLs are forbidden from retained evidence. Raw client logs
remain owner-only temporary input, are scanned for supplied secrets, and are
deleted before acceptance.

Evidence is incomplete unless an independent verifier checks the canonical
artifact, Prometheus queries, SQL/RGW inventory equality, and exact teardown.
A tool exit code, average latency, Grafana screenshot, or aggregate success
count alone cannot promote a release.

## Implementation Order

1. Add `poc/load-soak/topology.json` and a pure validator/state machine for
   profile, phase, fault, metric, identity, and cleanup contracts.
2. Add a deterministic no-network fixture adapter and canonical evidence
   verifier.
3. Implement the raw OCI protocol driver with verified TLS, bounded response
   bodies, finite retries, deterministic data generation, streaming hashes,
   and no credential retention.
4. Add real-client adapters for Docker, Podman, Skopeo, ORAS, and
   containerd/nerdctl with exact version/image pins.
5. Integrate Prometheus, Galera, RGW, quota, reconciliation, and host resource
   snapshots without granting the load identity operator/admin privileges.
6. Add bounded fault orchestration to the fresh Stage 6 Kolla pilot.
7. Run smoke, ramp, qualification, and soak only after exact released
   Distribution/Ceph inputs, maintenance identity, and backup/restore gates
   pass.
8. Independently verify evidence and teardown before accepting latency
   thresholds or changing worker/thread sizing.

## Primary References

- [CNCF Distribution HTTP API V2](https://distribution.github.io/distribution/spec/api/)
- [Docker image push and concurrent uploads](https://docs.docker.com/reference/cli/docker/image/push/)
- [ORAS push](https://oras.land/docs/commands/oras_push/)
- [nerdctl command reference](https://github.com/containerd/nerdctl/blob/main/docs/command-reference.md)
- [MariaDB Galera certification-based replication](https://mariadb.com/docs/galera-cluster/galera-architecture/certification-based-replication)
- [MariaDB Galera usage guide](https://mariadb.com/docs/galera-cluster/galera-cluster-quickstart-guides/mariadb-galera-cluster-usage-guide)
- [Ceph RGW administration, quotas, and rate limits](https://docs.ceph.com/en/latest/radosgw/admin/)
- [Ceph RGW metrics](https://docs.ceph.com/en/latest/radosgw/metrics/)
- [Kolla-Ansible logging and monitoring](https://docs.openstack.org/kolla-ansible/latest/reference/logging-and-monitoring/index.html)
