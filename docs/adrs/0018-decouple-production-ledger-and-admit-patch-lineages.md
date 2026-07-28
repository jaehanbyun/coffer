# ADR 0018: Decouple Production Scopes and Admit Reviewed Patch Lineages

- Status: accepted
- Date: 2026-07-28
- Decision owners: Coffer maintainers and security reviewers
- Related plan: `docs/exec-plans/0030-production-gate-decoupling.md`
- Supersedes in part:
  `docs/adrs/0001-compose-cnc-distribution.md` and
  `docs/adrs/0006-gate-production-distribution-release.md`
- Preserves:
  `docs/adrs/0003-rgw-s3-single-region-storage.md`

## Context

Ledger v1 correctly fails closed, but it combines Distribution, Ceph,
`oslo.messaging`, core and UI artifacts, RGW/Barbican KMS, Referrers, and all
later operating evidence into one serial production decision. That decision
cannot distinguish a Registry-core security blocker from a selected storage
or optional integration blocker.

The v1 upstream-only rule also treats the absence of a new official release
as conclusive even when an accountable vendor backport or narrowly maintained
Coffer patch could close the exact blocker. Allowing an arbitrary fork or
waiver would be unsafe; requiring one immutable lineage, one security bar,
independent review, and a bounded retirement contract can admit a downstream
release without concealing the additional maintenance obligation.

This decision does not make the current inputs production-ready.
Distribution v3.1.1 remains blocked by its recorded security and protocol
evidence. Ceph Tentacle v20.2.2 remains blocked for the RGW/Barbican
zero-byte SSE-KMS capability. The affected `oslo.messaging` input remains
blocked for Horizon and Skyline. Local fixtures and retained preview
deployments are not production evidence.

## Decision

### 1. Use one core and five independent profiles

Ledger v2 has these fixed scopes:

1. `registry_core`;
2. `storage_backend`;
3. `rgw_barbican_kms`;
4. `horizon`;
5. `skyline`; and
6. `referrers`.

Top-level `production_candidate` is true exactly when `registry_core` is
`qualified`. It means the Registry core software and operator contract
qualify. It does not claim that a deployment is runnable.

A baseline deployment additionally requires a qualified selected storage
backend whose tested Distribution lineage includes the exact qualified core
lineage. An RGW/Barbican KMS deployment additionally requires the same
backend identity and exact Distribution input on all three decisions.
Enabled UI and Referrers profiles are selected independently.

Profile failure, absence, or disablement cannot change the core decision.
Core failure cannot erase independently valid profile evidence, but no
combination using that core is deployable.

### 2. Derive four fail-closed statuses

- `blocked`: current explicit, source-bound evidence proves that a required
  input or check does not qualify.
- `pending`: required evidence is absent, incomplete, or not yet revalidated
  for this scope.
- `qualified`: every fixed required gate passed its source-bound verifier.
- `disabled`: an optional capability is intentionally not advertised or
  selected and is not production-ready.

Callers cannot submit a final gate, scope, or ledger status. Fixed schemas,
provider requirements, exact source hashes, policy catalogs, verifier
adapters, and prerequisite digests derive the result. Invalid, stale,
oversized, unsupported, or source-drifted evidence is rejected rather than
softened to `pending`.

### 3. Admit exactly three provider lineage classes

The preferred input remains a signed official upstream stable release. A
provider input may qualify only through one of these classes.

#### Signed official upstream release

- repository, release authority, and immutable tag are in the exact policy
  catalog;
- the tag is non-draft, non-prerelease, and resolves to one source revision;
- source archive, provenance subject, binary, image, and every supported
  architecture digest are bound;
- the downstream patch set is empty;
- SBOM, scanner database, vulnerability, signature, conformance, runtime, and
  upgrade evidence bind the same artifacts; and
- upstream support covers the Coffer support window.

#### Approved vendor backport

- vendor repository, release and advisory authorities, advisory channel,
  supported upstream base, and support policy are in the exact policy
  catalog;
- one public signed immutable release and advisory identify the ordered patch
  set;
- every patch maps to one upstream commit, issue, or pull request and states
  the security or correctness blocker it closes;
- a designated independent Coffer builder rebuilds the exact source subject
  for every supported architecture;
- source bundle, provenance, SBOM, scanner, binary, and image identities
  remain mutually consistent;
- vendor support covers the Coffer support window; and
- vendor EOL, advisory withdrawal, signer revocation, or an unqualified
  lifecycle observation blocks new promotion immediately.

#### Coffer-maintained minimal patch release

- the base is the latest supported upstream stable release admitted by the
  policy catalog;
- each ordered patch closes one recorded production blocker;
- the patch adds no feature, protocol extension, storage-format or database
  schema change, Referrers implementation, or unrelated dependency refresh;
- a public upstream issue or pull request exists before promotion;
- the patch owner, independent security reviewer, lifecycle observer, release
  authority, and two independent designated builders satisfy the policy's
  separation rules;
- both builders reproduce every supported architecture artifact;
- Coffer signs the source bundle, provenance, SBOM, binary, and image release;
  and
- the release support end is the earliest of the Coffer minor release EOL,
  twelve months from publication, or the replacement deadline below.

The same runtime, protocol, multi-architecture, security, persistence,
upgrade, rollback, and teardown qualification applies to all three classes.
Downstream classes receive additional obligations, never a lower product
threshold.

### 4. Fix replacement, upstream, and retirement semantics

Lifecycle status comes from an independently signed, source-bound observer
adapter selected by the exact trust-policy catalog. A caller-provided date,
replacement, or final status has no authority.

For a Coffer patch, the first qualifying official or approved-vendor
replacement fixes a deadline ninety days later, clipped by the patch's
existing support and release EOL. A later replacement does not restart or
extend that window. Vendor replacements must themselves be exact cataloged
releases; sharing the same upstream base is insufficient.

An upstream submission that is withdrawn, rejected, or closed for a valid
technical reason is a signed blocker for renewal. It does not erase the
already fixed support end or create a grace extension. A patch outside the
minimal boundary is a fork and requires a separate architecture and
maintenance ADR.

### 5. Permit only exact signed vulnerability dispositions

The security threshold is zero unresolved reachable Critical or High
findings. An independently reviewable signed OpenVEX statement may close a
finding only when it binds the exact artifact digest or PURL, CVE, scanner
database digest, issuer, evidence digest, issue date, and expiry.

Accepted dispositions are:

- `not_affected`, with source and binary reachability evidence; or
- `fixed`, with exact fixed-artifact evidence.

`under_investigation`, blanket package suppression, count adjustment,
expired or overdue evidence, a negative signed lifecycle observation, or a
statement for another artifact remains blocked. VEX does not waive protocol,
runtime, provenance, support, or lifecycle gates.

### 6. Keep Referrers independent and explicit

Registry core may qualify with Referrers disabled only when Coffer does not
advertise or depend on it. The profile records one fixed mode:

- `native`: endpoint, filtering, pagination, client, subject lifecycle,
  deletion, signing, and GC checks pass;
- `fallback-tag`: the accepted tag contract plus collision, concurrent
  update, subject deletion, client, signing, and GC limitations pass; or
- `disabled`: Coffer does not advertise or depend on the capability.

A deployment or signing policy that depends on Referrers must require the
selected qualified mode. `disabled` never means production-ready.

### 7. Preserve v1 and migrate evidence monotonically

Ledger v1 source, schema, CLI, Make targets, and output path remain unchanged.
V2 uses distinct modules, schemas, inputs, and output.

Migration embeds and hashes the exact original v1 ledger and release bytes.
A v1 `blocked` state remains `blocked`; `pending` remains `pending`; and a v1
`passed` state is still `pending` in v2 until a current v2 adapter
independently re-runs or revalidates the original specialist payload. The
migration record preserves each original gate evidence reference as
`legacy_evidence`; a gate name or digest is never treated as a v2 pass.

General v2-to-v1 projection and semantic reconstruction are forbidden.
Compatibility can replay only the exact original v1 bytes bound by a signed
pre-upgrade checkpoint, a still-trusted frozen verifier bundle, current
revocation policy, a separately signed writer fence and rollback
authorization, and a deployment-wide shared compare-and-swap state adapter.

The publication transaction is `claimed -> publishing -> completed`. Its
authorization, claim, logical destination, canonical destination descriptor,
payload, and receipt are all digest-bound. A local file or receipt is only a
cache and can never substitute for shared completion.

No production shared-state adapter or production verifier-registry entry is
configured by this work package. Production rollback therefore remains
unavailable and fails closed. The injected fixture proves only the protocol
and failure boundary.

### 8. Bound evidence resources

Every input, embedded v1 payload, checkpoint, provider result, scope result,
ledger, and rollback document has an explicit serialization budget. No
producer, loader, validator, or owner-only writer may exceed the common
16 MiB hard ceiling. Narrower contracts keep their smaller limits.

### 9. Preserve the MVP storage decision

ADR 0003 remains the selected single-region MVP storage baseline: Ceph RGW
through Distribution's upstream S3 driver. `storage_backend` makes the
capability independently visible; it does not approve Swift, filesystem, or
another backend. Each additional production backend requires its own ADR,
maintainer, compatibility contract, and complete qualification.

## Relationship to Earlier Decisions

- ADR 0001 remains the product composition baseline. This ADR narrowly
  supersedes its absolute “unmodified Distribution” restriction only for an
  exact cataloged Coffer minimal patch satisfying this decision. Coffer still
  does not embed or reimplement the registry data plane.
- ADR 0003 is unchanged and remains the MVP/default storage selection.
- ADR 0006 remains the Distribution security and protocol gate, but its
  upstream-only lineage and globally coupled RGW/Referrers requirements are
  superseded by the three-lineage policy and independent profiles here.

## Alternatives Rejected

- **Keep one global minimum:** continues to classify optional-profile
  blockers as core blockers.
- **Infer v2 passes from v1 gate names or digests:** turns evidence migration
  into retrospective self-attestation.
- **Wait only for official upstream forever:** prevents an accountable,
  time-bounded repair even when the product threshold can be met.
- **Allow arbitrary private forks or date waivers:** lacks immutable
  provenance, support, review, upstream, and retirement accountability.
- **Lower the scanner or protocol threshold for downstream builds:** weakens
  the product precisely where Coffer owns more risk.
- **Treat a local fixture or preview as production evidence:** confuses
  contract testing with deployed qualification.
- **Rewrite ledger v1 or project v2 back into it:** invalidates retained
  evidence and changes downgrade meaning.
- **Enable production rollback with local lock files:** cannot serialize
  replicas and can publish conflicting evidence.

## Consequences

- Operators can distinguish Registry-core qualification from the exact
  storage, KMS, UI, and Referrers profile that blocks a deployment.
- A core candidate still cannot be described as a deployable service without
  a compatible qualified storage profile.
- Vendor and Coffer patch releases are possible only with stricter
  provenance, independent rebuild, support, upstream, and retirement duties.
- Current v1 evidence remains valid for v1 consumers and negative migration
  facts, but no state is retrospectively promoted.
- Exact signed checkpoints can preserve rollback intent, while the production
  command remains fail-closed until a real shared-state adapter and trusted
  verifier entry are deliberately deployed.

## Acceptance Evidence

Plan 0030 implements and verifies:

1. exact admission and rejection branches for all three lineage classes,
   lifecycle observations, replacement deadlines, and VEX;
2. source-bound independent scope evidence and ledger v2;
3. negative-first v1 migration with exact legacy evidence references;
4. frozen-verifier checkpoint validation, downgrade refusal, and
   shared-CAS rollback protocol fixtures;
5. current machine-readable evidence with no qualified scope and
   `production_candidate=false`;
6. owner-only files, bounded payloads, source drift, CLI enforcement, and
   complete focused and repository regression; and
7. independent security and compatibility reviews with no remaining P0/P1
   finding.
