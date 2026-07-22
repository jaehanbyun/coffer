# Coffer Product Discovery

- Status: proposed baseline
- Updated: 2026-07-21
- Scope: OpenStack-native private OCI registry

## Product Naming

- Project codename: `coffer`
- Descriptive service name: `OCI Registry service`
- Proposed Keystone service type: `oci-registry` (not registered in the OpenStack service-types authority)
- User-facing CLI noun: `registry`, for example `openstack registry repository list`

The project codename is used for source repositories, packages, processes, configuration, and contributor-facing references. Operator and user documentation should prefer the descriptive service name. Deployers remain free to choose the Keystone service-catalog display name.

## Problem Statement

OpenStack provides identity, projects, service discovery, compute, orchestration, and object storage, but no current first-class Keystone-integrated OCI registry service or registered registry service type was verified in official sources. OpenStack-Helm does ship a registry deployment chart, and Zun, Ironic, Kolla, and other projects consume external registries, but none supplies the regional multi-tenant service/control plane described here. Coffer should close that integration gap without creating another OCI blob and manifest implementation. The evidence and time-bounded search limitation are recorded in `docs/research/openstack-registry-landscape.md`.

## Target Users and Jobs

### Primary users

- OpenStack operators who need to offer a supported private registry as a regional cloud service.
- OpenStack project members and service workloads that need to push and pull OCI images using familiar Docker, Podman, containerd, ORAS, and Kubernetes workflows.

### Core jobs

- Create and discover project-scoped repositories.
- Authenticate using OpenStack identities or application credentials without maintaining a second permanent credential system.
- Push and pull OCI images and related artifacts through the standard Distribution API.
- Apply project and repository authorization, bounded soft quota, retention, and audit policy.
- Operate the service in an HA OpenStack region using existing object storage and observability systems.

## Hyperscaler Capability Mapping

The comparison is directional: it establishes user expectations, not a requirement for one-for-one compatibility.

| Capability | AWS ECR | Azure Container Registry | Google Artifact Registry | Coffer disposition |
|---|---|---|---|---|
| Private OCI/Docker push and pull | Core | Core | Core Docker repository | **MVP** |
| Cloud identity and scoped access | IAM and repository policies | Entra ID, RBAC, repository-scoped permissions | IAM at project/repository scope | **MVP**, mapped to Keystone project roles |
| Repository CRUD, tag/digest listing, deletion | Core | Core | Core | **MVP** |
| TLS, encrypted backing storage, auditable operations | Managed service baseline | Managed service baseline | Managed service baseline | **MVP operator baseline** |
| Tag immutability and safe deletion controls | Repository template/settings | SKU features plus locking/retention controls | Immutable tags and cleanup policies | **MVP** for immutability; richer retention later |
| Lifecycle or cleanup policy | Lifecycle policies | Untagged retention and soft delete options | Delete/keep cleanup policies | **Post-MVP**; manual admin GC in PoC |
| Vulnerability scanning | Basic or Inspector-enhanced scanning | Defender integration | Artifact Analysis | **Post-MVP integration**, not a built-in scanner |
| Upstream pull-through or artifact cache | Pull-through cache | Artifact Cache | Remote repositories | **Post-MVP** |
| Cross-region or geo replication | Cross-region/cross-account replication | Active-active geo-replication | Regional/multi-regional repository placement | **Post-MVP** |
| Signing, attestations, SBOM/referrers | OCI artifacts and managed signing | OCI artifacts, Notation/signing integrations | Artifact metadata and supply-chain integrations | **Post-MVP policy/integration**; preserve OCI referrers in MVP |
| Webhooks, events, monitoring | Cloud-native event/audit integration | Webhooks and platform monitoring | Pub/Sub, audit logs, metrics | Basic audit/metrics in **MVP**; events later |
| Cloud image build service | Outside ECR's registry core | ACR Tasks | Cloud Build integration | **Non-goal**; integrate external builders |
| Universal package repository | OCI-compatible artifacts | OCI-related artifacts | Multiple language/OS package formats | **Non-goal for MVP**; OCI artifacts only |
| Public registry | Separate ECR Public | Optional anonymous pull | Public access can be configured | **Non-goal for MVP** |
| Image streaming/prewarming | Platform-dependent | Premium artifact streaming | GKE image streaming | **Non-goal** |

## Evidence

- [Amazon ECR overview](https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html) documents private OCI repositories, IAM permissions, lifecycle policies, scanning, cross-region/cross-account replication, pull-through cache, repository templates, and managed signing.
- [Amazon ECR lifecycle policies](https://docs.aws.amazon.com/AmazonECR/latest/userguide/LifecyclePolicies.html) document rule preview and automatic expiration/archive behavior.
- [Azure Container Registry introduction](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-intro) documents OCI images, Entra/RBAC authentication, geo-replication, Tasks, and security integrations.
- [Azure Container Registry SKU capabilities](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-skus) documents repository-scoped permissions, zone redundancy, geo-replication, content trust, customer-managed keys, artifact cache, retention, and network controls.
- [Google Artifact Registry overview](https://cloud.google.com/artifact-registry/docs/overview) documents IAM integration, vulnerability metadata, remote and virtual repositories, and CI/CD integration.
- [Google Artifact Registry repository modes](https://cloud.google.com/artifact-registry/docs/repositories) documents standard, remote, and virtual repositories, regional placement, immutable tags, and cleanup policies.

## Proposed MVP Boundary

### Required

1. A standard OCI Distribution endpoint that works with unmodified Docker/Podman/ORAS clients.
2. Keystone-backed short-lived registry authorization with project isolation and explicit pull/push/delete actions.
3. Project-scoped repository management and service-catalog discovery.
4. Content-addressed object storage with safe deletion and an operator-invoked garbage-collection path.
5. Single-region HA stateless service replicas, TLS, structured audit logs, metrics, health checks, bounded soft-quota enforcement/reconciliation, and tag immutability.
6. OCI images, image indexes, and artifacts supported by the pinned upstream release; native OCI 1.1 Referrers support is an explicit PoC gate, not an assumed capability.

### Deferred

- Vulnerability scanning orchestration and findings UI/API.
- Lifecycle-policy engine and soft-delete recovery.
- Pull-through cache, virtual repositories, and dependency-confusion policy.
- Cross-region replication and global routing.
- Managed signing, key management workflow, admission policy, and provenance verification.
- Rich search/indexing, web UI, billing, and per-feature service tiers.

### Explicit non-goals

- Implementing the OCI Distribution protocol, blob store, or scanner from scratch.
- Building container images or replacing CI/CD systems.
- Replacing Glance's VM image service.
- Supporting Maven, npm, Python, OS packages, or arbitrary non-OCI repository formats in the MVP.
- Public/anonymous registry hosting or internet-scale multi-region service in the first release.
- Claiming official OpenStack project status or publishing a governance/service-type proposal before community discovery and working evidence exist.

## Product Principles

- **OpenStack-native control, OCI-native data:** OpenStack APIs and Keystone govern the service; standard registry clients move artifacts.
- **Compose before build:** reuse an upstream Distribution implementation and add only the missing OpenStack control/auth/operations layer.
- **Project isolation by default:** a namespace is never inferred only from a client-supplied path; authorization is bound to verified Keystone context.
- **Portable artifacts:** data remains OCI-compatible so operators are not locked into Coffer.
- **Operator-owned policy:** storage, quotas, retention, network exposure, and optional security integrations are deployer-configurable.

## Unresolved Questions

- Whether repository-level role overrides are needed after the MVP's standard project-role mapping.
- Whether Ceph RGW passes every required S3 compatibility gate; a Swift-native driver is not part of the Distribution v3 MVP baseline.
- Whether the control API belongs in a new OpenStack service endpoint or can initially be a narrow sidecar API plus Keystone auth service.
- Which existing OpenStack community, if any, is the right initial governance home and when a service-type proposal should be made.
- Whether finite application credentials plus an OS credential helper are sufficient for interactive users, or a later federated/MFA exchange helper is required.
