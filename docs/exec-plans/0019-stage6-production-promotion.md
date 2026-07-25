---
title: "Stage 6 production promotion"
status: active
updated: 2026-07-25
owner: primary-agent
---

# Objective

Turn the completed Stage 5 HA pilot into a production-candidate operator
baseline without weakening any accepted security, storage, identity, data
protection, or operability gate. Stage 6 qualifies released upstream
Distribution and Ceph inputs, closes the maintenance-identity and existing-data
cutover contracts, proves restart-correct observability and controlled garbage
collection, exercises representative load and recovery, and finishes with one
repeatable Kolla companion-role pilot whose evidence can support an
operator-local release.

## Done Criteria

- [ ] A signed, supported CNCF Distribution release passes ADR 0006 on x86_64
      and aarch64: immutable provenance, Coffer runtime, OCI supported-profile
      conformance, malformed-reference behavior, Referrers disposition, SBOM,
      secret scanning, and zero unresolved reachable Critical/High findings.
- [ ] A released, supported Ceph/RGW combination passes verified-TLS
      Distribution storage behavior with Barbican SSE-KMS for positive-size and
      zero-byte moves, wrong-key/outage recovery, key rotation, restart
      persistence, multipart cleanup, and least-privilege access.
- [ ] Reconciliation and authenticated live inventory use an accepted,
      expiring, owner-controlled maintenance identity over private verified TLS;
      credential materialization, rotation, revocation, audit, and fail-closed
      behavior are repeatable without secret residue.
- [ ] A representative disposable copy completes writer exclusion, restorable
      SQL and RGW backup, exact-release inventory, transactional import,
      authenticated comparison, admission cutover, rollback, and recovery with
      deterministic evidence and no mutation of production data.
- [ ] API, edge, registry, reconciliation, database, RGW, KMS, and load-balancer
      signals have restart-correct metrics, bounded-cardinality labels, alerts,
      logs, and an operator-owned failure-budget/SLO baseline.
- [ ] Coordinated write-stopped Distribution garbage collection passes dry-run
      and approved destructive collection on a disposable shared-blob fixture;
      referenced content survives, reclaimed content is measured, restore is
      rehearsed, and RGW orphan/lifecycle cleanup remains separately owned.
- [ ] Representative private-TLS/shared-SQL/RGW load and soak tests cover the
      accepted client matrix, upload shapes, quota contention, Galera
      retry/deadlock behavior, reconciler fencing, replica and dependency
      faults, and resource saturation with recorded limits.
- [ ] A fresh Kolla multinode production-candidate pilot deploys immutable
      release artifacts, passes tenant isolation and all Stage 5 availability
      gates, rehearses upgrade/rollback/backup/restore, and is completely
      removed by an independently audited teardown.
- [ ] Operator documentation, accepted/rejected ADR decisions, release notes,
      supply-chain evidence, repository regression, secret checks, and
      `HANDOFF.md` accurately describe what is and is not production-ready.

## Non-goals

- Official OpenStack governance, Kolla/Kolla-Ansible upstream inclusion, or
  service-type authority registration. Those begin only after an
  operator-local production candidate exists.
- Deploying into a production OpenStack cloud or reading, modifying, deleting,
  backing up, or restoring production tenant data.
- Publishing commits, images, attestations, SBOMs, releases, issues, or pull
  requests without separate authorization.
- Carrying an unreleased Distribution or Ceph branch, silently introducing a
  private fork, or waiving a reachable Critical/High finding to satisfy a date.
- Creating credentials, rotating real keys, changing a security boundary, or
  executing destructive GC without the explicit approval required by
  `AGENTS.md`.
- Recreating the six-VM Stage 5 lab before the selected released dependencies
  and production-candidate inputs pass their cheaper qualification gates.

## Context and Evidence

- Plan 0018 completed the disposable three-controller Kolla/Galera/HAProxy and
  three-storage-node Ceph/RGW HA pilot, then removed every exact Stage 5
  identity, credential, bucket, object namespace, VM, volume, and network.
  Post-destroy repository regression passed 251 Python tests and 52 companion
  role contract checks.
- Plan 0017 left a deterministic `production_candidate=false` result:
  Coffer-owned ARM64 image findings were reduced to zero Critical/High, but the
  signed Distribution v3.1.1 binary retained reachable vulnerabilities. ADR
  0006 therefore still prohibits production promotion.
- Official GitHub release metadata checked on 2026-07-25 still reports signed
  Distribution v3.1.1 as the latest stable release. No newer released input is
  available for the existing production-image harness.
- Ceph Tentacle v20.2.2 is still the latest stable Tentacle point release.
  That release intentionally rejects ordinary `CopyObject` for an encrypted
  source, leaving Distribution's zero-byte SSE-KMS move incompatible.
- Ceph PR 69277 was merged to the protected `tentacle` branch on 2026-07-22.
  It backports encrypted `CopyObject` support and related fixes/tests, so the
  blocker now has a concrete upstream release path. It is not acceptable
  evidence until it appears in a signed stable point release and passes the
  exact Coffer/Distribution/Barbican matrix.
- Stage 5 already proves Galera/HAProxy, replica loss, worker fencing, signing
  key overlap, rolling update, and compatible rollback. Stage 6 reuses those
  contracts only after dependency, identity, and data-protection promotion
  inputs are ready.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Treat plan 0018 commit `610b576` as the Stage 5 atomic boundary and begin Stage 6 with a new plan | The worktree is clean and Stage 5 completion, teardown, and final verification are already committed | Empty checkpoint commit; rewriting the Stage 5 completion commit | 2026-07-25 |
| Run Stage 6 as gated workstreams that converge before a new multinode pilot | Distribution and Ceph releases are external dependencies, while identity, data protection, and observability design can progress independently without recreating infrastructure | Blocking every task on the next upstream release; recreating the full lab before candidate inputs exist | 2026-07-25 |
| Accept only signed stable upstream releases for executable promotion evidence | ADR 0006 and the unmodified-data-plane decision require reproducible supported inputs | Testing a branch build and labeling it production-ready; private dependency fork without a separate ADR | 2026-07-25 |
| Treat merged Ceph PR 69277 as a release candidate signal, not a closed gate | The backport is in `tentacle` but absent from released v20.2.2; exact zero-byte and failure-mode behavior still needs an official image and live test | Claiming source inspection or upstream tests as Coffer runtime acceptance | 2026-07-25 |
| Keep official Kolla upstream work outside Stage 6 | Companion-role contracts may still change as production identity, data protection, and operations gates close | Starting governance review around provisional deployment contracts | 2026-07-25 |
| Approve the dedicated expiring maintenance identity boundary for pure local implementation | A separate service user, exact dual-role policy, server-side SQL authority, pull-only token reduction, and private mTLS bound cross-project reads without sharing tenant, signer, or RGW credentials | Per-project credential fan-out; API middleware password/admin reuse; service/system or mTLS-only authority; signer key in the worker; separate read proxy | 2026-07-25 |
| Represent live-comparison authority as a finite SQL session bound to the imported digest, workload, and writer-exclusion evidence reference | The broker needs current server-side authority that can expire, complete, revoke, and replay safely without storing a credential or repository path | Caller-supplied route/action; static configuration flag; a bearer token as approval; claiming that the SQL row itself proves external writer exclusion | 2026-07-25 |

## Tasks

- [x] Recover the completed Stage 5 boundary and refresh current official
      Distribution/Ceph release and source-branch evidence.
- [x] Add a deterministic upstream-release readiness check that distinguishes
      signed stable artifacts from merged-but-unreleased fixes and feeds the
      existing fail-closed production-image and RGW/KMS harnesses.
- [x] Select and prove the production maintenance identity and owner-only
      secret-delivery lifecycle without creating a real credential.
- [ ] Package and qualify the exact-release RGW inventory helper and complete
      the disposable backup/import/comparison/cutover/rollback rehearsal.
- [ ] Implement restart-correct metrics, protected scrape/aggregation, alerts,
      operational dashboards, and failure-budget documentation.
- [ ] Implement and execute the approved coordinated GC/retention fixture and
      restore rehearsal.
- [ ] Implement and execute the representative client/load/soak/fault matrix.
- [ ] Build immutable production-candidate artifacts and rerun dependency,
      protocol, security, architecture, and runtime qualification on both
      supported architectures.
- [ ] Recreate a fresh isolated Kolla multinode pilot only after every
      pre-deployment gate passes; accept and tear it down.
- [ ] Close operator documentation, supply-chain evidence, ADRs, repository
      regression, and the Stage 6 handoff.

## Progress Log

### 2026-07-25 — Stage 6 activated at the existing Stage 5 commit boundary

- Completed: Recovered `AGENTS.md`, the complete plan 0018, the handoff,
  current Git state, ADRs 0003/0006/0011/0014, and the retained production
  image and Barbican/RGW evidence. Confirmed the clean worktree at
  `610b576`, 126 local commits ahead of `origin/main`, with no uncommitted
  Stage 5 work requiring another checkpoint.
- Upstream evidence: Official release metadata still identifies signed
  Distribution v3.1.1 and Ceph Tentacle v20.2.2 as the current stable inputs.
  The protected Ceph `tentacle` branch merged PR 69277 at
  `c6fc9801f55e24152f0e934b2ddc3e5cda33d63e`, replacing the released
  encrypted-source rejection with decrypt/re-encrypt copy support and related
  tests. No stable release contains that backport yet.
- Decision: Activate the Stage 6 promotion harness now, preserve the external
  release gates as fail-closed, and progress independent work instead of
  rebuilding the six-VM lab or adopting an unreleased branch.
- Changed files: This plan and `.codex/state/HANDOFF.md`.
- Next exact action: Add
  `poc/production-images/check_upstream_readiness.py` with fixture-driven unit
  tests. It must classify current Distribution/Ceph release metadata and the
  Ceph encrypted-copy backport as `blocked`, `candidate-released`, or
  `candidate-qualified` without downloading, building, mutating infrastructure,
  or treating a branch commit as a released artifact.

### 2026-07-25 — Upstream release readiness classifier completed

- Completed: Added a read-only official GitHub metadata classifier with three
  monotonic states: `blocked`, `candidate-released`, and
  `candidate-qualified`. Distribution requires a newer non-draft,
  non-prerelease release with a verified release commit. Ceph requires a newer
  Tentacle v20.2.z stable tag whose commit descends from the exact merged
  encrypted-copy fix. A later Ceph series requires a separately reviewed
  baseline and ancestry. Qualification requires a separate exact-schema
  evidence file matching both component versions and revisions.
- Current live evidence: Distribution v3.1.1 at verified commit
  `9a8d98b679740cd514aa7e7d84d23d442a5ef54c` and Ceph v20.2.2 at
  `0fcffee29411e3a38036764817b6e1afc59741cc` classify as `blocked`.
  Ceph PR 69277 is correctly reported as merged to `tentacle` but absent from
  the latest stable release.
- Failure and correction: The first live run expected a `head_commit` object
  in GitHub's Compare API response and failed before classification. The
  classifier now resolves the Ceph release revision through the separate
  official commit endpoint and keeps Compare solely for fix ancestry.
- Verification: Ten fixture-driven tests cover the current block, stable
  candidate transition, draft/prerelease/unsigned refusal, exact
  qualification matching, schema and malformed-revision refusal, Tentacle
  series filtering, and atomic output. All 261 Python tests and 52 Kolla
  companion-role checks pass; compilation, the live classifier, and diff
  checks pass.
- Changed files: `poc/production-images/check_upstream_readiness.py`,
  `poc/production-images/Makefile`, `poc/production-images/README.md`,
  `tests/test_upstream_readiness.py`, this plan, and `HANDOFF.md`.
- Next exact action: Create
  `docs/research/stage6-maintenance-identity.md`. Inventory the implemented
  reconciliation/live-comparison authentication seams and evaluate expiring
  Keystone application credentials, service credentials, and private mTLS
  against least privilege, rotation overlap, revocation, audit, Barbican
  materialization, and Kolla ownership. Do not create or deliver any
  credential and do not accept an ADR yet.

### 2026-07-25 — Maintenance identity candidates researched

- Completed: Documented the exact implemented authentication boundary.
  `AuthenticatedManifestProbe` is provider-ready, while the installed
  reconciler creates a verified-TLS probe with no Authorization header.
  `coffer_enable_reconcile` is false by default and remained false in Stage 5;
  Stage 5 proved shared-Galera claim/fencing behavior, not an authenticated
  Distribution HEAD.
- Recommendation requiring approval: Use a separate maintenance service user
  with `service` plus a proposed `registry_maintenance` role and a finite,
  restricted, access-rule-bearing Keystone application credential. An
  internal-only Coffer broker should resolve authority from SQL and issue one
  short-lived pull-only, one-repository JWT. A dedicated HAProxy mTLS frontend
  should provide workload/path defense in depth; it is not authorization.
- Rejected directions: Per-project credential fan-out as the global default;
  reuse of the current admin-assigned API middleware password; service/system
  tokens as implicit Distribution authority; giving the signing key to
  `coffer-reconcile`; and adding a separate authorization proxy.
- Security boundaries: The public edge must deny `/v1/internal/`; the
  maintenance credential and per-replica client key go only to approved
  workers; Coffer API retains the signer; failures remain indeterminate; and
  tokens never enter SQL, config, disk cache, environment, arguments, metrics,
  logs, or evidence.
- Changed files: Added
  `docs/research/stage6-maintenance-identity.md`; updated this plan and
  `HANDOFF.md`. No credential, role, endpoint, ACL, certificate, secret
  recipient, policy, or runtime setting changed.
- Next exact action requiring user approval: Accept or reject the recommended
  cross-project maintenance authority, dedicated role/user, access-rule
  application credential, and private mTLS frontend. If accepted, first create
  proposed ADR `docs/adrs/0015-use-expiring-maintenance-identity.md`; keep it
  proposed until pure policy/token/edge-denial tests pass.

### 2026-07-25 — Maintenance identity boundary approved for local proof

- Approval: The user approved the recommended dedicated maintenance identity
  boundary. The approval covers the architecture and pure local contract proof,
  not creation or delivery of credentials, roles, certificates, Barbican
  secrets, endpoints, remote deployment, or production-data operations.
- Completed: Added proposed ADR 0015. It fixes the dedicated service user,
  exact `service` plus `registry_maintenance` policy, finite access-rule
  application credential, private mTLS frontend, public-edge denial,
  server-side claim/session authority, one-repository pull-only JWT, signer and
  recipient separation, rotation/revocation, secret-safety, and fail-closed
  contracts.
- Decision: Keep ADR 0015 proposed until pure local policy, token, stale
  authority, edge-denial, and secret-safety tests pass. Keep reconciliation
  disabled and do not add Kolla recipients or real credentials in this
  milestone.
- Changed files: Added
  `docs/adrs/0015-use-expiring-maintenance-identity.md`; updated this plan and
  `.codex/state/HANDOFF.md`.
- Next exact action: Inspect `src/coffer/tokens.py`, `src/coffer/quota.py`,
  `src/coffer/db.py`, and the edge routing tests, then add the smallest
  injectable maintenance authorization/token-broker core beginning in
  `src/coffer/maintenance_token.py`.

### 2026-07-25 — Reconciliation maintenance-token local core completed

- Completed: Added the optional middleware-protected internal token resource,
  exact maintenance user/project/dual-role/application-credential/access-rule
  policy, trusted non-HTTP workload context, strict typed request parser,
  read-only live reconciliation claim authority, server-side repository route
  resolution, and one-repository pull-only JWT reduction.
- Edge and secret safety: The public edge now rejects `/v1/internal` and all
  descendants before opening either upstream. Password tokens, unrestricted
  application credentials, wrong user/project/roles/workload, caller-selected
  project/repository/action/audience/subject, stale claim/token/version/worker/
  expiry, and dependency exception text fail with fixed secret-safe results.
- Scope boundary: The resource is injectable for local proof and is not enabled
  by `build_product_application`. No configuration, identity, credential,
  certificate, Barbican secret, Kolla recipient, endpoint, remote service, or
  production data changed. The live-comparison request is typed but still has
  no approved-session SQL authority, so ADR 0015 remains proposed and the
  maintenance-identity task remains open.
- Verification: 291 Python tests pass, including 30 new maintenance/API/edge
  cases; all 52 Kolla companion-role checks pass; compilation and diff checks
  pass.
- Changed files: `src/coffer/maintenance_token.py`, `src/coffer/quota.py`,
  `src/coffer/registry_proxy.py`, `src/coffer/tokens.py`,
  `src/coffer/wsgi.py`, `tests/test_maintenance_api.py`,
  `tests/test_maintenance_token.py`, `tests/test_registry_proxy.py`, ADR 0015,
  this plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Define the approved live-comparison session lifecycle in
  ADR 0015, then begin its local SQL schema with
  `src/coffer/migrations/versions/0005_maintenance_comparison_sessions.py`.

### 2026-07-25 — Live-comparison session authority completed

- Completed: Added Alembic revision
  `0005_maintenance_comparison_sessions` and matching quota-store lifecycle.
  An owner-controlled approval request is finite, idempotent, bound to the
  imported digest, workload, and non-secret writer-exclusion evidence
  reference, and refuses missing import authority or active reconciliation
  claims. Completion/revocation is irreversible and idempotent.
- Authorization: Each live token request rechecks the exact session/digest/
  workload/state/expiry, baseline marker, absence of active reconciliation
  claims, and a committed imported repository before resolving the current
  route and reducing it to one pull-only JWT. Stale, mismatched, unknown,
  completed, revoked, and expired sessions fail with fixed secret-safe errors.
- Schema safety: Revision 0005 adds no credentials, tokens, repository names,
  manifest digests, or tenant paths. Downgrade refuses to discard retained
  session evidence. The current schema revision and bootstrap/migration
  contracts now use revision 0005.
- Decision: Accept ADR 0015 for the architecture and pure local contract. This
  is not production acceptance: the resource remains optional/unconfigured and
  there is still no mTLS workload adapter, Kolla recipient, Barbican
  materialization, real identity lifecycle, or disposable private-TLS
  end-to-end evidence.
- Verification: 105 focused maintenance/session/migration/import/live-inventory
  tests pass. Full regression passes 308 Python tests, all 52 Kolla
  companion-role checks pass, and compilation and diff checks pass.
- Changed files: ADRs 0010/0015, the schema runbook, revision 0005,
  `src/coffer/schema.py`, `src/coffer/quota.py`,
  `src/coffer/maintenance_token.py`, maintenance/session/migration/bootstrap
  tests, this plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Create
  `docs/research/stage6-maintenance-secret-delivery.md` and map the existing
  Kolla owner-only file-copy and Barbican contracts to the accepted application
  credential plus per-replica mTLS key lifecycle without changing a recipient
  or creating a secret.

### 2026-07-25 — Maintenance secret-delivery baseline completed

- Completed: Added
  `docs/research/stage6-maintenance-secret-delivery.md`. It maps the existing
  controller-side mode-0600 precheck, per-process Kolla file copy, current
  secret recipients, and disposable Barbican pattern to the accepted
  maintenance identity without changing the role.
- Recommendation: Use one finite restricted application credential and one
  client key/certificate per reconciler replica or approved one-shot comparison
  job. Store credential secret and client key in separate owner-only Barbican
  records; let only the deployment owner retrieve and atomically materialize
  per-host files; never give a runtime process the Barbican controller
  credential.
- Recipient boundary: Only the exact reconciler replica/job receives its
  application-credential ID/secret and client keypair. API retains only the
  signer and maintenance policy identifiers; HAProxy receives only the client
  CA/mapping; edge, registry, bootstrap, and other replicas receive none of the
  maintenance secret material.
- Trust gap: The local API intentionally ignores an HTTP workload header and
  consumes a server-side WSGI value. A private mTLS HAProxy frontend therefore
  also needs a reviewed trusted adapter from verified certificate identity to
  WSGI context. Header injection alone is not acceptable.
- Existing evidence boundary: Current Kolla owner/mode/no-log and the
  disposable RGW Barbican stream are reusable patterns, but they do not prove
  maintenance ACL/consumer, per-replica rotation, mTLS mapping, or residue
  cleanup. `coffer_enable_reconcile` remains false.
- Changed files: Added the research document; updated this plan and
  `.codex/state/HANDOFF.md`. No Kolla variable, recipient, role, user,
  credential, certificate, Barbican object, frontend, endpoint, or remote
  state changed.
- Next exact action requiring approval: Approve or reject a local
  fixture-only Kolla contract milestone that adds maintenance variables,
  generated-placeholder prechecks, exact per-process `config.json` recipients,
  private mTLS frontend rendering, trusted workload adapter, and negative
  contract tests. It will keep reconciliation disabled and create no real
  identity, secret, certificate, Barbican object, or remote deployment.

### 2026-07-25 — Fixture-only Kolla maintenance contract completed

- Authorization: The user directed the long-horizon harness to complete
  appropriately sized local milestones without per-step interruptions. This
  milestone remained inside the previously described fixture boundary: no
  real identity, credential, certificate, Barbican object, endpoint, remote
  deployment, or reconciliation enablement.
- Product integration: Added opt-in maintenance configuration and wired the
  accepted SQL authorities, policy, token broker, resource, and trusted proxy
  adapter into the product application. The adapter always removes the
  incoming workload header and any preexisting private WSGI value, then
  restores one configured workload only for an allowlisted direct HAProxy
  peer. Maintenance remains disabled by default.
- Kolla contract: Added host-addressed per-replica source paths, exact
  owner/mode/regular-file/single-link checks, unique application-credential
  IDs, CA verification, certificate/private-key pairing, and unique
  certificate fingerprints. Generated credential and client-key material is
  copied only to the disabled reconciler fixture.
- Private frontend: Added a separately rendered internal-VIP mTLS frontend
  that requires the exact maintenance client CA, maps an exact SHA-256
  certificate fingerprint to one workload, accepts only the broker POST path,
  and verifies API backend TLS. The ordinary API frontend strips the assertion
  and denies `/v1/internal/`; the public edge denial remains in place.
- Failure boundary: Missing/unsafe maintenance files, invalid client keys,
  reconciliation enablement, untrusted proxy addresses, unknown workloads,
  and caller-prepopulated WSGI context fail closed. No runtime worker token
  provider, real secret delivery, remote HAProxy syntax/run, rotation,
  revocation, or teardown evidence is claimed.
- Verification: Full Python regression passes 310 tests. The focused
  maintenance/config/API matrix passes 115 tests, the pinned local Kolla role
  lifecycle passes 68 checks, compilation and diff checks pass, and generated
  secrets remain absent from retained harness output/state.
- Changed files: Product maintenance configuration/adapter/builder and tests;
  Coffer Kolla defaults, prechecks, config recipients, HAProxy template and
  fixture harness; ADR 0015, secret-delivery research, this plan, and
  `.codex/state/HANDOFF.md`.
- Next exact action: Create
  `poc/maintenance-identity/README.md` defining the abort-safe disposable
  create/rotate/revoke/teardown harness and its exact allowlists without
  creating an identity, secret, certificate, Barbican object, or remote
  resource.

### 2026-07-25 — Disposable maintenance lifecycle contract fixed

- Completed: Added `poc/maintenance-identity/README.md` with immutable-ID
  ownership, exact resource/workload/generation allowlists, finite
  application-credential and access-rule requirements, project-private
  Barbican recipients, per-workload mTLS identity, owner-only state/evidence,
  and noninteractive lifecycle actions.
- Abort and teardown boundary: Every mutation must follow recorded immutable
  IDs, atomic transitions, a single-invocation lock, and reverse-dependency
  cleanup. Prefix/wildcard deletion, lost-state mutation, broader roles,
  in-place rotation, and secret-bearing retained output are refused. Teardown
  closes workers/sessions and mappings before credentials, materializations,
  Barbican consumers/secrets, assignments, user/project, and an owned
  unreferenced role.
- Failure and rotation boundary: The contract requires generation overlap,
  measured cache/token drain, old-generation rejection, Keystone/Barbican/
  HAProxy/API/Distribution failure closure, replica survival, log/residue
  scans, and unchanged unrelated-resource signatures.
- Scope: This milestone created no identity, role, assignment, application
  credential, Barbican secret, certificate, endpoint, mapping, SQL session,
  remote file, or infrastructure resource.
- Changed files: `poc/maintenance-identity/README.md`, this plan, and
  `.codex/state/HANDOFF.md`.
- Next exact action: Add `poc/maintenance-identity/topology.json`,
  `state_machine.py`, and fixture-driven tests. Implement only pure topology,
  state-transition, exact-ownership, cleanup-plan, and redacted-evidence
  validation; do not call OpenStack, Barbican, SSH, Ansible, or Kolla.

### 2026-07-25 — Pure maintenance lifecycle model completed

- Completed: Added a versioned exact topology and a pure Python state machine
  for owner-bound preflight state, complete per-generation resource sets,
  ordered create/verify/overlap/drain/revoke/failure transitions,
  immutable-ID cleanup targeting, reverse-dependency cleanup, explicit
  zero-residue teardown, and allowlisted redacted evidence.
- Fail-closed coverage: The model refuses topology expansion, broader roles or
  access rules, invalid targets/workloads, incomplete or renamed resources,
  duplicate immutable IDs, out-of-order rotation, insufficient cache/token
  drain, name-only or unowned cleanup, reordered teardown, nonzero residue,
  secret-bearing fields, Authorization/Bearer/private-key/JWT patterns, known
  secret values, and state/topology tampering.
- Verification: All 25 lifecycle-model tests pass; full Python regression
  passes 335 tests; the Kolla companion role passes 68 checks; compilation,
  JSON parsing, and diff checks pass.
- Scope: The model contains no network, OpenStack, Barbican, SSH, Ansible, or
  Kolla call and changed no external state.
- Changed files: `poc/maintenance-identity/topology.json`,
  `poc/maintenance-identity/state_machine.py`,
  `tests/test_maintenance_identity_state_machine.py`,
  `poc/maintenance-identity/README.md`, this plan, and `HANDOFF.md`.
- Next exact action: Add a fixture-driven `lifecycle.py` command adapter with
  read-only `preflight` and `status`, atomic mode-0600 state writes,
  nonblocking locks, fixed failure categories, and deterministic dry-run
  cleanup output. It must refuse mutating actions unless a fixture adapter is
  selected and must not contact a remote service.

### 2026-07-25 — Fixture-only lifecycle command boundary completed

- Completed: Added `lifecycle.py` with read-only preflight/status, an exact
  invocation-local store, mode-0700 directory, atomic mode-0600 state,
  nonblocking lock, deterministic hashed cleanup output, and fixed
  secret-safe failure categories. Create, verify, rotate, revoke-old,
  failure-matrix, and teardown actions refuse to run without the exact fixture
  adapter and target signature.
- Lifecycle evidence: The CLI fixture reaches generation-1 verification,
  generation-2 overlap, bounded drain, old-generation revocation, failure
  verification, dependency-ordered teardown, and explicit zero residue.
  Repeated preflight is idempotent; mismatched replay, missing adapter,
  out-of-order action, target mismatch, nonzero residue, concurrent lock,
  unsafe file mode, symlink lock, and invalid secret-bearing fixture all fail
  without changing state or exposing details.
- Decision: Close the plan task that selects and proves the maintenance
  identity and owner-only lifecycle without a real credential. The Stage 6
  done criterion remains open until a fresh pilot supplies real expiring
  identity, Barbican, private-TLS, rotation, revocation, outage, audit, and
  residue evidence.
- Verification: Eleven CLI tests plus 25 model tests pass; full Python
  regression passes 346 tests; compilation, both JSON fixtures, CLI help, and
  diff checks pass.
- Scope: The adapter imports no OpenStack client and performs no network, SSH,
  Ansible, Kolla, Keystone, Barbican, certificate, SQL, VM, or remote-file
  operation.
- Changed files: `poc/maintenance-identity/lifecycle.py`,
  `tests/fixtures/maintenance_identity.json`,
  `tests/test_maintenance_identity_lifecycle_cli.py`,
  `poc/maintenance-identity/README.md`, this plan, and `HANDOFF.md`.
- Next exact action: Inspect and pin the selected Distribution release's
  storage enumerator plus S3/RGW driver construction, then create
  `poc/data-protection/README.md` defining the disposable writer-exclusion,
  SQL/RGW backup, exact-release inventory, import/comparison, cutover,
  rollback, restore, and residue phases without accessing a live registry.

### 2026-07-25 — Data-protection and cutover contract fixed

- Source result: The filesystem PoC constructs `filesystem.New` directly and
  cannot qualify RGW. Distribution v3.1.1 constructs the runtime S3 path from
  `configuration.Parse`, `Storage.Type/Parameters`, blank driver
  registration, `factory.Create`, and `storage.NewRegistry`. Starting
  `handlers.NewApp` would also activate unrelated HTTP, purge, cache, event,
  middleware, and health behavior and is rejected for the helper.
- Completed: Added `poc/data-protection/README.md` with the exact-release
  helper construction/refusal boundary, immutable disposable topology,
  owner-only state, writer exclusion, immediately restored SQL/RGW backups,
  double inventory, import/idempotency, authenticated comparison, admission
  cutover, rollback, recovery, bounded failures, and exact teardown.
- Backup decision: Treat raw S3/RGW object identifiers only as backup
  transport. Repository authority remains the selected Distribution
  enumerators. Accept a backup only after isolated SQL and RGW restore plus
  inventory/client digest verification, never from a zero exit code alone.
- Scope: No registry, RGW, SQL, KMS, identity, credential, certificate,
  endpoint, container, VM, network, volume, object, database, or remote file
  was created, read, modified, or deleted.
- Changed files: `poc/data-protection/README.md`, this plan, and `HANDOFF.md`.
- Next exact action: Refactor the canonical scan/evidence code out of
  `poc/inventory/main.go`, preserve the filesystem result, then add an
  exact-release S3 configuration adapter using `configuration.Parse` and
  `factory.Create` with fixture tests for middleware/proxy/TLS/ambient-
  credential refusal. Do not connect to RGW.

### 2026-07-25 — Exact-release S3 inventory adapter completed locally

- Completed: Refactored the canonical scan to accept one constructed
  Distribution namespace. Filesystem retains its direct read-only driver;
  the new S3 path parses an owner-only config, registers the exact release's
  `s3-aws` driver, calls `factory.Create` and `storage.NewRegistry`, and runs
  the same two scans under one finite context. It never starts the registry
  HTTP application, upload purger, cache, events, health, delete, or GC.
- Fail-closed configuration: Exact release/config digest, mode-0600 regular
  single-link ownership, static distinct credentials, HTTPS endpoint,
  secure/verified TLS, v4/path-style RGW access, non-root prefix, and disabled
  body/request logging are mandatory. `REGISTRY_*`, ambient AWS credentials,
  middleware, proxy, multiple/non-S3 drivers, insecure transport, symlink/
  hardlink, and mismatches are refused before driver construction.
- Verification: Seven Go tests and vet pass under the pinned Go 1.25.3
  toolchain. The host had an ambient Homebrew `GOROOT` for Go 1.26.5; removing
  only that command-local override restored the matching mise toolchain.
  Full Python regression passes 346 tests. The existing filesystem Podman
  fixture still proves equal scans, digest-only enumeration, SQL/storage
  nonmutation, and zero container/volume/network/state residue; the Podman VM
  was returned to stopped.
- Dependency lock: The exact S3 path adds Distribution's pinned AWS SDK,
  JMESPath, and YAML dependencies to the module sums.
- Scope: No RGW, registry, SQL, identity, KMS, certificate, endpoint, remote
  file, or infrastructure resource was contacted or changed.
- Changed files: `poc/inventory/main.go`, `s3_config.go`,
  `s3_config_test.go`, `go.mod`, `go.sum`, `poc/inventory/README.md`,
  `poc/data-protection/README.md`, this plan, and `HANDOFF.md`.
- Next exact action: Add an S3 evidence/provenance schema binding the exact
  Distribution revision, canonical module graph, helper binary, config,
  storage type, endpoint, bucket, and root hashes. Extend
  `coffer-inventory-verify` and `coffer-import-inventory` to preserve and
  validate that provenance while keeping filesystem v1 byte-compatible.

### 2026-07-25 — Provenance-bound helper artifact completed locally

- Completed: Added S3 scan evidence v2 and inventory v2. The helper binds the
  pinned Distribution source revision and hashes of its canonical runtime
  module graph, executable, exact configuration, endpoint, bucket, root, and
  storage type. The verifier rejects missing, extra, malformed, unsupported,
  or unpinned provenance, preserves it in the canonical inventory, and the
  importer validates it before accepting the artifact digest. Filesystem
  scan/inventory v1 remains byte-compatible.
- Image contract: Added a digest-pinned Go 1.25.3 multi-architecture builder
  and scratch runtime containing only the static helper plus CA bundle. It
  runs as `65532:65532` with one helper entry point and no shell, registry
  server, command, listener, or exposed port.
- Verification: Fifty-three focused inventory/import/image Python tests, eight
  Go tests and vet, full 359-test Python regression, compilation, and diff
  checks pass. A local Linux ARM64 image built as
  `bbdf44f30f9435b5ca4ee2c61540d1d388a44f77e6577eb7c8b5b58a29faea64`;
  inspection proved architecture, non-root UID, exact entry point, and
  no-network CLI help. The exact image was deleted and Podman returned to
  stopped with no tagged helper image or container.
- Boundary: This is local packaging/provenance evidence, not a signed image,
  x86_64 qualification, RGW execution, released dependency promotion, backup,
  cutover, or production authorization.
- Changed files: Inventory Go provenance and tests; Python verifier/importer
  v2 validation and tests; `poc/inventory/Containerfile` and its contract
  tests; inventory/data-protection/runbook/ADR documents; this plan and
  `HANDOFF.md`.
- Next exact action: Add `poc/data-protection/topology.json`,
  `state_machine.py`, and fixture-driven tests for exact phase ordering,
  immutable ownership, writer-fence evidence, backup/restore manifests,
  cutover/rollback transitions, fixed failures, cleanup planning, and
  secret-safe evidence. Do not call an external service.

### 2026-07-25 — Data-protection rehearsal state model completed locally

- Completed: Added the versioned disposable topology and pure state machine
  for preflight, immutable resource registration, fixture creation, writer
  exclusion, restored SQL/RGW backup, equal exact-release inventory scans,
  transactional import, authenticated comparison, admission cutover,
  rollback, restore, the fixed failure matrix, and teardown.
- Integrity boundary: The model binds every phase to an exact evidence-key set
  and canonical monotonic history. The cutover marker commits to the writer
  fence, backup, inventory provenance, import database, maintenance session,
  workload, routing, and cutover database. Rollback requires an exact manifest
  and equal created/removed post-cutover write counts.
- Cleanup boundary: Every resource requires a complete allowlisted name,
  kind, and immutable ID. Cleanup is dependency ordered, mutation targets
  must match the retained immutable tuple, unrelated resources must keep the
  same signature, and all 16 fixed residue categories must be explicit
  zeroes before terminal state.
- Fail-closed coverage: Tests refuse topology expansion/reordering,
  incomplete, renamed, or duplicate resources, phase skips, open writer
  paths, unstable source signatures, unrestored or divergent backups,
  multipart residue, unequal scans, import/live/cutover/rollback/restore
  gaps, partial cleanup/residue reports, tampered evidence/history, and
  secret fields or patterns.
- Verification: Twenty-seven focused state-model tests, all 386 Python tests,
  and all 68 Kolla companion-role checks pass. Compilation, topology JSON
  parsing, diff checks, and Gitleaks pass.
- Scope: The implementation imports no service client and performs no
  network, SSH, Ansible, Kolla, OpenStack, RGW, SQL, KMS, registry, identity,
  certificate, VM, or remote-file operation.
- Changed files: `poc/data-protection/topology.json`,
  `poc/data-protection/state_machine.py`,
  `tests/test_data_protection_state_machine.py`,
  `poc/data-protection/README.md`, this plan, and `HANDOFF.md`.
- Next exact action: Add fixture-only
  `poc/data-protection/lifecycle.py`,
  `tests/fixtures/data_protection.json`, and CLI tests for read-only
  preflight/status, atomic mode-0600 state, nonblocking locks, exact
  target/adapter gates, every ordered phase, deterministic cleanup, fixed
  failures, and idempotent zero-residue teardown. Do not contact a remote
  service.

### 2026-07-25 — Fixture-only data-protection lifecycle completed locally

- Completed: Added a command adapter that replays every ordered
  data-protection phase through the pure state model. Read-only
  preflight/status/cleanup planning cannot select an adapter; every mutation
  requires the exact fixture, target signature, unrelated signature, and
  topology.
- State safety: The invocation directory is owner mode 0700. State and lock
  are regular single-link owner mode 0600; state replacement is atomic and
  fsynced under a nonblocking lock. Existing unsafe directories/files/links
  are refused rather than remediated.
- Lifecycle result: The fixture reaches all 14 phases, exposes cleanup targets
  only as name/kind plus immutable-ID hashes, proves all fixed residue
  categories zero, retains a secret-safe terminal summary, and repeats
  teardown idempotently.
- Failure coverage: Missing/wrong adapters, target or unrelated-signature
  drift, reordered actions, evidence drift, incomplete failure/residue sets,
  concurrent locks, unsafe modes, symlink locks, and secret-bearing malformed
  fixtures fail with one fixed category and leave the last accepted state
  unchanged.
- Verification: Twelve lifecycle CLI tests plus 27 state-model tests pass;
  all 398 Python tests pass. Compilation, fixture JSON parsing, CLI help, and
  diff checks pass.
- Scope: No OpenStack client or remote adapter is imported; no network, SSH,
  Ansible, Kolla, registry, RGW, SQL, KMS, identity, certificate, VM, or
  remote-file operation occurs.
- Changed files: `poc/data-protection/lifecycle.py`,
  `tests/fixtures/data_protection.json`,
  `tests/test_data_protection_lifecycle_cli.py`,
  `poc/data-protection/README.md`, this plan, and `HANDOFF.md`.
- Next exact action: Add a canonical secret-safe SQL/RGW backup manifest
  verifier and fixture tests. It must bind backup provenance, versioned object
  identifiers, pagination, checksums/metadata/encryption disposition,
  multipart absence, and isolated restore comparisons without reading a live
  database, bucket, KMS key, or registry.

### 2026-07-25 — Canonical SQL/RGW backup verifier completed locally

- Completed: Added a versioned secret-safe backup bundle and verifier. Exact
  invocation/target/topology provenance, SQL tool/server/schema/recovery
  coordinates, backup artifact and logical content, and isolated SQL restore
  must agree before evidence is accepted.
- RGW coverage: Complete version pagination, canonical key/version hash order,
  unique version identities, zero- and positive-size SSE-KMS objects, delete
  markers, checksum/ETag/metadata/KMS hashes, zero multipart uploads, and an
  isolated restore with equal inventory, metadata, counts, bytes, and client
  pull digests are mandatory.
- Lifecycle integration: `verify-backups` no longer trusts fixture-provided
  phase booleans or hashes. It runs the canonical verifier, binds the emitted
  provenance and artifact hashes into state, and refuses an invalid bundle
  without changing the last accepted phase.
- File boundary: The CLI reads only an owner mode-0600 regular single-link
  manifest and atomically writes only into a pre-existing owner mode-0700
  directory. It does not create or remediate an unsafe output path and emits
  only fixed secret-safe failures.
- Verification: Twenty-nine backup-verifier, 13 lifecycle, and 27 state-model
  tests pass together (69 focused); all 428 Python tests pass. Compilation,
  both JSON artifacts, both CLIs, and diff checks pass.
- Scope: The verifier and fixture adapter perform no SQL, S3/RGW, KMS,
  registry, network, subprocess, SSH, Ansible, Kolla, VM, identity, or
  remote-file operation.
- Changed files: `poc/data-protection/backup_manifest.py`,
  lifecycle/state integration, the complete backup fixture, backup/lifecycle/
  state tests, `poc/data-protection/README.md`, this plan, and `HANDOFF.md`.
- Next exact action: Add a no-network `backup_adapter.py` seam with fake
  MariaDB and versioned-S3 clients. It must build the exact verified bundle
  from typed observations, keep credentials outside arguments/results, prove
  phase order and pagination, and refuse any real adapter or external call.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 5 atomic boundary | `git status --short --branch`; `git log -8 --oneline` | passed; clean at `610b576`, ahead of origin by 126 |
| Distribution release state | Official GitHub latest-release API and signed release page | passed; v3.1.1 remains latest stable |
| Ceph stable release state | Official Tentacle release notes and GitHub tags | passed; v20.2.2 remains latest stable |
| Ceph fix disposition | Official PR 69277 metadata and protected `tentacle` source | passed; merged on 2026-07-22, not released |
| Plan/HANDOFF structure | Markdown inspection and local-link check | passed |
| Upstream classifier fixtures | `uv run pytest -q tests/test_upstream_readiness.py` | passed; 10 |
| Live upstream classifier | `make -C poc/production-images check-upstream` | passed; valid `blocked` result |
| Full Python regression | `uv run pytest -q` | passed; 310 |
| Kolla companion-role regression | `make -C poc/kolla-ansible-role verify` | passed; 68 |
| Maintenance identity code/config inventory | Focused inspection of live comparison, reconciliation runner/probe, WSGI, Kolla config, secrets, and Stage 5 inputs | passed |
| Maintenance identity primary sources | Current Keystone, keystonemiddleware, Barbican, and Distribution specifications | passed |
| ADR 0015 contract consistency | Focused comparison with ADRs 0008, 0013, 0014 and the Stage 6 identity research | passed; proposed pending local proof |
| Maintenance token/API/edge focused regression | `uv run pytest -q tests/test_maintenance_api.py tests/test_maintenance_token.py tests/test_registry_proxy.py tests/test_tokens.py tests/test_quota_reconciliation.py` | passed; 85 |
| Python compilation and diff checks | `uv run python -m compileall -q src tests`; `git diff --check` | passed |
| Maintenance session/migration/import/live focused regression | `uv run pytest -q tests/test_maintenance_sessions.py tests/test_migrations.py tests/test_bootstrap.py tests/test_maintenance_token.py tests/test_maintenance_api.py tests/test_quota_import.py tests/test_quota_import_verification.py tests/test_live_inventory_verification.py` | passed; 105 |
| Maintenance secret-delivery inventory | Focused inspection of Kolla defaults, prechecks, per-process config, `kolla_start` file recipients, HAProxy model, ADRs 0014/0015, and disposable Barbican evidence | passed; design only, no recipient changed |
| Maintenance proxy/Kolla fixture focused regression | `uv run pytest -q tests/test_maintenance_api.py tests/test_maintenance_token.py tests/test_config_validator.py tests/test_api_runner.py tests/test_registry_proxy.py tests/test_tokens.py tests/test_quota_reconciliation.py tests/test_maintenance_sessions.py`; pinned role harness | passed; 115 tests and 68 role checks |
| Maintenance lifecycle model | `uv run pytest -q tests/test_maintenance_identity_state_machine.py` | passed; 25 |
| Full regression after lifecycle model | `uv run pytest -q` | passed; 335 |
| Maintenance lifecycle CLI | `uv run pytest -q tests/test_maintenance_identity_lifecycle_cli.py` | passed; 11 |
| Full regression after lifecycle CLI | `uv run pytest -q` | passed; 346 |
| Exact-release S3 config adapter | `env -u GOROOT "$(mise which go)" test ./...`; `vet ./...` in `poc/inventory` | passed; 7 tests |
| Filesystem inventory compatibility | persistent-PTY `make -C poc/inventory verify` | passed; equal scans, immutable SQL/storage, zero residue |
| S3 provenance verifier/importer | `uv run pytest -q tests/test_inventory.py tests/test_quota_import.py tests/test_inventory_helper_container.py` | passed; 53 |
| Provenance helper Go regression | pinned Go 1.25.3 `test ./...`; `vet ./...` | passed; 8 tests |
| Static helper image contract | ARM64 Podman build, inspect, no-network `--help`, exact image removal | passed; non-root scratch image, zero tagged image/container residue |
| Full regression after provenance helper | `uv run pytest -q` | passed; 359 |
| Data-protection state model | `uv run pytest -q tests/test_data_protection_state_machine.py` | passed; 27 |
| Full regression after data-protection state model | `uv run pytest -q` | passed; 386 |
| Kolla role after data-protection state model | `make -C poc/kolla-ansible-role verify` | passed; 68 |
| Fixture-only data-protection lifecycle | `uv run pytest -q tests/test_data_protection_lifecycle_cli.py tests/test_data_protection_state_machine.py` | passed; 39 |
| Full regression after data-protection lifecycle | `uv run pytest -q` | passed; 398 |
| Canonical backup bundle and lifecycle integration | `uv run pytest -q tests/test_data_protection_backup_manifest.py tests/test_data_protection_lifecycle_cli.py tests/test_data_protection_state_machine.py` | passed; 69 |
| Full regression after canonical backup verifier | `uv run pytest -q` | passed; 428 |

## Failures, Blockers, and Risks

- Distribution v3.1.1 remains the latest signed stable release and fails ADR
  0006. Stage 6 can progress independent contracts but cannot produce a final
  production candidate until a release or reviewable VEX closes this gate.
- Ceph's encrypted-copy fix is merged but unreleased. Branch execution may be
  useful only as explicitly labelled anticipatory evidence; it cannot satisfy
  the stable-release gate.
- The maintenance architecture, broker, trusted adapter, and generated Kolla
  recipient/frontend fixture are locally proven. Creating or delivering a real
  identity, credential, certificate, endpoint, or remote Kolla secret remains
  separately gated. Destructive GC also remains unapproved.
- The local branch remains ahead of `origin/main`. This is not a technical
  blocker, but remote publication remains a separately authorized action and
  must use the `jaehanbyun` GitHub account.

## Handoff

- Current state: Stage 5 is complete and committed. Stage 6 has deterministic
  upstream release gates plus an accepted local maintenance broker/session
  design. The opt-in generated Kolla recipient/private-frontend fixture and
  trusted workload adapter and fixture-only lifecycle are complete; defaults
  and reconciliation remain disabled. The provenance-bound S3 inventory helper
  plus the pure state model and fixture-only data-protection lifecycle are
  complete. The canonical restored SQL/RGW backup verifier now gates the
  lifecycle. Real lifecycle evidence and current stable dependencies remain
  blocked; no real identity, credential, certificate, endpoint, or remote state
  changed.
- Exact next action: Add a no-network backup adapter seam with fake MariaDB and
  versioned-S3 clients that builds the exact verified bundle without accepting
  credentials or invoking an external service.
- Questions requiring user input: None for the next fixture-only lifecycle
  milestone. The user has already authorized atomic milestone publication and
  the bounded disposable Stage 6 sequence; exact safety and release gates
  remain fail closed.
