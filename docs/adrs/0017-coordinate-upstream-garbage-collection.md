# ADR 0017: Coordinate Upstream Garbage Collection

- Status: proposed
- Date: 2026-07-25
- Decision owners: Coffer maintainers and deployment operators
- Related plan: `docs/exec-plans/0019-stage6-production-promotion.md`
- Research: `docs/research/stage6-gc-retention.md`
- Related ADRs: `docs/adrs/0001-compose-cnc-distribution.md`,
  `docs/adrs/0003-rgw-s3-single-region-storage.md`,
  `docs/adrs/0011-use-pinned-distribution-storage-enumerator-for-inventory.md`

## Context

Coffer's selected Distribution data plane uses stop-the-world mark-and-sweep.
The prior RGW PoC ran only two empty-candidate dry runs with one stopped
registry. It did not reclaim a deleted shared-storage graph, prove every HA
writer fenced, restore a versioned SSE-KMS backup, or connect physical
reclamation to logical quota safely.

The current registry template enables deletion and background upload purging
but has no maintenance read-only transition, one-shot collector, candidate
authority, restore gate, or cluster-wide audit contract. Distribution's CLI
prints human text. Its broad `--delete-untagged` option is incompatible with
Coffer's valid digest-only content unless a future durable retention policy
explicitly authorizes it.

With RGW bucket versioning, a Distribution storage-driver delete can make an
object absent from the current namespace while retaining noncurrent object
versions and delete markers. Distribution reclamation, RGW lifecycle
expiration, Ceph internal GC, and experimental orphan cleanup therefore have
different owners and safety contracts.

## Proposed Decision

1. Use only the exact qualified Distribution release's upstream
   `registry garbage-collect` command as reachability authority. Coffer
   coordinates it and does not implement a competing mark/sweep engine.
2. Run only against an invocation-owned disposable/restorable copy until the
   complete production-candidate pilot accepts the procedure.
3. Forbid `--delete-untagged`. Select content for retention/deletion through an
   explicit audited manifest DELETE by digest before the GC writer fence.
4. Fence every public, load-balanced, and direct backend writer. Every
   Distribution replica must run the same read-only configuration or be
   stopped. Upload purging, active uploads/multipart, reconciliation mutation,
   import, restore, RGW lifecycle, other GC, and deletion are excluded for the
   whole interval.
5. Require complete, independently restore-checked SQL and versioned RGW
   backups plus an exact inventory before candidate analysis.
6. Run two dry runs from one immutable image, binary revision, configuration,
   backend, fence epoch, backup, and inventory. Normalize only the exact
   release's bounded summary/candidate lines. Unknown output or unequal
   candidate sets fails closed.
7. Bind one finite, single-use collection authorization to the exact invocation,
   owned targets, source/config/fence/backup/inventory hashes, equal candidate
   hash, bounded counts, and command shape.
8. After collection, prove shared blobs, index children, digest-only content,
   subject/referrer/fallback content, and all other expected survivors remain
   readable. Only the authorized deleted graph may be absent.
9. Prove the collector does not mutate Coffer SQL. Reconcile logical quota only
   through the existing fenced reconciliation state machine after survivor
   verification.
10. Report current-visible namespace reclamation, complete object-version/
    delete-marker deltas, and Ceph physical bytes separately. Do not run RGW
    lifecycle or orphan deletion to manufacture immediate physical savings.
11. Restore the pre-GC backup in an isolated target and verify all expected
    digests/inventory before teardown.
12. Retain only hashed, bounded, secret-free evidence and remove every exact
    invocation-owned disposable resource in reverse dependency order.

## Content Fixture

The acceptance graph contains:

- two tagged manifests in separate repositories sharing one blob;
- private blobs unique to each retained manifest;
- one tagged OCI index and readable children;
- one digest-only manifest that must survive;
- one retained subject plus the selected release's qualified referrer
  representation; and
- one separate graph explicitly deleted and expected to be reclaimed.

The dry-run candidate set must equal the pre-authorized deleted graph and must
not intersect the retained graph. A future release with native OCI 1.1
Referrers reruns this acceptance rather than inheriting a v3.1.1 fallback
assumption.

## Failure Semantics

Every pre-collection failure invalidates collection authority. A partial or
failed collection never resumes from inferred progress; the operator restores
or tears down from immutable ownership evidence.

The procedure refuses:

- non-disposable, incomplete, ambiguous, or prefix-selected targets;
- any writable path, inconsistent replica/config, active upload/multipart, or
  background storage mutator;
- missing/corrupt/non-restorable backup or inventory drift;
- candidate drift, malformed exact-release output, excessive candidates,
  `--delete-untagged`, or retained-content intersection;
- changed image, binary, configuration, backend, fence, backup, or baseline;
- expired, replayed, mismatched, or already consumed authorization;
- KMS/RGW outage, collector timeout/interruption/nonzero exit, or partial sweep;
- missing survivors, readable deleted content, SQL mutation, or unexpected
  object-version/delete-marker delta;
- restore mismatch, mixed RGW lifecycle/orphan deletion, cleanup residue, or a
  changed unrelated-resource signature.

## Rejected Alternatives

- **Coffer reachability implementation:** duplicates mature registry/storage
  semantics and can diverge from the selected data plane.
- **Online GC:** unsupported by the selected Distribution baseline and risks
  sweeping concurrently uploaded blobs.
- **Global `--delete-untagged`:** digest-only content is valid and no accepted
  global retention policy authorizes its removal.
- **Parse arbitrary collector output:** only exact-release bounded output is a
  reviewable adapter contract.
- **Treat inventory as deletion authority:** inventory proves observed
  content, not exclusive reachability or safe reclamation.
- **Use RGW lifecycle or orphan tooling instead:** those operate below
  Distribution's content graph and cannot replace its reachability.
- **Claim physical bytes from logical deletes:** versioning, delete markers,
  and asynchronous Ceph cleanup make that claim false.
- **Continue after partial sweep:** candidate authority no longer describes a
  known state.

## Consequences

GC is a scheduled maintenance transaction with explicit read-only impact and
recovery capacity. It is deliberately slower than an online lifecycle engine.
The operator needs enough temporary capacity for a full versioned backup and
isolated restore. Evidence and alerting must distinguish logical from physical
reclamation.

This ADR remains proposed until the versioned pure topology/state model,
fixture-only lifecycle, exact-release filesystem collection, failure matrix,
restore, full repository regression, and secret checks pass. Production
acceptance additionally requires the released dependency, disposable RGW/KMS
copy, fresh Kolla HA pilot, and zero-residue teardown.

The pure topology/state model and fixture-only lifecycle now pass locally.
They prove owner-only atomic state, nonblocking locking, exact phase replay,
compound fence/backup/candidate/authority/survivor/reclaim/restore contracts,
fixed failure refusal, secret-safe public evidence, idempotent teardown, and
zero reported fixture residue without invoking a registry, storage, SQL, KMS,
subprocess, container, or network. This evidence does not yet accept the ADR;
the exact-release output adapter and real temporary collection remain open.

## Primary References

- [CNCF Distribution garbage collection](https://distribution.github.io/distribution/about/garbage-collection/)
- [CNCF Distribution configuration](https://distribution.github.io/distribution/about/configuration/)
- [OCI Distribution Specification](https://github.com/opencontainers/distribution-spec/blob/main/spec.md)
- [Ceph RGW versioned bucket index](https://docs.ceph.com/en/latest/dev/radosgw/bucket_index/)
- [Ceph RGW lifecycle metrics](https://docs.ceph.com/en/latest/radosgw/metrics/)
- [Ceph RGW orphan tooling](https://docs.ceph.com/en/latest/radosgw/orphans/)
