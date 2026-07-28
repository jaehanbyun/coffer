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
