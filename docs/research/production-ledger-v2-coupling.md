# Production ledger v2 coupling review

## Purpose

This note records why Stage 6 ledger v1 cannot answer the narrower question
"is the Registry core a production candidate, and which optional or
deployment-specific profiles are independently ready?" It is design evidence
for plan 0030 and does not change a gate or qualify an input.

## Current coupling

| Current boundary | Coupled concerns | Consequence |
|---|---|---|
| `readiness.py` | Distribution, Ceph, and `oslo.messaging` use one minimum status | A UI dependency or an optional KMS backend can block the Registry core before its evidence is read |
| `artifacts.py` | Core, Horizon, and Skyline images on amd64 and arm64 compile into one digest | A single UI surface can prevent otherwise valid core artifacts from being represented |
| `maintenance_identity.py` | Core cross-project maintenance authorization requires the RGW/KMS result digest | Identity cannot be judged independently of one storage encryption profile |
| `data_protection.py` | Control SQL, imported inventory, RGW versioned backup, and SSE-KMS restore are one transaction | Backend-specific recovery is indistinguishable from core metadata recovery |
| `kolla_multinode.py` | RGW, Barbican, Horizon, Skyline, and core services are one fixed topology | A valid core-only operator deployment cannot be represented |
| `operator_release.py` | `official_upstream_only` and `no_private_fork` are fixed booleans | A signed supported vendor backport or a narrowly maintained Coffer patch cannot be evaluated |
| `ledger.py` | Ten gates are one global candidate | Optional capability failure is reported as a product-wide production failure |

The current v1 behavior is internally consistent and must remain available.
It is too coarse for a product with independently selectable storage and UI
profiles.

## Security versus capability ownership

### Registry core

The Registry core owns the Distribution protocol and security input, Coffer
control and token services, project isolation, quota admission and
reconciliation, core data protection, core observability, core load and
fault recovery, Kolla lifecycle, and the operator release review. A reachable
Distribution vulnerability or core OCI protocol failure is a core blocker.

### Storage backend

A backend profile proves one exact driver and provider combination: verified
TLS, least privilege, upload and multipart semantics, persistence,
backup/restore, cleanup, load, failure recovery, and teardown. The profile is
required for a deployable combination but is not the identity of the core
software candidate.

### RGW and Barbican SSE-KMS

This capability adds Ceph release provenance, Barbican integration,
positive-size and zero-byte encrypted moves, wrong-key and KMS-outage
behavior, rotation, restart persistence, multipart cleanup, and zero residue.
The Tentacle v20.2.2 zero-byte failure blocks this capability, not every
possible storage backend.

### Horizon and Skyline

Each UI profile owns its exact parent dependency, wheel/overlay,
multi-architecture image, vulnerability, catalog, tenant, browser,
reconfigure, rollback, and teardown evidence. The current `oslo.messaging`
finding is a real security blocker for affected UI images but is not a
Registry-core dependency.

### Referrers

Referrers is an advertised capability with three explicit dispositions:

- `native`: the OCI endpoint, filters, pagination, subject lifecycle, GC, and
  client matrix qualify;
- `fallback-tag`: the accepted tag scheme, collision and concurrent-update
  limitations, subject deletion, signing workflow, GC, and clients qualify;
- `disabled`: Coffer does not advertise or depend on Referrers.

Failure or absence in this profile does not block core unless an explicitly
selected deployment or signing policy depends on that mode.

## Existing evidence remap

| v1 evidence | Safe v2 use | Prohibited inference |
|---|---|---|
| v1 ledger bytes and digest | Migration provenance and original rollback bytes | Any v2 pass |
| Distribution component observation | Exact version, revision, and current blocker for core | Qualified provider lineage |
| Ceph component observation | Exact version, revision, and KMS blocker | Generic storage-backend failure or pass |
| `oslo.messaging` observation | Horizon and Skyline dependency blocker | Registry-core blocker |
| Combined artifact result | Revalidate the original payload, then project only the surfaces actually proven | Split pass from a digest alone |
| RGW/KMS PoC | Supporting positive-size, wrong-key, outage, and recovery facts | Production KMS pass while zero-byte move fails |
| Filesystem GC fixture | Contract and regression evidence for its exact release | Current production core or backend pass |
| Horizon/Skyline fixtures and retained preview | Functional, packaging, and UX evidence | Production image or deployment pass |
| Stage 5 HA acceptance | Historical topology and failure-contract evidence | Fresh v2 core or profile pass |

The current retained v1 ledger contains no passed gate. Its conservative v2
remap is therefore:

- Registry core: `blocked` by the Distribution input, with all live core
  qualification evidence still absent;
- storage backend: `pending`;
- RGW and Barbican SSE-KMS: `blocked` by the Ceph zero-byte path and absent
  production result;
- Horizon: `blocked` by the affected parent dependency and absent surface
  result;
- Skyline: `blocked` for the same independent dependency reason;
- Referrers: non-qualified with no exact-release production result.

## Ledger v2 invariants

1. Top-level `production_candidate` equals only
   `core.production_candidate`.
2. A deployable combination is evaluated separately as core plus the selected
   storage and integration profiles.
3. Gate, scope, profile, mode, and reason identifiers use exact allowlists.
4. Callers never supply a final gate or scope status.
5. Missing evidence is `pending`; explicit negative provider evidence is
   `blocked`; only all required verified gates produce `qualified`.
6. A v1 `blocked` or `pending` state never becomes a v2 pass.
7. A v1 `passed` digest alone remains pending until the original specialist
   payload is revalidated under a v2 scope contract.
8. Invalid, stale, unsupported, source-drifted, or unsafe evidence aborts
   compilation; it is not converted to a softer status.
9. Core and each profile retain their own evidence and blockers.
10. v1 and v2 output files never overwrite one another.

## Compatibility and rollback

Ledger v1 remains the source of truth for existing v1 consumers. Ledger v2 is
created only after a valid v1 ledger and release observation are captured into
a source-bound migration record.

There is no general v2-to-v1 projection. Core qualification cannot become v1
global qualification, and independent profile states cannot be collapsed
without changing meaning. The only allowed compatibility replay is to verify
the exact original v1 digest and reproduce those original bytes into a
separate owner-only output. A vendor or Coffer patch lineage, a changed v2
scope, or a digest mismatch forbids that replay.

Operational rollback selects the old v1 consumer and original v1 evidence; it
does not delete ledger v2 or rewrite v2 semantics.

## Implemented v2 boundary

Plan 0030 implements the additive path without modifying `ledger.py` or
`readiness.py`:

| Layer | Contract |
|---|---|
| Trust policy | Exact authority, vendor, release, builder, lifecycle-observer, VEX, replacement, support, and adapter catalogs |
| Provider lineage | Official upstream, approved vendor backport, or Coffer minimal patch; final status is derived |
| Migration | Embeds exact v1 ledger and release bytes, hashes every source, preserves `legacy_evidence`, and maps only negative facts |
| Provider bundle | Independently resolves Distribution, Ceph, and `oslo.messaging` as blocked, pending, or qualified |
| Scope evidence | Fixed checks, modes, provider bindings, backends, source closures, expiry, and non-synthetic adapter identity per scope |
| Ledger v2 | Core candidate, five profile decisions, selected-combination constraints, and compatibility state |
| Checkpoint verifier | Frozen versioned verifier bundle plus current policy, revocation, and semantic replay validation |
| Rollback protocol | Signed target, writer fence, authorization, logical destination, shared-CAS claim/publication/completion, and signed receipt |

All evidence paths use strict JSON, owner-only files, exact field sets, source
hashes, canonical digests, and explicit byte budgets. The common hard ceiling
is 16 MiB; narrower inputs retain lower limits. Production policy catalogs are
empty by default, so a fixture authority, vendor, adapter, or release cannot
accidentally become production trust.

The rollback fixture uses an injected shared-state adapter to prove concurrency,
destination binding, retry, and outage behavior. The production verifier
registry contains no entry and no production shared-CAS adapter is configured.
The production rollback command therefore refuses execution. This is an
intentional deployment boundary rather than missing positive evidence.

## Current machine-readable result

The current owner-only v2 output is
`work/production-promotion/promotion-ledger-v2.json`. It is derived from the
retained v1 ledger and current release observation, with no v2 scope result
promoted from a fixture:

| Decision | Status | Current reason |
|---|---|---|
| Registry core | `blocked` | Distribution provider is explicitly blocked and scope evidence is absent |
| Storage backend | `pending` | No v2 backend scope evidence |
| RGW and Barbican KMS | `blocked` | Ceph and Distribution providers are blocked and scope evidence is absent |
| Horizon | `blocked` | `oslo.messaging` provider is blocked and scope evidence is absent |
| Skyline | `blocked` | `oslo.messaging` provider is blocked and scope evidence is absent |
| Referrers | `pending` | No selected mode or v2 scope evidence |

The aggregate is four blocked, two pending, zero qualified, and zero disabled.
`production_candidate=false`,
`baseline_deployment_ready=false`, and
`rgw_barbican_kms_deployment_ready=false`.

The retained v1 ledger raw digest is
`sha256:e59fd5342d1d92f233cf9377e85c101d4781c60dd339795044ed3bc681bdf0ff`.
The regenerated current v2 files have raw SHA-256 digests:

- migration:
  `b4f9dffb9e2227c63401b1d52d87992f5113854e6650d4fdbf28a9eb9ddd2d5b`;
- provider inputs:
  `6d41482254055107c480ca6a4f76c9e12a9c2272e660d951f41aef5472d29ee0`;
- ledger:
  `9e6eacc42d3024b6e7b39b100bebaf9b89a1fb2558d3ca6ffd518bd50fc2ffbc`.

No signed pre-upgrade checkpoint exists for that retained deployment, so
checkpoint status is `missing`, semantic replay is false, exact-v1 replay is
ineligible, and v2-to-v1 projection is forbidden. These compatibility facts
do not change the validity of v1 for existing v1 consumers.
