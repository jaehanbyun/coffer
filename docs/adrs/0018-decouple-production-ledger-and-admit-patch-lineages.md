# ADR 0018 Candidate: Decouple Production Scopes and Admit Reviewed Patch Lineages

- Status: proposed
- Date: 2026-07-28
- Decision owners: Coffer maintainers and security reviewers
- Related plan: `docs/exec-plans/0030-production-gate-decoupling.md`
- Supersedes in part:
  `docs/adrs/0006-gate-production-distribution-release.md`

## Context

Ledger v1 correctly fails closed but combines Distribution, Ceph,
`oslo.messaging`, core and UI artifacts, RGW/Barbican KMS, Referrers, and all
later operating evidence into one serial production decision. This makes a
real UI or optional capability blocker appear to be a Registry-core blocker.
It also permits only an official upstream stable release, even when a
reviewed vendor backport or a narrowly maintained patch release could close a
known blocker under stronger provenance and lifecycle obligations.

This ADR does not make the current inputs production-ready. Distribution
v3.1.1 remains blocked by its recorded security and protocol evidence. Ceph
Tentacle v20.2.2 remains blocked for the RGW/Barbican zero-byte SSE-KMS
capability. The affected `oslo.messaging` input remains blocked for Horizon
and Skyline.

## Proposed Decision

### 1. Add independent production scopes

Ledger v2 has one Registry core decision and five independent profiles:

1. storage backend;
2. RGW and Barbican SSE-KMS;
3. Horizon;
4. Skyline; and
5. Referrers.

Top-level `production_candidate` is exactly the Registry core result. It says
that the core software and operator contract qualify; it does not by itself
claim a runnable deployment. A deployable combination additionally requires
the selected storage backend and every enabled integration profile.

Profile failure, absence, or disablement does not change the core decision.
Core failure does not erase independently valid profile evidence, although a
deployment using that core remains unavailable.

### 2. Preserve fail-closed status semantics

- `blocked`: current explicit evidence proves that a required input or check
  does not qualify.
- `pending`: required evidence is absent, not yet revalidated, or incomplete.
- `qualified`: every fixed required gate in that scope passed its
  source-bound verifier.
- `disabled`: an optional capability is intentionally not advertised or
  selected and therefore is not production-ready.

Callers cannot submit any of these final statuses. Ledger and profile
verifiers derive them from exact schemas, source hashes, prerequisite
digests, provider lineages, and bounded evidence.

### 3. Admit only three dependency lineage classes

The preferred input remains a signed official upstream stable release. The
following classes may also qualify:

#### Signed official upstream release

- allowed upstream repository and signing identity;
- non-draft, non-prerelease immutable tag and source revision;
- verified source archive, provenance subject, binary, image, and
  architecture digests;
- empty downstream patch set; and
- upstream support covering the Coffer support window.

#### Approved vendor backport

- vendor repository, signing identity, advisory channel, and support policy
  are explicitly allowlisted;
- one public signed immutable release and advisory;
- exact supported upstream base revision;
- every ordered patch maps to one upstream commit, issue, or pull request and
  its security or correctness reason;
- Coffer independently rebuilds the same source subject and verifies both
  supported architectures;
- vendor support covers the Coffer support window; and
- vendor EOL, advisory withdrawal, or signer revocation immediately blocks
  new promotion.

#### Coffer-maintained minimal patch release

- latest supported upstream stable base;
- every patch closes one recorded production blocker;
- no feature expansion, protocol extension, storage-format change, schema
  change, Referrers reimplementation, or unrelated dependency refresh;
- public upstream issue or pull request before promotion;
- named patch owner and independent security reviewer;
- two independent builders reproduce each architecture artifact digest;
- source bundle, provenance, SBOM, and images use the Coffer release signing
  identity; and
- support ends at the earliest of the Coffer minor release EOL, twelve months
  from the patch release, or ninety days after an upstream or approved vendor
  replacement qualifies.

Extending a Coffer patch beyond that boundary requires a new ADR and complete
requalification. A patch rejected upstream for a valid technical reason may
run only to the existing support end and cannot renew automatically. A change
outside the minimal scope is a fork and requires a separate architecture and
maintenance decision.

### 4. Apply one security and protocol threshold

All three lineage classes must pass the same:

- supported OCI core conformance and advertised-capability tests;
- Coffer runtime, persistence, upgrade, rollback, and teardown tests;
- native amd64 and arm64 artifact inspection;
- immutable provenance, SBOM, secret, and vulnerability review; and
- zero unresolved reachable Critical or High findings.

A downstream class never receives a weaker product threshold. It receives
additional provenance, ownership, support, upstream, and retirement duties.

### 5. Allow only exact signed VEX evidence

An independently reviewable signed OpenVEX statement may close a finding only
when it binds the exact product digest or PURL, CVE, scanner database digest,
issuer identity, evidence digest, issue date, and expiry. Accepted
dispositions are `not_affected` with source and binary reachability evidence
or `fixed` with exact fixed-artifact evidence.

`under_investigation`, blanket package suppression, scanner-count adjustment,
expired evidence, or evidence for another artifact remains blocked.

### 6. Split Referrers from core

Registry core may qualify with Referrers disabled if Coffer does not advertise
or depend on it. The profile records one mode:

- `native`: exact OCI endpoint, pagination/filtering, clients, subject
  lifecycle, deletion, and GC pass;
- `fallback-tag`: explicit product/security acceptance plus concurrency, tag
  collision, subject deletion, client, signing, and GC limitations pass; or
- `disabled`: the capability is not advertised.

A deployment or signing policy that depends on Referrers must separately
require its selected qualified mode.

### 7. Preserve v1 and constrain rollback

Ledger v1 code, schema, CLI, Make targets, and output remain unchanged.
Ledger v2 and its inputs use distinct paths. Migration is conservative:
blocked and pending states never pass, and a v1 passed digest remains pending
until its original specialist result is revalidated.

General v2-to-v1 projection is forbidden. The only compatible replay verifies
and copies the exact original v1 bytes bound by the migration digest. It is
unavailable when a vendor/Coffer lineage or changed v2 scope would make the
v1 meaning stale. Rollback preserves v2 evidence for audit.

## Alternatives Rejected

- **Keep one global minimum:** continues to misclassify optional profile
  blockers as core blockers.
- **Treat every valid local fixture as a profile pass:** replaces evidence
  with self-attestation.
- **Wait only for official upstream forever:** can leave unrelated profiles
  unnecessarily blocked and provides no accountable emergency patch policy.
- **Allow arbitrary private forks:** lacks provenance, support, upstream, and
  retirement accountability.
- **Make vendor/Coffer findings easier to waive:** weakens the security
  threshold precisely where maintenance responsibility is higher.
- **Rewrite ledger v1 in place:** invalidates retained source-bound evidence
  and removes a deterministic rollback boundary.

## Consequences

- Operators can see whether the Registry core or one selected profile is the
  actual blocker.
- A core candidate still cannot be called deployable without a qualified
  storage profile.
- Vendor and Coffer patch releases become possible but carry explicit,
  time-bounded maintenance and upstream obligations.
- Current v1 evidence remains valid for v1 consumers and negative migration
  facts, but no state is retrospectively promoted.
- Existing specialist verifiers may remain as stronger legacy evidence.
  V2-native scope compilers must remove transitive optional-profile
  prerequisites before their results can qualify an independent scope.

## Acceptance Conditions

This ADR becomes accepted only after plan 0030 implements and verifies:

1. immutable lineage admission for all three classes and exact VEX rules;
2. independent source-bound scope evidence and ledger v2;
3. negative-only v1 migration and exact-byte rollback;
4. current evidence remap with no qualified scope;
5. focused and full regression, secret, documentation, and diff checks; and
6. independent security review of the final implementation.
