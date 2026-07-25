# Stage 6 coordinated GC and retention baseline

- Date: 2026-07-25
- Scope: production-promotion design and fixture contract
- Related plan: `docs/exec-plans/0019-stage6-production-promotion.md`
- Related ADRs: `docs/adrs/0001-compose-cnc-distribution.md`,
  `docs/adrs/0003-rgw-s3-single-region-storage.md`,
  `docs/adrs/0011-use-pinned-distribution-storage-enumerator-for-inventory.md`

## Outcome

Coffer should continue to use the exact qualified Distribution release's
stop-the-world mark-and-sweep collector. It must not implement a second
reachability engine. The production baseline is an operator-owned,
dry-run-first maintenance transaction over one disposable, restorable copy:

1. populate and verify an explicit shared-blob, index, digest-only, and
   Referrers-fallback fixture;
2. apply only an exact policy-authorized manifest deletion;
3. fence every tenant/data-plane writer and every other storage mutator;
4. take and independently restore-check SQL plus every RGW object version;
5. prove every Distribution replica is read-only or stopped;
6. run two equal normalized dry runs from the same immutable image/config;
7. execute the upstream collector without `--delete-untagged`;
8. prove referenced/shared/index/referrer content survives and only the
   approved unreachable graph disappears;
9. measure logical current-visible and physical-version effects separately;
10. restore the pre-GC state in isolation and verify every digest; and
11. tear down only invocation-owned disposable resources with zero residue.

This is coordinated maintenance, not online GC and not a background Coffer
retention scheduler.

## Current implementation inventory

The Kolla registry template enables Distribution manifest/blob deletion and
keeps upload purging active. It has no read-only maintenance switch, GC
one-shot service, global writer-fence state, candidate verifier, approval
record, or restore gate. The ordinary admin token may grant Distribution's
`delete` action, but Coffer has no accepted durable retention-policy resource.

Existing evidence is intentionally narrower:

- ADR 0003 ran the v3.1.1 collector twice with `--dry-run` while the sole
  registry was stopped. It found no candidate and performed no collection.
- The inventory helper reuses exact-release repository/manifest enumeration
  for read-only evidence. ADR 0011 explicitly says that inventory cannot
  authorize deletion or establish GC eligibility.
- The Stage 6 data-protection model verifies complete versioned RGW backup,
  delete-marker, SSE-KMS, pagination, multipart, SQL restore, and isolated
  pull/inventory equality without using a live backend.
- Kolla Stage 5 proved multi-replica behavior but did not run a shared-blob
  destructive collection or restore.

No existing result satisfies the Stage 6 destructive GC done criterion.

## Exact Distribution v3.1.1 behavior

The pinned baseline is Distribution v3.1.1 at
`9a8d98b679740cd514aa7e7d84d23d442a5ef54c`.
`registry/storage/garbagecollect.go` enumerates every repository and manifest,
marks the manifest blob and recursively marks manifest references, enumerates
global blobs, then removes unmarked blobs and repository layer links through
the configured storage driver.

The public CLI has only `--dry-run`, `--delete-untagged`, and `--quiet`.
Its progress and candidate output are human text, not a versioned JSON
contract. A Coffer adapter may normalize only the exact pinned release's
bounded summary and candidate lines and must bind their hash to the image,
binary revision, configuration, backend, writer fence, backup, and inventory.
Unknown, duplicate, malformed, reordered-with-different-set, or changed output
fails closed. The collector binary remains the reachability authority.

`--delete-untagged` is excluded from the production baseline. Digest-only
manifests are valid Coffer content, and the option globally treats every
currently untagged manifest as removable. Coffer has no durable retention
policy that can prove that global choice. The fixture uses an explicit
manifest DELETE by digest and the default collector behavior.

Upstream requires the registry to be read-only or stopped. A concurrent upload
can otherwise add a layer after the mark phase and lose it during sweep. One
read-only replica is insufficient: every ingress path and direct registry
backend must be fenced, and upload purging, lifecycle expiration, deletion,
inventory/import, backup mutation, restore, and another GC must be excluded
for the complete interval.

## Content graph and Referrers safety

The fixture must contain:

- two tagged manifests in distinct repositories sharing one blob and each
  owning one private blob;
- one tagged OCI index whose child manifests remain readable by digest;
- one digest-only manifest that must survive because
  `--delete-untagged` is forbidden;
- one retained subject plus artifact/referrer graph; and
- one separate manifest graph selected for exact deletion and reclamation.

OCI Distribution Spec 1.1 defines a native Referrers API and a fallback
referrers-tag schema when the API returns 404. The pinned v3.1.1 evidence does
not establish native Referrers. Therefore the fixture must use the actually
qualified client/release disposition and retain its fallback index/tag as a
root. It must prove subject, referrer manifest, referrers index, and referenced
blobs survive. Deleting a subject while a retained referrer still points to it
is rejected rather than guessed.

The Stage 6 dependency gate may later select a release with native Referrers.
That release must rerun this graph; this document does not hard-code v3.1.1
fallback behavior as a permanent product contract.

## Writer fence and maintenance transaction

The writer fence is a compound invariant, not a UI maintenance flag:

- edge and every HAProxy registry path refuse POST, PUT, PATCH, and DELETE;
- every Distribution replica has the same immutable read-only configuration
  digest and has restarted into it, or every replica is stopped;
- direct backend write probes fail on every registry host;
- no active upload or multipart upload exists;
- reconciliation, import, restore, deletion, upload purging, RGW lifecycle,
  and other GC jobs are inactive;
- the writer-fence epoch and exact replica/image/config set remain unchanged
  from backup through survivor verification; and
- losing any part of the fence invalidates dry-run approval immediately.

The fixture may create and logically delete its designated manifest before the
fence. No deletion occurs between backup/inventory and the two dry runs.
Production data is never a target.

## SQL and logical quota boundary

Distribution GC must not write Coffer SQL. A logical manifest DELETE can make
content absent before its physical blobs are swept; the existing fenced
reconciler later releases the corresponding committed reservation only after
the post-GC survivor/deletion checks pass. The GC transaction records only
hashes and aggregate counts, not project, repository, digest, object-key, or
credential values.

The acceptance fixture proves:

- SQL and inventory hashes are unchanged by dry-run and collection;
- shared referenced descriptors retain their logical reference counts;
- the explicitly deleted manifest becomes absent and later reconciles through
  the existing quota state machine; and
- a failed or partial collector never triggers an inferred quota release.

## RGW versioning, KMS, and physical reclamation

Distribution deletes through its S3 storage driver. On a versioned RGW bucket,
an S3 delete creates or advances delete-marker/noncurrent-version state.
Therefore a successful Distribution sweep can reclaim the current logical
namespace without immediately reclaiming physical RADOS bytes.

Evidence must report separate values:

- Distribution mark count and eligible manifest/blob/link counts;
- current-visible S3 object count/bytes before and after;
- complete object-version and delete-marker count/bytes before and after; and
- RGW/Ceph physical usage as observational, delayed evidence only.

The pre-GC backup retains every version, delete marker, encryption disposition,
and metadata hash and must restore in an isolated bucket before collection.
Wrong-key or KMS outage must fail before sweep and preserve the fence and
backup.

RGW lifecycle expiration is not enabled merely to make a byte-reclamation
number look successful. Noncurrent-version and delete-marker expiration is a
separate, explicitly configured RGW lifecycle procedure with its own backup
retention and recovery consequences.

RGW internal garbage collection and orphan cleanup are also separate. Ceph
documents `rgw-orphan-list` as experimental and warns about false positives;
Coffer will not turn its output into automatic RADOS deletion. RGW GC/orphan
state may be observed, but it never substitutes for Distribution reachability
or authorizes Coffer cleanup.

## Candidate evidence contract

The versioned topology and state machine should require these ordered phases:

1. `preflighted`
2. `source-created`
3. `fixture-populated`
4. `logical-delete-applied`
5. `writers-excluded`
6. `backups-verified`
7. `baseline-verified`
8. `dry-run-one-verified`
9. `dry-run-two-verified`
10. `collection-authorized`
11. `collection-executed`
12. `survivors-verified`
13. `reclaim-verified`
14. `restore-verified`
15. `failures-verified`
16. `torn-down`

Authorization binds one invocation, exact disposable resource IDs, image and
binary revision, configuration/backend/fence/backup/baseline hashes, the two
equal normalized candidate-set hashes, a finite expiry, and the exact command
without `--delete-untagged`. It cannot be replayed after a failure, fence
change, expiry, or successful collection.

Retained evidence contains only schema/version, immutable-ID hashes, aggregate
counts/bytes, phase/result enums, timestamps needed for ordering/expiry, and
artifact hashes. It excludes credentials, tokens, private keys, endpoints,
project/repository names or IDs, digests, object keys, paths, config bodies,
command arguments containing secrets, and dependency exception text.

## Required failure cases

The pure model and disposable execution must fail closed for:

- production/non-fixture target or incomplete immutable ownership;
- missing writer path, writable direct backend, fence epoch/config drift, or
  active upload/multipart/background mutator;
- missing/corrupt/non-restorable SQL or complete versioned RGW backup;
- inventory or candidate drift between two dry runs;
- malformed/unknown collector output or a changed image/binary/config/backend;
- `--delete-untagged`, an unbounded candidate set, or an unauthorized digest;
- retained shared blob, index child, digest-only manifest, subject, referrer,
  or fallback index appearing in the candidate set;
- wrong-key/KMS/RGW outage before or during dry run;
- collector interruption, timeout, partial sweep, or nonzero exit;
- a missing survivor, readable deleted graph, SQL mutation, or unexpected
  current/version/delete-marker delta;
- restore digest/inventory mismatch;
- RGW lifecycle/orphan deletion mixed into the Coffer transaction; and
- incomplete cleanup or changed unrelated-resource signature.

Any failure ends collection authority. Recovery is restore or teardown from
immutable recorded ownership, never “continue sweep”.

## Recommended implementation sequence

1. Add proposed ADR 0017 for this boundary.
2. Add `poc/gc-retention/topology.json` and a pure state machine with exact
   evidence, approval, failure, cleanup, and secret-safety contracts.
3. Add a fixture-only lifecycle CLI and fake adapter; prove dry-run drift,
   failure injection, restore, and zero residue without a registry or S3.
4. Add an exact-release collector-output normalizer and filesystem-backed
   Distribution fixture. Execute real upstream dry run and collection only
   against invocation-owned temporary storage.
5. Reuse the Stage 6 versioned RGW backup adapter in a disposable RGW copy.
6. Add the guarded Kolla one-shot maintenance service/read-only transition and
   execute it only in the fresh candidate pilot after release gates pass.

The current user's long-horizon authorization permits autonomous local and
disposable-fixture progression. It does not authorize production data, a
shared non-Coffer bucket, prefix-based deletion, or an unqualified dependency.

## Primary references

- CNCF Distribution garbage collection:
  <https://distribution.github.io/distribution/about/garbage-collection/>
- CNCF Distribution configuration, read-only, upload purging, and delete:
  <https://distribution.github.io/distribution/about/configuration/>
- Distribution v3.1.1 release:
  <https://github.com/distribution/distribution/releases/tag/v3.1.1>
- OCI Distribution Specification 1.1 Referrers and fallback:
  <https://github.com/opencontainers/distribution-spec/blob/main/spec.md>
- Ceph RGW versioned bucket index:
  <https://docs.ceph.com/en/latest/dev/radosgw/bucket_index/>
- Ceph RGW lifecycle metrics:
  <https://docs.ceph.com/en/latest/radosgw/metrics/>
- Ceph RGW orphan tooling and warnings:
  <https://docs.ceph.com/en/latest/radosgw/orphans/>
- Ceph RGW S3 permission mapping:
  <https://docs.ceph.com/en/latest/radosgw/s3/authentication/>
