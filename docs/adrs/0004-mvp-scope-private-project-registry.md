# ADR 0004: Limit the MVP to a Private, Project-Scoped, Single-Region OCI Registry

- Status: accepted
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0001-product-discovery.md`

## Context

ECR, Azure Container Registry, and Google Artifact Registry establish a broad managed-registry feature set: cloud identity, repository policy, lifecycle management, scanning, replication, upstream cache, signing, network controls, audit, build/deploy integration, and in some cases multiple package formats. Attempting to match that whole surface would prevent Coffer from validating its unique OpenStack integration risk.

The highest-risk unknowns are Keystone-to-standard-registry authentication, immutable project isolation, upstream Distribution composition, Ceph RGW behavior, and operator-safe lifecycle handling.

## Decision

The Coffer MVP is a private, project-scoped, single-region service for OCI images and compatible artifacts.

The MVP includes:

- standard OCI Distribution push/pull with unmodified clients;
- Keystone project identity and action-scoped authorization;
- explicit repository management and stable project-ID namespaces;
- tag immutability, logical deletion, bounded soft-quota enforcement/reconciliation, and controlled GC;
- TLS, HA stateless replicas, health, metrics, request IDs, and audit logs;
- Ceph RGW S3-backed content and a relational control database;
- preservation of the selected upstream release's OCI artifact behavior.

The MVP defers scanning, signing policy, lifecycle automation, pull-through cache, rich search/UI, notifications as a public product API, strict physical-byte quotas, public access, cross-region replication, and deployment admission policy.

Container builds, CI/CD orchestration, image streaming, billing/service tiers, and non-OCI package formats are explicit non-goals.

## Why This Choice

- It covers the shared core user journey across the three hyperscaler registries without copying their surrounding cloud platforms.
- It focuses engineering evidence on the OpenStack-specific value and failure modes.
- Deferred capabilities can be added as external integrations or independent workers without changing the OCI data plane.
- Single-region HA matches a normal OpenStack service-catalog boundary and avoids premature global consistency design.

## Alternatives Rejected

### ECR/ACR/Artifact Registry feature parity in the first release

Rejected because the cloud services bundle years of supply-chain, networking, replication, and adjacent platform work. Feature count is not a useful first acceptance criterion.

### A universal artifact repository

Rejected because Maven, npm, Python, and OS packages introduce unrelated protocols, metadata, dependency-resolution, and security models. OCI artifacts already cover the intended container and supply-chain attachment boundary.

### Public registry and anonymous pull

Rejected because abuse prevention, content moderation, internet-scale distribution, egress control, and public namespace governance are materially different product and operations problems.

### Build service bundled with the registry

Rejected because image building belongs to CI/CD and build services. Coffer should integrate through standard push and event interfaces.

## Consequences

- Early users receive a smaller product than hyperscaler registries but a clear OpenStack-native core.
- The product must document deferred features plainly and keep extension boundaries stable.
- Artifact/referrer support is limited by the pinned Distribution release until conformance evidence supports a stronger claim.
- Operators initially schedule GC maintenance instead of receiving an always-online lifecycle engine.
- The first release is not suitable for public hosting or global multi-region workloads.

## Promotion Gates for Deferred Features

Add a deferred capability only when a validated user need and an operational design exist. Priority order after MVP is expected to be:

1. scanner integration plus artifact/security metadata;
2. lifecycle policy and safer deletion/GC workflow;
3. notifications/webhooks and richer metadata/search;
4. pull-through cache;
5. signing/provenance policy integration;
6. replication and multi-region routing.

This order is a planning hypothesis, not an accepted roadmap.

## Primary Evidence

- [Amazon ECR overview](https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html)
- [Azure Container Registry introduction](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-intro)
- [Azure Container Registry SKU capabilities](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-skus)
- [Google Artifact Registry overview](https://cloud.google.com/artifact-registry/docs/overview)
- [Google Artifact Registry repository modes](https://cloud.google.com/artifact-registry/docs/repositories)
