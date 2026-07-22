# ADR 0001: Compose an Unmodified CNCF Distribution Data Plane

- Status: accepted
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0001-product-discovery.md`

## Context

Coffer needs an OCI-compatible push/pull data plane plus OpenStack-specific identity, tenancy, policy, service discovery, quota, and operations. Implementing the Distribution protocol and content-addressed storage again would create a large interoperability and security burden. Adopting a full registry product could instead duplicate or conflict with Keystone projects, roles, and OpenStack service operations.

The evaluated upstream choices were CNCF Distribution, Harbor, and Quay. The decision concerns the MVP baseline; it does not prevent a later reassessment if mandatory capabilities cannot be delivered without a fork.

## Decision

Use a pinned, unmodified CNCF Distribution v3 release as the OCI data plane. Start the PoC at v3.1.1 or a newer supported security release and pin the exact image digest after CVE review.

- Distribution owns `/v2/` uploads, blobs, manifests, tags, supported artifacts, deletion semantics, and its storage driver.
- Coffer owns the Keystone-aware token issuer, project/repository resources, policy, metadata projections, audit, bounded soft-quota enforcement/reconciliation, and operational orchestration.
- Clients transfer content directly through load-balanced Distribution replicas; Coffer control services do not proxy blob bodies.
- Ceph RGW is used through Distribution's S3-compatible driver. Coffer will not write a custom storage driver unless the PoC demonstrates a concrete blocking incompatibility.
- Distribution notifications feed metadata and audit projections, but an idempotent reconciliation process is required because notification queues are per-instance, in-memory, and not ordered.
- MVP garbage collection wraps the upstream mark-and-sweep command with read-only mode, dry run, maintenance coordination, and audit. Coffer does not reimplement reachability.
- Scanning, signing policy, cache, and replication remain separate post-MVP integrations.

## Why This Choice

- The external Bearer token challenge is explicitly designed for a separate authorization service, which maps cleanly to a Keystone-aware issuer.
- Distribution has the smallest component and operational surface among the evaluated choices.
- The S3 driver provides the shortest route to common Ceph RGW deployments.
- Keeping upstream unmodified preserves compatibility and reduces long-term fork and security-update cost.
- Missing metadata, policy, and OpenStack identity are precisely the parts Coffer is intended to add.

## Alternatives Rejected

### Build a registry data plane

Rejected because upload resumption, content addressing, cross-repository mounts, manifest compatibility, object-store correctness, and garbage collection are mature protocol/storage concerns rather than Coffer differentiators.

### Fork or embed Distribution internals

Rejected because upstream Go library interfaces are not a stable integration contract and a fork would own ongoing protocol and security maintenance. Integrate through documented HTTP, token, notification, metrics, and storage configuration surfaces.

### Adopt Harbor as the data plane

Rejected for the MVP because Harbor brings its own projects, users/authentication, RBAC, database, quotas, jobs, and policy surface and does not provide a native Keystone model. It remains a useful feature benchmark, particularly for replication, scanning, and online GC.

### Adopt Quay wholesale or as a component

Not selected because Quay's Keystone adapter still maps into Quay's user/organization/team model, and its broader database, Redis, worker, migration, and operations surface would become the Coffer platform. Reassess adopting Quay wholesale—not extracting it as a library—if native OCI 1.1 Referrers and always-online GC become mandatory before Distribution supports them.

## Consequences

### Positive

- Small HA data-plane topology: stateless replicas, shared object storage, shared configuration/secrets, and offline token verification.
- Clear ownership boundary and standard-client compatibility.
- Portable OCI data without a Coffer manifest format.
- Independent evolution of control-plane policy and optional security integrations.

### Negative and follow-up work

- Current Distribution documentation states OCI Distribution Spec 1.0.1; native OCI 1.1 Referrers support must be verified rather than assumed.
- Upstream GC is stop-the-world and requires read-only or stopped registry operation to avoid corruption.
- Notifications are best-effort projections, not a durable event log.
- Distribution does not provide project quotas, rich metadata/search, replication policy, integrated scanning, or signing enforcement.
- Swift is not a current v3 storage-driver baseline; Ceph RGW must work through S3 compatibility or the architecture must be reconsidered.

## Required PoC Evidence

1. Run the current OCI Distribution conformance suite, including the selected release's actual artifact/referrer behavior.
2. Validate Docker, Podman, containerd, and ORAS against Coffer's token flow.
3. Validate RGW multipart/resumable uploads, requests routed across replicas, cross-repository mounts, deletes, listing, addressing style, redirects, encryption, and consistency.
4. Prove notification deduplication and reconciliation after lost, duplicated, and reordered events.
5. Exercise GC dry run and a controlled read-only collection window against RGW-backed content.
6. Verify rolling restart behavior while uploads and pulls use shared storage.

## Primary Evidence

- [OCI Distribution Specification](https://github.com/opencontainers/distribution-spec/blob/main/spec.md)
- [CNCF Distribution token authentication](https://distribution.github.io/distribution/spec/auth/token/)
- [CNCF Distribution storage drivers](https://distribution.github.io/distribution/storage-drivers/)
- [CNCF Distribution garbage collection](https://distribution.github.io/distribution/about/garbage-collection/)
- [CNCF Distribution notifications](https://distribution.github.io/distribution/about/notifications/)
- [CNCF Distribution deployment guidance](https://distribution.github.io/distribution/about/deploying/)
- [CNCF Distribution v3.1.1 release](https://github.com/distribution/distribution/releases/tag/v3.1.1)
- [Harbor architecture](https://github.com/goharbor/harbor/wiki/Architecture-Overview-of-Harbor)
- [Harbor authentication](https://goharbor.io/docs/main/administration/configure-authentication/)
- [Project Quay architecture](https://docs.projectquay.io/architecture.html)
- [Project Quay configuration](https://docs.projectquay.io/config_quay.html)
