# ADR 0011: Use a Pinned Distribution Storage Enumerator for Cutover Inventory

- Status: proposed; disposable PoC evidence passed
- Date: 2026-07-23
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0008-existing-content-inventory.md`
- Downstream ADR: `docs/adrs/0012-import-existing-content-into-empty-quota-ledger.md`
- Related research: `docs/research/m3-existing-content-inventory.md`
- Related runbook: `docs/runbooks/existing-content-inventory.md`

## Context

ADR 0009 requires existing registry data to be imported before logical quota
admission becomes authoritative. An empty Coffer ledger would undercount any
manifest and descriptor already present in Distribution.

The standard V2 API lists repositories and current tags and can fetch a known
tag or digest, but it has no endpoint that enumerates every manifest revision.
A manifest may be pushed only by digest or become untagged after tag movement.
Distribution notifications are best effort, in memory, unordered, and not
historical. Neither surface can prove a complete pre-ledger inventory.

Distribution v3.1.1 garbage collection uses exported `RepositoryEnumerator` and
`ManifestEnumerator` interfaces to walk repository revision links independently
of tags, then loads each manifest and its references. Its dry-run output is
human-oriented and coupled to global mark/sweep analysis. Direct parsing of
filesystem or RGW keys would bind Coffer to unchecked storage-layout details.

## Proposed Decision

For the PoC cutover-evidence seam:

1. Stop every registry writer, or place every replica in independently verified
   read-only mode, and exclude GC, retention, lifecycle, migration, and delete
   operations through the complete scan window.
2. Run a helper compiled against the exact qualified Distribution release and
   the same storage-driver implementation/configuration. It opens the namespace
   read-only, invokes the exported repository and manifest enumerators, loads
   payload facts through `ManifestService.Get`, and records current tag presence
   only as completeness evidence.
3. Mount or authorize the helper read-only at the operating-system/backend
   boundary. Never supply storage or database credentials on its command line or
   emit its storage configuration.
4. Run two independent scans. Bounded pages, continuation keys, record counts,
   record hashes, and every manifest/descriptor fact must agree. Any difference
   fails closed.
5. Match every backend repository exactly to current Coffer authority using the
   immutable canonical name `p/<project UUID>/<repository name>`. Unknown,
   malformed, duplicate, or mismatched authority fails closed; ownership is
   never inferred.
6. Verify revision-link versus content digest, supported manifest media type,
   payload size, descriptor digest/media/size consistency, and same-repository
   index-child existence.
7. Emit a deterministic `coffer.inventory/v1` artifact containing immutable
   project/repository IDs and content facts. Exclude manifest bodies, tag names,
   display names, backend paths, origins, URLs, credentials, tokens, headers,
   and timestamps.
8. Treat the artifact only as input to a separately approved, transactional
   ledger import. This decision does not write quota state, enable admission,
   delete content, or authorize production access.

The current helper supports only a read-only filesystem-backed disposable
fixture. It proves the interface behavior and artifact contract, not a deployable
RGW cutover tool.

## Consequences

- Digest-only and superseded untagged revisions can be represented without
  trusting mutable tags or notification history.
- The helper reuses Distribution's validated revision links and manifest
  decoder instead of reverse-engineering RGW object keys.
- Inventory now has a deliberate version-coupled dependency on Distribution's
  Go storage packages. Every data-plane upgrade requires source review and an
  exact fixture rerun before the helper can be paired with that release.
- Production packaging must use a reviewed, reproducible, signed helper artifact;
  disposable `go run` and live dependency download are not acceptable there.
- A stopped/read-only maintenance window remains mandatory. Two equal scans
  detect observed drift but do not replace writer exclusion or a restorable
  backup.
- Logical inventory does not establish physical exclusivity, safe deletion, or
  GC eligibility. It cannot authorize object reclamation.

## Alternatives Rejected for the PoC

- **Catalog plus tags:** cannot discover digest-only or untagged revisions.
- **Notifications:** cannot reconstruct history and may lose events with an
  instance.
- **Parsing GC stdout:** relies on human text from a command whose purpose and
  output include global sweep candidates.
- **Parsing backend object keys:** bypasses Distribution link validation and
  decoder semantics and would hard-code a storage layout.
- **Enable quota and reconcile later:** begins from known undercount and violates
  the bounded-soft quota claim.

## Evidence and Acceptance Gates

The disposable filesystem fixture publishes one tagged image manifest and one
digest-only untagged OCI index. The HTTP tag list exposes only the tagged item;
the pinned storage helper exposes both. Two scans compare equal, index-child and
four project-unique descriptor facts validate, registry file-content and control
SQLite hashes remain unchanged, both digests remain readable after restart, and
all labeled runtime resources and state are removed.

Proposed ADR 0012 separately proves that one canonical artifact can populate an
empty disposable SQLite/PostgreSQL/MariaDB quota ledger atomically, roll back a
forced partial failure, converge concurrent exact replay to one write plus one
no-op, and retain honest over-limit usage. That downstream evidence does not
qualify the filesystem helper for production RGW or complete the operator
cutover sequence.

Before this ADR can be accepted for a production candidate, maintainers must
still provide:

- an upstream-supported machine-readable inventory command or a reviewed,
  reproducible helper pinned to the production Distribution release;
- the production storage driver/config loader with owner-only credential
  delivery and a proof that the backend role cannot write or delete;
- a write-exclusion procedure across every ingress and replica, plus start/end
  audit evidence and real data-volume duration/capacity limits;
- RGW/S3 execution against a disposable copy of representative storage,
  including nested indexes, malformed/orphan links, paging scale, timeout, and
  restart behavior;
- an operator-owned restorable backup, control-authority export, inventory
  retention/signing policy, representative-scale transactional import,
  authenticated post-import comparison, admission cutover, and rollback
  procedure; and
- explicit approval for production credentials, data access, SQL writes, and
  the maintenance window.
