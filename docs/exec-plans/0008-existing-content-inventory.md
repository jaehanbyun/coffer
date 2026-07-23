---
title: "Read-only existing OCI content inventory and quota cutover discovery"
status: completed
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0007-unified-control-schema.md
---

# Objective

Establish the smallest evidence-backed, read-only inventory boundary required before Coffer can import an existing Distribution registry into project-logical quota accounting. Determine which interface can enumerate every repository manifest revision, including untagged digest-only content; define how backend names match immutable Coffer project/repository authority; specify a deterministic secret-free inventory artifact and fail-closed cutover checks; and implement only a disposable read-only verifier that cannot mutate registry, object storage, or quota state. Do not implement the production ledger import or enable admission in this package.

## Done Criteria

- [x] Current primary Distribution documentation/source and a disposable fixture establish whether catalog/tags/manifests APIs, notifications, GC traversal, or storage-driver traversal can provide a complete revision inventory, with untagged content tested explicitly.
- [x] A documented snapshot contract names the required write stop, GC exclusion, repository-authority match, pagination bounds, media/digest/size validation, child-manifest traversal, and start/end consistency evidence.
- [x] A versioned, deterministic inventory schema records only immutable project/repository/digest/media-type/descriptor facts and aggregate evidence; it excludes credentials, URLs with userinfo, bearer tokens, tenant-friendly names where immutable IDs suffice, and object payload bodies.
- [x] A read-only disposable verifier detects missing/orphan authority, pagination anomalies, unsupported/invalid manifests, digest mismatch, duplicate conflicting descriptor sizes, incomplete untagged coverage, and snapshot drift without changing Distribution, RGW/S3, or Coffer SQL.
- [x] Focused tests and an isolated pinned Distribution fixture pass; architecture/ADR/runbook/HANDOFF record what remains before a separately approved import; full structural/safety checks pass and the diff is ready for atomic publication.

## Non-goals

- Writing repository, quota, reservation, manifest, descriptor, tag, or object-storage state; enabling admission; deleting blobs; running GC; or migrating a production database.
- Supplying registry/database/RGW credentials, service-token design, KMS changes, or production deployment packaging.
- Treating tag enumeration, notifications, or `_catalog` as complete without explicit digest-only evidence.
- Defining final operator backup/restore, maintenance-window duration, performance capacity, Galera behavior, or rollback authorization.
- Importing foreign/orphan namespaces by guessing a project from repository text.

## Context and Evidence

- Published plan 0007 preserves exact Coffer repository identity in Alembic revision `0003`, but explicitly does not inspect Distribution/RGW content or populate quota state.
- ADR 0009 charges descriptor graphs from accepted manifest/index PUTs. An existing registry predates those reservations, so starting with an empty ledger would undercount and violate the bounded-soft quota claim.
- Coffer canonical repository paths embed immutable project IDs, but backend state can contain missing control rows, orphan repositories, digest-only revisions, invalid media, or content that changed during a scan.
- Distribution notifications are in-memory/advisory and cannot reconstruct history. The standard V2 catalog and tags endpoints enumerate names and tags, not obviously every stored manifest revision.
- The previous write-stopped GC dry-run proved safe traversal against the real RGW fixture but did not retain or define a machine-readable project-logical inventory contract.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Keep this package read-only and separate from ledger import | Completeness must be proven before any quota mutation; rollback and production data authority require separate approval | Write provisional quota rows during discovery; enable admission with an incomplete scan | 2026-07-23 |
| Fail closed on any backend/control authority mismatch | Guessing ownership can disclose or mischarge tenant data | Infer project from display names; assign orphans to a service project; skip silently | 2026-07-23 |
| Require immutable digests and authoritative fetched sizes in a deterministic artifact | Import must be replayable, diffable, and independent of mutable tags | Store only tag names/counts; trust client-declared sizes; retain manifest bodies | 2026-07-23 |
| Treat API-only completeness as an open hypothesis until digest-only evidence passes | `_catalog` and tags may omit revisions, and notifications are not history | Assume all manifests are tagged; rely on current client behavior | 2026-07-23 |
| Prototype the exact-version Distribution storage enumerator as the PoC evidence surface | v3.1.1 GC uses exported repository/manifest enumerators over validated revision links, while HTTP has no revision-list endpoint | Parse GC stdout; parse RGW/filesystem keys; treat tags or notifications as history | 2026-07-23 |

## Tasks

- [x] Research the pinned Distribution API, GC, and storage traversal paths from primary sources and map them to Coffer's quota descriptor semantics.
- [x] Prove tagged versus digest-only visibility and snapshot-drift behavior in an isolated unmodified Distribution fixture.
- [x] Define the inventory schema/cutover invariants and implement a bounded read-only verifier for the selected evidence surface.
- [x] Update ADR/architecture/runbook/README/HANDOFF, run the complete matrix, inspect the diff, and prepare one atomic publication.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Published unified control-schema plan 0007 at `6d36ed7`, bounded plan 0008 to read-only completeness discovery and verification, and excluded ledger/object mutation and production cutover.
- Evidence: Current checked-in decisions require a write-stopped import before quota is authoritative; no implementation currently enumerates pre-ledger manifests or proves untagged revision coverage.
- Changed files: Added this plan and activated it in `HANDOFF.md`.
- Next exact action: Inspect primary Distribution API/GC/storage source for repository and manifest enumeration, then record the completeness matrix before writing a verifier.

### 2026-07-23 — Completeness boundary selected

- Completed: Compared the standard HTTP catalog/tag/manifest APIs, notifications, GC traversal, storage layout, and exported storage enumerators; documented the write-stopped two-scan and immutable-authority contract.
- Evidence: `docs/research/m3-existing-content-inventory.md` records that the API can fetch only a known reference, notifications are best effort and in memory, and v3.1.1 GC enumerates repository revision links independently of tags before recursively loading references.
- Decision: Use a version-pinned read-only Go helper over Distribution's exported repository/manifest enumerators for disposable PoC evidence. GC human logs and direct backend-key parsing are explicitly non-authoritative.
- Changed files: Added the research record and updated this plan.
- Next exact action: Implement the deterministic storage-evidence schema and Python verifier unit tests before attaching the pinned Distribution fixture.

### 2026-07-23 — Read-only verifier and digest-only fixture passed

- Completed: Added strict storage-evidence and repository-authority schemas, a deterministic secret-free inventory builder/CLI, 17 focused negative/positive tests, the exact-version Go enumerator, and a stopped-registry filesystem fixture.
- Evidence: The HTTP tags API returned only one tagged image manifest; the storage enumerator returned that manifest plus a digest-only untagged OCI index. Two scans matched, four project-unique descriptors resolved, registry file-content and control-SQLite hashes stayed equal, both digests survived restart, and cleanup removed every labeled runtime resource and state file.
- Boundaries: The helper volume was mounted read-only and the verifier opened no registry, backend, or SQL connection. The helper is filesystem-only and built through disposable `go run`; production RGW/configuration/packaging and ledger import remain unimplemented and unauthorized.
- Failure correction: The first post-restart check assumed digest lexical order and omitted explicit OCI media `Accept` values. Verification now keys facts by digest and supplies the supported manifest/index media types; the complete rerun passed.
- Changed files: Added `src/coffer/inventory.py`, `tests/test_inventory.py`, `poc/inventory/`, research, proposed ADR 0011, the inventory runbook, and architecture/README/operator-boundary updates.
- Next exact action: Run the complete Python, Go, Bash/ShellCheck, Compose, Make, Markdown/link, diff, and secret-safety matrix, then close the plan and publish atomically.

### 2026-07-23 — Final regression passed; package ready to publish

- Completed: Closed empty-repository authority coverage, project aggregate overflow, atomic mode-0600 output, and fixture-derived snapshot-drift rejection found in final review; completed the full cross-version/runtime/structure/safety matrix.
- Evidence: Python 3.11, 3.12, and 3.13 each pass 151 tests. Go test/vet, the stopped-registry fixture, lock/compile, Alembic head, both installed CLIs, 58 Bash/ShellCheck files, six Compose models, ten Make dry-runs, 50 Markdown files, 29 local links, 99 external links, 204-file Gitleaks, key/JWT shapes, trailing whitespace, and diff checks pass. One OpenStack Wiki TLS timeout returned 200 on bounded retry.
- Runtime state: The final fixture again reports tags=1, storage manifests=2, four descriptors, equal snapshots, explicit drift rejection, unchanged registry/control hashes, two readable digests after restart, and zero container/volume/network/state residue. Podman is stopped.
- Changed files: Final inventory implementation, fixture, proposed ADR 0011, research, operator guidance, architecture, active-plan, and handoff set.
- Next exact action: Commit and atomically push plan 0008, then activate a separately bounded plan for transactional inventory-to-ledger import design without production access or admission enablement.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Baseline recovery | clean local/remote `main` at `6d36ed7`; schema/quota/fixture call graph | passed |
| Primary-source completeness matrix | Distribution docs and pinned source | passed; HTTP/notifications incomplete, exact-version storage enumerator selected |
| Disposable digest-only proof | isolated unmodified Distribution | passed; tags=1, storage manifests=2, untagged digest-only index included, state hashes equal |
| Read-only verifier | focused tests and state-before/after equality | passed; 17 tests plus installed CLI and fixture |
| Complete regression | Python, Go, compile, Bash/ShellCheck, Compose, docs, diff, secret scan | passed; 151 tests per Python, Go test/vet, 58 shell, 6 Compose, 10 Make, 50 Markdown, 99 external links, 204-file Gitleaks |

## Failures, Blockers, and Risks

- The registry HTTP API cannot enumerate untagged manifest revisions. The selected storage-library seam is exact-version PoC evidence, not a stable protocol or upstream inventory command.
- Distribution's storage layout remains an implementation detail. Parsing RGW keys or human GC logs directly is rejected; production still needs a reviewed exact-release helper and driver/configuration qualification.
- Nested indexes can reference child manifests not reachable by tags. The verifier requires each child in the same repository and deduplicates project descriptors, but real RGW scale and malformed/orphan link cases remain untested.
- The disposable helper uses filesystem storage and runtime Go compilation. It cannot accept production RGW configuration or credentials and is not production packaging.
- A complete logical inventory cannot prove physical blob exclusivity or safely delete content; GC remains separate.

## Handoff

- Current state: Completed and fully verified; atomic Git publication is the remaining action in this turn.
- Exact next action: Commit and push the complete plan 0008 diff, verify local/remote head equality, then create the next bounded execution plan for disposable transactional ledger import design.
- First action: Inspect staged scope and create one atomic plan 0008 commit.
- Questions requiring user input: none for read-only research and disposable verification; credentials, production data access, import writes, admission cutover, and destructive actions remain outside authorization.
