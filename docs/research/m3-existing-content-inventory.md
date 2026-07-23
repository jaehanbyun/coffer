# M3 Existing OCI Content Inventory Boundary

- Date: 2026-07-23
- Target: unmodified Distribution v3.1.1 with Coffer repository authority
- Outcome: HTTP and notification surfaces are incomplete; a version-pinned,
  read-only Distribution storage enumerator is the PoC evidence surface

## Required Outcome

Coffer cannot enable project-logical quota over an existing registry with an
empty ledger. The cutover input must enumerate every repository-linked manifest
revision, including a manifest pushed only by digest and no longer referenced by
a tag, and reconstruct each manifest's immediate descriptor graph without
writing Distribution, object storage, or Coffer SQL.

This work package proves and verifies that input. It does not import the result,
set quota rows, enable admission, delete content, or authorize a production
maintenance window.

## Completeness Matrix

| Surface | What it can establish | Completeness result | Disposition |
|---|---|---|---|
| `GET /v2/_catalog` | Repository names, with lexical pagination | Repository presence is explicitly not a proof of absence; it has no manifest-revision list | Diagnostic comparison only |
| `GET /v2/<name>/tags/list` | Current tag names, with lexical pagination | A tag can resolve one current manifest, but digest-only and superseded untagged revisions have no tag to list | Incomplete and non-authoritative |
| Manifest `GET`/`HEAD` | Payload or existence for a *known* tag or digest | There is no standard endpoint that discovers all manifest digests | Payload/probe use only after enumeration |
| Notifications | Best-effort events generated after an endpoint is configured | Per-instance queues are in memory, order is not guaranteed, and instance loss can drop events; they cannot reconstruct history | Reconciliation hint only |
| `registry garbage-collect --dry-run` | Walks all repositories and manifest revisions, recursively marks references, and makes no deletion in dry-run mode | Complete traversal code path, including untagged revisions, but stdout is human-oriented and the command also computes global sweep candidates | Fixture corroboration only; do not parse as an import contract |
| Direct RGW/filesystem key parsing | Storage-layout paths and link objects | Can observe implementation details but bypasses Distribution's link validation and decoder behavior | Rejected |
| Pinned `RepositoryEnumerator` + `ManifestEnumerator` + `ManifestService.Get` | Repository-linked revision digests, decoded payload media type and size, immediate descriptor references, and current tag presence | Same enumeration seam used by v3.1.1 GC; `manifestStore.Enumerate` walks revision links rather than tag links | Selected PoC evidence surface |

The V2 API permits manifest `PUT` by either tag or digest, while `GET` and
`HEAD` require a caller-supplied reference. `_catalog` and `tags/list` therefore
cannot discover a digest-only revision. The pinned source makes the distinction
explicit: tag listing walks `_manifests/tags`, whereas manifest enumeration
walks `_manifests/revisions` and validates each revision link before yielding
its digest.

## Pinned Source Contract

Distribution v3.1.1 garbage collection:

1. asserts that its namespace implements `RepositoryEnumerator`;
2. opens each repository's manifest service and asserts
   `ManifestEnumerator`;
3. enumerates every linked manifest digest before consulting tag lookup for the
   optional untagged-deletion decision;
4. loads each manifest and recursively marks descriptor references; and
5. skips deletion in dry-run mode.

The interfaces are exported Go types, but the registry construction and
storage implementation are not an OCI or OpenStack interoperability standard.
The PoC helper must therefore pin the exact Distribution release and storage
driver behavior. A later production design should seek an upstream-supported,
machine-readable inventory command or hold the helper to the same release and
configuration qualification as the data plane.

## Snapshot and Authority Contract

A candidate inventory is valid only when all of these conditions hold:

1. **Write exclusion:** Distribution is stopped or restarted in verified
   read-only mode before the first scan. All upload, manifest, tag, mount, and
   delete routes remain unavailable through the second scan.
2. **Maintenance exclusion:** GC, retention, repository deletion, migration,
   and object-store lifecycle mutation are excluded for the whole interval.
3. **Storage identity:** the helper uses the same pinned Distribution release,
   storage driver, root/prefix, and backend configuration as the stopped or
   read-only data plane. It never accepts credentials in command arguments or
   emits configuration values.
4. **Two-scan equality:** independently enumerated start and end records are
   sorted canonically and must match byte-for-byte. Repository, manifest,
   descriptor, tag-presence, or payload-size drift fails closed.
5. **Bounded continuation:** every evidence page has a contiguous sequence,
   exact prior continuation, strictly increasing record keys, bounded item
   count, and a summary count/hash. Missing, repeated, reordered, or conflicting
   pages fail closed.
6. **Immutable authority:** every backend repository name must equal
   `p/<project UUID>/<control repository name>` for exactly one current Coffer
   repository row. Unknown roots, invalid UUIDs, missing control rows, and
   duplicate authority fail closed. Empty control repositories need not have a
   backend path and are not errors.
7. **Payload validation:** the enumerated digest and SHA-256 of the bytes loaded
   through `ManifestService.Get` must agree; payload length and media type are
   recorded; unsupported or undecodable manifests fail the scan.
8. **Descriptor validation:** descriptor digests are canonical SHA-256 values,
   sizes are non-negative signed 64-bit integers, duplicate digests have one
   size, and each index child resolves to an enumerated manifest in the same
   repository with matching digest, media type, and size.
9. **Untagged evidence:** each enumerated revision records only whether a current
   tag resolves to it. At least the disposable proof must contain one tagged and
   one digest-only manifest and show both in storage evidence while the HTTP tag
   list exposes only the tagged revision.
10. **Secret-free output:** the final deterministic inventory contains only
    schema/release identity, immutable project and repository IDs, manifest and
    descriptor digests/media types/sizes, direct graph edges, and aggregate
    counts/bytes. It excludes payload bodies, tag names, display names, origins,
    storage paths, URLs, credentials, tokens, request headers, and timestamps.

The final artifact is evidence for a separately approved import. It is not
self-authorizing: an operator must still own the restorable backup, maintenance
window, import transaction, comparison, admission enablement, and rollback.

## Verification Design

The disposable proof uses three read-only parts:

- an exact-version Go helper that opens a filesystem storage driver through
  Distribution's storage package, runs two complete enumerations, computes
  content digests and descriptor facts, and writes bounded deterministic
  evidence;
- a Python verifier that checks page continuity, two-scan equality, authority,
  digest/media/size consistency, nested indexes, untagged evidence, and
  deterministic aggregate construction; and
- an unmodified pinned Distribution fixture that publishes tagged and
  digest-only content, switches to write exclusion, compares the HTTP tag view
  with the storage evidence, and proves storage/control state is unchanged.

The helper and verifier never invoke `Put`, `Delete`, `Move`, quota reservation,
or SQL mutation methods. Fixture checksums and row counts before and after make
that negative claim observable.

## Primary References

- [Distribution V2 HTTP API](https://distribution.github.io/distribution/spec/api/)
- [Distribution v3.1.1 garbage-collection documentation](https://github.com/distribution/distribution/blob/v3.1.1/docs/content/about/garbage-collection.md)
- [Distribution v3.1.1 notification guarantees](https://github.com/distribution/distribution/blob/v3.1.1/docs/content/about/notifications.md)
- [Distribution v3.1.1 repository catalog and enumeration](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/catalog.go)
- [Distribution v3.1.1 manifest service and revision enumeration](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/manifeststore.go)
- [Distribution v3.1.1 linked-blob enumeration](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/linkedblobstore.go#L231-L272)
- [Distribution v3.1.1 tag store](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/tagstore.go)
- [Distribution v3.1.1 GC traversal](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/garbagecollect.go#L33-L141)
- [Distribution v3.1.1 exported namespace enumerator](https://github.com/distribution/distribution/blob/v3.1.1/registry.go#L25-L55)
- [Distribution v3.1.1 exported manifest enumerator](https://github.com/distribution/distribution/blob/v3.1.1/manifests.go#L30-L50)
