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
- [x] Coordinated write-stopped Distribution garbage collection passes dry-run
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
| Use direct per-replica scrapes and one API/edge worker per container as the Stage 6 observability candidate | Current process-local collectors plus VIP scraping are incomplete; multiple HA replicas and gthread concurrency provide a simpler initial scale boundary whose resets have normal Prometheus semantics | VIP/public-FQDN scrape; unproven Python multiprocess mode; Pushgateway; parsing logs as the sole SLI source | 2026-07-25 |
| Use upstream stop-the-world GC without `--delete-untagged`, and separate Distribution logical reclamation from RGW physical-version cleanup | Digest-only manifests are valid content; the pinned collector is the reachability authority; S3 versioning means a sweep need not reclaim physical bytes immediately | Coffer reachability implementation; global untagged deletion; online GC; automatic RGW orphan/lifecycle deletion | 2026-07-25 |

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
- [x] Implement restart-correct metrics, protected scrape/aggregation, alerts,
      operational dashboards, and failure-budget documentation.
- [x] Implement and execute the approved coordinated GC/retention fixture and
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

### 2026-07-25 — No-network backup adapter seam completed locally

- Completed: Added typed MariaDB and versioned-S3 backup client seams plus
  exact fixture implementations. The builder reconstructs the canonical
  bundle from observations rather than trusting the checked-in bundle as
  phase evidence.
- Order and completeness: SQL source inspection must precede backup and
  isolated restore. S3 source inspection must precede bounded nonempty
  version pages, exact version-set copy, and isolated restore. Repeated
  cursors, page-bound exhaustion, empty pages, copy-set drift, observation
  drift, and restore mismatch are refused.
- Real-client gate: The builder checks the exact fixture client types, not
  merely a claimed adapter name. No future real client can enter this path
  without a deliberate code and target-contract change.
- Lifecycle integration: `verify-backups` now invokes the ordered adapter,
  canonical verifier, and state transition in that order. Invalid bundle or
  adapter evidence leaves the last accepted state unchanged.
- Secret/network boundary: Public adapter parameters and results contain no
  credential fields. Static inspection proves no boto, HTTP, socket, SQL, or
  subprocess runtime import in this milestone.
- Verification: Eleven adapter tests plus the 29 backup, 13 lifecycle, and 27
  state-model tests pass together (80 focused); all 439 Python tests pass.
  Compilation, fixture JSON, and diff checks pass.
- Scope: No database, S3/RGW, KMS, registry, network, subprocess, SSH,
  Ansible, Kolla, VM, identity, certificate, or remote-file operation occurs.
- Deferral: A live backup adapter and disposable data rehearsal remain gated
  on an explicit target contract and the fresh isolated convergence pilot.
  The fixture boundary is sufficient to proceed with independent Stage 6
  observability work without recreating the six-VM lab.
- Changed files: `poc/data-protection/backup_adapter.py`, lifecycle
  integration, adapter tests, `poc/data-protection/README.md`, this plan, and
  `HANDOFF.md`.
- Next exact action: Inspect current API, edge, registry, reconciler,
  database, RGW/KMS, and HAProxy metrics/logging contracts, then create
  `docs/research/stage6-observability.md` defining restart-correct ownership,
  bounded labels, protected collection, alerts, dashboards, and an initial
  SLO/failure budget. Do not contact a remote service.

### 2026-07-25 — Restart-correct observability contract fixed

- Current-state result: API owns an optional private process-local collector
  but defaults to multiple Gunicorn workers; edge has no operational
  application; reconciler counters have no endpoint; Prometheus targets one
  API FQDN/VIP; Distribution metrics are disabled; and there are no Coffer
  rules, alerts, dashboards, or failure-budget documents.
- Candidate decision: Start with one API/edge worker per container, retain
  thread concurrency, scale with HA replicas, and scrape every replica
  directly over verified backend TLS. A worker count above one fails the
  production metrics precheck until another aggregation ADR is accepted.
- Dependency ownership: Use Distribution's private metrics-only debug
  listener, Kolla's native HAProxy and MariaDB surfaces, and the external Ceph
  mgr Prometheus endpoint. Coffer/Kolla does not provision Ceph. Barbican
  HTTP health and the RGW KMS functional signal remain distinct.
- Completed contract: Added
  `docs/research/stage6-observability.md` with restart/stale-series semantics,
  protected target topology, fixed labels and metric families, reconciler
  freshness gauges, structured log/leak rules, initial 30-day SLO budgets,
  alerts, dashboard rows, Kolla changes, pilot acceptance, and ADR 0016
  candidates.
- Primary-source check: Prometheus Python multiprocess mode requires an
  externally initialized/wiped directory and has collector/Gauge/exemplar
  limitations. Current Kolla uses native HAProxy Prometheus support and
  supports protected Prometheus, while Distribution warns its debug endpoint
  must remain private. Ceph mgr owns cluster metric aggregation.
- Scope: Read-only source/config and official-document inspection only. No
  config, metric endpoint, Prometheus, Grafana, HAProxy, Ceph, registry,
  container, network, or remote state changed.
- Changed files: `docs/research/stage6-observability.md`, this plan, and
  `HANDOFF.md`.
- Next exact action: Add proposed ADR 0016 and a pure observability contract
  model with tests for exact component/route/method/status/result/dependency
  labels, per-replica target generation, one-worker enforcement,
  public-path denial, recording/alert/dashboard references, restart/stale
  transitions, and secret-safe evidence. Do not contact a remote service.

### 2026-07-25 — Direct-replica observability architecture accepted locally

- Completed: Accepted ADR 0016 after adding a versioned topology and pure
  local contract. The topology fixes API, edge, reconciler, and Distribution
  scrape ownership, private ports and paths, one worker per Coffer process,
  bounded application/result labels, public operational-path denials, six
  recording rules, eight alerts, eight dashboard rows, a 30-second scrape
  interval, and a 90-second stale bound.
- Target and restart safety: Inventory must contain every component and at
  least one unique backend address. Every target uses verified TLS, matches
  the fixed worker count, and cannot equal an operator-supplied VIP/public
  address. A counter decrease is accepted only with a newer process-start
  timestamp; stale series become explicit after the fixed bound.
- Secret/cardinality safety: Retained targets/state/evidence reject
  credential, tenant, repository, digest, and secret fields or patterns.
  Durable acceptance evidence contains only topology, target-set, and restart
  state hashes plus bounded counts.
- Verification: Fifty-one focused observability tests pass. Full Python
  regression passes 490 tests; the Kolla companion role passes 68 checks;
  compilation, topology JSON parsing, and diff checks pass.
- Leak-check note: A directory-wide scan after the role harness also traversed
  its generated `work/kolla-ansible-stage3` dependency/fixture tree and
  reported non-source findings. The atomic commit gate therefore scans only
  the staged source set; the generated work tree is not accepted evidence.
- Scope: No runtime metric endpoint, Kolla target, Prometheus rule, Grafana
  dashboard, HAProxy listener, Distribution debug port, Ceph target, network,
  container, or remote state changed.
- Changed files: ADR 0016, `poc/observability/topology.json`,
  `poc/observability/contract.py`, observability contract tests, research,
  this plan, and `HANDOFF.md`.
- Next exact action: Begin runtime observability in
  `src/coffer/observability.py`. Make the application metric schema explicit
  and bounded, add process-start/restart evidence, instrument the API and
  edge without exposing tenant/repository values, and keep the production
  one-worker rule fail closed. Do not change Kolla or contact a remote service
  in that atomic milestone.

### 2026-07-25 — Bounded runtime metric core completed locally

- Completed: `CofferMetrics` now binds each collector to exactly `api`,
  `edge`, or `reconcile`; exports a component/version process-start timestamp;
  and validates every HTTP route, method, status class, token result,
  readiness result, reconciliation result, duration, component, and version
  before touching a series.
- API and edge: API route templates remain bounded and now use component
  `api` rather than the provisional `control` label. The WSGI edge wrapper
  reduces every resource-bearing path to `edge-auth`, `edge-manifest`,
  `edge-upload`, `edge-blob`, or `edge-other`; raw tenant, repository,
  digest, reference, and upload identifiers never enter its metrics.
- Process boundary: API and edge startup reject a metrics-enabled
  configuration unless Gunicorn workers equal one. The check happens before
  application construction and logs only the fixed invalid-configuration
  result. A Gunicorn post-fork hook refreshes the process-start gauge inside
  the actual worker, so worker replacement cannot pair reset counters with a
  stale master timestamp. Reconciliation identifies its own process
  component.
- Compatibility: Runtime allowlists are cross-checked against the checked-in
  topology so an implementation/ADR drift fails the test suite.
- Verification: The observability/API/edge/token/reconciliation/proxy focused
  matrix passes 141 tests; full Python regression passes 507 tests.
  Compilation and diff checks pass.
- Scope: No Kolla variable/template, scrape endpoint, Prometheus target/rule,
  Grafana dashboard, HAProxy ACL, Distribution listener, network, container,
  or remote state changed.
- Changed files: Runtime observability, API/edge/reconciliation runners,
  product WSGI wiring, focused tests, ADR/research, this plan, and
  `HANDOFF.md`.
- Next exact action: Add bounded quota-admission outcome and duration
  instrumentation in `src/coffer/quota_admission.py`, pass the edge collector
  from `src/coffer/edge_runner.py`, and prove accepted, over-quota,
  missing-quota, invalid-manifest, unauthorized, upstream-unavailable, and
  internal-error paths without retaining a repository or token. Do not change
  Kolla or contact a remote service in that atomic milestone.

### 2026-07-25 — Quota-admission metrics completed locally

- Completed: Added one bounded admission counter and duration histogram to the
  edge collector. The manifest application now records exactly `accepted`,
  `over_quota`, `missing_quota`, `invalid_manifest`, `unauthorized`,
  `upstream_unavailable`, or `internal_error`.
- Failure separation: A missing configured quota is distinct from a database
  error; registry metadata/write exceptions and upstream 5xx are upstream
  failures; SQL reserve/commit/release/reconciliation errors are internal;
  normal status-derived client and policy outcomes remain fixed.
- Collector ownership: The edge runner constructs one collector and passes the
  same object to admission middleware and outer WSGI request instrumentation,
  preventing split registries inside one process.
- Secret/cardinality result: Tests exercise a real issued JWT and concrete
  project/repository path but retain none of those values, failure exception
  text, or request tokens in Prometheus output.
- Verification: The quota/observability/edge/proxy focused matrix passes 112
  tests; full Python regression passes 515 tests. Compilation and diff checks
  pass.
- Scope: No endpoint, Kolla variable/template, Prometheus target/rule,
  Grafana dashboard, HAProxy ACL, Distribution listener, network, container,
  or remote state changed.
- Changed files: `src/coffer/observability.py`,
  `src/coffer/quota_admission.py`, `src/coffer/edge_runner.py`, focused tests,
  ADR/research, this plan, and `HANDOFF.md`.
- Next exact action: Implement a metrics-enabled edge operational dispatcher
  and the matching Kolla fail-closed boundary together. Direct backend
  `/metrics` must work with one worker, both edge HAProxy frontends must deny
  all operational/debug paths, and the Prometheus fragment must enumerate
  every API/edge backend address instead of a VIP. Do not deploy remotely.

### 2026-07-25 — Direct API/edge scrape boundary completed locally

- Runtime: A metrics-enabled edge now dispatches direct-backend `/healthz`,
  SQL `/readyz`, and `/metrics` to the same collector used by its outer HTTP
  and quota-admission instrumentation. With metrics disabled, the public edge
  proxy continues to return its fixed 404 for every operational path.
- Kolla precheck: Metrics require enabled Prometheus, verified backend TLS,
  exactly one API and edge worker, a nonempty CA path and TLS server name, and
  direct API-interface targets unequal to both Kolla VIPs. Four negative role
  cases prove those failures occur before deployment.
- Routing: The ordinary API frontend denies internal, health, readiness,
  metrics, and debug paths. The edge internal frontend plus its internal and
  shared-external mapped backends deny health, readiness, metrics, and debug
  paths. Direct backend scrapes bypass HAProxy deliberately; tenant paths do
  not.
- Discovery: The Prometheus fragment has separate `coffer-api` and
  `coffer-edge` jobs. It enumerates each inventory host address, labels only
  stable service/instance values, verifies the operator CA and fixed TLS
  server name, and contains no internal/external VIP or service FQDN target.
- Verification: Edge/observability/admission/proxy focused regression passes
  60 tests; full Python regression passes 515 tests; the complete Kolla role
  lifecycle passes 78 checks, including negative prechecks, deploy,
  idempotent reconfigure/pull/stop, upgrade, config validation, secret-safety,
  rendered Prometheus/HAProxy inspection, and zero harness residue.
- Scope: Local code, templates, and fixture-only Ansible execution only. No
  Prometheus/HAProxy/container was changed remotely and no live scrape was
  attempted.
- Changed files: edge runtime/tests; Kolla defaults, prechecks, service
  config, Prometheus template, fixture, and verifier; ADR/research, this plan,
  and `HANDOFF.md`.
- Next exact action: Add a private metrics-only Distribution debug listener
  and a periodic reconciler management application to the local runtime/Kolla
  contract. Prometheus must target each registry/reconciler backend directly,
  profiling must remain disabled, one-shot reconciliation must not expose a
  persistent series, and every public/ordinary service route must deny the
  management paths. Do not deploy remotely.

### 2026-07-25 — Distribution metrics isolation completed locally

- Source finding: Distribution v3.1.1's debug configuration has only an
  address and Prometheus options. Its registry starts that address with Go's
  default HTTP mux, and the registry binary imports `net/http/pprof`.
  Therefore the upstream listener is not metrics-only.
- Runtime boundary: Added `coffer-registry-metrics`, a one-worker verified-TLS
  allowlist proxy. It accepts one exact loopback HTTP `/metrics` upstream,
  exposes only `/healthz` and `/metrics`, forwards no request headers, bounds
  the response to 16 MiB, returns fixed 503 failures, and returns 404 for
  query, pprof, debug, and unknown paths.
- Kolla boundary: Distribution binds the debug mux only to `127.0.0.1`; the
  sidecar shares the registry host, has no HAProxy route, and Prometheus
  directly enumerates every registry backend. Prechecks require one sidecar
  worker, distinct bounded service/debug ports, verified TLS, and non-VIP
  targets.
- Secret boundary: A dedicated mode-0600 configuration omits the database
  section. The sidecar receives only that config and backend listener
  certificate/key; it receives no database, Keystone, RGW, Distribution HTTP,
  signing, JWKS, or maintenance secret.
- Verification: Twenty focused proxy/config-validator tests and all 525
  Python tests, lock, compilation, and diff checks pass. The complete Kolla companion-role
  lifecycle passes 85 checks, including negative worker/port prechecks,
  config validation, direct discovery, secret-recipient inspection,
  reconfigure/pull/upgrade/stop idempotency, and zero fixture residue.
- Scope: Local code, templates, and fixture-only Ansible execution only. No
  remote listener, Prometheus, container, network, or service changed.
- Next exact action: Add the periodic reconciler management listener beginning
  in `src/coffer/reconciliation_runner.py`. It must own restart-correct cycle
  and SQL-derived freshness metrics in the periodic process, expose only
  verified-TLS `/healthz` and `/metrics`, stay absent in one-shot mode, and
  integrate direct per-host Kolla discovery without an HAProxy route.

### 2026-07-25 — Periodic reconciler management metrics completed locally

- Runtime: The serial periodic process now owns cycle result/duration,
  last-success/scanned, and SQL-derived backlog, active/expired claim, oldest
  eligible age, and bounded database dependency metrics. Metrics never
  participate in SQL claim/fencing correctness.
- Exposure: Periodic mode requires a TLS certificate/key and starts a small
  management server in the same process. Only exact GET `/healthz` and
  `/metrics` are accepted; query/debug/pprof paths return fixed 404 responses.
  One-shot mode never constructs the listener.
- Failure semantics: Cycle exceptions increment only
  `dependency_unavailable`; SQL snapshot failure sets the bounded database-up
  gauge to zero. Exception text, worker/project/repository/digest/claim, and
  credential values do not enter metrics or management responses.
- Kolla contract: The future enabled reconciler binds its management listener
  to the direct API-interface address and receives only its existing
  maintenance inputs plus the backend listener certificate/key. The service
  has no HAProxy route. Prometheus emits a per-host reconciler job only when
  the reconciler is enabled; the current fail-closed profile emits no phantom
  target.
- Verification: The focused observability/quota/runner/config matrix passes
  73 tests, including a real verified-TLS listener, and all 536 Python tests
  pass. The complete Kolla
  lifecycle passes 88 checks, including listener rendering, owner-only key
  delivery, disabled target refusal, lifecycle idempotency, and zero fixture
  residue. Compilation, syntax, and diff checks pass.
- Scope: Local runtime, SQL read model, templates, and fixture-only Ansible
  execution. The reconciler remains disabled; no remote listener, credential,
  Prometheus target, container, network, or service changed.
- Next exact action: Add versioned Prometheus recording/alert rules and a
  Grafana operator dashboard under the companion role. Validate rule/query
  references, fixed labels/annotations, enable/disable cleanup, and
  idempotency without contacting a remote service.

### 2026-07-25 — Operator rules, alerts, dashboard, and runbook completed locally

- Artifacts: Added six fixed Prometheus recording rules, eight bounded alerts,
  the `Coffer Operator` Grafana dashboard with the exact eight topology rows,
  and one runbook section per alert. The dashboard references every recording
  rule and exposes no tenant, repository, digest, credential, or content
  variable.
- Kolla lifecycle: Metrics now require Prometheus, Alertmanager, and Grafana.
  The role installs the exact mode-0640 controller rule/dashboard files and
  reconfigures Prometheus and Grafana on both enable and disable transitions.
  Disabling metrics removes the Coffer scrape fragment, rule file, dashboard,
  and registry metrics sidecar; repeated disable is idempotent and re-enable
  restores the exact contract.
- Failure and correction: The first lifecycle run proved that generic
  enabled-service filtering did not remove an already-running disabled
  registry metrics sidecar. The role now performs an exact
  `stop_and_remove_container` for that disabled Coffer-owned sidecar. The
  complete rerun passed.
- Verification: `promtool` accepts all 14 rules. Ninety-nine focused
  observability/runtime tests pass; all 541 Python tests pass; and the pinned
  Kolla lifecycle passes 96 checks including three monitoring prechecks,
  rendered artifact/schema/permission inspection, enable/disable/re-enable
  transitions, idempotency, secret-safe output, and zero fixture residue.
- Scope: Local code, controller templates, static dashboard/runbook, and the
  fixture-only Kolla harness only. No remote Prometheus, Grafana, Alertmanager,
  container, network, or service changed.
- Next exact action: Create `docs/research/stage6-gc-retention.md` and inspect
  the accepted Distribution, SQL ledger, RGW versioning/SSE-KMS, inventory,
  backup, and Referrers boundaries. Fix an exact dry-run-first coordinated GC
  topology and restore gate before implementing any mutation adapter.

### 2026-07-25 — Coordinated GC and retention boundary researched

- Source findings: The pinned Distribution collector recursively marks
  manifests/references and sweeps through the configured driver, requires
  read-only/stopped writers, and emits human rather than versioned JSON
  candidate output. The current Kolla role enables delete/upload purging but
  has no cluster-wide fence, read-only transition, one-shot collector,
  candidate authority, or restore gate.
- Decision: Keep the upstream collector as reachability authority and normalize
  only exact-release bounded output. Forbid `--delete-untagged` because
  digest-only manifests are valid Coffer content and no accepted global
  retention resource exists. Apply only an explicit authorized digest delete.
- Data boundary: Treat current-visible Distribution reclamation, complete S3
  object versions/delete markers, and Ceph physical bytes as separate evidence.
  RGW lifecycle, internal GC, and experimental orphan tooling remain separately
  owned and cannot authorize or substitute for Distribution GC.
- Safety: Require every ingress/direct backend and background mutator fenced,
  complete restorable SQL/versioned-RGW backup, two equal dry runs, immutable
  finite authorization, shared/index/digest-only/referrer survivor proof,
  isolated restore, fixed failure injection, and exact zero-residue teardown.
- Scope: Research and checked-in design only. No manifest, object, SQL row,
  registry configuration, container, credential, network, or remote resource
  changed.
- Next exact action: Add proposed ADR 0017 plus
  `poc/gc-retention/topology.json` and a pure state machine. Prove phase order,
  immutable ownership, writer fence, two equal candidate sets, single-use
  authorization, survivor/reclaim/restore evidence, fixed failures, secret
  safety, and zero residue without a registry, S3, SQL, subprocess, or network.

### 2026-07-25 — Coordinated GC pure state contract completed

- Architecture: Added proposed ADR 0017. It keeps the exact upstream collector
  as reachability authority; forbids global untagged deletion and online GC;
  separates Distribution logical reclamation from RGW versions/lifecycle/
  orphan cleanup; and requires a restorable disposable maintenance transaction.
- Topology: Added the exact v3.1.1 revision, sixteen ordered phases, eleven
  invocation-owned resources, reverse cleanup, thirteen residue categories,
  nine survivor classes, thirty fixed failures, two dry runs, a bounded
  candidate set, and a finite authorization lifetime.
- State model: Immutable ownership, explicit logical deletion, compound
  two-replica writer fencing, complete backup/baseline, equal candidate sets,
  current binding, single-use expiry, survivor/SQL safety, logical-versus-
  physical deltas, isolated KMS restore, failure outcomes, tamper-evident
  history, secret-safe public evidence, and zero residue fail closed.
- Verification: Forty-six focused pure tests and all 587 Python tests pass.
  Compilation, topology JSON, static no-network/import inspection, and diff
  checks pass.
- Scope: Pure local data structures only. No registry, S3, SQL, KMS,
  subprocess, container, network, credential, or remote resource was used.
  ADR 0017 remains proposed.
- Next exact action: Add fixture-only `poc/gc-retention/lifecycle.py` and a
  fake adapter. Use owner-only atomic state/evidence, a nonblocking lock,
  exact phase replay, bounded failure injection, single-use collection,
  idempotent teardown, and zero residue. Refuse every non-fixture adapter and
  do not invoke the Distribution binary yet.

### 2026-07-25 — Fixture-only coordinated GC lifecycle completed

- CLI/store: Added preflight/status/cleanup-plan plus every ordered mutating
  action. State is stored below one exact invocation in mode-0700 directories
  and mode-0600 atomic files under a nonblocking, no-follow, single-link lock.
- Adapter boundary: Only the literal `fixture` adapter exists. Its versioned
  input pins the exact Distribution revision, fixed refused failures, and zero
  residue. Read-only actions reject fixture arguments; mutation without the
  explicit adapter fails closed.
- Lifecycle: Deterministic fake evidence traverses explicit delete, fence,
  backup, baseline, two dry runs, finite authorization, single collection,
  survivors, separated reclaim, restore, failures, and teardown. Out-of-order
  actions, pin/residue drift, unsafe paths/modes/links, concurrent locks,
  tampered history, and secret-bearing fixture failures preserve prior state.
- Verification: Sixty combined GC model/CLI tests and all 601 Python tests
  pass. Compilation, CLI help, both JSON fixtures/topology, static no-network/
  SQL/S3/subprocess inspection, and diff checks pass.
- Scope: No registry binary, storage, SQL, KMS, subprocess, container, network,
  credential, or remote resource was used. ADR 0017 remains proposed.
- Next exact action: Add `poc/gc-retention/collector_output.py` with captured
  exact-v3.1.1 dry-run fixtures. Normalize only bounded repository/summary/
  candidate lines into sorted hashed sets and aggregate counts; reject unknown,
  malformed, duplicate, mixed-version, secret-like, retained-intersecting, or
  over-limit output without invoking the collector.

### 2026-07-25 — Exact-release GC dry-run output contract completed

- Semantic correction: Without `--delete-untagged`, an explicitly deleted
  manifest is absent from enumeration and its data appears as unmarked blob/
  layer-link candidates, not a manifest candidate. The pure fixture now
  correctly models four blobs, zero manifests, and two links.
- Parser: Added an exact-v3.1.1 normalizer for repository enumeration, mark
  lines, the single summary, blob candidates, and layer-link candidates.
  Candidate order is normalized; repository and digest identities are exposed
  only to the in-process verifier and become sorted hashes in public evidence.
- Refusals: Release drift, unknown/malformed/control/secret-like output,
  duplicate repositories/candidates/summary, ordering violations, summary
  mismatch, any manifest candidate, retained intersection, expected-set drift,
  empty candidates, and the 1,000-item ceiling fail closed.
- Verification: Fifteen parser tests plus the prior sixty model/CLI tests pass
  together (75 focused). All 616 Python tests pass; compilation,
  captured-shape synthetic fixture parsing, static no-subprocess/network/SQL/S3
  inspection, and diff checks pass.
- Scope: Captured local text only. The parser does not invoke the registry,
  collector, storage, SQL, KMS, container, network, credential, or remote
  resource. ADR 0017 remains proposed.
- Next exact action: Add a guarded filesystem adapter and disposable fixture
  that reuses the pinned `registry:3.1.1` image and existing inventory harness.
  Populate retained shared/index/digest-only/referrer content plus one explicit
  deleted graph, stop the registry, snapshot the temporary volume, run two real
  upstream dry runs through this normalizer, execute one real collection only
  against that volume, verify survivors/reclaim/restore, and remove every
  exact fixture resource. Do not connect to S3/RGW yet.

### 2026-07-25 — Disposable filesystem collection and restore completed

- Fixture: Added an exact-image Compose service, deterministic retained and
  explicitly deleted OCI graph, exact candidate authority, owner-only
  adapter state, survivor verifier, and cleanup-safe shell harness. The graph
  includes shared/private blobs, tagged and digest-only manifests, an index
  and child, a subject/referrer, and the OCI fallback referrers index.
- Transaction: The only registry writer stops before a byte-identical
  snapshot. Two networkless upstream dry runs normalize to one exact set,
  which authorizes one collection for 900 seconds. Authorization is consumed
  before execution and replay fails closed. The collector never receives the
  global untagged-deletion option.
- Result: The pinned v3.1.1 collector reported three unreferenced blobs plus
  two repository layer links. All nine survivor classes and the shared blob
  in both repositories remained readable; the deleted graph was unreadable;
  613 logical filesystem bytes were reclaimed; and a separately started
  registry over the snapshot copy passed restore verification.
- Failure corrections: The exact log level is `warn`, not `warning`;
  a stopped container now fails health wait immediately; the alternating
  rootless bind mount requires shared SELinux relabel plus only
  `DAC_OVERRIDE`; and a digest-only repository may express no tags as either
  an empty 200 response or a `NAME_UNKNOWN` 404 while digest HEAD succeeds.
- Safety and cleanup: Root filesystem read-only, network none, all
  capabilities dropped except the bind-mount DAC requirement,
  no-new-privileges, one exact labelled project, and guarded temporary cleanup
  ended with zero container, network, lock, file, or state residue. No S3,
  RGW, SQL, KMS, Keystone, Kolla, credential, or remote host was used.
- Verification: Nine filesystem-adapter tests plus the prior seventy-five GC
  tests pass together (84 focused). All 625 Python tests pass; compilation,
  Compose rendering, Bash, ShellCheck, diff, and live teardown checks pass.
  ADR 0017 remains proposed for an RGW production target.
- Next exact action: Add `docs/research/stage6-load-soak.md`. Inventory the
  accepted clients, request shapes, private-TLS/shared-SQL/RGW topology,
  concurrency/fault seams, metrics, limits, and existing Stage 5 evidence,
  then fix a bounded disposable load/soak matrix before implementing it.

### 2026-07-25 — Load, soak, and fault baseline researched

- Inventory: Stage 5 already proves serial Docker push/pull, a two-part
  resumable upload, quota denial, isolation, replica/VIP/Galera/RGW faults,
  concurrent quota transactions, claim fencing, and key rotation. It does not
  sustain load through faults, measure latency/saturation, or exercise ORAS
  and containerd/nerdctl.
- Client and protocol boundary: Real Docker, Podman, Skopeo, ORAS, and
  containerd/nerdctl compatibility surrounds a deterministic raw OCI driver
  that owns concurrency, content generation, chunked/resumed uploads,
  cross-mounts, indexes, artifacts, quota contention, and exact digest checks.
- Profiles: Fixed smoke, qualification, and two-hour soak profiles plus a
  saturation ramp. Hard transfer ceilings, 30% resource headroom, 70% queue/
  pool limits, no growing backlog, and one measured higher point prevent an
  untested capacity claim.
- Gates: Initial p95/p99 control, manifest, finalize, and first-byte latency
  limits now close the pending ADR 0016 load input. Fault windows cover one
  API/edge/registry/RGW/ingress/Galera replica, HAProxy VIP ownership, KMS
  outage, reconciler claim abandonment, and rolling restart under load.
- Evidence: Versioned bounded aggregates bind exact releases/configuration,
  phases, faults, latency/status/retry buckets, transferred bytes, resource
  limits, quota/Galera/claim invariants, Prometheus reset/staleness, inventory,
  leak scans, and zero residue. Tenant/object/credential/request identities
  and raw payload/log data are forbidden.
- Scope: Research only. No load, credential, registry, SQL, RGW, KMS, Kolla,
  container, VM, network, or remote resource changed.
- Next exact action: Add `poc/load-soak/topology.json` and
  `poc/load-soak/state_machine.py`. Prove exact profiles, phases, content and
  client matrices, ramp/latency/resource gates, fault order/outcomes,
  canonical evidence, secret safety, and zero residue without network,
  subprocess, credential, database, registry, or infrastructure access.

### 2026-07-25 — Pure load and soak state contract completed

- Topology: Added exact smoke/qualification/two-hour soak profiles, seven ramp
  levels, six clients, twelve operations, nine content classes, five
  p95/p99 latency gates, three availability objectives, resource/retry/replica
  boundaries, ten fault windows, direct metrics/rules/alerts, fifteen owned
  resources, and eighteen residue categories.
- Dependency fence: No load phase can pass until signed Distribution and Ceph
  evidence is `qualified` on aarch64 and x86_64. Candidate or blocked inputs,
  one missing architecture, non-private/edge-only/shared topology, an insecure
  client, or replica drift fail before seed data.
- State model: Tamper-evident ordered history validates deterministic bounded
  seed, smoke, measured ramp with the next higher failure, qualification,
  bounded secure fault recovery, soak, exact digest/inventory/quota/claim/
  Galera/upload invariants, direct restart-correct metrics, and zero residue.
- Secret safety: Raw endpoints, tenant/repository/object/upload/credential
  identities, bearer/JWT/private-key material, and unsupported retained types
  are rejected; state retains only hashes and bounded aggregates.
- Verification: Fifty-five focused tests and all 680 Python tests pass;
  compilation, topology JSON, static no-runtime/external-adapter inspection,
  and diff checks pass. The model made no network, subprocess, credential,
  database, registry, storage, infrastructure, or remote call.
- Next exact action: Add fixture-only `poc/load-soak/lifecycle.py` plus a
  versioned evidence fixture. Replay the exact phase machine through owner-only
  atomic state under a nonblocking lock, reject every non-fixture adapter,
  prove fixed failure cases and idempotent teardown, and retain only canonical
  secret-safe output. Do not start a load client or external service.

### 2026-07-25 — Fixture-only load lifecycle completed

- Lifecycle: Added a one-shot/resumable fixture adapter that traverses every
  state phase, atomically checkpoints after each transition, and emits only a
  bounded public history/facts hash. It marks all output `synthetic=true`; it
  cannot be mistaken for measured performance or dependency qualification.
- Local safety: Exact invocation paths, mode-0700 directories, mode-0600
  state/lock files, no-follow open, nonblocking flock, atomic fsync/replace,
  tamper validation, exact rerun/status, and idempotent cleanup are enforced.
- Fixture boundary: The versioned fixture must contain the exact twenty fixed
  refusals and eighteen zero-residue categories. Only the literal `fixture`
  adapter exists; missing, drifted, identity-bearing, or secret-like input
  fails before state mutation.
- Verification: Eight lifecycle tests plus fifty-five state tests pass
  together (63 focused); all 688 Python tests pass. Compilation, fixture/
  topology JSON, static no-network/subprocess/database/registry adapter
  inspection, and diff checks pass.
- Scope: No client, load, credential, registry, SQL, RGW, KMS, Kolla,
  container, VM, network, or remote resource was used. This is executable
  lifecycle evidence only.
- Next exact action: Add `poc/load-soak/evidence.py` with a canonical
  `coffer.load-soak-evidence/v1` parser. Bind exact topology/release/image/
  configuration hashes, bounded histograms and fault windows, inventory/quota/
  Galera/metrics/cleanup facts, and reject raw identities, secrets, unknown
  fields, over-limit cardinality, or synthetic input in production mode.

### 2026-07-25 — Canonical load evidence verifier completed

- Artifact: Added a bounded 16 MiB canonical JSON verifier whose only accepted
  schema contains exact qualified bindings plus thirteen ordered phase
  evidence objects. Unknown fields, noncanonical bytes, synthetic mode, and
  missing/reordered phases fail closed.
- Release binding: Expected Distribution, Ceph, driver, image, client, and
  configuration versions/revisions/hashes come from an independent caller.
  Both architectures and literal `qualified` readiness are mandatory; the
  evidence cannot weaken the supplied binding.
- Replay: Every phase is revalidated through the pure state machine. The
  output exposes only topology, binding, artifact, facts, and history hashes
  plus the fixed phase count.
- Current live fence: A new official metadata check still reports Distribution
  v3.1.1 and Ceph v20.2.2 `blocked`; Ceph PR 69277 remains merged but absent
  from a stable point release. Therefore no production-mode load execution or
  fresh pilot is currently permitted.
- Verification: Fourteen evidence tests plus the prior sixty-three
  state/lifecycle tests pass (77 focused); all 702 Python tests pass.
  Compilation, canonical/noncanonical file checks, static no-runtime adapter,
  and diff checks pass.
- Next exact action: Add the deterministic raw OCI driver beginning with a
  standalone Go module under `poc/load-soak/driver/`. Implement verified TLS,
  finite Bearer acquisition/retry, bounded monolithic and chunked streaming,
  deterministic digest generation, fixed latency/result buckets, cancellation,
  and canonical temporary output. Unit-test it with local `httptest` only; do
  not target a registry until the release fence is qualified.

### 2026-07-25 — Deterministic raw OCI protocol core completed

- Artifact: Added a standalone Go 1.25 standard-library module under
  `poc/load-soak/driver/`. It generates replayable deterministic content up to
  256 MiB, computes canonical SHA-256 without retaining payloads, and supports
  monolithic plus bounded chunked blob upload.
- Transport and identity: The client requires an explicit CA pool, HTTPS, TLS
  1.2 or newer, one exact same-origin Bearer challenge, injected finite Basic
  credentials used only at the token endpoint, and bounded token/response
  bodies. Ambient proxies, redirects, insecure TLS, cross-origin realms and
  upload locations, traversal, raw URLs, and credential-bearing errors are
  refused.
- Retry and integrity: Replay-safe transport and 502/503/504 outcomes retry
  finitely. Digest, `Content-Range`, upload `Location`, final blob `Location`,
  and response ceilings are exact. Ambiguous chunk start/PATCH failures stop
  without blind replay; status-based loss-safe recovery remains the next
  slice.
- Evidence: A concurrency-safe recorder exposes only fixed operation/result/
  latency buckets, attempts, retries, transferred bytes, and digest-check
  counts. Atomic canonical output requires an owner-only directory and writes
  a mode-0600 regular file; symlink targets fail closed.
- Verification: Fifteen top-level Go contract tests pass with the race
  detector; `go vet` passes. The matrix includes exact Coffer Bearer parsing,
  8-way concurrency, trusted/untrusted TLS, cancellation, retry exhaustion,
  bounded responses, same-origin continuity, no-blind-PATCH replay, canonical
  output, permissions, symlink refusal, and secret-safe failures. All servers
  are local TLS `httptest`; no registry, credential, container, VM, network
  service, or remote resource was used.
- Next exact action: Extend `poc/load-soak/driver/client.go` with bounded
  upload-status reconciliation after ambiguous chunk PATCH results. Accept
  only the exact prior or committed range and same-origin continuation, then
  retry or advance once; test transport/502/503/504 loss, range/location drift,
  cancellation, and exhaustion locally before adding the CLI boundary.

### 2026-07-25 — Loss-safe resumable upload reconciliation completed

- Protocol correction: The official Distribution API exposes upload progress
  through authenticated GET on the latest opaque upload `Location`, returning
  204 plus inclusive `Range` and a refreshed `Location`. The driver now uses
  that status operation instead of replaying an ambiguous non-idempotent PATCH.
- Recovery: After transport loss or 502/503/504, an exact prior offset permits
  a finite bounded resend and an exact committed offset permits forward progress.
  Partial progress, the empty/one-byte ambiguous case, malformed/missing
  ranges, cross-origin/traversal continuation, unexpected status, cancellation,
  and exhaustion fail closed. Chunk-start POST remains non-replayed because no
  owned upload location exists after an ambiguous response.
- Integrity: Both `Range: 0-N` and the documented `Range: bytes=0-N` are
  normalized, but only exact expected offsets are accepted. Transferred-byte
  aggregates include bytes sent before a lost response and any verified
  resend; completion still requires the locally computed digest.
- Verification: Eighteen top-level Go contract tests pass under the race
  detector and `go vet`. Local TLS cases cover response lost before and after
  commit, status-query 502/503 retry exhaustion, range and location drift,
  cancellation, and byte-exact completion with no duplicate append. No
  external registry, credential, container, VM, or remote resource was used.
- Next exact action: Add the owner-only executable boundary beginning with
  `poc/load-soak/driver/cmd/coffer-raw-oci-driver/main.go`. Load exact
  mode-0600 invocation, CA, and credential files without environment or secret
  arguments; require independently verified qualified readiness; execute only
  bounded monolithic/chunked operations; atomically emit canonical aggregates
  and remove temporary state. Test with local TLS only.

### 2026-07-25 — Owner-only raw OCI executable boundary completed

- Executable: Added `coffer-raw-oci-driver` with one accepted argument,
  `--invocation <absolute-path>`. Invocation, CA, credential, and readiness
  inputs must be exact mode-0600 regular, owner-matched, single-link files.
  Paths are absolute and pairwise distinct; the output parent and any existing
  output are validated before an HTTP request.
- Release fence: The invocation binds the exact SHA-256 of a separate
  `coffer.upstream-readiness/v1` document. Overall, Distribution, and Ceph
  states must all be `candidate-qualified`; verified release/fix predicates,
  current accepted baselines and Ceph fix identity, newer exact versions and
  revisions, and empty reason arrays are mandatory. The current live blocked
  classifier output cannot authorize execution.
- Secret boundary: Credentials exist only in a separate owner-only JSON file
  and an injected in-process provider. Arguments, environment, proxies,
  redirects, errors, and result evidence carry none. Raw input byte buffers are
  overwritten after parsing. Retained canonical aggregates expose no target,
  repository, seed, username, password, token, upload location, or raw URL.
- Lifecycle: The executable applies one finite context deadline, supports only
  bounded monolithic/resumable upload, closes idle connections, validates the
  canonical output path before mutation, atomically writes mode 0600, and
  leaves no invocation-created temporary file.
- Verification: Twenty-three driver and two command top-level tests pass under
  the race detector; `go vet` and command build pass. Local TLS end-to-end
  execution, blocked/hash-drifted readiness, baseline/fix/version weakening,
  unsafe file modes, symlink/single-link/path-alias/unknown-field boundaries,
  unsafe output, fixed CLI failures, secret scans, and residue checks pass. No
  external registry, credential, container, VM, or remote resource was used.
- Next exact action: Add `poc/load-soak/driver/manifest.go` with authenticated
  manifest PUT/HEAD/GET and blob HEAD/range/full GET. Require exact media type,
  lengths and locally verified digest, keep response bodies bounded, refuse
  redirects, classify fixed outcomes, and cover cancellation using local TLS
  `httptest` only.

### 2026-07-25 — Raw manifest and blob-read integrity slice completed

- Manifest operations: Added OCI image manifest/index PUT, HEAD, and GET. A
  bounded 4 MiB document must be valid JSON with schema version 2 and an exact
  supported media type. Tag/digest reference, local digest, response digest,
  media type, size, path, and same-origin publication location are exact.
- Blob operations: Added HEAD and full/range GET against deterministic content.
  The generator can begin at any bounded byte offset without materializing the
  prefix. Status, length, local digest, full-versus-partial response,
  `Content-Range`, and every returned byte are verified while streaming.
- Transport: Authentication/retry remains finite and same-origin. Redirects
  are not followed, payload and response bounds remain fixed, cancellation
  interrupts body verification, and failures retain only the existing fixed
  protocol/digest/dependency/cancelled classes.
- Evidence: Aggregates use only the topology's `manifest-publish`,
  `manifest-read`, and `blob-read` operations. Transferred bytes and digest
  checks are retained; payloads, target/repository/reference, URLs, and
  credentials are not.
- Verification: Twenty-nine driver plus two command top-level tests pass under
  the race detector and `go vet`. Local TLS covers publish/head/get,
  full/range reads, block-unaligned deterministic windows, body/digest/range/
  location drift, redirect refusal, stream cancellation, and invalid-input
  no-network refusal. No external registry or infrastructure was used.
- Next exact action: Extend `poc/load-soak/driver/invocation.go` with exact
  owner-only manifest input and operation-specific fields for manifest
  PUT/HEAD/GET and blob HEAD/full/range GET, then implement same-project
  cross-mount with exact source/destination/digest handling and 201/202
  classification. Test local TLS only.

### 2026-07-25 — Nine-operation invocation and cross-mount completed

- Invocation: Expanded the owner-only executable to monolithic/resumable
  upload; blob HEAD, full GET, range GET, and cross-mount; and manifest PUT,
  HEAD, and GET. Operation-specific seed/content/chunk/range/manifest/reference/
  source fields are exact and cannot be mixed. The optional manifest is a
  distinct owner-only single-link file and its runtime buffer is overwritten
  after execution.
- Authorization: Cross-mount learns the destination challenge but requests two
  exact token scopes together: destination `pull,push` and source `pull`.
  Destination and source routes must be distinct canonical Coffer routes under
  the same project UUID; cross-project authorization is refused before any
  request.
- Mount outcomes: 201 requires the local digest and exact same-origin blob
  location. A 202 fallback must identify one empty same-origin upload; the
  driver cancels it immediately and records fixed `fallback`, not `success`.
  Missing/drifted state or failed cleanup is fatal.
- Verification: Thirty-five driver plus two command top-level tests pass under
  the race detector and `go vet`. Local TLS covers multi-scope token order,
  native mount, fallback cleanup and cleanup failure, cross-project refusal,
  manifest/blob/mount invocation dispatch, operation-field separation, and
  retained-result safety. No external registry or infrastructure was used.
- Next exact action: Add `poc/load-soak/driver/referrers.go` for a
  subject-bearing OCI artifact and exact native OCI 1.1 Referrers-versus-
  fallback-tag disposition, then add bounded partial-upload ownership and
  cancellation for the abandoned-upload shape. Test local TLS only.

### 2026-07-25 — Artifact/referrers and abandoned-upload slice completed

- Artifact validation: A bounded subject-bearing OCI image manifest now
  requires exact schema/media/artifact types, SHA-256 descriptors, portable
  config/layer descriptors, annotations, and subject. Publication still uses
  the existing digest and same-origin manifest contract.
- Referrers disposition: The driver queries the filtered OCI 1.1 endpoint and
  requires the exact OCI index, `OCI-Filters-Applied`, and one byte-exact
  descriptor. Only a 404 activates the standard `sha256-<encoded>` fallback
  tag. The bounded existing index is preserved, the descriptor is inserted
  when absent, and manifest digest plus descriptor are verified on read-back.
  This path records `fallback`, never native success, because a registry
  without conditional manifest publication retains a concurrent lost-update
  limitation.
- Abandoned uploads: One operation creates exactly two distinct partial
  uploads, sends one exact bounded prefix to each, tracks opaque same-origin
  locations only in memory, and cancels every owned upload on success or
  failure with a separate bounded cleanup context. A known location from a
  malformed start response is still cleaned; unknown or drifted ownership
  fails closed.
- Executable: The owner-only invocation now exposes eleven operations,
  including `artifact` and `abandoned-upload`. Artifact files reuse the
  mode-0600 single-link input boundary; partial upload size is exact and must
  be smaller than the deterministic content.
- Verification: Forty-two driver plus two command top-level tests pass under
  the race detector and `go vet`. Local TLS covers native and fallback
  discovery, exact descriptor/digest mismatch, invalid subject refusal,
  two-upload cleanup, failure cleanup, malformed-start cleanup, and both new
  invocation dispatch paths. Retained evidence contains no subject, tag,
  reference, repository, upload identity, URL, payload, or credential. No
  external registry or infrastructure was used.
- Next exact action: Add the real-client adapter boundary beginning with
  `poc/load-soak/clients/contract.py`. Pin Docker, Podman, Skopeo, ORAS, and
  nerdctl/containerd versions; fix each client's verified-TLS, stdin
  credential, owner-only state, bounded command, digest-verification, and
  cleanup contract; and prove argv/environment/log safety with fake
  executables before any release-gated pilot execution.

### 2026-07-25 — Five real-client adapter contracts completed

- Pins: Added exact 2026-07-25 client inputs for Docker Engine/CLI 29.6.2,
  Podman 6.0.2, Skopeo 1.23.0, ORAS 1.3.3, nerdctl 2.3.5, and containerd
  2.3.3 with source revisions, release URLs, architecture scope, and upstream
  GitHub verification disposition. Skopeo is honestly marked unverified; it
  is compatibility input, not accepted supply-chain provenance.
- Input boundary: Every adapter requires the exact version plus executable
  SHA-256, mode-0600 owner-only CA/credential/artifact files, a mode-0700 work
  root, canonical same-project Coffer routes, private hostname, finite timeout,
  and expected manifest digest. Docker additionally requires an identical
  read-only daemon CA at `<registry>/ca.crt`; the live client VM must bind that
  evidence to `/etc/docker/certs.d`.
- Command boundary: Passwords enter only login stdin. Commands use absolute
  binaries, no shell, a fixed seven-variable environment without ambient
  proxy/auth/home state, explicit TLS verification and CA/auth paths, streaming
  one-MiB output limits, process-group timeout termination, isolated client
  roots, fixed version parsers, and one exact digest parser.
- Client shapes: Docker, Podman, and nerdctl tag/push/pull/inspect; Skopeo
  performs authenticated same-project registry copy/inspect; ORAS attaches to
  an exact subject digest, discovers with the same explicit native or fallback
  Referrers mode, and pulls the artifact by exact digest.
- Cleanup/evidence: Image cleanup and logout run after success or failure;
  generated state is removed. Retained results contain only fixed client,
  version, Referrers disposition, binary/pins hashes, counts, and result.
  Registry, project/repository, source, subject, tag, credential, artifact,
  CA, state, and command output are not retained.
- Verification: Seventeen focused tests pass using local executable fakes. They
  cover all five clients, both ORAS dispositions, exact pins, binary/input
  drift, clean environment, stdin-only passwords, secret echo refusal,
  output-limit and timeout process-group termination, command flags, CA/hosts
  materialization, failure cleanup, unsafe input, and zero generated residue.
  Python compilation and diff checks pass. No real client, daemon, containerd,
  registry, network, credential, or remote infrastructure was used.
- Full regression: All 719 Python tests pass after the adapter boundary and
  bounded subprocess implementation.
- Next exact action: Add `poc/load-soak/clients/run.py` as the owner-only
  executable boundary. Load exact invocation, credential, CA, pins, qualified
  readiness, and output files; atomically emit canonical results; retain fixed
  failures only; and test interruption/output/residue behavior with the same
  executable seam before qualifying real client binaries or images.

### 2026-07-25 — Owner-only real-client execution boundary completed

- Invocation: Added the exact `coffer.load-client-run/v1` file contract around
  the five client adapters. The invocation, pins, and upstream readiness files
  must be absolute, owner-matched, single-link, mode-0600 regular files; their
  raw SHA-256 bindings, every nested client path, work root, and output path
  are pairwise distinct.
- Release fence: Overall, Distribution, and Ceph readiness must all be
  `candidate-qualified`. The accepted baselines, newer stable versions,
  verified Distribution commit, Tentacle series, merged/in-release Ceph
  encrypted-copy fix, exact fix identity, revisions, publication metadata,
  and empty reason sets cannot be weakened.
- Output and failure boundary: The output parent must already be owner-owned
  mode 0700 and any existing output mode 0600. A successful run fsyncs and
  atomically replaces one canonical mode-0600 execution document containing
  only pins/readiness hashes and the bounded adapter result. CLI output and
  every failure category are fixed.
- Interruption: SIGINT, timeout, output overflow, command failure, and unsafe
  input/output paths terminate or clean owned client state. They leave no
  result or temporary client session and retain no command output, endpoint,
  repository, path, credential, or secret.
- Verification: Nine runner tests plus seventeen adapter tests pass locally.
  The runner matrix covers canonical success, blocked readiness, pins drift,
  unsafe mode/symlink/path alias, command failure cleanup, SIGINT child
  termination, exact fixed output, and zero generated residue. Compilation and
  diff checks pass. No real binary, daemon, containerd, registry, network,
  credential, or remote infrastructure was used.
- Full regression: All 728 Python tests pass after the owner-only runner.
- Next exact action: Add `poc/load-soak/telemetry.py` as a no-network canonical
  evidence adapter. Bind exact before/during/after Prometheus query snapshots,
  Galera/RGW/quota/reconciliation/host resource inputs, restart/stale-series
  windows, and owner-only output; reject missing targets, unbounded labels,
  invariant drift, or secret-like evidence before a live collector exists.

### 2026-07-25 — Canonical load telemetry adapter completed

- Three-window contract: Added exact before/during/after snapshots bound to
  both checked-in load and observability topology hashes. Observation times
  increase, direct target identities and counts are bounded, counters cannot
  reset without a newer process start, and at least one restart plus a
  zero/nonzero/zero stale-series transition is mandatory.
- Signal coverage: Every snapshot contains the exact recording-rule and alert
  sets, per-replica API/edge/reconciler/registry health, Galera
  primary/ready/synced state, RGW daemon/ingress/KMS/multipart state, quota
  headroom and transaction invariants, reconciliation freshness/fencing,
  HAProxy backends, and three controller plus three storage host resource
  envelopes.
- Gates: Normal windows require all replicas; the fault window permits at most
  one missing replica per service and requires a bounded alert. Resource and
  quota usage remain at or below 70 percent with at least 30 percent headroom,
  transaction attempts remain at or below three, and post-window multipart,
  stale claim, fencing, schema, secret, OOM, and unexpected-error counts are
  zero.
- Evidence boundary: The owner-only canonical input and mode-0700 output
  parent produce one atomic mode-0600 verified result containing only hashes,
  counts, source disposition, and the exact load `metrics-verified` phase.
  Host/target identities and raw samples are not retained.
- Promotion fence: With no typed live collector, only explicit fixture,
  `synthetic=true` input is accepted. Claimed non-synthetic Prometheus export
  is refused, so local validation cannot satisfy production evidence.
- Verification: Thirty-three focused tests and all 761 Python tests pass.
  Drift cases cover every dependency/resource family, under/over-counts,
  rules, alerts, stale/restart transitions, topology bindings, owner/mode/
  symlink/canonical output, fixed CLI failures, and static absence of network
  or subprocess imports. No network, Prometheus, SQL, RGW, Kolla, container,
  VM, credential, or remote resource was used.
- Next exact action: Add `poc/load-soak/plan.py` as a pure deterministic
  execution-manifest compiler. Expand the exact client/operation/content,
  smoke/ramp/qualification/soak, serial fault, transfer-budget, and telemetry
  schedule; bind readiness, client, driver, image, and configuration evidence;
  emit owner-only canonical plan hashes without starting a workload.

### 2026-07-25 — Deterministic load execution manifest completed

- Binding: Added the exact `coffer.load-execution-plan-request/v1` contract.
  It requires both architectures, literal qualified readiness, newer
  Distribution and Tentacle v20.2 releases, full source revisions, exact
  readiness/image/configuration/client/driver hashes, and the checked-in load
  topology hash.
- Matrix: The compiler fixes all six clients, twelve operation requirements,
  nine deterministic content classes and byte sizes, three ordered profiles,
  seven ramp levels, ten serial faults, thirteen lifecycle phases, and
  before/during/after telemetry windows. Capability union must exactly cover
  the topology.
- Budgets: Smoke, qualification, and soak ceilings are copied byte-exact from
  the topology; the seven ramp allocations together cannot exceed the
  qualification ceiling; the overall plan cannot exceed the soak ceiling.
- Honesty boundary: Each client matrix entry says that an executor contract
  and verified TLS are required; it does not claim execution. The entire
  envelope remains `synthetic=true`, so compilation cannot satisfy a measured
  load phase.
- File boundary: A canonical owner-only request and mode-0700 output parent
  produce one deterministic atomic mode-0600 envelope with a canonical plan
  hash. Inputs and output are distinct; symlink, mode, canonicalization,
  binding, version, capability, and topology drift fail closed.
- Verification: Twenty-three focused compiler tests and all 784 Python tests
  pass. Static inspection confirms no network or subprocess adapter. No
  client, workload, credential, service, container, VM, network, or remote
  resource was used.
- Next exact action: Add `poc/load-soak/orchestrator.py` with typed executor,
  fault, and telemetry seams. Replay the compiled profile/matrix/ramp/fault
  order and cumulative transfer budgets through fixture-only executors,
  checkpoint owner-only canonical state, reject every live adapter, and expose
  the missing real executor capabilities without starting a workload.

### 2026-07-25 — Fixture-only checkpointed load orchestrator completed

- Exact order: The orchestrator derives one 29-step schedule from the compiled
  plan: six client qualification entries, smoke, seven ramp levels,
  qualification, ten serial faults, soak, and before/during/after telemetry.
  Step count, names, kinds, order, and schedule hash cannot drift.
- Executor boundary: Only the exact `FixtureExecutor` type is accepted.
  Every entry requires fixed passed/attempt/error/transfer evidence; live or
  lookalike executors fail before a step can advance. The result and state
  remain explicitly synthetic.
- Budgets: Non-load steps transfer zero bytes. Profile steps cannot exceed
  their own ceiling; every ramp step has a fixed ceiling and their aggregate
  cannot exceed the qualification budget. Over-budget evidence fails without
  advancing the checkpoint.
- Recovery: Canonical owner-only plan/invocation/state/output inputs, exact raw
  plan-file hash, pairwise-distinct paths, mode-0700 state directory,
  no-follow files, and a nonblocking mode-0600 lock protect execution. State
  fsyncs after every step; an injected failure preserves the last valid entry,
  resumes deterministically, and terminal reruns return byte-identical output.
- Evidence: The terminal mode-0600 result retains only adapter/synthetic
  disposition, plan/budget/history hashes, and the fixed step count. Stale
  output, altered history, unsafe files, lock contention, invalid checkpoint
  limits, and incomplete execution fail closed.
- Verification: Fifteen focused orchestrator tests and all 799 Python tests
  pass. Static inspection confirms no network or subprocess import. No real
  executor, workload, fault, service, credential, container, VM, network, or
  remote resource was used.
- Next exact action: Add `poc/load-soak/runtime_manifest.py`. Bind every one of
  the 29 schedule entries to an exact owner-only executable/input/output
  contract, binary SHA-256, qualified readiness hash, target class, timeout,
  and cleanup owner. Reuse the completed raw OCI and five-client runners,
  expose missing control/quota/fault/telemetry executors explicitly, and fail
  closed until the manifest is complete; do not execute it.

### 2026-07-25 — Fail-closed runtime capability manifest completed

- Evidence binding: The manifest accepts only canonical owner-only plan,
  readiness, and client-pins files. The raw readiness and pins hashes must
  match the compiled plan; readiness must satisfy the exact
  candidate-qualified Distribution/Ceph fence before capability inspection.
- Per-step boundary: All 29 schedule entries now declare executor, current
  disposition, source-contract hash when one exists, required input/output
  schemas, target class, finite timeout, cleanup owner, owner-only files,
  readiness binding, verified TLS, and executable SHA.
- Honest disposition: The five client runners and raw OCI driver are
  `contract-only`, not runtime-qualified. Profile/ramp and fault executors plus
  the live telemetry collector are missing. Standalone control, token-only,
  and quota-contention operations are also missing even though the raw OCI
  driver covers the other protocol shapes.
- Binary gate: No current entry has qualified binary/runtime evidence, so
  every executable SHA is null. The canonical output is always
  `synthetic=true`, `ready=false`, includes twelve unique gaps, and the CLI
  returns the distinct blocked status 3 rather than success.
- File/supply-chain boundary: Source-contract hashes bind the two Python
  client runner files, all raw-driver Go sources, and the telemetry verifier.
  Input/output paths and raw targets are not retained. Unsafe modes, symlinks,
  aliases, noncanonical bytes, evidence drift, blocked readiness, and compiler
  drift fail before output.
- Verification: Fourteen focused runtime-manifest tests and all 813 Python
  tests pass. Static inspection confirms no network or subprocess import. No
  binary, client, workload, fault, telemetry service, credential, container,
  VM, network, or remote resource was used.
- Next exact action: Add a bounded owner-only control/token/quota driver
  contract beginning under `poc/load-soak/control/`. Fix finite Keystone token
  acquisition, repository control requests, standalone registry-token
  requests, concurrent quota-manifest admission, verified TLS, secret-safe
  aggregates, cancellation, and cleanup using local TLS fakes only.

### 2026-07-25 — Control, token, and quota protocol core completed

- Transport: Added a standalone Go 1.25 standard-library module requiring
  explicit HTTPS Keystone/control/registry origins, an explicit CA pool,
  TLS 1.2 or newer, no ambient proxy or redirect, finite timeout, and bounded
  concurrency. Invalid origin, route, service, credential, or configuration
  fails before a request.
- Identity/control: The core obtains one Keystone token using the exact
  application-credential method and bounded response, then probes the
  project-scoped repository collection with `X-Auth-Token`. The credential
  provider is injected and its JSON buffer is overwritten after use.
- Registry token: A separate Basic application-credential request uses an
  exact encoded service and canonical project-scoped repository pull/push
  scope. Only a bounded successful token document is accepted.
- Quota contention: Two through sixty-four distinct bounded manifests publish
  concurrently. Exact expected 201 and 429 counts are mandatory; every 201
  requires the locally calculated digest. All owner-created digests are
  deleted under an independent bounded cleanup context before outcome
  acceptance, including mismatch, primary failure, or caller cancellation.
- Evidence: Only sorted fixed operation/result/count/duration aggregates are
  retained. Credential, token, project/repository, manifest, digest, URL, and
  cleanup identities are absent. Authentication, dependency, protocol, quota,
  cleanup, and cancellation failures remain distinct.
- Runtime manifest: `control`, standalone `token`, and `quota-contention`
  changed from missing to `contract-only` under one source-hashed
  `control-load` owner. The total runtime gap set drops from twelve to nine;
  no executable SHA or qualified runtime claim was added.
- Verification: Four Go top-level tests pass with the race detector and
  `go vet`; fourteen runtime-manifest tests still pass. Local TLS covers the
  success path, untrusted CA, redirect, cancellation, count mismatch, required
  cleanup, cleanup failure, invalid configuration, and secret-safe evidence.
  No external endpoint, credential, registry, workload, or infrastructure was
  used.
- Full regression: All 813 Python tests remain passing after the control core.
- Next exact action: Add `poc/load-soak/control/cmd/coffer-control-load/main.go`
  plus an owner-only invocation loader. Bind exact CA, application credential,
  readiness, manifests, output, target class, timeouts, expected quota counts,
  and binary/source evidence; atomically emit canonical aggregates and prove
  unsafe-file, interruption, failure, and residue behavior with local TLS.

### 2026-07-25 — Owner-only control load execution boundary completed

- Executable: Added `cmd/coffer-control-load` with one fixed
  `--invocation <absolute-path>` interface and fixed secret-safe success,
  invalid-argument, and execution-failure messages.
- Preflight: The exact invocation now binds the disposable Stage 6 target,
  three HTTPS origins, project-scoped repository/service, finite timeout and
  concurrency, exact positive 201/429 counts, the running executable SHA-256,
  source-contract SHA-256, qualified readiness SHA-256, explicit CA and
  application credential files, two through 64 distinct SHA-bound manifests,
  and one canonical output. All files are absolute, distinct, owner-matched,
  mode 0600, regular, single-link, and no-follow; the output parent is
  owner-only and a stale existing output is refused. Binary, release, output,
  and all manifest checks complete before a request.
- Execution/evidence: One finite context obtains and probes a Keystone token,
  obtains a standalone registry token, executes the exact concurrent
  contention counts, and finishes independent digest cleanup before success.
  The atomic mode-0600 result contains only executable, source-contract,
  readiness, and ordered-manifest-set hashes plus sorted fixed aggregates.
  URLs, paths, credential material, tokens, project/repository identities,
  manifests, manifest digests, and cleanup identities are excluded.
- Failure safety: Unsafe modes, links, aliases, unknown fields, executable,
  readiness, or manifest drift, blocked dependencies, duplicate manifests,
  quota mismatch, and cancellation fail closed. Preflight never reaches the
  local TLS server; runtime failure performs cleanup and writes no success
  result. The shared canonical-output boundary now also verifies process
  ownership and single-link outputs.
- Qualification boundary: The source-contract digest is provenance for
  independent comparison with `runtime_manifest.py`; the executable verifies
  only its actual binary digest. Local TLS is contract evidence, not
  both-architecture or disposable-pilot qualification. The runtime manifest
  therefore still reports nine gaps and `ready=false`.
- Verification: Control and command packages pass the Go race detector and
  `go vet`; the raw OCI driver passes the same checks after the shared output
  strengthening. Runtime-manifest and full repository regression are recorded
  below after the final milestone gate.
- Next exact action: Add the bounded owner-only profile executor beginning
  under `poc/load-soak/profile/`. Compile smoke, ramp, qualification, and soak
  steps into finite concurrent raw-OCI/control child invocations, enforce
  transfer and cleanup budgets, checkpoint interruption-safe aggregate
  evidence, and prove only local executable fakes before any live pilot.

### 2026-07-25 — Checkpointed profile and ramp executor completed

- Plan contract: Every ramp level now has an explicit 120-second duration in
  the deterministic compiled plan. Smoke, qualification, and soak retain their
  120-, 1800-, and 7200-second durations and exact steady/burst concurrency and
  transfer ceilings.
- Invocation boundary: Added the owner-only
  `coffer.load-profile-invocation/v1` runner. It revalidates the exact compiled
  schedule step and binds target/source class, runner source hash, plan hash,
  state/lock/output/work paths, and one exact binary/invocation/contract hash
  plus cleanup and transfer ownership for every operation. All twelve
  operations have exactly one owner; `control-load` owns control, token, and
  quota contention and raw OCI owns the remaining nine.
- Runtime: Profile waves use steady clients in the first/final quarters and
  burst clients in the middle half; ramps use the exact client level.
  `control-load` runs at most once per wave so its fixed quota tags and cleanup
  cannot race another invocation. Remaining slots rotate deterministically
  through raw operations.
- Process/file safety: Children receive only an owner-only temporary
  invocation path, a minimal fixed environment, no stdin, no shell, and an
  independent process group. Runtime and stdout/stderr are bounded while the
  process is alive. Timeout, nonzero/fixed-output drift, malformed result,
  transfer violation, interruption, or cleanup residue terminates all groups
  and removes exact generated invocation/result/stream files.
- Checkpoint/evidence: Each successful wave extends a replay-validated
  hash-chain with operation counts, elapsed duration, attempts, and transferred
  bytes, then atomically writes mode-0600 state. Resume rejects altered state,
  plan, binary, invocation, source, operation ownership, link/mode, or path
  boundaries. Terminal output retains only fixed counts and provenance hashes.
  Fixture output is explicitly synthetic and exits 3; a pilot cannot exit 0
  before real duration, full operation coverage, zero unexpected errors, and
  the transfer ceiling pass.
- Qualification boundary: The runtime manifest now source-hashes
  `profile-load` and marks all ten profile/ramp schedule entries
  `contract-only`. It still reports nine gaps and `ready=false` because no
  executable SHA or both-architecture pilot evidence is qualified; fault and
  live telemetry executors remain missing.
- Verification: Fifteen profile tests use actual local fake executables plus
  an accelerated test clock and cover checkpoint/resume/idempotence, cadence,
  transfer/failure refusal, state tamper, input drift, interruption, process
  timeout, output bounds, fixed CLI behavior, and zero temporary residue. The
  broader load matrix passes 136 tests; all 828 Python tests and compilation
  pass.
- Next exact action: Add the serial owner-only fault executor beginning under
  `poc/load-soak/fault/`. Bind each compiled fault window to exact
  preflight/inject/observe/recover/verify commands and target evidence, enforce
  one active fault, process/time/output bounds, recovery deadlines, and
  interruption-safe rollback using local executable fakes only.

### 2026-07-25 — Serial recovery-first fault executor completed

- Invocation/target boundary: Added the exact owner-only fault invocation for
  all ten compiled serial windows. It binds the disposable source class, plan
  step, action binary and source-contract hashes, target-evidence hash, and
  distinct state/lock/output/work paths. Each fault has one fixed adapter class
  and a bounded owner-only list of non-secret selectors whose canonical hash,
  ownership hash, and topology hash are verified but not retained raw.
- State machine: Every run holds one nonblocking lock and advances
  `preflight -> inject -> full window -> observe -> recover -> verify` through
  a replay-validated hash-chain checkpoint. Success requires the exact five
  actions, exact window, bounded combined recovery evidence, zero unexpected
  errors, and no failure phase.
- Ambiguous/lost execution: Inject failure is conservatively treated as
  active. Observe failure, `KeyboardInterrupt`, or a process disappearing
  after injection checkpoints a fixed failure and performs recover then
  verify. A later invocation with an injected/observed/recovered checkpoint
  also recovers first. Successful rollback ends `failed-recovered` without
  output; recovery failure retains the actionable checkpoint; a missed
  recovery deadline is terminal and can never be promoted.
- Process/file safety: Actions receive only one owner-only generated
  invocation path. The shared profile subprocess boundary provides no shell or
  stdin, minimal environment, independent process groups, finite timeout,
  live 4-KiB stdout/stderr bounds, fixed output, termination escalation, and
  exact temporary cleanup. Action results contain only fixed phase/fault,
  timing, status, and target-evidence hash fields.
- Qualification boundary: Runtime source evidence for `fault` includes both
  the fault executor and shared subprocess implementation. All ten fault steps
  are now `contract-only`; the runtime manifest remains `ready=false` with
  nine gaps because executable SHA and pilot evidence are unqualified. The
  live telemetry collector is the last missing schedule executor.
- Verification: Sixteen fault tests with actual local action executables cover
  full window/success/idempotence, observe failure rollback, lost-process
  recovery, ambiguous inject, deadline failure, hash-chain tamper, exact
  binary/plan/target/adapter/step/source/path refusal, fixed CLI behavior, and
  zero temporary residue. The broader load matrix passes 152 tests; all 844
  Python tests and compilation pass.
- Next exact action: Add the owner-only live telemetry collector beginning
  under `poc/load-soak/collector/`. Fetch the exact direct Prometheus targets
  and native HAProxy/MariaDB/Ceph surfaces over verified TLS, bind each
  before/during/after window to the compiled plan, cap samples/series/labels,
  emit the existing canonical telemetry bundle, and prove transport behavior
  with local TLS fakes only.

### 2026-07-25 — Owner-only telemetry collection boundary completed

- Invocation/target boundary: Added exact owner-only before/during/after
  invocations bound to one compiled plan step, checked collector/telemetry
  source, CA, disposable target, shared state/lock/bundle paths, and distinct
  result paths. The target binds seven unique credential-free HTTPS URLs for
  Prometheus, HAProxy, Galera, RGW, quota, reconciliation, and host surfaces.
- Transport safety: The client ignores ambient proxies, requires verified TLS
  1.2 or newer and hostname validation, refuses insecure URLs, redirects,
  content-type drift, content encoding, noncanonical or misbound documents,
  and caps per-surface bytes, total bytes, JSON depth, keys, arrays, and
  strings. Local tests use a real TLS server and certificate.
- State/evidence: Each semantic snapshot advances an atomic replay-validated
  hash chain. Phases cannot skip or reorder. Each phase emits one redacted
  `coffer.load-telemetry-collection-result/v1`; `after` additionally emits the
  existing canonical telemetry bundle. Raw instance identities remain only in
  owner-only state/bundle input.
- Promotion safety: Standalone verification still rejects a caller-labelled
  live bundle. `prometheus-export` is accepted only when the final result
  independently matches the expected plan, collector source, target, bundle,
  snapshot, and history hashes. Fixture output remains synthetic.
- Qualification boundary: The seven local endpoints return normalized
  phase-bound surfaces. They prove collection/state/transport, not parsing of
  real Prometheus HTTP API, HAProxy, mysqld-exporter, Ceph mgr/RGW, or
  node-exporter output. All three telemetry schedule entries are now
  source-hashed `contract-only`; the runtime manifest remains `ready=false`
  with nine unqualified executors and no executable hashes.
- Verification: Nineteen collector tests cover the three-window transaction,
  idempotence, independent pilot binding, verified TLS, redirects, response
  and semantic drift, size/canonical limits, exact preflight, phase order,
  tamper, lock, and fixed CLI behavior. Collector, telemetry, and runtime
  manifest tests pass 66 cases; the broader load matrix passes 204; all 863
  Python tests and compilation pass.
- Next exact action: Add
  `poc/load-soak/collector/native_surfaces.py`. Parse bounded Prometheus HTTP
  API and strict HAProxy, mysqld-exporter, Ceph mgr/RGW, and node-exporter
  responses from their exact verified-TLS URLs into the seven internal
  surface schemas. Pin query/metric/label allowlists, refuse missing or extra
  series, and prove each parser with captured local TLS fakes only.

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
| No-network backup adapter and integrated backup gate | `uv run pytest -q tests/test_data_protection_backup_adapter.py tests/test_data_protection_backup_manifest.py tests/test_data_protection_lifecycle_cli.py tests/test_data_protection_state_machine.py` | passed; 80 |
| Full regression after no-network backup adapter | `uv run pytest -q` | passed; 439 |
| Stage 6 observability source/config inventory | Focused inspection of Coffer metrics/runners, Distribution config, Kolla scrape/log/HAProxy model, and prior M3 evidence | passed; gaps and owners fixed |
| Stage 6 observability primary sources | Official Prometheus client, Kolla-Ansible, Distribution, and Ceph documentation | passed; candidate is consistent with supported surfaces |
| Pure observability contract | `uv run pytest -q tests/test_observability_contract.py` | passed; 51 |
| Full regression after observability contract | `uv run pytest -q` | passed; 490 |
| Kolla role after observability contract | `make -C poc/kolla-ansible-role verify` | passed; 68 |
| Runtime observability focused regression | `uv run pytest -q tests/test_observability_contract.py tests/test_observability.py tests/test_api_runner.py tests/test_edge_runner.py tests/test_token_api.py tests/test_quota_reconciliation.py tests/test_reconciliation_runner.py tests/test_registry_proxy.py` | passed; 141 |
| Full regression after runtime metric core | `uv run pytest -q` | passed; 507 |
| Quota-admission observability focused regression | `uv run pytest -q tests/test_quota_admission.py tests/test_observability.py tests/test_observability_contract.py tests/test_edge_runner.py tests/test_registry_proxy.py` | passed; 112 |
| Full regression after quota-admission metrics | `uv run pytest -q` | passed; 515 |
| Direct edge operational surface | `uv run pytest -q tests/test_edge_runner.py tests/test_observability.py tests/test_quota_admission.py tests/test_registry_proxy.py` | passed; 60 |
| Kolla direct API/edge scrape contract | `make -C poc/kolla-ansible-role verify` | passed; 78 |
| Full regression after direct API/edge scrape boundary | `uv run pytest -q` | passed; 515 |
| Distribution metrics proxy focused regression | `uv run pytest -q tests/test_registry_metrics_runner.py tests/test_config_validator.py` | passed; 20 |
| Full regression after Distribution metrics isolation | `uv run pytest -q` | passed; 525 |
| Kolla Distribution metrics isolation contract | `make -C poc/kolla-ansible-role verify` | passed; 85 |
| Periodic reconciler management focused regression | `uv run pytest -q tests/test_observability.py tests/test_quota_reconciliation.py tests/test_reconciliation_runner.py tests/test_config_validator.py` | passed; 73 |
| Full regression after periodic reconciler management | `uv run pytest -q` | passed; 536 |
| Kolla periodic reconciler management contract | `make -C poc/kolla-ansible-role verify` | passed; 88 |
| Prometheus rule syntax | `promtool check rules ansible/roles/coffer/templates/prometheus-coffer.rules.j2` | passed; 14 rules |
| Observability artifact/runtime focused regression | `uv run pytest -q tests/test_observability_artifacts.py tests/test_observability_contract.py tests/test_observability.py tests/test_reconciliation_runner.py` | passed; 99 |
| Full regression after operator observability assets | `uv run pytest -q` | passed; 541 |
| Kolla observability enable/disable lifecycle | `make -C poc/kolla-ansible-role verify` | passed; 96 |
| Stage 6 GC/retention source and contract inventory | Exact Distribution v3.1.1 source plus official Distribution, OCI, and Ceph documentation | passed; upstream ownership and fail-closed candidate boundary fixed |
| Pure coordinated GC/retention model | `uv run pytest -q tests/test_gc_retention_state_machine.py` | passed; 46 |
| Full regression after GC/retention state model | `uv run pytest -q` | passed; 587 |
| Fixture-only coordinated GC lifecycle | `uv run pytest -q tests/test_gc_retention_state_machine.py tests/test_gc_retention_lifecycle_cli.py` | passed; 60 |
| Full regression after fixture-only GC lifecycle | `uv run pytest -q` | passed; 601 |
| Exact-release GC output normalizer | `uv run pytest -q tests/test_gc_collector_output.py tests/test_gc_retention_state_machine.py tests/test_gc_retention_lifecycle_cli.py` | passed; 75 |
| Full regression after GC output normalizer | `uv run pytest -q` | passed; 616 |
| Filesystem GC adapter/model regression | `uv run pytest -q tests/test_gc_filesystem_fixture.py tests/test_gc_collector_output.py tests/test_gc_retention_state_machine.py tests/test_gc_retention_lifecycle_cli.py` | passed; 84 |
| Disposable exact-image filesystem GC | persistent-PTY `make -C poc/gc-retention/filesystem verify` | passed; candidates 5, survivors 9, reclaimed 613 bytes, restore passed, residue 0 |
| Full regression after filesystem GC | `uv run pytest -q` | passed; 625 |
| Pure load/soak state contract | `uv run pytest -q tests/test_load_soak_state_machine.py` | passed; 55 |
| Full regression after load/soak state contract | `uv run pytest -q` | passed; 680 |
| Fixture-only load/soak lifecycle | `uv run pytest -q tests/test_load_soak_state_machine.py tests/test_load_soak_lifecycle_cli.py` | passed; 63 |
| Full regression after load/soak lifecycle | `uv run pytest -q` | passed; 688 |
| Canonical load evidence verifier | `uv run pytest -q tests/test_load_soak_state_machine.py tests/test_load_soak_lifecycle_cli.py tests/test_load_soak_evidence.py` | passed; 77 |
| Full regression after load evidence verifier | `uv run pytest -q` | passed; 702 |
| Raw OCI driver local TLS contract | `env -u GOROOT mise x go@1.25.3 -- go test -race ./...` in `poc/load-soak/driver` | passed; 15 top-level tests |
| Raw OCI driver static analysis | `env -u GOROOT mise x go@1.25.3 -- go vet ./...` in `poc/load-soak/driver` | passed |
| Loss-safe upload-status reconciliation | `env -u GOROOT mise x go@1.25.3 -- go test -race -count=1 ./...` in `poc/load-soak/driver` | passed; 18 top-level tests |
| Owner-only raw OCI executable | `env -u GOROOT mise x go@1.25.3 -- go test -race -count=1 ./...` in `poc/load-soak/driver` | passed; 23 driver plus 2 command tests |
| Raw OCI executable build/static analysis | `env -u GOROOT mise x go@1.25.3 -- go vet ./...`; `go build ./cmd/coffer-raw-oci-driver` | passed |
| Raw manifest/blob-read integrity | `env -u GOROOT mise x go@1.25.3 -- go test -race -count=1 ./...` in `poc/load-soak/driver` | passed; 29 driver plus 2 command tests |
| Nine-operation invocation and cross-mount | `env -u GOROOT mise x go@1.25.3 -- go test -race -count=1 ./...` in `poc/load-soak/driver` | passed; 35 driver plus 2 command tests |
| Artifact/referrers and abandoned uploads | `env -u GOROOT mise x go@1.25.3 -- go test -race -count=1 ./...` in `poc/load-soak/driver` | passed; 42 driver plus 2 command tests |
| Five real-client adapter contracts | `uv run pytest -q tests/test_load_client_contract.py` | passed; 17 |
| Full regression after real-client adapters | `uv run pytest -q` | passed; 719 |
| Owner-only real-client runner | `uv run pytest -q tests/test_load_client_run.py` | passed; 9 |
| Full regression after owner-only client runner | `uv run pytest -q` | passed; 728 |
| Canonical load telemetry adapter | `uv run pytest -q tests/test_load_soak_telemetry.py` | passed; 33 |
| Full regression after load telemetry adapter | `uv run pytest -q` | passed; 761 |
| Deterministic load execution manifest | `uv run pytest -q tests/test_load_soak_plan.py` | passed; 23 |
| Full regression after execution manifest | `uv run pytest -q` | passed; 784 |
| Fixture-only checkpointed orchestrator | `uv run pytest -q tests/test_load_soak_orchestrator.py` | passed; 15 |
| Full regression after fixture orchestrator | `uv run pytest -q` | passed; 799 |
| Fail-closed runtime capability manifest | `uv run pytest -q tests/test_load_soak_runtime_manifest.py` | passed; 14 |
| Full regression after runtime manifest | `uv run pytest -q` | passed; 813 |
| Control/token/quota local TLS core | pinned Go 1.25.3 `go test -race -count=1 ./...`; `go vet ./...` in `poc/load-soak/control` | passed; 4 top-level tests |
| Runtime manifest after control core | `uv run pytest -q tests/test_load_soak_runtime_manifest.py` | passed; 14; runtime gaps 9 |
| Full Python regression after control core | `uv run pytest -q` | passed; 813 |
| Owner-only control load executable | pinned Go 1.25.3 `go test -race -count=1 ./...`; `go vet ./...`; `go build ./cmd/coffer-control-load` in `poc/load-soak/control` | passed; 11 control plus 2 command tests |
| Raw driver after shared output strengthening | pinned Go 1.25.3 `go test -race -count=1 ./...`; `go vet ./...` in `poc/load-soak/driver` | passed |
| Runtime manifest after control CLI | `uv run pytest -q tests/test_load_soak_runtime_manifest.py` | passed; 14; runtime gaps 9 |
| Full Python regression after control CLI | `uv run pytest -q` | passed; 813 |
| Owner-only profile/ramp executor | `uv run pytest -q tests/test_load_profile_run.py` | passed; 15 |
| Broader load matrix after profile executor | profile, plan, orchestrator, runtime manifest, state machine, and evidence tests | passed; 136 |
| Full Python regression after profile executor | `uv run pytest -q`; `uv run pytest --collect-only -q` | passed; 828 collected |
| Serial recovery-first fault executor | `uv run pytest -q tests/test_load_fault_run.py` | passed; 16 |
| Broader load matrix after fault executor | fault, profile, plan, orchestrator, runtime manifest, state machine, and evidence tests | passed; 152 |
| Full Python regression after fault executor | `uv run pytest -q`; `uv run pytest --collect-only -q` | passed; 844 collected |
| Owner-only telemetry collector and canonical verifier | `uv run pytest -q tests/test_load_telemetry_collector_run.py tests/test_load_soak_telemetry.py tests/test_load_soak_runtime_manifest.py` | passed; 66 |
| Broader load matrix after telemetry collector | collector, telemetry, fault, profile, plan, orchestrator, runtime manifest, state machine, and evidence tests | passed; 204 |
| Full Python regression after telemetry collector | `uv run pytest -q`; `uv run pytest --collect-only -q` | passed; 863 collected |

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
  separately gated. The approved destructive filesystem fixture is complete;
  real RGW collection remains gated by released dependencies and the fresh
  pilot transaction.

## Handoff

- Current state: Stage 5 is complete and committed. Stage 6 has deterministic
  upstream release gates plus an accepted local maintenance broker/session
  design. The opt-in generated Kolla recipient/private-frontend fixture and
  trusted workload adapter and fixture-only lifecycle are complete; defaults
  and reconciliation remain disabled. The provenance-bound S3 inventory helper
  plus the pure state model and fixture-only data-protection lifecycle are
  complete. The canonical restored SQL/RGW backup verifier now gates the
  lifecycle through an ordered no-network adapter seam. The controlled
  filesystem GC/restore gate is complete with live exact-image evidence.
  Real RGW lifecycle evidence and current stable dependencies remain blocked;
  no real identity, credential, certificate, endpoint, or remote state
  changed.
- Exact next action: Add
  `poc/load-soak/collector/native_surfaces.py`. Parse bounded Prometheus HTTP
  API and strict HAProxy, mysqld-exporter, Ceph mgr/RGW, and node-exporter
  responses from their exact verified-TLS URLs into the seven internal
  surface schemas. Pin query/metric/label allowlists, refuse missing or extra
  series, and prove each parser with captured local TLS fakes only.
- Questions requiring user input: None for the next local adapter milestone.
  The user has already authorized atomic milestone publication and the bounded
  disposable Stage 6 sequence; exact safety and release gates
  remain fail closed.
