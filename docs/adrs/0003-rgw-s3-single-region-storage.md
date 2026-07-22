# ADR 0003: Use Ceph RGW S3 for the Single-Region Storage Baseline

- Status: accepted
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0001-product-discovery.md`

## Context

The selected Distribution v3 data plane provides a first-party S3-compatible storage driver. Its Swift driver is no longer supported, and upstream does not accept new storage drivers. Ceph RGW is common in OpenStack environments and implements an S3-compatible API, while Swift's S3 middleware would introduce an additional compatibility surface.

Distribution uses one active storage backend. A bucket per Keystone project would therefore require separate registry fleets or a custom routing/data-plane layer. Globally content-addressed blobs also make physical-byte attribution to one project ambiguous when content is shared.

## Decision

- Use one private, service-owned Ceph RGW S3 bucket for the regional MVP data plane.
- Access it through the pinned Distribution release's upstream S3 driver with TLS verification, SigV4, the explicit RGW endpoint/region, and path-style addressing when required.
- Use a dedicated least-privilege RGW credential restricted to the registry bucket. Compare a native RGW service key with Keystone-managed EC2 credentials during PoC; do not block the initial data path on per-request Keystone availability.
- Set registry redirect disablement initially so clients cannot access RGW directly and registry-layer audit remains complete. Evaluate expiring signed redirects only after security, replay, network, and performance tests.
- Request server-side encryption with a Barbican/Vault/KMIP-backed RGW KMS path and verify actual headers/algorithms against the selected stable Ceph release.
- Keep signing keys, Distribution HTTP secret, Redis credentials, and S3 credentials outside normal configuration files. Distribution receives only token verification public keys.
- Run multiple Distribution replicas with identical backend configuration and HTTP secret. Use shared Redis when configured, multiple RGWs in one Ceph zone, and HA SQL for Coffer control data.
- Treat Ceph multisite and cross-region registry replication as later disaster-recovery work, not synchronous MVP active-active.

## Quota Decision

RGW bucket/user quotas provide a service-wide guardrail, not project-level truth in a shared bucket. Coffer defines logical project usage as unique digests referenced within that project and charges each project independently even when physical blobs deduplicate across projects.

MVP enforcement is a **bounded soft quota** using reservation/admission plus authoritative reconciliation. Distribution notifications are advisory because their queues are in-memory and best effort. Concurrent/chunked uploads and per-RGW cached quotas mean byte-perfect hard enforcement is not claimed.

## Deletion and Garbage Collection

- Logical manifest deletion is policy-controlled and audited.
- Keep upload purging enabled for abandoned uploads.
- Before Distribution GC, globally disable writes across every replica and run the upstream collector in dry-run mode.
- Run the real mark-and-sweep only in a coordinated read-only/stopped window; prove referenced shared blobs survive.
- RGW's own asynchronous backend/orphan cleanup is a separate process and never substitutes for Distribution reachability GC.

## Alternatives Rejected

### Write or revive a native Swift driver

Rejected because it creates a custom data-path fork against upstream's stated driver policy. Swift remains a possible future storage architecture only after a dedicated need and maintenance owner exist.

### Use Swift's S3 compatibility layer without qualification

Rejected as the baseline because it adds a second compatibility layer that must pass the same multipart, resume, delete, listing, redirect, and consistency gates. It can be evaluated as a deployment-specific option later.

### One bucket or registry fleet per project

Rejected for the MVP because it multiplies control/data-plane resources and complicates routing, upgrades, and operations. It may be reconsidered for strict tenant keys or physical isolation.

### Direct client access to RGW

Rejected initially because it expands credential and URL leakage risk, bypasses registry audit/control, and complicates private networking.

### Treat physical stored bytes as exact project usage

Rejected because cross-repository/global deduplication makes ownership and billing ambiguous. Logical usage is explicit and stable even if it overcharges shared content relative to physical storage.

## Consequences and Risks

- RGW S3 compatibility becomes a release/version gate and requires real-Ceph acceptance, not only MinIO/local testing.
- A shared bucket increases the blast radius of the registry storage credential and depends on strict private access and rotation.
- Soft quotas can overshoot under concurrency; the bound and operator alerting must be measured and documented.
- Always-online GC is not supported by the selected baseline.
- Tenant-specific encryption keys likely require a different topology and are deferred.

## Required PoC Evidence

1. Small, multi-GB, multipart, resumed, concurrent, mounted, deduplicated, and deleted content across at least two Distribution replicas.
2. Kill one replica mid-upload and continue through another without corruption.
3. Deny anonymous access, other buckets, and RGW administration to the registry key.
4. Compare native RGW and Keystone EC2 credentials under Keystone outage and rotation.
5. Verify stored objects are encrypted using the chosen stable Ceph release's supported KMS flow; test key and KMS failure modes.
6. Race tiny logical and RGW quotas across replicas, measure overshoot/reconciliation, and verify OCI-compatible `429` or dependency `503` behavior.
7. Run Distribution GC dry run and controlled collection, then verify shared referenced blobs and RGW backend cleanup.

## PoC Evidence Update — 2026-07-22

- Confirmed the upstream Distribution v3.1.1 S3 driver against Ceph Tentacle 20.2.2 RGW over verified TLS, SigV4, path-style addressing, and a pre-created private bucket.
- Confirmed an ordinary non-system registry user with no admin capabilities, one key, and `max-buckets=1`; anonymous, separately owned bucket, and additional-bucket requests were denied.
- Confirmed redirect disablement: a registry blob read returned 200 with no object-store `Location` header.
- Confirmed identical digest reads after Distribution and RGW restarts and after online one-OSD lab PG merges. Distribution logs contained none of the S3 or HTTP-secret values.
- Confirmed the same RGW path behind the real Keystone/Coffer Bearer flow: project A completed Skopeo and Podman push/pull, project B was denied project A, and the Skopeo digest survived both Distribution and Coffer broker restarts.
- Ran the exact pinned image's `garbage-collect --dry-run` twice while the only Distribution instance was stopped. RGW object count remained 19, no deletion candidate was reported, and the baseline plus integrated Skopeo/Podman manifests retained their digests after restart. No real collection was executed.
- This closes the first single-replica compatibility and least-privilege slice of evidence items 1 and 3 plus the non-destructive portion of item 7. Multi-replica/mid-upload recovery, native-versus-Keystone EC2 comparison, KMS, quota races, and destructive shared-blob GC remain open; the evidence does not change the production gate on Distribution v3.1.1.

## Primary Evidence

- [CNCF Distribution storage drivers](https://distribution.github.io/distribution/storage-drivers/)
- [CNCF Distribution S3 driver](https://distribution.github.io/distribution/storage-drivers/s3/)
- [CNCF Distribution HA deployment](https://distribution.github.io/distribution/about/deploying/)
- [CNCF Distribution garbage collection](https://distribution.github.io/distribution/about/garbage-collection/)
- [Ceph Object Gateway](https://docs.ceph.com/en/latest/radosgw/)
- [Ceph RGW Keystone integration](https://docs.ceph.com/en/latest/radosgw/keystone/)
- [Ceph RGW encryption](https://docs.ceph.com/en/latest/radosgw/encryption/)
- [Ceph RGW administration, quotas, and rate limits](https://docs.ceph.com/en/latest/radosgw/admin/)
- [Swift S3 compatibility](https://docs.openstack.org/swift/rocky/s3_compat.html)
