# Existing OCI Content Inventory Boundary

- Status: verified read-only filesystem PoC; not a production import procedure
- Related ADRs: `docs/adrs/0011-use-pinned-distribution-storage-enumerator-for-inventory.md`, `docs/adrs/0012-import-existing-content-into-empty-quota-ledger.md`
- Related plans: `docs/exec-plans/0008-existing-content-inventory.md`, `docs/exec-plans/0009-transactional-inventory-import.md`, `docs/exec-plans/0010-post-import-ledger-comparison.md`

## Purpose

This runbook defines the evidence required before pre-existing Distribution
content can be considered for Coffer logical-quota import. It explains the
checked-in verifier and disposable proof. It does not authorize a production
maintenance window, registry/RGW/database credentials, quota writes, admission
enablement, content deletion, or garbage collection.

The authoritative completeness reasoning and primary source links are in
`docs/research/m3-existing-content-inventory.md`.

## Input Contracts

`coffer-inventory-verify` consumes two secret-free JSON inputs:

1. `coffer.distribution-storage-scan/v1` evidence from the exact-version storage
   enumerator. It contains start/end bounded pages of repository-linked manifest
   facts, current tag-presence booleans, and count/hash summaries.
2. `coffer.repository-authority/v1` exported through an operator-owned read-only
   control-database path. It contains only canonical repository UUID, project
   UUID, and repository suffix records.

The verifier does not connect to Distribution, object storage, or SQL. It opens
only those two local inputs and either writes a new output path exclusively or
prints to stdout. Unknown fields are rejected so an accidental credential,
token, URL, or payload cannot be copied into the final artifact.

Successful output is canonical compact JSON with schema `coffer.inventory/v1`.
It contains:

- exact Distribution release and enumerator identity;
- immutable project and repository IDs;
- manifest digest, media type, byte size, and immediate descriptor edges;
- project-unique descriptor digest, media type, and size facts; and
- fixed aggregate project/repository/manifest/descriptor counts and logical
  bytes.

It intentionally omits repository names and backend paths after authority
resolution, mutable tag evidence, manifest bodies, storage locations, URLs,
request headers, credentials, tokens, timestamps, and SQL connection data.

## Refusal Conditions

The verifier fails without output when any of the following occurs:

- wrong schema, Distribution release, or enumerator identity;
- empty/oversized input, unknown field, invalid type, or a configured bound is
  exceeded;
- missing, repeated, short intermediate, reordered, overlapping, or
  continuation-mismatched page;
- page/record count or SHA-256 summary mismatch;
- unequal start/end scan, including tag-presence drift;
- noncanonical repository/project/repository UUID, duplicate authority, or a
  backend repository with no exact control row;
- non-SHA-256 or link/content digest mismatch, zero/oversized manifest, invalid
  media type, duplicate reference, conflicting descriptor size/media type, or
  unsupported manifest shape; or
- index child absent from the same repository or disagreeing with its descriptor.

An empty control repository may have no backend path and is not an error. A
backend path without control authority always is.

## Required Production Sequence

The following is a design checklist, not an executable production procedure:

1. Obtain explicit owners and approval for the registry maintenance window,
   read-only storage/control credentials, backup, evidence retention, import,
   cutover, and rollback.
2. Produce and restore-test a backup that covers Distribution backend state and
   the Coffer control database at a defined consistency point.
3. Remove every direct/bypass writer and stop every Distribution replica, or
   independently verify read-only behavior on every ingress and replica. Exclude
   GC, retention, lifecycle, migration, and deletion.
4. Export only the required repository authority through a read-only database
   role and owner-only transient path. Do not place database URLs on a command
   line or retain them in evidence.
5. Run a reviewed helper built for the exact Distribution release and exact
   production storage driver/configuration with a backend role that cannot
   write/delete. Capture start/end evidence without logging config values.
6. Run `coffer-inventory-verify` in an owner-only workspace, hash/sign the final
   artifact through the operator evidence system, and independently compare the
   aggregate to expected repository/manifest ranges.
7. If any refusal condition or observed change occurs, discard the candidate,
   keep admission disabled, restore normal service deliberately, and investigate.
8. Perform the separately reviewed transactional ledger import, then run the
   read-only exact ledger comparator against the same signed artifact and digest.
   Separately compare authenticated live Distribution digest availability.
   Enable quota admission only after every comparison, writer-exclusion, and
   rollback-readiness gate passes with explicit authorization.
9. Remove transient authority/evidence material according to the approved
   retention policy and restore writers through a controlled rollout.

The checked-in filesystem helper cannot perform steps 4–7 against production
RGW. `coffer-import-inventory` and `coffer-verify-inventory-import` implement the
disposable SQL import/comparison semantics for step 8, but neither establishes
writer exclusion, backup/restore, production authorization, representative
capacity, authenticated live content availability, rollback readiness, or
permission to enable admission. Those remain explicit gates.

## Disposable Verification

With an already-running Podman machine:

```bash
make -C poc/inventory verify
```

The fixture:

1. starts exact pinned unmodified Distribution v3.1.1 on loopback;
2. migrates a disposable SQLite control database and creates one authority row;
3. uploads config/layer content, one tagged OCI image manifest, and one OCI index
   addressed only by digest;
4. proves the paged HTTP tags response contains only the tag;
5. stops Distribution and records registry-file plus control-database hashes;
6. mounts the storage volume read-only into a pinned Go 1.25.1 environment and
   invokes the exact-version helper, which performs two scans;
7. validates and materializes the deterministic inventory without opening SQL,
   then changes one end-scan fact in memory and proves the candidate is rejected
   as snapshot drift;
8. proves both hashes are unchanged, restarts Distribution, and checks both
   digests remain readable; and
9. removes every labeled container, volume, network, SQLite database, evidence,
   inventory, and log file.

The Go environment and module checksums are pinned for a reproducible disposable
proof, but it downloads and compiles dependencies at run time. That is not an
approved production packaging model.

The downstream empty-ledger transaction is tested independently with:

```bash
make -C poc/quota-sql verify
```

After its normal migration/reconciliation checks, that harness uses synthetic
authority and a canonical in-memory artifact on PostgreSQL 17.10 and MariaDB
11.4.12. It forces the second manifest row to fail and observes zero marker and
ledger rows, then proves concurrent one-writer/exact-no-op convergence, a
different-baseline refusal, exact 2/5/2/4 reservation-edge-manifest-descriptor
shape, and honest 220-byte usage against a 10-byte limit. It then verifies the
complete ledger in one read-only repeatable snapshot, rejects a released-manifest
mutation, restores the row, and verifies the exact ledger again. It never
connects to Distribution/RGW or enables admission and removes all runtime state
and random database passwords.

## Separately Approved Next Work

- Build and attest an exact-release helper image with production storage-driver
  configuration support and no command-line secrets.
- Run read-only against a disposable RGW copy with a non-writing role.
- Qualify transaction duration, locks, WAL/binlog, deadlock, crash, capacity,
  chunking, and Galera behavior with a representative disposable copy.
- Qualify the exact SQL comparator at representative scale, implement and
  approve authenticated live Distribution comparison, and design the admission
  switch plus rollback/forward-repair procedure without permitting re-baseline
  resurrection.
- Add large-inventory memory/time bounds and evidence chunk storage/retention.

Until those gates pass, `coffer.inventory/v1` is verified PoC evidence only and
must not be represented as a production-imported or production-authoritative
quota ledger.
