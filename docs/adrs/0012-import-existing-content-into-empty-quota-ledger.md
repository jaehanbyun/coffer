# ADR 0012: Import One Verified Baseline into an Empty Quota Ledger

- Status: proposed
- Date: 2026-07-23
- Decision owners: Coffer maintainers
- Related plans: `docs/exec-plans/0009-transactional-inventory-import.md`, `docs/exec-plans/0010-post-import-ledger-comparison.md`
- Related ADRs: `docs/adrs/0009-add-private-edge-manifest-quota-admission.md`, `docs/adrs/0011-use-pinned-distribution-storage-enumerator-for-inventory.md`
- Related runbooks: `docs/runbooks/existing-content-inventory.md`, `docs/runbooks/quota-schema-reconciliation.md`

## Context

ADR 0009 requires a write-stopped import before project-logical quota can be
authoritative for an existing Distribution registry. Proposed ADR 0011 now
defines a deterministic, secret-free `coffer.inventory/v1` artifact containing
every repository-linked tagged and digest-only manifest plus its immediate
descriptor graph. The existing quota ledger already defines the desired target
shape for newly admitted content, but it previously had no completion marker or
safe baseline import transaction.

Treating an incomplete ledger as recoverable through later reconciliation is
unsafe: reconciliation probes only reservations that already exist. Enabling
admission over a partial or empty baseline would knowingly undercount existing
content.

## Decision

For the disposable PoC, import exactly one verified inventory baseline under
these rules:

1. `coffer-import-inventory` reads only canonical compact
   `coffer.inventory/v1` and requires the operator-supplied SHA-256 of those
   exact bytes. It recomputes every project/repository/manifest/descriptor fact
   and summary before opening the database.
2. The database URL is supplied only through `COFFER_DATABASE_URL`; the CLI
   accepts no database URL, password, token, or credential argument and emits
   only fixed aggregate counts, artifact digest, status, and over-limit project
   count.
3. The current control schema must already contain every project quota and an
   exact repository-ID/project-ID binding for every inventory repository. The
   importer never creates a quota limit, guesses ownership, or changes
   repository metadata.
4. The quota ledger and reconciliation-claim tables must be globally empty and
   all quota usage/reservation counters must be zero. Admission remains disabled
   for the whole import. Incremental or live-ledger merge is rejected.
5. Revision `0004_inventory_import` owns one immutable `baseline` marker keyed
   by artifact SHA-256 and aggregate counts. The marker, deterministic committed
   reservations, reservation descriptor graphs, committed manifests,
   project-unique descriptors/reference counts, and project usage updates are
   written in one transaction.
6. An exact artifact replay returns `already_imported` without changing the
   ledger. A different artifact cannot replace the marker. A committed marker
   also blocks downgrade across revision `0004`, preventing Alembic from
   discarding the completion authority while imported state remains.
7. Imported `used_bytes` records observed project-unique logical bytes even when
   that value exceeds the configured limit. It never truncates reality or
   raises the limit. Existing admission semantics then deny novel unique bytes
   while an idempotent existing graph adds zero.
8. Whole-transaction retry is limited to at most three attempts and only known
   MySQL lock-timeout/deadlock codes 1205/1213 and PostgreSQL
   serialization/deadlock SQLSTATEs 40001/40P01. Between attempts, a committed
   matching marker converts the contender to an exact no-op. Other database or
   constraint failures return failure without a marker or partial ledger.
9. `coffer-verify-inventory-import` reparses the same canonical artifact and
   supplied SHA-256, derives the import facts through the importer's shared pure
   fact builder, and compares the complete ledger in one read-only repeatable
   database snapshot. It requires the singleton marker, exact repository
   authority, quota counters/timestamps, reservations, descriptor edges,
   manifests, project-unique descriptor reference counts, and zero claims. It
   permits unrelated empty control repositories and zero-usage quota rows, but
   rejects every unrelated ledger row or nonzero counter.
10. Comparator success is named `verified`, never `ready` or
    `cutover-approved`. Mismatch returns one fixed refusal without tenant,
    repository, manifest, descriptor, database URL, credential, or SQL detail.
    The database URL remains environment-only and comparison never repairs or
    writes ledger state.

This is a PoC import contract, not authorization to execute against a production
database or declare quota authoritative.

## Consequences

- Crash and constraint failure behavior is simple: either the marker and entire
  ledger baseline commit, or none of them do.
- Deterministic reservation IDs and request IDs make replay evidence stable;
  they are identifiers, not authentication material.
- Existing over-limit projects are visible and immediately unable to add novel
  logical bytes, but this PoC does not define the operator policy for reducing
  content or changing limits.
- The singleton deliberately prevents re-baselining after reconciliation later
  releases a deleted manifest. Re-import cannot resurrect removed content.
- A whole-artifact transaction can be too large for production PostgreSQL,
  MariaDB, or Galera. Production promotion requires representative duration,
  lock, WAL/binlog, certification, timeout, backup, and rollback evidence.
- The marker records import completion, not proof that Distribution stayed
  stopped, the backup is restorable, or live Distribution content still equals
  the artifact. The read-only comparator closes marker-versus-ledger equality at
  one instant only; writer exclusion and live-content evidence remain external
  operator gates.

## Alternatives Rejected for the PoC

- **Import per project or page:** exposes a partially authoritative ledger and
  needs a more complex resumable-state and admission fence design.
- **Merge into a live ledger:** makes descriptor reference counts and baseline
  ownership ambiguous under concurrent admission/reconciliation.
- **Create missing quotas automatically:** invents tenant policy and can hide an
  intentionally unconfigured project.
- **Reject inventory above the current limit:** prevents honest accounting and
  encourages undercounting. Recording actual usage safely denies future growth.
- **Allow a second baseline marker:** silently redefines historical authority
  and can resurrect content already released by reconciliation.
- **Retry every database failure:** can repeat deterministic constraint/schema
  errors and mask operator action requirements.

## Evidence and Production Gates

SQLite focused tests and the pinned PostgreSQL 17.10/MariaDB 11.4.12 harness
prove:

- one tagged child manifest plus one digest-only index becomes two committed
  reservations, five reservation edges, two committed manifests, and four
  project-unique descriptors with reference counts 2/1/1/1;
- a forced failure on the second reservation leaves marker, reservation, edge,
  manifest, and descriptor counts at zero and quota usage unchanged;
- two concurrent exact importers converge to one `imported` and one
  `already_imported`; a different digest is rejected;
- used/reserved bytes become 220/0 with a configured limit of 10, and a novel
  descriptor is denied; and
- the read-only comparator accepts the exact imported ledger, rejects marker,
  authority, counter, timestamp, reservation, edge, manifest, descriptor,
  claim, and extra-row drift with a fixed message, and accepts the restored
  ledger on both pinned shared-SQL engines without issuing DML; and
- all disposable containers, volumes, networks, database passwords, and state
  are removed after verification.

Before accepting this ADR for a production candidate, maintainers still need:

- the exact-release RGW inventory helper qualified against a disposable copy of
  representative production-scale data;
- a restorable, consistency-defined backup of Distribution/RGW and Coffer SQL,
  plus explicit maintenance/import/rollback owners and approvals;
- write exclusion across every ingress and replica, an admission-off proof, the
  read-only exact ledger comparison, and an authenticated comparison of live
  Distribution digest availability to the signed inventory before service
  restoration;
- measured transaction/chunking, timeout, lock, WAL/binlog, deadlock, Galera,
  crash, and capacity behavior at representative scale;
- a reviewed rollback or forward-repair design that cannot lose the marker or
  resurrect released content; and
- explicit authorization for production credentials, data access, SQL writes,
  maintenance, admission enablement, and any later destructive reclamation.
