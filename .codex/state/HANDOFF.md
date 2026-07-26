# Coffer Handoff

- Updated: 2026-07-26
- Status: plan 0019 active; local production observability, disposable
  filesystem GC/restore, load model/lifecycle, and canonical evidence verifier
  complete; raw OCI and five real-client execution boundaries complete;
  telemetry, deterministic plan, and fixture orchestrator complete; runtime
  manifest, control/token/quota protocol core, and owner-only control CLI
  complete; checkpointed profile/ramp and recovery-first fault executors
  complete; owner-only telemetry collection boundary, native
  Prometheus/exporter parser seam, versioned native target, and exact-schema
  collector dispatch complete; no-network disposable-pilot target renderer
  and phase-bound auxiliary evidence compiler plus private TLS evidence server,
  source-summary acquisition, and local secret/workload artifact collectors
  complete; quota/reconciliation source mapping complete; read-only control
  SQL evidence snapshot and claim-version binding complete; bounded quota
  transaction-attempt observability and quota/reconciliation control artifact
  collection complete; Galera transaction artifact collection complete; RGW
  evidence source mapping and no-network artifact collection complete;
  six-surface phase preparation and verified-HTTPS live RGW evidence adapter
  plus qualified disposable-pilot schedule and checkpointed fixture executor
  plus exact-prefix cleanup, non-synthetic RGW, and external fault action
  contracts complete; phase materializers next
- Completed execution plans: `docs/exec-plans/0001-product-discovery.md`, `docs/exec-plans/0003-barbican-kms-quota-poc.md`, `docs/exec-plans/0004-shared-sql-quota-reconciliation.md`, `docs/exec-plans/0005-multi-worker-reconciliation.md`, `docs/exec-plans/0006-reconciliation-runner.md`, `docs/exec-plans/0007-unified-control-schema.md`, `docs/exec-plans/0008-existing-content-inventory.md`, `docs/exec-plans/0009-transactional-inventory-import.md`, `docs/exec-plans/0010-post-import-ledger-comparison.md`, `docs/exec-plans/0011-authenticated-live-inventory-comparison.md`, `docs/exec-plans/0012-synthetic-inventory-scale-characterization.md`, `docs/exec-plans/0013-kolla-deployment-topology.md`, `docs/exec-plans/0014-kolla-runtime-images.md`, `docs/exec-plans/0015-kolla-ansible-operator-role.md`, `docs/exec-plans/0016-kolla-aio-end-to-end.md`, `docs/exec-plans/0017-production-image-remediation.md`, `docs/exec-plans/0018-kolla-multinode-ha-pilot.md`
- Superseded execution plan: `docs/exec-plans/0002-thin-vertical-poc.md`
- Active execution plan: `docs/exec-plans/0019-stage6-production-promotion.md`

## Current Objective

Plan 0019 is active. Stage 6 is converting the completed Stage 5 HA pilot into
a fail-closed production-candidate operator baseline. The first workstream
qualifies only signed stable Distribution and Ceph/RGW inputs; maintenance
identity, data protection/cutover, observability, controlled GC, and load may
progress independently before they converge in a fresh Kolla multinode pilot.

The approved teardown removed every exact Stage 5 identity, credential,
bucket, object namespace, guest, volume, and network. Repeated status reports
zero Stage 5 residue and a complete marker. Before/after signatures preserve
18 unrelated domains, eight unrelated networks, three unrelated Coffer-pool
volumes, host containers/services, and the running autostart-disabled
`coffer-rgw-poc`.

Stage 5 remains complete at clean commit `610b576`. Post-destroy regression
passes 251 tests, 52 role-contract checks, dependency lock, compilation, shell,
Go, structured-document/link, Gitleaks, and diff gates. ADR 0006 still blocks
signed Distribution v3.1.1, and released Ceph Tentacle v20.2.2 still blocks
encrypted zero-byte moves. Ceph PR 69277 merged the required encrypted-copy
backport to the protected `tentacle` branch on 2026-07-22, but no stable point
release contains it yet.

## Plan 0019 Activation

- Recovered the clean Stage 5 boundary at `610b576`; no empty or duplicate
  Stage 5 checkpoint is required.
- Activated `docs/exec-plans/0019-stage6-production-promotion.md` with explicit
  dependency, maintenance-identity, data-protection/cutover, observability, GC,
  load/soak, production-candidate pilot, teardown, and release-evidence gates.
- Official release metadata checked on 2026-07-25 still reports signed
  Distribution v3.1.1 and Ceph Tentacle v20.2.2 as the stable inputs.
- Ceph PR 69277 is merged to protected branch `tentacle` at merge commit
  `c6fc9801f55e24152f0e934b2ddc3e5cda33d63e`. It is an actionable upstream
  release signal, not released production evidence.
- Stage 6 will not recreate the six-VM lab until cheaper dependency, identity,
  and data-protection qualification gates pass.
- Added `poc/production-images/check_upstream_readiness.py` and ten
  fixture-driven tests. The classifier separates merged branch fixes, released
  candidates, and exact qualified evidence; scopes the Ceph ancestry to the
  selected Tentacle v20.2 series; and reports `blocked` for Distribution
  v3.1.1 and Ceph v20.2.2.
- The first live run failed safely because GitHub Compare has no
  `head_commit` object. The corrected implementation obtains the Ceph release
  revision from the official commit endpoint and uses Compare only for exact
  fix ancestry.
- All 261 Python tests, 52 companion-role contract checks, compilation, live
  metadata classification, and diff checks pass.
- Added `docs/research/stage6-maintenance-identity.md`. It records that the
  installed reconciler has verified TLS but no Bearer provider, is disabled by
  default and throughout Stage 5, and therefore has no authenticated live
  Distribution evidence.
- The recommended but unaccepted boundary is a dedicated maintenance service
  user, `service` plus `registry_maintenance` roles, finite access-rule
  application credential, internal Coffer broker that emits one pull-only
  repository JWT from server-resolved SQL authority, and a private mTLS
  HAProxy frontend. The signer remains API-only and the public edge must deny
  `/v1/internal/`.
- The user approved that maintenance identity architecture for pure local
  proof. Added proposed ADR 0015 to fix the exact identity, role, access-rule,
  private mTLS, edge denial, server-side authority, pull-only JWT,
  rotation/revocation, signer-recipient, failure, and secret-safety contracts.
  This approval does not create or authorize delivery of a real identity,
  credential, Barbican secret, certificate, endpoint, Kolla recipient, remote
  deployment, or production-data operation. ADR 0015 remains proposed until
  its pure local acceptance tests pass.
- No credential, role, endpoint, ACL, certificate, secret recipient, policy,
  or runtime setting changed.
- Added the pure local maintenance token core and optional internal resource.
  Exact maintenance user/project/roles, restricted application credential and
  access rule, trusted workload context, live SQL reconciliation claim/version/
  worker/lease, server-resolved route, pull-only JWT, public-edge denial, and
  fixed secret-safe failures now have local evidence. The product builder does
  not enable the resource.
- Full regression now passes 291 Python tests and 52 Kolla companion-role
  checks. Compilation and diff checks pass.
- Added revision `0005_maintenance_comparison_sessions`. Finite idempotent
  sessions now bind the exact imported digest, workload, writer-exclusion
  evidence reference, and expiry; active reconciliation claims and stale,
  mismatched, completed, revoked, or expired sessions fail closed. Downgrade
  refuses to discard retained session evidence.
- ADR 0015 is accepted for the architecture and pure local contract. Production
  configuration, mTLS workload adapter, owner-only secret delivery, and real
  identity/private-TLS lifecycle evidence do not exist.
- Full regression now passes 308 Python tests. The 105-test focused maintenance,
  session, schema, import, and live-inventory matrix also passes.
- Added `docs/research/stage6-maintenance-secret-delivery.md`. It maps the
  existing mode-0600/no-log Kolla source boundary and disposable Barbican
  pattern to distinct per-replica application credentials and mTLS keys,
  exact recipients, owner-only materialization, overlap rotation, revocation,
  and teardown. It identifies a required trusted adapter from HAProxy-verified
  certificate identity to the server-side WSGI workload value; an HTTP header
  alone is rejected.
- The research changed no Kolla variable, recipient, identity, credential,
  certificate, Barbican object, frontend, endpoint, or remote state.
- Completed the opt-in, fixture-only Kolla maintenance contract. Generated
  host-addressed credential/client-key inputs now have exact owner/mode/link,
  uniqueness, CA, certificate/key-pair, and recipient checks. Only the disabled
  reconciler fixture receives those generated inputs.
- Added a private internal-VIP HAProxy fixture requiring the exact maintenance
  client CA and SHA-256 certificate fingerprint, accepting only the broker POST
  path, and verifying backend TLS. The ordinary API frontend strips workload
  assertions and denies `/v1/internal/`; the public edge denial remains.
- Wired the accepted maintenance policy, SQL authorities, broker/resource, and
  trusted proxy adapter into the product builder behind a disabled-by-default
  `[maintenance]` switch. The adapter discards raw headers and preexisting WSGI
  values unless the direct peer and mapped workload are both allowlisted.
- Full regression passes 310 Python tests; the focused maintenance/config/API
  matrix passes 115; the pinned Kolla companion role passes 68 checks.
  Compilation and diff checks pass. No real identity, credential, certificate,
  Barbican object, endpoint, remote service, or reconciliation setting changed.
- Added `poc/maintenance-identity/README.md`. The disposable lifecycle now has
  immutable-ID resource and workload/generation allowlists, exact finite
  Keystone/access-rule and project-private Barbican contracts, per-workload
  mTLS mapping, owner-only atomic state/evidence, generation-overlap rotation,
  bounded failure tests, and reverse-dependency teardown. Prefix deletion,
  lost-state mutation, broader roles, in-place rotation, and retained secret
  values are explicitly refused.
- The lifecycle contract changed no identity, role, assignment, credential,
  secret, certificate, mapping, endpoint, session, remote file, or
  infrastructure resource. The user authorized autonomous milestone commits
  and pushes; the previously accumulated 134 commits were published to
  `jaehanbyun/coffer` `main` under the verified `jaehanbyun` account.
- Added the versioned lifecycle topology and pure state machine. It validates
  complete exact resources, ordered two-generation rotation, bounded drain,
  immutable-ID cleanup ownership, reverse-dependency teardown, zero residue,
  and secret-safe hashed evidence without any external service adapter.
- Twenty-five focused lifecycle tests and all 335 Python tests pass. The Kolla
  companion role still passes 68 checks; compilation, topology JSON parsing,
  and diff checks pass.
- Added the fixture-only lifecycle CLI. Read-only preflight/status, atomic
  owner-only state, nonblocking locks, fixture-gated mutations, exact target
  replay, hashed cleanup, fixed errors, two-generation rotation, failure
  verification, and zero-residue teardown pass 11 focused tests. Full Python
  regression passes 346 tests; compile, JSON, CLI-help, and diff checks pass.
- The plan's no-real-credential maintenance lifecycle task is complete. The
  final Stage 6 maintenance done criterion still requires real private-TLS,
  credential/Barbican rotation, outage, audit, and residue evidence in the
  fresh disposable pilot.
- Added `poc/data-protection/README.md`. It fixes exact-release S3 helper
  construction, immutable ownership, writer exclusion, immediately restored
  SQL/RGW backups, double inventory, import/comparison, admission cutover,
  rollback/recovery, bounded failures, and exact residue teardown.
- Source inspection confirms the existing helper is filesystem-only.
  Production-compatible enumeration must parse the exact Distribution config,
  create the registered S3 driver, and construct only the storage namespace;
  it must not start the registry application or its purge/event/HTTP behavior.
- Implemented that S3 adapter without connecting to RGW. Exact release/config
  digest, owner-only file, static credentials, verified HTTPS, v4/path style,
  root prefix, no middleware/proxy/ambient credentials, and finite timeout are
  enforced before the shared two-scan core. Failures emit fixed categories.
- Seven Go tests and vet, all 346 Python tests, and the original filesystem
  Podman inventory fixture pass. The fixture again proved storage/SQL
  nonmutation and zero residue; the Podman VM was restored to stopped.
- The host exposed an ambient Go 1.26.5 `GOROOT` while mise supplied Go 1.25.3.
  Go verification succeeded with only `GOROOT` removed for those commands;
  no shell configuration was changed.
- Added S3 evidence/inventory v2. Exact Distribution revision plus helper,
  module graph, configuration, endpoint, bucket, and root hashes now survive
  verifier output and are validated by import; filesystem v1 remains
  byte-compatible.
- Added and built the scratch/non-root helper image locally on ARM64. The
  image ran as `65532:65532`, exposed only the exact helper entry point, and
  passed no-network CLI inspection. The exact image was deleted, no tagged
  helper image/container remains, and Podman is stopped.
- Fifty-three focused inventory/import/image tests, eight Go tests and vet,
  all 359 Python tests, compilation, and diff checks pass. This remains local
  evidence only; no RGW connection or signed/x86_64 promotion occurred.
- Added the versioned data-protection topology and pure state machine. Exact
  phase evidence/history, immutable ownership, writer exclusion, restored
  SQL/RGW manifests, equal inventory scans, provenance-bound cutover,
  manifest-bound rollback, fixed failures, dependency cleanup, all fixed
  zero-residue categories, and unchanged unrelated state now fail closed.
- Twenty-seven focused model tests, all 386 Python tests, and all 68 Kolla
  companion-role checks pass. Compilation, topology parsing, diff checks, and
  Gitleaks pass. The model performs no network, OpenStack, registry, RGW, SQL,
  KMS, Kolla, VM, or remote-file operation.
- Added the fixture-only data-protection lifecycle CLI. It replays every
  ordered phase through owner-only atomic state under a nonblocking lock,
  refuses unsafe existing paths or any non-fixture mutation, hashes immutable
  cleanup IDs, reaches the complete zero-residue terminal state, and repeats
  teardown idempotently.
- Twelve lifecycle tests plus 27 model tests and all 398 Python tests pass.
  Compilation, fixture parsing, CLI help, and diff checks pass. No external
  client, network, remote service, or infrastructure resource was used.
- Added the canonical backup bundle verifier and connected it to the lifecycle
  gate. Exact SQL artifact/content/schema/recovery and isolated restore
  evidence plus complete versioned RGW objects/delete markers, SSE-KMS
  metadata, pagination, multipart absence, and isolated inventory/pull
  equality are now mandatory.
- The owner-only CLI refuses unsafe input/output paths and emits fixed
  secret-safe failures. Twenty-nine backup, 13 lifecycle, and 27 model tests
  pass together; all 428 Python tests pass. Compilation, JSON/CLI, and diff
  checks pass. No SQL/S3/KMS/network/subprocess or remote call occurred.
- Added the no-network backup adapter seam. Exact fixture client types enforce
  SQL inspect/backup/restore, bounded versioned-S3 pagination/copy/restore,
  canonical bundle reconstruction, and verifier/state ordering. Lookalike or
  future real clients fail closed.
- Eleven adapter plus 69 backup/lifecycle/model tests pass together (80
  focused); all 439 Python tests pass. Static inspection finds no network,
  SQL/S3, HTTP, socket, or subprocess runtime import.
- Live backup execution remains part of the fresh disposable convergence
  pilot after a target contract and acceptable released dependencies exist.
  No external resource was touched.
- Added `docs/research/stage6-observability.md`. Source/config inspection
  confirms process-local API metrics plus multiple workers and a VIP scrape
  are incomplete; edge/reconciler/Distribution and rules/dashboard/SLO
  surfaces are also missing.
- The Stage 6 candidate uses one API/edge worker per container, replica
  scale-out, direct verified-TLS per-replica scrapes, private Distribution and
  reconciler metrics, Kolla native HAProxy/MariaDB metrics, and external Ceph
  mgr metrics. It fixes bounded labels, log/leak rules, initial SLO budgets,
  alerts, dashboard rows, and restart/stale-series acceptance.
- Official Prometheus, Kolla-Ansible, Distribution, and Ceph documents were
  checked. No local runtime configuration or external state changed.
- Added the six topology recording rules, eight bounded alerts, exact
  eight-row `Coffer Operator` Grafana dashboard, and alert runbook. `promtool`
  accepts all 14 rules, the dashboard references every recording rule without
  tenant/content variables, and artifact tests bind names, labels,
  annotations, runbook anchors, and schema to the versioned topology.
- Kolla metrics now require Prometheus, Alertmanager, and Grafana. Exact
  mode-0640 rule/dashboard files are installed on the controller and
  Prometheus/Grafana reconfigure on enable and disable transitions.
- The first disable lifecycle exposed that generic enabled-service filtering
  left the old registry metrics sidecar running. The role now removes that
  exact disabled Coffer-owned container. The complete rerun proves scrape,
  rule, dashboard, and sidecar removal; idempotent repeated disable; exact
  re-enable restoration; secret-safe output; and zero fixture residue.
- Ninety-nine focused observability/runtime tests, all 541 Python tests, and
  all 96 pinned Kolla lifecycle checks pass. Local Stage 6 observability
  implementation is complete; fresh-pilot target, fault-alert, rolling
  compatibility, and teardown evidence remains in the convergence pilot.
- Added `docs/research/stage6-gc-retention.md`. Exact Distribution v3.1.1
  source confirms stop-the-world recursive mark/sweep through the selected
  driver, a human CLI output contract, and global `--delete-untagged`
  semantics. The current role has no global fence/read-only/one-shot/restore
  lifecycle.
- The candidate keeps upstream reachability, forbids `--delete-untagged`,
  permits only explicit digest deletion, requires every writer/background
  mutator fenced, binds two equal dry runs to one finite authorization, and
  proves shared/index/digest-only/referrer survival plus isolated restore.
- Distribution current-visible reclamation, complete versioned-RGW
  objects/delete markers, and Ceph physical usage are separate evidence. RGW
  lifecycle, internal GC, and experimental orphan cleanup remain separately
  owned. No live data or service changed.
- Added proposed ADR 0017 and the versioned pure GC topology/state machine.
  The exact v3.1.1 revision, sixteen phases, immutable ownership, compound
  writer fence, complete backup/baseline, two equal candidate sets, bounded
  single-use authority, survivor/SQL checks, separated reclamation, isolated
  KMS restore, thirty failure refusals, tamper history, secret-safe public
  evidence, and zero residue are fixed.
- Forty-six focused pure GC tests and all 587 Python tests pass. Compilation,
  topology JSON, no-network/import inspection, and diff checks pass. No
  registry, S3, SQL, KMS, subprocess, container, network, credential, or
  remote resource was used. ADR 0017 remains proposed.
- Added the fixture-only GC lifecycle CLI. Owner-only atomic state,
  nonblocking/no-follow locking, explicit fixture adapter, exact phase replay,
  bounded fake collection, single-use authority, secret-safe status/cleanup
  plan, idempotent teardown, and unchanged-state failures are executable.
- Sixty combined GC model/CLI tests and all 601 Python tests pass. Compilation,
  CLI/JSON, static no-network/SQL/S3/subprocess inspection, and diff checks
  pass. No registry binary or external resource was used; ADR 0017 remains
  proposed.
- Corrected the baseline candidate semantics to four blobs, zero manifests,
  and two layer links: with global untagged deletion forbidden, explicit
  manifest DELETE removes enumeration authority and its content is swept as
  unmarked blobs/links.
- Added the exact-v3.1.1 dry-run output normalizer and captured-shape synthetic
  fixture. It
  binds reviewed line shapes/release/order/counts, hashes identities, and
  refuses manifest candidates, retained intersection, drift, duplicates,
  unknown/malformed/secret-like text, and excessive candidates.
- Seventy-five combined GC parser/model/CLI tests and all 616 Python tests
  pass. No collector subprocess or external resource was used; ADR 0017
  remains proposed.
- Added the guarded exact-v3.1.1 filesystem GC fixture. It builds a retained
  shared/index/digest-only/subject/referrer graph plus one explicitly deleted
  manifest graph, snapshots only the new temporary bind mount, and runs the
  collector without network or global untagged deletion.
- Two dry runs produced the same exact five-candidate set. One 900-second
  candidate-bound authorization was consumed once; replay failed closed; the
  real collector removed three blobs and two repository layer links.
- Nine survivor classes and the shared blob in both repositories passed after
  collection. The snapshot copy restored byte-for-byte, 613 logical
  filesystem bytes were reclaimed, and exact teardown reported zero container,
  network, lock, file, and state residue.
- Failure-safe iterations corrected only the exact `warn` log-level contract,
  exited-container health detection, shared bind relabel plus one
  `DAC_OVERRIDE` capability, and the valid digest-only `NAME_UNKNOWN` tag
  response. Every failed run cleaned to zero residue before retry.
- Eighty-four focused GC tests and all 625 Python tests pass. Compose, Bash,
  ShellCheck, compilation, diff, and the live exact-image fixture pass. No
  S3/RGW, SQL, KMS, Keystone, Kolla, credential, or remote host was used; ADR
  0017 remains proposed for the production RGW boundary.
- Added `docs/research/stage6-load-soak.md`. It separates real-client
  compatibility from a deterministic raw OCI concurrency driver and fixes
  exact content shapes, smoke/qualification/two-hour soak profiles, a measured
  saturation ramp, latency/resource gates, serial fault windows, Galera/quota
  invariants, bounded evidence, and secret/residue rules.
- Existing Stage 5 evidence is reusable for functional fault contracts but
  does not claim sustained load, latency, capacity, ORAS, or
  containerd/nerdctl compatibility. No load or external mutation occurred.
- Added the load/soak topology and pure state machine. Qualified stable
  dependencies on aarch64 and x86_64 are a mandatory early fence; exact
  profiles, client/operation/content matrices, ramp, latency/resource/
  availability gates, ten fault recoveries, Galera/quota/data invariants,
  metrics, tamper history, secret safety, and eighteen zero-residue categories
  now fail closed.
- Fifty-five focused tests and all 680 Python tests pass. Compilation,
  topology parsing, static no-runtime/external-adapter inspection, and diff
  checks pass. No external client or resource was used.
- Added the fixture-only load lifecycle. It replays all thirteen phases
  through owner-only atomic state under a nonblocking lock, marks dependency
  and result evidence synthetic, rejects non-fixture adapters and contract
  drift, resumes idempotently, detects tampering/contention, and cleans its
  exact state to zero residue.
- Sixty-three focused state/lifecycle tests and all 688 Python tests pass.
  Compilation, topology/fixture JSON, static no-external-adapter inspection,
  and diff checks pass. No load or external resource was used.
- Added the canonical production-mode load evidence verifier. It requires
  exact independently supplied qualified release/image/configuration/client/
  driver bindings and all thirteen phase records, replays the state machine,
  and returns only stable hashes. Synthetic, unknown, noncanonical, drifted,
  incomplete, identity-bearing, or secret-like evidence is refused.
- Seventy-seven focused load tests and all 702 Python tests pass. The refreshed
  official metadata classifier still reports Distribution v3.1.1 and Ceph
  v20.2.2 blocked, so no live load or fresh pilot is permitted yet.
- Added the standalone standard-library Go raw OCI core. It uses explicit CA
  trust and TLS 1.2+, exact same-origin Bearer acquisition, bounded response
  bodies and retries, deterministic replayable streams, monolithic and
  chunked upload, digest/range/location checks, cancellation, fixed
  secret-safe aggregates, and atomic mode-0600 canonical result files.
- Fifteen top-level Go contract tests pass under the race detector and `go
  vet`. Local `httptest` TLS is the only target. Eight simultaneous uploads
  are aggregated safely; untrusted TLS, unsafe configuration, cross-origin or
  traversal locations, malformed challenge, retry exhaustion, cancellation,
  response overflow, symlink output, and credential-bearing errors fail
  closed. Chunk start/PATCH failures are deliberately not replayed blindly.
- Added bounded loss-safe PATCH recovery using the official Distribution
  upload-status GET. After transport loss or 502/503/504, only the exact prior
  offset permits a bounded resend and only the exact committed offset
  permits forward progress. Partial, ambiguous, malformed, cross-origin, or
  traversal state fails closed; chunk-start failures still never create an
  untracked retry.
- Eighteen top-level Go tests pass under the race detector and `go vet`.
  Local TLS tests cover response-lost-after-commit, response-before-commit,
  status retry exhaustion, range/location drift, cancellation, and byte-exact
  completion without duplicate append. No external registry was contacted.
- Added `coffer-raw-oci-driver`. Its sole input is one absolute owner-only
  invocation path; invocation, CA, credential, and independently produced
  readiness files must be mode 0600, regular, owner-matched, single-link,
  absolute, and distinct. No proxy, environment, or argument supplies a
  credential.
- Exact SHA-bound `coffer.upstream-readiness/v1` must report
  `candidate-qualified` for Distribution and Ceph, verified release/fix
  predicates, the accepted baselines/fix identity, newer exact versions, and
  empty reasons. Output-directory preflight occurs before network use.
  Current blocked official evidence therefore cannot run this executable
  against a registry.
- Twenty-three driver plus two command tests pass under the race detector;
  `go vet` and command build pass. A local TLS end-to-end invocation writes one
  canonical mode-0600 aggregate with no URL, repository, seed, username,
  password, token, or temporary residue. Blocked/hash-drifted readiness,
  unsafe modes, symlink/hardlink boundary, path aliasing, unknown fields,
  unsafe output, and fixed-error CLI paths fail closed before network access.
- Added OCI image manifest/index PUT, HEAD, and GET plus blob HEAD and
  full/range GET. Manifest bytes are bounded to 4 MiB and must declare schema
  version 2 plus the exact media type. Publication and reads verify locally
  computed digest, content type, length, exact path, and same-origin location.
- Blob reads compare the bounded response stream byte-for-byte against an
  offset-capable deterministic generator, validate full/range status and exact
  `Content-Range`, reject redirects, and honor cancellation without retaining
  payloads. Result aggregates remain fixed `manifest-publish`,
  `manifest-read`, and `blob-read` classes.
- Twenty-nine driver plus two command top-level tests pass under the race
  detector and `go vet`. Local TLS covers publish/head/get, full/range reads,
  unaligned deterministic windows, body/digest/range/location drift, redirect
  refusal, cancellation, and invalid-input preflight. No external target was
  contacted.
- Expanded the exact invocation schema to nine operations: monolithic and
  resumable upload; blob HEAD, full GET, range GET, and same-project
  cross-mount; manifest PUT, HEAD, and GET. Operation-specific seed, size,
  chunk, range, manifest, reference, and source fields cannot be mixed.
  Manifest inputs reuse the owner-only single-link boundary and are wiped from
  the retained runtime buffer after execution.
- Cross-mount Bearer acquisition now requests destination `pull,push` and
  source `pull` together while validating the server challenge against the
  destination scope. Both repository routes must be canonical and share the
  exact project UUID; cross-project or same-repository requests fail before
  network use.
- A native 201 mount requires exact digest and same-origin blob location. A
  202 fallback requires an empty exact upload range and same-origin opaque
  location, then the driver cancels that upload and records `fallback`.
  Cleanup failure is fatal and never reported as a completed mount.
- Thirty-five driver plus two command tests pass under the race detector and
  `go vet`. Invocation execution covers manifest GET, blob range GET, and
  cross-mount; native/fallback scope, cleanup, cross-project, operation-field,
  digest/location, and no-network refusals pass. No external target changed.
- Added subject-bearing artifact publication and exact OCI 1.1 Referrers
  disposition. A filtered native index requires the exact artifact descriptor.
  Only native 404 enters the standard fallback tag path, which preserves the
  bounded existing index, publishes when needed, and verifies both manifest
  digest and descriptor on read-back. Fallback remains a distinct result
  because its concurrent lost-update limitation is not hidden.
- Added the bounded abandoned-upload shape. Exactly two distinct partial
  uploads receive the same deterministic prefix and every known opaque
  location is cancelled on success or failure. Cleanup uses a finite context
  independent of the interrupted work request, and a known location from a
  malformed start response is still removed.
- The owner-only executable now exposes eleven operations. Forty-two driver
  plus two command top-level tests pass under the race detector and `go vet`;
  local TLS covers native/fallback and mismatch cases, two-upload/failure/
  malformed-start cleanup, new invocation dispatch, and retained identity
  safety. No external target or infrastructure changed.
- Pinned Docker 29.6.2, Podman 6.0.2, Skopeo 1.23.0, ORAS 1.3.3, nerdctl
  2.3.5, and containerd 2.3.3 with exact source revisions and verification
  disposition. Skopeo v1.23.0 remains explicitly unverified rather than being
  treated as supply-chain evidence.
- Added five real-client command adapters. They bind exact binary SHA-256,
  version, CA, owner-only credentials/artifacts, private target, canonical
  same-project route, expected digest, isolated state, finite timeout,
  streaming one-MiB output limit, process-group termination, fixed
  environment, and cleanup. Passwords enter only login stdin; no shell, proxy,
  ambient auth/home, or insecure transport flag is used.
- Docker/Podman/nerdctl cover tag/push/pull/inspect, Skopeo covers authenticated
  same-project copy/inspect, and ORAS covers exact-subject attach/discover/pull
  with separately retained native or fallback Referrers disposition. Docker
  also requires an identical read-only daemon CA input; live placement under
  `/etc/docker/certs.d` remains a pilot preflight.
- Seventeen local fake-executable tests pass. They prove all client command
  shapes, pin/input drift refusal, clean environment, stdin-only password,
  secret echo refusal, bounded output and timeout termination, CA/hosts state,
  exact version/digest parsing, cleanup after failure, and zero generated
  residue. No real client, daemon, containerd, registry, network, credential,
  or remote target changed.
- Full Python regression passes 719 tests after the real-client adapter
  boundary and bounded subprocess implementation.
- Added the owner-only client runner. Exact invocation/pins/readiness hashes,
  owner/mode/link/path boundaries, qualified Distribution/Ceph release
  predicates, canonical atomic mode-0600 output, fixed errors, and zero
  interruption/failure residue are enforced before a real target can run.
- Nine runner plus seventeen adapter tests pass. They include blocked
  readiness, pins drift, unsafe mode/symlink/path alias, command failure,
  SIGINT child termination, canonical output, and zero generated state. No
  real binary, daemon, registry, credential, network, or remote state changed.
- Full Python regression passes 728 tests after the owner-only runner.
- Added the canonical no-network load telemetry adapter. Exact
  before/during/after direct Prometheus target/rule/alert/restart/stale facts,
  Galera, RGW, quota, reconciliation, HAProxy, and six-host resource gates
  produce only hashes, counts, and the load metrics phase.
- Thirty-three focused telemetry tests and all 761 Python tests pass. Until a
  typed live collector exists, the adapter accepts only explicit fixture,
  synthetic evidence; a claimed production export fails closed. No service,
  network, credential, or remote state changed.
- Added the pure deterministic execution-manifest compiler. Exact qualified
  bindings expand into all six clients, twelve operations, nine content
  classes, three profiles, seven ramp levels, ten serial faults, transfer
  ceilings, lifecycle phases, and telemetry windows without claiming any
  executor ran.
- Twenty-three compiler tests and all 784 Python tests pass. Owner-only
  canonical output, deterministic hashes, version/topology/capability drift,
  and no-network/no-subprocess scope are proven.
- Added the fixture-only checkpointed orchestrator. It derives the exact
  29-step client/profile/ramp/fault/telemetry order, enforces step and
  cumulative budgets, checkpoints under a nonblocking lock, resumes after
  failure, and returns byte-identical synthetic terminal evidence.
- Fifteen orchestrator tests and all 799 Python tests pass. Live/lookalike
  executors, stale output, tampered state, unsafe files, lock contention, and
  over-budget evidence fail closed. No workload or external state changed.
- Added the fail-closed runtime capability manifest. Every one of 29 steps now
  declares its required schemas, owner, timeout, TLS/readiness/file boundary,
  source-contract hash, binary hash, and current disposition.
- Fourteen manifest tests and all 813 Python tests pass. The current baseline
  remains synthetic and blocked with twelve explicit gaps; all executable
  hashes are null because no runtime binary is qualified. No external state
  changed.
- Added the verified-TLS Go protocol core for Keystone application-credential
  token acquisition, Coffer repository control probing, standalone registry
  token acquisition, concurrent quota admission, and independent cleanup.
- Four race-enabled Go tests, `go vet`, and fourteen updated runtime-manifest
  tests pass. Control/token/quota are now contract-only instead of missing,
  reducing the runtime gap set from twelve to nine. No executable or live
  target is qualified.
- All 813 Python tests remain passing after the control core.
- Added the owner-only `coffer-control-load` executable and exact invocation
  boundary. It binds the running executable SHA, source-contract provenance,
  qualified readiness, explicit CA/application credential, distinct
  SHA-addressed manifests, exact quota outcomes, finite concurrency/timeout,
  target class, and canonical output before any request.
- Local TLS tests prove success, pre-network release/binary/manifest/output
  refusal, owner/mode/link/path boundaries, unknown-field refusal, duplicate
  manifest refusal, interruption, failure cleanup, fixed CLI output, and
  secret-safe canonical evidence. Eleven control and two command tests pass
  with the race detector; `go vet`, a command build, the shared raw-driver
  race/vet suite, 14 runtime-manifest tests, and all 813 Python tests pass.
  Real targets and both-architecture runtime qualification remain gated; the
  runtime manifest remains `ready=false` with nine gaps.
- Added the checkpointed owner-only profile/ramp executor. It revalidates the
  exact compiled step, binds one binary/invocation/source contract and cleanup
  owner for every operation, executes full-duration steady/burst or fixed-ramp
  waves, serializes quota contention to at most one child per wave, and
  atomically advances a replay-validated hash-chain state.
- Fifteen profile tests with actual local fake executables prove
  checkpoint/resume/idempotence, operation coverage, cadence, failure and
  transfer refusal, state tamper, preflight drift, interruption, process
  timeout/output bounds, fixed CLI status, and zero temporary residue. The
  broader load matrix passes 136 tests and all 828 Python tests pass. Profile
  entries are now source-hashed `contract-only`; the runtime manifest remains
  `ready=false` with nine unqualified executors.
- Added the serial recovery-first fault executor for all ten compiled windows.
  Exact binary/source/plan/target hashes, bounded non-secret adapter selectors,
  one active lock, full observation windows, replayable action checkpoints,
  recovery deadlines, fixed output, and zero temporary residue are enforced.
- Ambiguous inject, observe failure, interruption, and a lost process after
  injection recover then verify before returning failure. Successful rollback
  ends `failed-recovered` without output; failed/deadline recovery remains
  fail-closed. Sixteen local-executable tests pass. Fault steps are now
  source-hashed `contract-only`; live telemetry is the last missing schedule
  executor. The broader load matrix passes 152 tests and all 844 Python tests
  pass.
- Added the owner-only three-window telemetry collector. Exact source, CA,
  plan, target, session paths, phase order, distinct seven-surface HTTPS URLs,
  strict TLS/hostname, response size/shape, semantic snapshots, atomic
  hash-chain state, redacted per-phase results, and canonical final bundle are
  enforced.
- Arbitrary non-synthetic bundles remain refused. Independent live
  verification requires the final result to match the expected plan,
  collector source, target, bundle, snapshot, and history hashes. Nineteen
  collector tests pass against a real local TLS server; collector/telemetry/
  manifest tests pass 66, the broader load matrix 204, and all 863 Python
  tests pass.
- The current HTTPS endpoints expose normalized surface schemas. Native
  Prometheus API and HAProxy/MariaDB/Ceph/node exporter parsing was still open
  at this checkpoint. Telemetry entries are source-hashed `contract-only`; the
  runtime manifest still has nine unqualified executors and remains
  `ready=false`.
- Added the native telemetry parser seam and direct verified-TLS/no-proxy
  client. It normalizes exact Prometheus v1 query/rule, HAProxy, stock
  mysqld-exporter/Galera, Ceph mgr/ceph-exporter/RGW ingress, and node-exporter
  series into the seven existing payload shapes while refusing selected
  series/label/identity/rule drift.
- Galera readiness is reduced only from up, synced local state, matching state
  UUIDs, one shared cluster identity, and exact cluster size. CPU/session-OOM
  require Prometheus interval-query vectors; quota/claim/fencing,
  KMS/multipart, and workload-error facts remain explicit auxiliary evidence.
  Nothing is inferred from a non-equivalent metric.
- The normalized v1 target remains unchanged. A separately versioned native
  target must still bind exact PromQL/URL hashes and source/auxiliary
  allowlists before `collector/run.py` can select this seam. Fourteen native
  parser/TLS tests, 80 focused tests, the 253-test broad load matrix, and all
  878 Python tests pass.
- Concurrent focused/full verification exposed the existing Darwin
  exited-child `killpg()` `EPERM` race. Commit `a9c341d` reaps only that exact
  completed child and fails closed for a still-live inaccessible group. The
  noisy-child case passed 20 repetitions, all 16 profile tests pass, and the
  standalone 878-test regression passes.
- Added the separate `coffer.load-telemetry-native-target/v1`. Its canonical
  hash binds the exact Prometheus queries and PromQL text hashes, filtered
  rules, content types, every component/backend/Galera/RGW/node allowlist, and
  all phase-specific auxiliary evidence URLs while leaving normalized v1
  unchanged.
- The target cross-checks direct and HAProxy instances with controller hosts,
  Galera membership, RGW daemon-to-storage placement, ingress membership, and
  node roles. Distribution restart/activity use the verified upstream process
  and HTTP counters; non-equivalent secret/quota/claim/KMS/error facts remain
  explicit `coffer.load-telemetry-native-evidence/v1` documents.
- One complete phase composed through 26 requests to a real local TLS server.
  Phase/surface mismatch and query/hash/encoding/rule/content/identity/URL
  drift fail closed. Twenty-three focused native tests, all 262 broad load
  tests, and all 887 Python tests pass. Collection also reports 887 tests. The
  target was not yet selected by `collector/run.py` at that boundary; no
  endpoint, credential, container, VM, or remote state changed.
- `collector/run.py` now dispatches only the exact normalized or native target
  schema, repeats native topology validation before state mutation, and
  includes `native_target.py` in its source hash. Unknown schemas fail before
  transport and no compatibility fallback exists.
- A complete native before/during/after transaction made 78 verified-TLS
  requests, captured bounded service/dependency loss and recovery plus one
  edge restart, and emitted the canonical independently verified bundle.
  Normalized v1 remains compatible. The focused native/collector matrix passes
  91 tests, the broad load matrix passes 264, and full regression and
  collection both report 889 tests. This remains local adapter evidence; no
  pilot endpoint or remote state changed.
- Added the no-network native target renderer. One canonical owner-only
  request now binds exact sorted pilot inventory, RGW placement, explicit
  credential-free HTTPS origins, both topology hashes, and the checked
  renderer/target/parser source hash. Every query, rule, metrics, and evidence
  route plus content type and identity allowlist is generated and revalidated.
- The renderer atomically emits mode-0600 canonical JSON under a mode-0700
  owner directory and refuses unsafe modes/links/aliases, noncanonical bytes,
  source/topology/inventory drift, URL credentials, HTTP, implicit ports,
  paths, role overlap, and duplicate final URLs. Twenty-seven renderer tests
  and 70 focused native tests pass; the broad load matrix passes 291, and full
  regression and collection both report 916. No discovery, network, endpoint,
  credential, container, VM, or remote state changed.
- Added the no-network phase evidence compiler. Six exact source-summary
  classes bind phase, window, payload, and source hash; the output bundle binds
  the exact native target, topology, compiler sources, individual native
  evidence documents, source/document hashes, and one bundle hash.
- The compiler preserves bounded failure facts for the later verifier while
  refusing raw/extra fields, URLs, identities, credentials, phase/hash drift,
  unsafe files, nonfinite or excessive aggregates, inconsistent quota
  percentages, and worker-topology drift. Fifty-eight compiler/validator/file
  tests pass, including native evidence-reader compatibility; the focused
  native pipeline passes 129, the broad load matrix 349, and full regression
  and collection both report 974. No summary was collected and no SQL, RGW,
  log, network, endpoint, credential, container, VM, or remote state changed.
- Added the private phase-evidence TLS server. One owner-only configuration
  binds the exact target/bundle/source hashes, private IPv4 listener, TLS
  name/certificate/key, finite timeout, bounded concurrency, and all exact
  target routes before binding.
- Native-client verified TLS succeeds for all six documents. Wrong CA/name,
  public/wildcard bind, unsafe or aliased files, key/certificate/hash drift,
  cross-phase paths, queries, bodies, changed/duplicate headers, and other
  methods fail without redirect, listing, response body, product/version, Date,
  or request logging. Thirty-four focused server tests pass; the complete
  focused native pipeline passes 163, the broad load matrix 383, and full
  regression and collection both report 1008. No summary was collected and no
  SQL, RGW, log, credential, remote endpoint, container, VM, or remote state
  changed.
- Promoted the source summary to v2 before pilot use so every aggregate binds
  the exact dedicated collector source and raw canonical artifact file hashes.
  Added a source-artifact schema with target/phase/window/source/observation
  provenance and a source-summary acquisition seam that validates all six
  artifacts and emits the exact phase compiler request.
- Forty-four acquisition tests and the 136-test acquisition/compiler/server
  matrix pass; the broad load matrix passes 427, and full regression and
  collection both report 1052. Unsafe/aliased files, raw fields, phase/target/
  window/source/file/self-hash drift, invalid observations, and payload drift
  fail closed. No source artifact was collected and no SQL, RGW, log,
  credential, endpoint, container, VM, or remote state changed.
- Promoted the unused source-artifact contract to v2 before pilot use so every
  aggregate binds its exact input-file set. Added owner-only local collectors
  for fixed/supplied-fingerprint credential scanning and exact nonsynthetic
  profile/fault workload-error aggregation. They retain only hashes and
  counts, require one plan hash, and cannot emit Galera, RGW, quota, or
  reconciliation facts.
- Fifty-one local collector tests and the 188-test local/acquisition/compiler/
  server matrix pass; the broad load matrix passes 479, and full regression
  and collection both report 1104. No real secret, workload result, source
  artifact, SQL/RGW/log/exporter endpoint, container, VM, or remote state was
  read or changed.
- Added `docs/research/stage6-control-evidence-sources.md`. Every quota and
  reconciliation auxiliary field now maps to exact SQL/metric evidence or an
  explicit gap. The configured retry ceiling, schema constraints, desired
  replica count, freshest worker, and rejected stale writes cannot substitute
  for runtime facts.
- The accepted next boundary is one identity-free, non-mutating SQL snapshot
  for stored-versus-recomputed quota charge, pending deltas, stale claims, and
  active-claim consistency. Observed quota transaction attempts still require
  separate instrumentation before a control artifact collector can be
  truthful. No database or endpoint was contacted.
- Added migration `0006_claim_version_binding`; claims now persist the
  reservation version captured at acquisition. Read and mutation paths require
  the supplied version to match both claim and current reservation, existing
  claims are backfilled, and downgrade refuses retained claim versions.
- Added immutable identity-free `QuotaControlEvidenceSnapshot`. One bounded
  reader transaction independently recomputes committed/pending quota charge,
  compares every pending delta, counts stale claims, and checks active claim
  state/version consistency without mutation or retained identities.
- Twenty-one snapshot tests and the 183-test quota/reconciliation/migration/
  bootstrap/maintenance/runner matrix pass. Full regression and collection
  both report 1126. No real database, endpoint, identity, credential,
  container, VM, or remote state was read or changed.
- Quota write retries now emit one terminal observation with fixed operation
  and result classes plus the actual attempt count 1 through 3. The
  `coffer_quota_transaction_attempts` histogram has exact integer buckets;
  edge and reconciler stores bind it only to their private process metrics.
- Retry success, conflict exhaustion, non-retryable database failure, domain
  rejection, observer-failure isolation, bounded labels, and exact histogram
  reconstruction pass the focused 74-test matrix. Full regression passes
  1140. No real SQL/Prometheus endpoint, identity, credential, container, VM,
  or remote state was read or changed.
- Added `control_artifacts.py`. Owner-only baseline/current capture now binds
  the identity-free SQL invariant snapshot and six fixed verified-TLS
  Prometheus queries to one target/phase/window. Database URL and project are
  fixed environment inputs and are never retained.
- The compiler reconstructs observed quota attempts, edge internal errors,
  quota charge/invariant, and worst per-reconciler health. It refuses series,
  counter, process-start, warning, timing, topology, or hash drift and emits
  the exact identity-free quota/reconciliation v2 artifacts consumed by the
  existing source-summary and phase compilers.
- Twenty-three control-collector tests, the 618-test
  load/observability/control matrix, and the full 1163-test regression pass.
  All endpoint behavior remains fake-adapter local evidence; no real
  SQL/Prometheus endpoint, identity, credential, container, VM, or remote
  runtime was read or changed.
- Added `galera_artifacts.py`. It reuses the exact Coffer retry-boundary
  control captures for maximum attempts and terminal database/conflict
  failures; it does not reinterpret mysqld-exporter cluster-health gauges as
  application retries. Native Galera node health remains separate.
- Sixteen Galera-artifact tests, the 634-test load/observability/control
  matrix, and the full 1179-test regression pass. The output is identity-free
  and source/target/phase/window bound. No real Galera/Prometheus/SQL endpoint
  or remote state was read or changed.
- Exact Ceph v20.2.2 and Distribution v3.1.1 source inspection confirmed that
  generic aborted-request and storage-action metrics cannot attribute KMS or
  unexpected storage failures. Only complete bucket-scoped
  `ListMultipartUploads` is a direct multipart-residue source.
- Added `rgw_artifacts.py`. One canonical phase-bound pilot probe must cover
  all seven fixed positive/zero-size operations; `during` must additionally
  observe wrong-key and KMS-outage results. Expected injected failures remain
  bound evidence but do not become promotion errors. A separate complete,
  unique-page multipart capture supplies the direct residue count.
- Thirty-six focused RGW-artifact tests, the 670-test
  load/observability/control matrix, and the full 1215-test regression pass.
  The no-network fake-adapter milestone changes no live S3 client, credential,
  endpoint, RGW, KMS, Barbican, Distribution, container, VM, or remote state.
- Added `phase_preparation.py`. One owner-only request now drives all local,
  control, Galera, and RGW compilers into six v2 artifacts, source summaries,
  one phase bundle, and a preflighted private evidence-server configuration.
- A fresh sibling staging directory makes the complete output set atomic.
  Late collector/TLS failure leaves no final or staging residue; exact repeats
  verify every retained byte and inode without rewrite. Seventeen end-to-end
  fake-adapter tests cover all phases, rollback, drift, tamper, and fixed CLI
  results. The 687-test load/observability/control matrix and full 1232-test
  regression pass without network, SQL, S3, listener, or remote operations.
- Accepted ADR 0016 for the local architecture after adding the versioned
  observability topology and pure contract. Exact direct targets, one-worker
  and VIP refusal, verified TLS, bounded labels/results, public operational
  path denial, counter reset and stale-series transitions, and hashed
  evidence pass 51 focused tests.
- Full Python regression passes 490 tests and the Kolla companion role passes
  68 checks. Compilation, topology JSON, and diff checks pass. No metric
  runtime, Prometheus, Grafana, HAProxy, Distribution debug listener, Ceph
  target, network, container, or remote state changed.
- A directory-wide Gitleaks invocation after role verification traversed the
  generated `work/kolla-ansible-stage3` dependency/fixture tree and reported
  non-source findings. The milestone commit gate scans the staged source set;
  generated work content is not promotion evidence.
- Completed the first runtime slice of ADR 0016. Collectors now bind to exact
  API/edge/reconcile components, export process-start timestamps, validate all
  application-controlled labels and durations, and reduce edge paths and HTTP
  statuses to bounded classes. The runtime and topology allowlists are tested
  for exact agreement.
- API and edge refuse metrics-enabled startup with more or fewer than one
  worker before application construction. The edge wrapper contains no raw
  tenant/repository/digest/reference/upload path in its series. Gunicorn
  refreshes the process-start gauge after each worker fork, so a counter reset
  cannot retain the master's old timestamp. The focused runtime matrix passes
  141 tests and full Python regression passes 507.
- This slice added no Kolla variable/template, Prometheus target/rule, Grafana
  dashboard, HAProxy ACL, private edge/reconciler endpoint, Distribution
  listener, network, container, or remote change.
- Added bounded manifest quota-admission count/duration metrics using the same
  edge collector as outer HTTP instrumentation. The seven exact results
  distinguish quota absence, database/internal failure, upstream failure,
  policy/client invalidity, and acceptance without dynamic labels.
- The quota/observability/edge/proxy focused matrix passes 112 tests and full
  regression passes 515. Tests use a real issued JWT and concrete repository
  path while proving neither value nor dependency exception text enters the
  metric payload. No endpoint, Kolla, Prometheus, HAProxy, network, container,
  or remote state changed.
- Completed the local direct API/edge scrape boundary. Metrics-enabled edge
  serves direct-backend health/readiness/metrics from its shared collector;
  metrics-disabled edge still refuses operational paths. API and edge
  workers must equal one before startup.
- The Kolla role now requires Prometheus and verified TLS inputs, rejects
  either VIP as a metrics target, renders separate per-host API/edge jobs with
  stable labels and TLS CA/server name, and denies operational/debug paths on
  API and edge HAProxy service routes, including the shared-external mapped
  backend.
- Focused runtime tests pass 60, full Python regression passes 515, and the
  fixture-only Kolla lifecycle passes 78 checks with zero harness residue.
  No remote Prometheus, HAProxy, container, network, or scrape changed.
- Source inspection found Distribution v3.1.1's debug listener is not
  metrics-only: it uses Go's default HTTP mux and the registry binary imports
  `net/http/pprof`. The accepted refinement binds that mux only to loopback.
- Added the one-worker `coffer-registry-metrics` allowlist proxy. It accepts
  one exact loopback HTTP `/metrics` upstream, exposes only verified-TLS
  `/healthz` and `/metrics`, forwards no client headers, bounds responses,
  maps failures to a fixed 503, and refuses query/debug/pprof paths.
- The Kolla role starts the proxy only with metrics enabled, gives it no
  HAProxy route, and renders a direct per-registry-host Prometheus target.
  Its dedicated mode-0600 config receives no database, Keystone, RGW,
  Distribution HTTP, signing, JWKS, or maintenance secret.
- Twenty focused proxy/config-validator tests and all 525 Python tests, lock,
  compilation, and diff checks pass. The complete fixture-only Kolla
  lifecycle passes 85 checks with
  negative worker/port cases, secret-recipient inspection, idempotent
  lifecycle actions, and zero harness residue. No remote listener,
  Prometheus, container, network, or service changed.
- Periodic reconciliation now owns cycle result/duration, last-success/scanned,
  and SQL-derived backlog, active/expired claim, oldest eligible age, and
  database dependency metrics. The gauges do not participate in claim,
  fencing, or scheduling correctness.
- Periodic mode requires a TLS management listener in the same process and
  exposes only exact `/healthz` and `/metrics`; query/debug/pprof paths are
  fixed 404. One-shot mode constructs no listener. Failures retain no
  dependency exception or tenant/repository/claim/credential value.
- The Kolla future recipient binds to the direct API-interface address and
  receives the backend listener certificate/key. It has no HAProxy route and
  creates a Prometheus target only when reconciliation is enabled. The current
  fail-closed profile stays disabled and emits no phantom target.
- Seventy-three focused runtime/config tests, all 536 Python tests, and 88
  Kolla role checks pass, including real verified TLS, owner-only key delivery,
  idempotent lifecycle, and zero fixture residue. No remote listener,
  credential, Prometheus target, container, network, or service changed.

## Plan 0018 Activation

- Published completed Stage 4 and plan 0017 to
  `https://github.com/jaehanbyun/coffer.git` as scoped commits `ae82f32` and
  `4f1ff7d`; local and remote `main` match at `4f1ff7d`.
- Activated `docs/exec-plans/0018-kolla-multinode-ha-pilot.md` with explicit
  exit gates for three-controller Galera/HAProxy, replicated Coffer services,
  independent external RGW HA, replica loss, fencing, key overlap, rolling
  upgrade, compatible rollback, cleanup, and repository regression.
- At activation, no Stage 5 remote mutation had occurred; the later bullets
  record the exact guest provisioning milestone.
- The current snapshot has 123.8 GiB available RAM, no swap, 876.5 GiB
  filesystem space, 18 running domains, 82 allocated vCPUs, and no Stage 5
  names. The retained one-node RGW remains running with autostart disabled.
- Selected `poc/kolla-ha/topology.yml`: three 8-vCPU/16-GiB controllers,
  three 4-vCPU/8-GiB storage nodes, 72 GiB total RAM, 576 GiB logical disk,
  and dedicated management/storage/external networks on currently unused
  `192.168.252.0/24` through `192.168.254.0/24`.
- Added `poc/kolla-ha/provision.sh preflight`. Bash/ShellCheck and target
  refusal checks pass. Ubuntu Noble daily build `20260705` and its x86_64
  QCOW2 SHA-256 are pinned from the official date-fixed checksum list.
- The live preflight passes for six domains/36 vCPUs and predicts 51.8 GiB
  RAM, 300.5 GiB filesystem, and 320.6 GiB pool capacity remaining.
- Local commit `1a78bd7` preserves the plan/inventory/preflight baseline.
- Added a paired remote libvirt helper with independent hard-coded allowlists,
  verified image download, autostart-disabled resources, exact destroy, and
  partial-create rollback. Local executable contracts and remote read-only
  status pass; all six domains, sixteen volumes, and three networks are absent.
- Local commit `5326093` preserved that harness. One exact create completed:
  six domains, sixteen volumes, and three dedicated networks now exist.
  Actual domain and network metadata confirms every autostart setting is off.
- `verify-guests.sh` confirms cloud-init, x86_64, vCPU/memory/root/OSD shape,
  fixed management/storage addresses, qemu guest agent, and controller-only
  external NICs across all six guests. The shared host retained about 119 GiB
  available RAM and 876 GiB free storage after first boot.
- Added and ran the storage preparation phase. All three storage nodes have
  chrony and the Ceph prerequisites, resolve the three storage addresses, and
  retain empty 64-GiB `/dev/vdb` devices. Ceph config and containers are
  absent. The first hostname check failed safely on cloud-init's loopback
  alias; the scoped idempotent correction passed.
- Exact next action: implement a MON/MGR-only Ceph Tentacle bootstrap. Bootstrap
  storage-1, adopt only storage-2/3 through the generated cephadm key, and
  establish three MON/two MGR services before any OSD or RGW mutation.
- Added and locally validated that MON/MGR-only harness. It pins the release
  and image, requires zero OSDs, hard-codes the three storage hosts, distributes
  only the generated public key to storage-2/3, and proves RGW remains absent.
  No bootstrap command has run.
- Exact next action: commit the control-plane harness locally, recheck the
  three empty OSD devices, then invoke
  `poc/kolla-ha/bootstrap-ceph-control.sh bb00` once.
- Preserved that harness in local commit `7f53b00`. Its first invocation
  failed before MON creation because `--skip-prepare-host` bypassed Tentacle's
  only Podman-version initialization path. cephadm automatically cleaned the
  partial FSID; read-only inspection found zero configuration, keyring,
  containers, FSID directories, authorization markers, disk signatures, or
  `/dev/vdb` LVM PVs.
- Removed only that flag so normal bootstrap performs the upstream
  prerequisite/container-engine checks on the already prepared primary.
- The corrected retry created one initial MON/MGR, but the first
  `cephadm shell` inside each stdin-streamed guest script consumed the remaining
  script. Aggregate inspection found one registered host, one MON, one MGR,
  zero OSDs, zero RGW services, and three still-empty OSD devices.
- Added explicit `/dev/null` input to every streamed `cephadm shell` call and
  the standalone public-key read so the partial cluster can resume
  idempotently.
- The corrected resume registered and labeled storage-2/3, then failed safely
  when the immediate placement dry-run raced the orchestrator cache and called
  storage-3 unknown. Later inspection found all three exact hosts healthy, one
  MON, one MGR, zero OSDs/RGW services, and three empty OSD devices.
- Added a bounded pre-placement gate requiring all three exact hosts to have
  empty orchestrator status before dry-run or apply.
- Preserved that correction in local commit `8950680`; the idempotent resume
  passed with three healthy hosts, MON quorum 3, two running MGRs, replica
  defaults 3/2, zero OSDs, and zero RGW services. The admin keyring remains
  primary-only and all three `/dev/vdb` devices are empty.
- A bounded MGR failover promoted storage-2 while two MGRs stayed running.
  Tentacle source inspection then identified the 30-minute default stray-check
  interval as the apparent inconsistency: a bounded temporary 30-second
  interval forced reevaluation, cleared both stale warnings, and was removed
  to restore the effective 1800-second default. Only `TOO_FEW_OSDS` remains;
  no health warning was disabled.
- Exact next action: implement and validate an exact `/dev/vdb` OSD-only
  harness for the three storage hosts. Prove one `up`/`in` OSD per host and
  keep RGW absent.
- Added and locally validated that OSD-only phase. It requires the healthy
  control plane, exact three-host inventory, size/min-size 3/2, and zero RGW;
  admits only one available 64-GiB `/dev/vdb` per allowlisted host; resumes
  only an exact partial state; and exits on three running/up/in OSDs plus
  `HEALTH_OK`.
- Exact next action: commit the OSD harness locally, recheck the three live
  device candidates and sole expected zero-OSD warning, then invoke
  `poc/kolla-ha/bootstrap-ceph-osds.sh bb00` once.
- Preserved the harness in local commit `831b66b` and invoked it. OSD 0/1/2
  map one-to-one to storage-1/2/3; all are managed, running, `up`, and `in`;
  CRUSH uses the host failure domain; every pool is size/minimum 3/2; cluster
  health is OK; and RGW remains absent.
- Each `/dev/vdb` is now exactly one LVM PV with one OSD container. A second
  complete invocation added nothing and returned the same healthy result.
- Exact next action: implement and validate a separate three-RGW/two-ingress
  phase using storage VIP `192.168.253.30`, verified TLS, and no S3 identity
  creation.
- Added and locally validated that phase. It places RGW TLS backends on
  storage-1/2/3 at 9443 and HAProxy/Keepalived on storage-1/2 behind
  `192.168.253.30:8443`. The frontend uses an owner-only short-lived lab key;
  only its public CA is exported under ignored `work/`.
- The exact RGW spec dry-run passes. Current preflight finds zero RGW/ingress
  daemons, users, or VIP owners, and all three reserved ports free on all
  storage hosts. No RGW/ingress apply or S3 identity operation has run.
- Exact next action: commit and invoke the RGW HA harness once, then verify
  three RGWs, two ingress pairs, one VIP owner, TLS, healthy 3/2 pools, and
  zero S3 users.
- Preserved the harness in local commit `1f0e6e9` and invoked it. Three RGWs,
  two HAProxy, two Keepalived, and exactly one VIP owner are running. Backend
  and frontend TLS pass; untrusted and plaintext paths fail; the Mac-to-`bb00`
  tunneled VIP path returns the expected S3 response.
- All five pools remain size/minimum 3/2, all 129 PGs are clean, health is OK,
  and user count is zero. A second invocation retained the same state.
- Added and locally validated a separate S3 fixture phase with owner-only
  registry/denial credentials, one-bucket limits, anonymous/cross-owner/
  extra-bucket denials, and a deterministic 4-MiB private sentinel. Credential
  files remain mode 0600 on storage-1, the helper is removed after execution,
  and storage-2/3 must have no fixture directory.
- Bash syntax, ShellCheck, Python compilation, refusal tests, source secret
  scans, fixture constant checks, Gitleaks, and diff checks pass. Live
  preflight reported health OK, boto3 present, zero users, zero buckets, and no
  fixture state on any node before invocation.
- Preserved the S3 fixture harness in local commit `8d7c4bd` and invoked it
  twice through `jh.byun@100.123.168.66`. Both runs returned anonymous 403,
  cross-owner 403, extra-bucket 400, and the same 4-MiB sentinel SHA-256
  `543e845c8c7185da3bc04a566b068274825c837a740d029726b169481b919e50`.
- Independent inspection confirms two one-key/no-cap/one-bucket identities,
  exact bucket ownership, root-only state on storage-1, no temporary helper,
  no credential directory on storage-2/3, three running RGWs, two running
  HAProxy daemons, zero inactive PGs, and `HEALTH_OK`.
- Exact next action: implement and validate the bounded daemon-level RGW and
  ingress failover harness. Test one exact RGW replica and then the active
  ingress pair with sentinel verification and full restore gates; defer whole
  storage-VM failure until this smaller fault phase closes.
- Added the exact daemon-level RGW/ingress fault harness and a read-only
  sentinel helper. It admits only storage-3's RGW and the current VIP owner's
  Ceph-managed Keepalived/HAProxy pair, requires five reads under each fault,
  and has an EXIT trap that restores every expected RGW and ingress daemon.
- Bash syntax, ShellCheck, Python compilation, refusal tests,
  forbidden-command scans, Gitleaks, and diff checks pass. The first live
  preflight exposed only a remote basename mismatch before daemon inventory;
  the corrected explicit destinations pass live 3/2/2 inventory,
  `HEALTH_OK`, expected sentinel digest, and helper cleanup. No stop action has
  run.
- Exact next action: commit and invoke
  `poc/kolla-ha/test-ceph-rgw-failover.sh
  jh.byun@100.123.168.66`, then independently verify restored daemons, exactly
  one VIP owner, clean PGs, health, sentinel digest, and no temporary helpers
  before any whole-VM fault.
- Preserved the daemon-fault harness in local commit `094b597` and ran the
  complete matrix. Storage-3's RGW stopped with two surviving backends and five
  successful sentinel reads, then restored to three and `HEALTH_OK`.
  Storage-1's active Keepalived/HAProxy pair stopped, the VIP moved to
  storage-2, and five more sentinel reads passed before both pairs restored.
- Independent recovery confirms three RGWs, two HAProxy, two Keepalived,
  exactly one VIP owner, zero inactive PGs, `HEALTH_OK`, the accepted sentinel
  digest, no fault/audit helpers, and no credential directory on storage-2/3.
- Exact next action: implement and validate
  `poc/kolla-ha/test-ceph-storage-vm-failover.sh` for only the
  autostart-disabled storage-3 domain. Prove two-node Ceph/RGW availability and
  sentinel reads while it is off, then full 3-MON/3-OSD/3-RGW clean recovery
  after starting the same domain. Do not fault an ingress or controller VM in
  that phase.
- Added that exact VM-fault harness. It validates storage-3's persistent XML,
  disabled autostart, CPU/memory, three disk filenames, two MAC/network pairs,
  and all other five running domains. Its only libvirt mutations are exact
  `destroy` and `start`; there is no undefine, storage, network, OSD, or
  unrelated-domain mutation.
- The outage gate requires two-MON quorum, 2/3 OSDs up and 3/3 in, two RGWs,
  both ingress pairs, no inactive PGs, one VIP owner, and five sentinel reads.
  Recovery requires full quorum, 3/3 up/in OSDs, three RGWs, clean PGs,
  `HEALTH_OK`, and the accepted digest. An EXIT trap starts the target and
  attempts the same recovery after any failure.
- Static checks and a mutation-free live preflight pass. The exact domain and
  five other VMs are running, healthy Ceph/sentinel gates pass, and temporary
  helpers are absent. No power-off/start action has run.
- Exact next action: commit and invoke
  `poc/kolla-ha/test-ceph-storage-vm-failover.sh
  jh.byun@100.123.168.66`, then independently audit complete recovery before
  controller/Kolla work.
- Preserved the VM-fault harness in local commit `9e9792d` and ran one full
  power-loss cycle. Only storage-3 shut off. The remaining cluster reached
  two-MON quorum, 2/3 OSDs up with 3/3 in, two RGWs, two ingress pairs, zero
  inactive PGs, 193 degraded PGs, one VIP owner, `HEALTH_WARN`, and five
  successful sentinel reads.
- The same domain restarted and returned to 3-MON quorum, 3/3 up/in OSDs,
  three RGWs, clean PGs, and `HEALTH_OK`. Independent audit confirms all six
  domains running, target autostart disabled, two ingress pairs, one VIP owner,
  accepted sentinel digest, and no temporary helpers.
- Exact next action: start the controller track with a mutation-free Kolla
  2026.1 multinode inventory/preflight for controller-1/2/3. Reuse the Stage 4
  commit and companion-role contracts; keep external RGW unchanged and do not
  deploy Coffer before Galera/HAProxy baseline health passes.
- Added and passed the mutation-free Kolla controller preflight. It renders
  the official pinned 2026.1 multinode group hierarchy with the three exact
  controllers in control/network/MariaDB/RabbitMQ/Keystone and no
  compute/monitoring/storage hosts.
- All three guests are clean Ubuntu Noble x86_64, 8-vCPU/16-GiB controllers
  with more than 70 GiB free root space, exact NIC/address/MAC shape, free
  reserved ports, synchronized time, no Kolla/container state, and working
  Quay/GitHub/RGW paths. The external storage audit remains fully healthy.
- Minimal Kolla baseline is fixed to MariaDB/ProxySQL, RabbitMQ, Memcached,
  HAProxy/Keepalived, Fluentd, and Keystone. OpenStack core remains disabled;
  external VIP TLS is enabled on ens5.
- Exact next action: commit this preflight checkpoint and implement
  `poc/kolla-ha/prepare-kolla-controllers.sh`. It may create only the
  owner-only controller-1 deployment key, exact public-key markers on the
  three controllers, pinned Kolla checkout/venv, passwords, and certificates;
  do not run `bootstrap-servers` in that phase.
- Added and locally validated that prepare phase. Controller-1 owns the sole
  private deployment key, pinned source/venv, root-only passwords, and
  short-lived external-VIP TLS. All three controllers receive only one bounded
  public-key marker. Transfer files are removed and final acceptance is three
  Ansible pings.
- Static/refusal/secret/diff checks pass. A live unknown action returned 64
  before state creation; all three controllers still have zero owner state,
  deployment key, `/etc/kolla`, or public marker. The prepare action has not
  run and contains no Kolla bootstrap/precheck/pull/deploy or container/VIP
  mutation.
- Exact next action: commit and invoke
  `poc/kolla-ha/prepare-kolla-controllers.sh
  jh.byun@100.123.168.66`, then independently verify exact recipients,
  source/venv commit, owner/modes, certificate, Ansible connectivity, zero
  containers/VIPs, and healthy external RGW before writing the Kolla lifecycle
  runner.
- Preserved the controller preparation harness in local commit `1b4785f`.
  Four resumable invocations then exposed and corrected, without starting
  Kolla, the venv `PATH`, generated-password mode, dedicated-known-hosts, and
  post-cleanup assertion contracts. Those corrections are preserved through
  local commit `d7cd2f6`.
- The final idempotent preparation passed. Controller-1 is the sole recipient
  of the mode-0600 deployment private key and owns the exact Kolla source,
  venv, root-only passwords, and verified 14-day external-VIP certificate.
  Controllers 1 through 3 each have exactly one matching public-key marker
  and all three Ansible pings return `pong`.
- Independent read-only acceptance confirms the pinned
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc` checkout, required generated
  password fields without disclosing values, certificate chain/SAN, absent
  transfer files, absent Docker/Kolla runtime, and absent internal/external
  VIPs. Controller-2/3 have no private key, owner state, or `/etc/kolla`.
- The independent external-storage audit still reports three-MON quorum,
  three of three OSDs up/in, three RGWs, two ingress pairs, zero inactive or
  unclean PGs, and `HEALTH_OK`.
- Exact next action: implement and locally validate a phase-selectable
  `poc/kolla-ha/run-kolla-lifecycle.sh` plus its controller-1 guest helper.
  It must admit only `bootstrap`, `prechecks`, `pull`, `deploy`, and read-only
  `status` actions, retain owner-only logs, bound each action, and recheck
  external RGW health. Do not invoke `bootstrap-servers` until that harness is
  committed and its refusal/allowlist contracts pass.
- Added and validated that phase-selectable lifecycle harness. Each mutating
  phase is independently bounded and locked, requires the preceding
  root-only success marker, replaces an owner-only controller-1 log, and
  creates its marker only after phase-specific postconditions. Only
  `prechecks` receives `--use-test-images`.
- The first read-only status attempt exposed two harness defects before any
  Kolla operation: `ssh -n` suppressed the nested audit script, and the empty
  result reached unsafe arithmetic. Bash then unexpectedly continued and
  created only `lifecycle/status.complete` plus empty lifecycle/log
  directories. Exact content, ownership, and sole-file/empty-directory state
  were verified; that marker and those two empty directories were removed.
  Docker, Kolla state, containers, images, and VIPs remained absent, and RGW
  stayed healthy before and after.
- Status can no longer name a marker, snapshot shape and numeric fields fail
  closed, and the nested script receives stdin normally. The corrected
  read-only status reports no completed phases, Docker `0/3`, zero images,
  containers, and VIPs; a separate residue assertion confirms no lifecycle
  directory was created. Unknown local and remote actions return 64 without
  state creation.
- Bash syntax, ShellCheck, exact phase/timeout checks, forbidden-mutation
  scans, Gitleaks, diff checks, the corrected live status, and external RGW
  before/after audits pass.
- Exact next action: commit the validated lifecycle harness locally, then
  invoke only
  `poc/kolla-ha/run-kolla-lifecycle.sh bootstrap
  jh.byun@100.123.168.66`. On failure, retain the owner-only remote log,
  verify no success marker, audit exact partial runtime state and external
  RGW, then correct and resume only `bootstrap`.
- Preserved the lifecycle harness in local commit `56632de` and invoked only
  `bootstrap`. It failed in about 20 seconds before any Docker installation
  because the ubuntu-run Kolla CLI could not read the intentionally
  `root:root:0600` passwords file. The success marker is absent; corrected
  `status` reports Docker `0/3`, zero images/containers/VIPs, and no completed
  phase. RGW remained healthy before and after.
- Kept the root-only secret boundary and changed the Kolla CLI plus deploy
  check to run as root. The exact nine Galaxy collections remain under the
  deployment owner's directory, so the root invocation pins
  `ANSIBLE_COLLECTIONS_PATH` to that path and the system path. Phase logs now
  become `root:root:0600`.
- Read-only root preflight confirms the passwords file remains root-only,
  all nine collections are available, the exact inventory parses, Kolla's
  bootstrap command loads, Docker remains absent, and no bootstrap marker
  exists. Bash syntax, ShellCheck, Gitleaks, and diff checks pass.
- Exact next action: commit the root-execution correction locally, then resume
  only
  `poc/kolla-ha/run-kolla-lifecycle.sh bootstrap
  jh.byun@100.123.168.66`.
- Preserved the correction in local commit `bb34850` and resumed only
  `bootstrap`. It completed with all three controllers at `failed=0` and
  `unreachable=0`; controller-1 changed 16 tasks and controller-2/3 changed
  17 each.
- Independent acceptance confirms Docker installed and active `3/3`, zero
  containers, zero images, zero internal/external VIP owners, an exact
  root-only bootstrap marker and log, unchanged root-only passwords, and no
  prechecks/pull/deploy marker. Lifecycle status reports only `bootstrap`
  complete.
- The external storage audit still reports three-MON quorum, three up/in OSDs,
  three RGWs, two ingress pairs, zero inactive/unclean PGs, and `HEALTH_OK`.
- Exact next action: invoke only
  `poc/kolla-ha/run-kolla-lifecycle.sh prechecks
  jh.byun@100.123.168.66`. If it fails, retain and inspect only the redacted
  root-only prechecks log, verify the success marker absent, and do not pull
  images.
- The exact prechecks phase passed with `changed=0`, `failed=0`, and
  `unreachable=0` on all three controllers. Independent status still reports
  Docker active `3/3`, zero images/containers/VIPs, and only `bootstrap` plus
  `prechecks` complete.
- The bootstrap/prechecks markers and logs are exact `root:root:0600`;
  passwords remain root-only, and pull/deploy markers are absent. External
  Ceph/RGW remains fully healthy.
- Exact next action: invoke only
  `poc/kolla-ha/run-kolla-lifecycle.sh pull
  jh.byun@100.123.168.66`. Do not deploy unless all three nodes have images,
  the root-only pull marker passes, and external RGW remains healthy.
- The exact pull phase passed with `failed=0` and `unreachable=0` on all three
  controllers. Each has 12 images and the sorted reference/digest set has the
  same SHA-256
  `2db835fbf628fe2b747ad44c27f9c8685d72547876fb7f8e0cbaa9228c6fee27`.
- Independent status reports only `bootstrap,prechecks,pull` complete, Docker
  active `3/3`, 12 images per node, and zero containers or VIPs. All three
  markers/logs are root-only and the deploy marker is absent. External
  Ceph/RGW remains fully healthy.
- Exact next action: invoke only
  `poc/kolla-ha/run-kolla-lifecycle.sh deploy
  jh.byun@100.123.168.66`. On failure, do not create a deploy marker or start
  Coffer; audit the exact Kolla partial state and recover the baseline first.
- The Kolla deploy itself completed with `failed=0` and `unreachable=0` on
  all controllers. All 36 containers were running/healthy, both VIPs had one
  owner, Kolla check and trusted internal/external Keystone probes passed, and
  external RGW remained healthy.
- Independent secret acceptance then failed: upstream Ansible item output put
  the raw RabbitMQ cluster cookie and a derived Basic Authorization credential
  into root-only `prechecks.log` and `deploy.log`. The cookie was never
  disclosed, but a redacted-context diagnostic exposed the Basic token, so the
  disposable RabbitMQ monitoring password must be rotated.
- Verified the exact deploy marker, removed it, and atomically sanitized only
  the affected root-only logs. Across all lifecycle logs, raw, URL-encoded,
  base64-encoded generated values and Basic/Bearer Authorization tokens are
  now absent. Services were not changed and remain running.
- Added `ANSIBLE_NO_LOG=True` to every Kolla/check execution and a mandatory
  post-run scan that rejects raw, URL/base64-derived generated credentials or
  Authorization tokens before recap or marker creation. Bash syntax,
  ShellCheck, Gitleaks, effective Ansible config, existing-log scan, and diff
  checks pass.
- Exact next action: commit the lifecycle log guard locally, rotate only the
  disposable `rabbitmq_monitoring_password` without printing or retaining its
  old/new value, then rerun only `deploy`. Do not restore the deploy marker
  until the new log scan and full control-plane acceptance pass.
- Preserved the log guard in local commit `d352870`.
- Added a bounded monitoring-password rotation helper. It requires the exact
  three preceding root-only markers and an absent deploy marker, changes only
  `rabbitmq_monitoring_password`, creates no backup, atomically retains the
  password file's root-only mode, and compares every unrelated parsed value
  before replacement. Neither old nor new value is output.
- Bash syntax, ShellCheck, Python compilation, missing/option-shaped refusal,
  forbidden-operation scan, Gitleaks, and diff checks pass. The helper has not
  run; the running services still use the old credential consistently.
- Exact next action: commit the bounded rotation helper locally, invoke it
  once through `jh.byun@100.123.168.66`, and immediately rerun only `deploy`.
- Preserved the rotation helper in local commit `9d4be4a` and ran it once.
  The target password changed without output or backup, the file remained
  root-only, the deploy marker stayed absent, and RGW passed both boundary
  audits.
- The guarded deploy reconciled the rotated credential and again completed
  Kolla/Ansible with `failed=0` and `unreachable=0`. All 36 containers were
  running/healthy and the new deploy/deploy-check logs passed the credential
  scan.
- Final acceptance then exposed a network-probe assumption: both VIPs moved
  from controller-1 to controller-2, and the external NIC is intentionally
  unnumbered on nonowners. Controller-1 therefore has no route to the external
  VIP. The single trusted probe failed from the wrong node and correctly left
  the deploy marker absent; services and RGW remained healthy.
- Changed external acceptance to identify the sole VIP owner, pass only the
  public CA in memory to that host, and run trusted TLS plus untrusted/plaintext
  denial probes there. A live owner-local read-only preflight passes on
  controller-2. Bash syntax, ShellCheck, Gitleaks, and diff checks pass.
- Exact next action: commit the VIP-owner probe correction locally and rerun
  only `deploy`. No further credential rotation is needed because the guarded
  reconciliation and new-log scan already passed.
- Preserved the probe correction in local commit `ea7e388` and reran only
  `deploy`. It converged with controller-1 changing three tasks and
  controller-2/3 changing zero, with `failed=0` and `unreachable=0`.
- Final lifecycle status reports `bootstrap,prechecks,pull,deploy` complete,
  Docker active `3/3`, 12 running/healthy containers per controller, the same
  12-name container set on each host, and exactly one owner for each VIP.
  The current owner-local external probe returns trusted TLS 200 and denies
  untrusted TLS and plaintext.
- Independent acceptance confirms four exact root-only markers, all lifecycle
  logs root-only and free of raw/URL/base64 generated credentials or
  Authorization tokens, Galera at three members `Primary`/`Synced`, RabbitMQ
  at three running nodes with zero partitions, and a working Keystone admin
  token with internal/public identity endpoints.
- External Ceph/RGW remains at three-MON quorum, three up/in OSDs, three RGWs,
  two ingress pairs, zero inactive/unclean PGs, and `HEALTH_OK`.
- Added and passed the mutation-free Stage 5 Coffer HA `clean|ready`
  preflight. Clean state proves the exact twelve healthy Kolla containers on
  each controller and zero Coffer runtime, listeners, configuration, routes,
  images, Galera schema/user, Keystone service/user, companion inventory,
  source, or input state. RGW remains fully healthy; owner-only credentials
  and its CA remain storage-1-only; the 4-MiB sentinel digest is unchanged.
- The ready contract pins published source commit
  `4f1ff7ddfd89d21f17ab7cbb531c335e85d94542`, identical x86_64 image IDs,
  three-host groups, production TLS/frontend settings, backend certificate
  recipients, exact RGW inputs, and owner-only files while retaining zero
  runtime/database/catalog state. A live ready run fails closed at the first
  missing image, as expected.
- Corrected two read-only preflight assumptions without remote mutation:
  OpenSSL hostname/IP acceptance now uses chain-aware `openssl verify`, and
  only storage-1 is required to retain the RGW CA/credential source.
- Exact next action: implement and statically validate
  `poc/kolla-ha/prepare-kolla-production-profile.sh`. It may prepare only the
  internal/external Kolla certificates and two production frontend globals;
  it must stop before Kolla reconfigure or any Coffer/image/input mutation.
- Preserved that harness in local commit `ebc08ff` and invoked `prepare`
  once. The existing CA remained unchanged; the new internal leaf verifies
  for `192.168.252.10`, and the replacement source external leaf verifies for
  `192.168.254.10` and `registry.coffer.stage5`. Only the three allowlisted
  internal-TLS/single-frontend/443 globals changed.
- No Kolla process reloaded: controller-1's exact container name/ID/start-time
  snapshot stayed at SHA-256
  `c0041e9f3aa7236c3811f97e42f0afcd756372737b668e11ee45ee78250505a9`;
  all 36 containers remain healthy and both VIPs retain one owner. Coffer
  runtime, images, inputs, database, and catalog remain absent.
- A second invocation passed idempotently without certificate rotation.
  Independent audit found exact root-only source PEMs and marker, valid
  identities, no rendered internal HAProxy PEM yet, no CA serial, no temporary
  directory, no backup, and fully healthy external RGW.
- Preserved the guarded production-profile phase in local commit `dac7bf5`.
  Its first run stopped before a completion marker on the missing ProxySQL TLS
  recipient contract; `a367f30` added the exact CA/certificate/key inputs.
  The second run stopped at Keystone registration because the toolbox lacked
  internal CA trust; `2b29f2a` added only Kolla's documented Ubuntu CA bundle
  path.
- The next service run completed but correctly withheld the marker because
  the expected catalog strings included `/v3` and explicit `:443`, while
  Kolla's canonical URLs omit both. Commit `c37c014` corrected only those
  expectations.
- The final idempotent `reconfigure` passed with controller-1 changing three
  tasks and controller-2/3 changing zero, all at `failed=0` and
  `unreachable=0`. All 36 Kolla containers are running/healthy; Galera has
  three `Primary`/`Synced`/ready/connected members and RabbitMQ has three
  running nodes with zero partitions.
- Trusted internal HTTPS and the external single frontend on port 443 return
  200; untrusted TLS, plaintext, and external port 5000 are denied. The DNS
  identity validates, and Keystone advertises
  `https://192.168.252.10:5000` internally and
  `https://192.168.254.10` publicly.
- Five exact lifecycle markers and seven logs are `root:root:0600`; all logs
  reject raw, URL/base64-derived generated credentials and Authorization
  tokens. Coffer runtime, images, listeners, configuration, database, and
  catalog remain absent. External Ceph/RGW remains fully healthy.
- Exact next action: implement and statically validate
  `poc/kolla-ha/build-distribute-coffer-images.sh` from published commit
  `4f1ff7ddfd89d21f17ab7cbb531c335e85d94542`. Build on controller-1,
  transfer directly to controller-2/3, require identical image IDs, and stop
  before companion inventory, input, database, catalog, or role mutation.
- Added and statically validated that exact `status|build` harness. It pins
  the published Coffer source, Kolla image source, Ubuntu x86_64 base digest,
  final local tags, owner/completion markers, and direct controller transfer.
  It never logs in, pushes, publishes, or uses a registry.
- Build acceptance requires the two exact image IDs to match on all three
  controllers, validates non-root Coffer and Distribution entry points, and
  retains zero Coffer runtime/config/listeners. Failed build/transfer state is
  resumable under one root-only owner marker and log; no completion marker is
  written early.
- The first mutation-free live status corrected only the deployment
  known-hosts mode expectation. The second normalized a blank missing-image
  result. Both stopped before any owner marker, source, build directory, or
  image was created.
- Final live status reports image state absent, 36 healthy Kolla containers,
  accepted reconfigure, no Coffer runtime/config/listeners, and healthy
  external RGW. Bash syntax, ShellCheck, target refusals, no-publication
  scans, Gitleaks, and diff checks pass.
- Exact next action: commit the validated image harness locally, then invoke
  only `poc/kolla-ha/build-distribute-coffer-images.sh build
  jh.byun@100.123.168.66`.
- Preserved that harness in local commit `ec7b649` and invoked the build
  action. It created only the owner marker, exact Coffer/Kolla source
  checkouts, and isolated venv, then stopped before image construction because
  Kolla's package does not install the Python Docker SDK used by its Docker
  engine.
- The completion marker and both final tags remain absent on all three
  controllers. All 36 Kolla containers, zero Coffer runtime/config/listeners,
  and external Ceph/RGW health passed the post-failure boundary.
- Added an exact `docker==7.2.0` build-venv input, matching the working
  controller deployment venv, and require that version before `kolla-build`.
- Exact next action: commit this isolated dependency correction locally, then
  resume only `poc/kolla-ha/build-distribute-coffer-images.sh build
  jh.byun@100.123.168.66`.
- Preserved that correction in local commit `ea6995e` and resumed the same
  phase. Controller-1 built both pinned Kolla-compatible x86_64 images and
  streamed them directly to controller-2/3 without a registry or retained
  archive.
- All three controllers have identical Coffer image ID
  `sha256:336140d2d9b552b8635a3a742c5ca30a95173ccfb4459a46e2430b8ef0b007d4`
  and Distribution-wrapper image ID
  `sha256:d9c108f8879de50aef9b6641d56a5e3459bf2ced122f6c21431efe708b0b3e67`.
  Architecture is Linux amd64 and users are exactly `coffer` and `registry`.
- A repeated complete build invocation was marker-only and retained
  image ID/creation snapshot SHA-256
  `1bb91f677fb9e3d15dabb76c5abcea9a65110fa1b2fe617e0dfef8545575b762`.
  Owner/completion markers and build logs are root-only mode 0600 and pass
  credential URL, Authorization, and private-key pattern scans.
- All 36 Kolla containers remain healthy; Coffer runtime/config/listeners
  remain absent; external RGW remains healthy. Docker emitted one non-fatal
  base-manifest signature-validation warning, so no signature/provenance claim
  is made and ADR 0006 remains blocked.
- The now-reachable `ready` control check exposed string identity comparison
  for `openstack_cacert`. The value-comparison correction passes the real
  profile and the negative gate now stops at the expected missing
  `/etc/kolla/coffer-globals.yml`.
- Exact next action: implement and statically validate
  `poc/kolla-ha/prepare-coffer-companion.sh` with exact three-host groups,
  owner-only inputs/backend TLS, direct storage-1 RGW secret transfer, and a
  hard stop before database/catalog/HAProxy/runtime mutation.
- Added the bounded `status|prepare` companion-input phase and its two guest
  helpers. It fixes the four Coffer groups to the three controllers, validates
  the production globals, creates signing/JWKS and backend-TLS inputs only on
  controller-1, and streams the existing RGW access key, secret key, and
  public CA directly from storage-1 without retaining a local archive.
- The prepare transaction preserves the original inventory and removes
  partial inputs/globals on failure. Its completion marker is withheld until
  the independent `ready` preflight passes; database, Keystone, HAProxy, and
  Coffer containers are outside this phase. `status` performs no cleanup or
  other mutation and fails if any fixed temporary transfer path exists.
- Bash syntax, ShellCheck, Python compilation, YAML parsing, target refusals,
  mutation-surface scans, Gitleaks, diff checks, and the live mutation-free
  status pass. The live boundary retains identical images, 36 healthy Kolla
  containers, healthy external Ceph/RGW, and fully absent companion/runtime/
  database/catalog state.
- Exact next action: commit the validated companion preparation harness
  locally, then invoke only
  `poc/kolla-ha/prepare-coffer-companion.sh prepare
  jh.byun@100.123.168.66`. On failure, verify rollback and temporary-residue
  absence before resuming this phase.
- Preserved that harness in local commit `192d154`. The first `prepare`
  invocation reached the final atomic install but stopped because the
  previously minimal Kolla deployment had no `/etc/kolla/config` parent.
  Rollback passed: the inventory, globals, and inputs are absent; only the
  expected owner marker remains; all fixed transfer paths are absent; all 36
  Kolla containers, both image IDs, and external Ceph/RGW remain healthy.
- Correction: create only the exact root-owned mode-0755 Kolla custom-config
  parent when absent, record ownership of that creation, and remove it with
  `rmdir` during a failed transaction after partial input cleanup. Existing
  parent state must match the same owner/mode contract.
- Exact next action: statically validate and locally commit this isolated
  parent-directory rollback correction, then resume only the same companion
  `prepare` action.
- Preserved the parent correction in local commit `f001f20`. The resumed
  transaction again rolled back fully but exited silently during final
  validation. A bounded controller-side mode probe identified the exact
  cause: `install -d -m 0700 <temporary>/coffer/secrets` gives its implicit
  intermediate `coffer` directory mode 0755, while the accepted secret-root
  contract requires 0700.
- Correction: create the temporary `coffer` parent explicitly as
  root-owned mode 0700 before its secret and public children. No final path,
  recipient, or deployment boundary changes.
- Exact next action: statically validate and locally commit the explicit
  temporary-parent-mode correction, then resume only the same companion
  `prepare` action.
- Preserved the mode correction in local commit `0400cca`; the next resume
  passed. Exact groups, owner-only inputs, backend/RGW TLS, the external
  sentinel, identical images, and continued absent runtime/database/catalog
  passed both pre-completion and post-completion `ready` gates.
- A repeated-prepare metadata check exposed a gate-ordering defect without
  changing state: the wrapper called the completed image-phase status first,
  but that lower phase intentionally rejects the now-present companion
  inputs. Owner/input/global/inventory metadata remained identical before and
  after the refused repeat.
- Correction: inspect companion markers first. Absent/owned state still
  requires the image-phase gate; prepared inputs and complete state use the
  stronger integrated `ready` gate. A complete repeat performs no transfer,
  key generation, or lower-phase absence check.
- Exact next action: validate and locally commit this idempotent gate-order
  correction, then repeat `prepare` with a before/after metadata comparison.
- Preserved the marker-first correction in local commit `3182f90`. The
  repeated complete `prepare` now passes `idempotent=yes`; server-side
  metadata for all markers, inventory, globals, directories, and input files
  is unchanged.
- Independent `status` accepts state `complete`, exact inventory and
  production profile, owner/modes and certificate identities, primary-only
  storage credentials, the 4-MiB sentinel, identical image IDs, 36 healthy
  Kolla containers, and no runtime/database/catalog or fixed transfer
  residue. Controller-2/3 retain no private deployment/input state.
- Exact next action: implement and statically validate a guarded Stage 5
  companion lifecycle wrapper for only `status`, `prechecks`, and `deploy`.
  It must use the pinned controller-1 source/venv, root-only no-log phase
  logs and markers, exact inventory/globals inputs, independent ready gates,
  and a hard stop before invoking `prechecks` until committed.
- Added that lifecycle wrapper and controller-1 helper. It invokes only the
  published companion entry point, orders `prechecks` before `deploy`, uses
  non-blocking locking and hard timeouts, retains root-only logs/markers,
  enables global Ansible no-log, and scans logs against Kolla plus companion
  credentials before accepting a phase.
- Deploy acceptance is fixed to nine healthy service replicas/listeners,
  twelve rendered service/bootstrap config directories, disabled reconciler,
  migration head `0004_inventory_import`, one database user, one
  `oci-registry` service/user with three exact endpoints, verified internal/
  backend/public TLS, external `/v2/` challenge, private-port denial, Kolla
  `check`, and external RGW health.
- The first live read-only status stopped at an over-escaped host parser after
  collecting the correct first-node snapshot; no lifecycle directory, log,
  marker, runtime, or configuration was created. The parser correction passes
  all three exact nodes with zero containers/listeners/configs and healthy
  external RGW before and after.
- Bash syntax, ShellCheck, target refusals, forbidden destructive/publication
  scans, Gitleaks, diff checks, and live mutation-free status pass.
- Exact next action: commit the validated lifecycle harness locally, then
  invoke only `poc/kolla-ha/run-coffer-companion-lifecycle.sh prechecks
  jh.byun@100.123.168.66`. Do not invoke deploy until the prechecks marker,
  log scan, and independent absent-state boundary pass.
- Preserved the guarded lifecycle in local commit `1f14cce` and invoked only
  `prechecks`. The three controller recaps are `changed=0`, `unreachable=0`,
  and `failed=0`; the secret-free root-only log and prechecks marker were
  accepted.
- Independent post-precheck `ready` still reports zero Coffer containers,
  listeners, rendered configs, database/user, Keystone service/user, and
  temporary residue. All 36 Kolla containers and external Ceph/RGW remain
  healthy.
- A repeated `prechecks` returned `idempotent=yes`; server-side marker/log
  metadata was unchanged, and the same independent ready/storage boundaries
  passed.
- Exact next action: record and locally commit the accepted prechecks
  checkpoint, then invoke only
  `poc/kolla-ha/run-coffer-companion-lifecycle.sh deploy
  jh.byun@100.123.168.66`. If deployment or acceptance fails, preserve its
  root-only log, require the deploy marker to remain absent, audit exact
  partial state, and do not run another lifecycle action until corrected.
- Preserved prechecks evidence in local commit `95bb95e` and invoked deploy.
  It stopped at the no-log one-shot schema bootstrap with no deploy marker.
  The protected lifecycle log remains root-only and passed the credential
  scan; its safe failure summary is `dependency_unavailable`.
- Exact root cause: the bootstrap process could reach ProxySQL but rejected
  its self-signed internal chain because `coffer-bootstrap` alone was omitted
  from Kolla's CA-copy service set and its config.json lacked the custom CA
  bundle entry.
- Exact partial state: each controller has four rendered Coffer config
  directories and three HAProxy listeners, but zero Coffer service/bootstrap
  containers. The database and user plus one Keystone service/user and three
  endpoints exist; `alembic_version` does not. External Ceph/RGW remains
  healthy and the deploy marker is absent.
- Correction: include the one-shot bootstrap in `coffer_processes` CA copying
  and its Kolla config.json CA input, with three focused rendering/source
  tests. Keep the already built images and published clean source unchanged;
  prepare a separate base-commit-plus-exact-two-files operator checkout whose
  file digests and Git diff are validated before resume.
- Added the bounded `status|prepare` operator-source phase and upgraded the
  lifecycle status/deploy gates to accept only either the clean predeploy
  boundary or this exact 0-container/12-config/9-listener/no-migration partial
  boundary.
- Bash/ShellCheck, embedded Python compilation, six focused bootstrap/runtime
  tests, diff checks, and live mutation-free operator-source absence status
  pass.
- Exact next action: commit the bootstrap CA, operator-source, and exact-resume
  correction locally. Invoke only operator-source `prepare`, require lifecycle
  `status` to classify `deploy-partial`, then resume only companion `deploy`.
- Preserved that repair in local commit `fa99e3a`. The operator-source
  transaction created the exact two-file overlay without changing the clean
  published source or images, and lifecycle status accepted the exact
  `deploy-partial` state.
- The resumed Ansible deploy and Kolla check both passed. All three recaps
  have zero failures/unreachable hosts, and nine Coffer service containers are
  running and healthy. Acceptance withheld the deploy marker because its
  listener expectation counted only nine service backends; production
  HAProxy also binds three nonlocal VIP frontends on every controller, so the
  observed exact total is 18.
- Correction: accept only the exact 9-container/18-listener/12-config healthy
  deploy candidate, rerun Kolla check plus schema/catalog/TLS/routing probes,
  and write the marker without unnecessarily replaying the successful deploy.
- Exact next action: validate and locally commit this listener/candidate
  correction, run lifecycle status to exercise every remaining post-deploy
  probe, then resume deploy only to write the marker after the same gates pass.
- Preserved the 18-listener candidate correction in local commit `16be9bb`.
  Read-only status then passed all replica, migration, database, and catalog
  gates but failed the endpoint phase: API and private Distribution returned
  200/401, while all three edge replicas returned 503 and the controller-local
  external VIP probe could not route to the VIP owner.
- Edge root cause: the edge connects to the Kolla internal VIP frontend, whose
  certificate is signed by the Kolla CA, but its explicit upstream CA file
  contained the separate Coffer backend CA. The registry upstream TLS
  connection therefore failed and HAProxy correctly held all three edge
  backends down.
- External-probe correction: non-owner controllers have no external-subnet
  source address and route the VIP through the management gateway. Select the
  unique external VIP owner and perform the DNS-name TLS, 401 challenge, and
  private-port-denial probes locally there using only the public Kolla CA.
- Operator-source v2 replaces only the already admitted `config.yml`, copying
  the Kolla root CA to edge/reconciler upstream trust while retaining the
  bootstrap CA fix. Its transactional v1-to-v2 upgrade validates the old
  overlay, prepares the new one, and restores v1 on failure.
- Exact next action: commit the upstream-CA/operator-v2 and owner-local probe
  corrections, upgrade only the operator source, require structural
  `deploy-candidate`, then replay the idempotent deploy so config handlers
  restart edge and the full marker gate runs.
- Preserved the Kolla frontend-upstream CA and transactional operator-source
  v2 correction in local commit `88de660`. The v1-to-v2 upgrade retained the
  published source and immutable image inputs and produced the exact admitted
  two-file overlay.
- Lifecycle status accepted the exact `deploy-candidate`; the replayed Ansible
  deploy and Kolla check had zero failed or unreachable hosts. The complete
  marker gate then passed with nine healthy service containers, eighteen
  sockets, twelve configs, migration `0004_inventory_import`, exact
  database/catalog resources, API 200, edge/registry 401, all nine direct
  backends correct, FQDN-verified external 401, private 8789 denied, and
  healthy external RGW.
- Independent status passed. A repeated deploy returned `idempotent=yes`, and
  the completion markers, three lifecycle logs, and controller-1 Coffer
  container IDs retained identical metadata.
- Strengthened the deployed boundary to collect all nine application logs
  into root-only temporary controller-1 files, scan them against every Kolla
  and companion secret plus private-key, Authorization, and JWT patterns, and
  remove them on every exit. Bash/ShellCheck, five focused runtime-contract
  tests, and the live all-node log audit pass with no retained audit residue.
- Exact next action: add and locally validate a bounded two-project Stage 5
  tenant acceptance harness with finite Keystone identities, unique external
  VIP owner-local OCI traffic, project-A push/pull, project-B denial, digest
  persistence, log hygiene, and exact identity/client cleanup. Do not create
  identities until the harness is committed and its mutation-free preflight
  passes.
- Added and committed the guarded tenant fixture in `03b3190`. It admits only
  `preflight`, `prepare`, `status`, and exact `cleanup`, reuses the deployed
  Kolla toolbox SDK, and limits the fixture to two projects/users/member
  assignments and two unrestricted-false twelve-hour application credentials.
- Three mutation-free attempts exposed the actual deployed boundaries before
  identity creation: the host has no `clouds.yaml`; toolbox is the supported
  SDK/config location; generated cloud/catalog defaults select the unreachable
  external VIP unless both auth URL and interface are fixed internally; and
  the isolated external FQDN intentionally requires a later temporary DNS
  override. Corrections are preserved through commits `c090000`, `af89def`,
  and `dc072fc`. Every failed attempt left fixture and `/run` residue absent.
- The final preflight passed with zero existing identities or client residue,
  controller-2 as the unique external owner, all client tools ready, and
  `dns=override-required`. Prepare created exactly two finite projects, users,
  and credentials expiring at `2026-07-25T05:20:30`; independent status and
  the accepted companion/RGW boundaries pass.
- Identity state and marker are `root:root:0600` only on controller-1.
  Repeated prepare returned `idempotent=yes` with identical inode, size,
  timestamp, ownership, and mode. Controller-2/3 have no client state, Docker
  CA override, or tenant images, and both root-only toolbox transfer files are
  absent.
- Exact next action: extend and commit a guarded tenant `accept` phase, then
  use it to create one project-A repository, prove quota 429 and success,
  Docker push/pull, resumable upload, project-B denial, digest persistence,
  all-node tenant-secret log hygiene, and zero external-owner client residue.
- Added the tenant OCI acceptance in `c3e5fb2`, with bounded corrections
  through `c2e7357`. The clean preflight passed before repository or quota
  mutation. One exact project-A repository now has a 2-GiB quota, positive
  committed usage, and zero reserved usage.
- The live acceptance proved exact OCI quota 429 with real descriptor blobs,
  Docker push/pull through the external VIP, project-B Docker and direct API
  denial, and a deterministic 2-MiB upload across two PATCH requests. Status
  returns manifest 200, resumable blob 200, and project-B 401.
- Every owner-local attempt restored `/etc/hosts`, removed the Docker CA/auth
  tree, deleted the secret copy and tenant image tags, and left no client
  directory. All nine Coffer logs pass tenant password/application-secret,
  private-key, Authorization, and JWT scans.
- Bounded failures corrected only demonstrated causes: Kolla venv path,
  host/container identity-file separation, explicit outer rc/marker handling,
  valid quota descriptors, nested SSH stdin isolation, evidence namespacing,
  and manifest media negotiation. No failed status was accepted as complete.
- Independent status and repeated `accept` pass. The latter returns
  `idempotent=yes`; repository, quota marker, evidence, and accepted-marker
  metadata remain inode/size/timestamp/owner/mode identical.
- Exact next action: add and commit a controller-3-only API, edge, and
  Distribution replica stop/probe/restore harness. Its tenant data probe must
  tolerate exactly one missing replica while retaining public digest,
  project-B denial, quota, owner cleanup, log hygiene, and full post-restore
  health.
- Added and committed the exact service fault boundary in `a77b572`, corrected
  the observed Kolla restart policy in `92d44bb`, and replaced an SSH-unsafe
  health delimiter in `243d5dc`. Static checks and the committed
  mutation-free live preflight pass.
- The controller-3 API, edge, and Distribution containers were each stopped
  separately. Three authenticated manifest/blob and project-B isolation
  probes passed during every outage, for nine first-attempt successes. Each
  target recovered healthy before the next fault, and every full recovery
  gate restored nine containers, eighteen listeners, twelve configs,
  catalog/schema, private-port denial, log hygiene, and healthy external RGW.
- The first API restore wait misparsed a remote Docker format separator after
  the three outage probes had passed. Independent inspection found API, edge,
  and registry already healthy; the exact local harness process was stopped
  after its recovery trap restarted API. No edge or registry fault had yet
  run. The corrected colon-delimited wait then passed the fresh preflight and
  complete matrix.
- Three root-owned mode-0600 completion markers remain only on controller-1.
  Repeated `run` skipped all faults as `idempotent=yes`; marker inode, size,
  timestamp, ownership, and mode were unchanged.
- Exact next action: inspect external VIP ownership and Kolla
  Keepalived/HAProxy tracking read-only, then add a committed active-owner
  HAProxy stop/VIP-move/tenant-probe/restore harness before any Galera fault.
- Read-only inspection confirmed one shared VRRP instance with a two-second
  HAProxy socket check, `fall 2`, `rise 10`, and `nopreempt`. The first
  mutation-free preflight corrected BSD awk compatibility and a masked owner
  failure before any stop.
- The first fault moved both VIPs from controller-2 to controller-3; its
  immediate token call returned transient 503, and the EXIT trap restored the
  exact HAProxy. All controller-3 Coffer backends remained `UP/L7OK`, and the
  same tenant probe passed after convergence.
- The corrected bounded-retry cycle stopped controller-3 HAProxy, moved both
  VIPs to controller-2, and passed all three authenticated outage probes in
  attempts 2, 2, and 1. Controller-3 HAProxy and Keepalived check recovered;
  all nine Coffer backends, tenant paths, log hygiene, RGW health, and exactly
  one shared VIP owner pass.
- The root-owned mode-0600 marker is controller-1-only. Repeated `run`
  returned `idempotent=yes` without a stop and retained identical marker
  metadata.
- Exact next action: inspect Galera wsrep membership, MariaDB container
  metadata, and ProxySQL backend state read-only, then add a committed
  controller-3 MariaDB stop/write-read/restore harness before reconciler
  claim/fencing tests.
- Added `database-status` in `c94e9fc` and the guarded member-fault boundary in
  `eb3570b`. Baseline quota write/read/2-GiB restoration and the committed
  mutation-free Galera/ProxySQL preflight pass.
- One read-only diagnostic exception included the disposable database root
  password in owner-visible tool output. The value was not stored in Git or
  remote evidence, but is compromised and must be rotated or removed before
  the final secret gate. Later database diagnostics use stdin-only delivery.
- A stop-based attempt invoked no database write but an external Docker client
  restarted controller-3 MariaDB despite restart policy `no`. The harness was
  recovered and converted in `76c8378` to exact pause/unpause. The first pause
  proved Galera size 2 but exposed ProxySQL's offline hostgroup 3 behavior;
  it was unpaused before writes and modeled in `2ab4e81`.
- The accepted pause cycle reached size 2/Primary/Synced and moved
  controller-3 offline in all three ProxySQL instances. Three quota
  write/read/restore plus digest/isolation probes passed first-attempt.
  Unpause restored size 3/Primary/Synced, reader3 ONLINE, 2-GiB quota, all
  Coffer/RGW gates, and zero owner-client residue.
- The controller-1-only mode-0600 marker is metadata-stable; repeated `run`
  skipped the pause as `idempotent=yes`.
- Added and committed a two-phase tenant application-credential renewal path
  in `1f73af1` without changing project IDs, user IDs, roles, or repository
  namespaces. It stages
  two fresh finite credentials, authenticates them, atomically records the
  replacement plus retiring IDs, then retires only the old credentials and
  atomically finalizes the owner-only state. Interrupted finalization is
  resumable and unknown additional credentials fail closed.
- Bash syntax, ShellCheck, embedded Python compilation, ten focused runtime
  contract tests, diff checks, and scoped Gitleaks pass. The live
  `renew-preflight` is mutation-free and confirms the exact two-project,
  two-user, two-credential state, the accepted external owner/client boundary,
  and expiry `2026-07-25T05:20:30`.
- The accepted live renewal briefly held exactly four credentials only after
  both replacements authenticated, then retired the two original IDs and
  finalized exactly two renewed credentials expiring at
  `2026-07-25T07:33:26`. The existing project IDs, repository, quota, manifest
  and blob digests remained authoritative; project B still received 401.
  Runtime logs passed the renewed-secret scan and client state was removed.
- The identity state and prepared/renewed markers are controller-1-only and
  mode 0600. Controller-2/3, all three `/run` transfer paths, and owner-client
  paths are absent. Repeated `renew` returned `idempotent=yes` and retained
  identical inode, size, timestamp, ownership, and mode for all three files.
- Exact next action: return to the real deployed quota transaction retry
  surface and add a bounded concurrent/deadlock Galera probe with exact row
  and 2-GiB quota restoration before separate reconciler workers.
- Implemented a common three-attempt transaction-conflict classifier for
  MySQL 1205/1213 and SQLSTATE 40001/40P01. The inventory importer reuses it,
  and all eight explicit `QuotaStore` write boundaries now rerun their whole
  rolled-back transaction only for those codes. Unclassified database and
  constraint failures are not retried.
- Retry warnings contain only the fixed operation name and bounded attempt
  number. Focused tests prove success on the third attempt, no retry for an
  unclassified outage, exhaustion after exactly three attempts, and supported
  SQLSTATE recognition. The complete suite passes 246 tests when the installed
  console-entry-point directory is placed on `PATH`; `uv lock --check`,
  compile, diff, and scoped Gitleaks pass.
- Preserved the product retry surface in `a6f476e`. Added a separate update
  image harness pinned to that exact local commit, its deterministic Git
  archive, both installed quota-module digests, the existing Kolla commit,
  and the immutable Ubuntu base digest. It can build only
  `localhost/coffer:stage5-quota-retry` and directly distribute it to the
  three controllers; the original image/tag is never removed or retagged.
- Bash syntax, ShellCheck, eleven focused runtime-contract tests, diff checks,
  and scoped secret scans pass. Live mutation-free preflight confirms all six
  API/edge containers still use the recorded current image ID, all three
  registries use their recorded image ID, all nine containers are healthy,
  and the update tag/state root is absent on every controller.
- Exact next action: commit the validated update-image harness locally, then
  invoke only `poc/kolla-ha/build-distribute-coffer-update.sh build
  jh.byun@100.123.168.66`. Validate one identical new image ID on all three
  controllers, installed retry source hashes and attempt bound, unchanged
  runtime image IDs/health, retained old image, owner-only evidence, and
  metadata-idempotent replay before any rolling deployment.
- Preserved the harness in `ad362bf` and invoked the exact build. Kolla
  completed the base and Coffer images, and the update tag reached all three
  controllers with the same ID. Validation then failed because the harness
  assumed `/var/lib/coffer/venv/bin/python3`; the image uses the Kolla-standard
  `/var/lib/kolla/venv/bin/python3`.
- A second fail-closed issue was exposed: a validation failure inside command
  substitution was not explicitly propagated, so distribution continued and
  wrote a mode-0600 four-line completion marker with an empty update image ID.
  Independent inspection confirms every API/edge/registry remains healthy on
  its original recorded image ID; the new tag is unused and identical on all
  three controllers.
- Corrected only the installed Python path and explicit failure propagation.
  The resume path admits exactly the observed owner-only four-line marker with
  an empty ID, validates the already distributed image and embedded source,
  then atomically replaces that marker. Any other malformed marker fails
  closed.
- Preserved that correction in `9dedfed`. Its first resume again failed before
  marker repair: `docker run` launched the correct Python, but omitted `-i`,
  so the embedded verifier received no stdin and returned an empty snapshot.
  Independent direct inspection confirms both installed module hashes and the
  three-attempt bound are exact; all current containers remain unchanged.
- Added only stdin attachment to the no-network, remove-on-exit validation
  container. Exact hash validation still occurs inside the built image.
- Preserved that correction in `cf40796` and resumed the same phase without a
  rebuild. All three controllers now carry update image ID
  `sha256:bf728bc1938d7f68a38fef16600d1c7a81bc0181863425736941fc0228bacb66`.
  The embedded installed module hashes and three-attempt bound pass; the
  original image ID remains
  `sha256:336140d2d9b552b8635a3a742c5ca30a95173ccfb4459a46e2430b8ef0b007d4`.
- Every running API/edge/registry retained its original recorded image ID and
  healthy state. The mode-0600 owner/completion markers and build log are
  controller-1-only, local/remote archive transfers are absent, and no image
  was published.
- Repeated `build` returned from the accepted marker. All three image
  ID/creation values plus owner/completion/build-log inode, size, timestamp,
  ownership, and mode were unchanged; no rebuild or transfer occurred.
- Exact next action: add a committed serial-one Coffer rolling-upgrade harness.
  It must use a temporary owner-only globals overlay selecting only the update
  Coffer image, keep Distribution unchanged, continuously probe tenant
  digest/isolation, require one host at a time, and retain the old image and an
  exact compatible rollback path before any live Galera retry probe.
- Added `preflight|status|upgrade|rollback` rolling-update actions. The guest
  admits only recorded old/update Coffer IDs, requires Distribution to retain
  its old ID, validates `coffer_image_full` as the sole semantic change in a
  mode-0600 `/run` overlay, and invokes the companion upgrade play with
  `kolla_serial=1`. The persistent globals file is never changed.
- The outer harness runs bounded tenant digest/blob/project-B probes while the
  Ansible process is alive, requires at least one in-flight and three total
  successful probes, and performs the full companion and tenant acceptance
  gates afterward. The same state machine can resume an old/new partial mix
  and has an exact serial rollback marker/action.
- Bash syntax, ShellCheck, twelve focused runtime-contract tests, diff checks,
  and scoped Gitleaks pass. Live mutation-free preflight reports current=3,
  updated=0, no rolling root or temporary overlay, retained digest/isolation,
  nine healthy services, and healthy external RGW.
- Exact next action: commit the rolling harness locally, then invoke only
  `poc/kolla-ha/run-coffer-rolling-update.sh upgrade
  jh.byun@100.123.168.66`. Require serial image transitions, continuous
  tenant probes, final current=0/updated=3, unchanged Distribution and
  persistent globals, owner-only logs/markers, and no temporary residue.
- Preserved the initial harness in `a1d431e` and invoked the exact upgrade.
  Kolla-Ansible completed with no failed or unreachable hosts and replaced
  API/edge serially on all three controllers. Independent status now shows
  current=0/updated=3, unchanged Distribution, nine healthy containers,
  accepted tenant digest/isolation, healthy RGW, clean logs, and no temporary
  globals.
- The outer probe nevertheless recorded transient failures because its former
  full `data-status` action scanned a container name during Kolla's deliberate
  remove/recreate window. The immediate guest postcheck also raced Docker
  health convergence. These harness failures correctly withheld the upgrade
  marker even though Ansible and the final runtime state succeeded.
- Added a mutation-window-only `path-status` probe for manifest, blob,
  project-B denial, and client cleanup; retained full control/quota/log scans
  after convergence. Added a bounded 180-second image/health convergence gate
  and an exact current=0/updated=3 postcheck-only resume that does not rerun
  Ansible.
- Bash syntax, eight focused resume/race contracts, diff checks, and a live
  path probe pass. ShellCheck passes when excluding the pre-existing
  indirect-trap SC2329 informational diagnostic. The remote rolling root has
  only its root-owned owner marker and mode-0600 upgrade log; the temporary
  overlay and upgrade completion marker are absent.
- Exact next action: commit the bounded rolling correction, invoke the exact
  `upgrade` action once to resume only postchecks and write its marker, then
  repeat `status` plus full tenant/service acceptance before the real-Galera
  concurrency probe.
- Preserved the correction in `772b23f` and resumed the exact upgrade. It
  detected current=0/updated=3, printed `resume=postcheck`, skipped Ansible,
  passed the first bounded convergence check, and wrote the owner-only upgrade
  marker.
- One in-flight and three total external path probes passed. Final companion,
  tenant, quota, digest, project-isolation, runtime-log, HAProxy, and external
  RGW gates all passed. The final result was probes=3, during=1, serial=1.
- Independent audit confirms three healthy updated API/edge pairs, three
  healthy unchanged Distribution replicas, unchanged persistent Coffer
  globals, no temporary overlay, and exact root-only rolling owner/log/marker
  evidence. No image was removed, retagged, or published.
- Exact next action: inspect the accepted shared-SQL concurrency fixtures and
  deployed database contract, then add a bounded real-Galera transaction
  harness proving one-winner concurrent reservation plus one actual
  retryable-conflict recovery with exact quota/row restoration and zero
  helper/credential residue.
- Added a guarded real-Galera transaction harness. It runs the installed
  updated `QuotaStore` inside `coffer_api`, reads the deployed database
  connection only in-process, and sends the helper over stdin without a
  retained host/container file.
- Two independent stores must produce one admitted and one denied 150-byte
  reservation against a 150-byte limit. A separate row-lock holder then forces
  a real MySQL 1205 through ProxySQL; success requires exactly one installed
  retry record for `set_limit` attempt 2 and a committed second attempt.
- Only two fixed temporary project IDs and two fixed repository IDs are in
  scope. Child-first cleanup runs before an owned resume and in `finally`;
  completion requires aggregate row residue zero. A root-only owner/completion
  marker state machine records ownership without credentials.
- Twenty-five focused tests, Bash/ShellCheck/Python compilation, four refusal
  and forbidden-command contracts, and diff checks pass. Live mutation-free
  preflight reports Galera size 3 Primary/Synced, healthy ProxySQL routing,
  retry bound 3, zero allowlisted row residue, and absent marker/helper state.
- Exact next action: commit the guarded transaction harness, invoke only
  `poc/kolla-ha/test-coffer-galera-transactions.sh run
  jh.byun@100.123.168.66`, and require the exact 1-admitted/1-denied,
  retry-code-1205/attempt-2, residue-zero result plus final tenant and
  three-node Galera health before compatible rollback.
- Preserved the harness in `8cb9a22` and ran it. Two independent installed
  stores returned exactly one admitted and one denied reservation against the
  shared 150-byte limit. A real MySQL 1205 then occurred through the deployed
  database path; the installed decorator emitted exactly one `set_limit`
  attempt-2 retry and committed that second transaction.
- Child-first cleanup and an independent helper preflight reported aggregate
  synthetic-row residue zero. The ordinary tenant database write/read/restore,
  manifest/blob, project-B denial, runtime-log, external RGW, Galera size-3
  Primary/Synced, and all ProxySQL route gates passed afterward.
- Root-only owner/completion markers were written only after final acceptance.
  An idempotent replay ran no transaction probe, reconfirmed residue zero and
  all health gates, and retained identical inode/size/timestamp/ownership/mode
  metadata for both markers.
- Exact next action: inspect the deployed reconciler topology and accepted
  multi-worker claim/fencing fixtures, then implement a bounded separate-worker
  Galera harness using only allowlisted stale reservations, exact claim/lease
  fencing, child-first cleanup, and final tenant/Galera health gates.
- Added a guarded reconciler claim/fencing harness that runs the installed code
  as separate stdin-only processes in controller-1 and controller-2
  `coffer_api`. The periodic reconciler stays disabled because the production
  maintenance identity is still unresolved.
- A setup-time cursor excludes every pre-existing global reconciliation
  candidate. Both workers claim only three newer fixed reservations with
  bounded size two; an initially smaller worker may retry to tolerate
  MariaDB's safe transient empty batch. Acceptance requires both workers,
  three unique rows/tokens, no overlap, and zero usage after consumption.
- Controller-2 also acquires a separate real two-second lease and exits.
  Controller-1 must prove pre-expiry blocking, wait for wall-clock expiry,
  acquire a replacement token, reject the old token with
  `StaleReconciliationClaim`, and restore the reservation.
- Root-only ownership authorizes child-first partial-run cleanup. Thirty-two
  focused tests, Bash/ShellCheck/Python compilation, four refusal/forbidden
  contracts, scoped Gitleaks, and diff checks pass. Live mutation-free
  preflight reports both controller helpers ready, retry bound 3, row residue
  zero, absent marker/helper state, and full tenant/Galera health.
- Exact next action: commit the guarded reconciler fencing harness and invoke
  only `poc/kolla-ha/test-coffer-reconciler-fencing.sh run
  jh.byun@100.123.168.66`; require disjoint claims, actual lease recovery,
  stale-token denial, exact cleanup, final tenant/Galera health, and
  idempotent marker replay.
- Preserved that harness in `b5b954a`. The first `run` created only the
  root-only owner marker and three allowlisted reservations, then both workers
  returned safe empty batches. The bounded retry exhausted and completion was
  withheld before lease/fence work.
- MariaDB stores this migrated `updated_at` at whole-second precision, while
  the application cursor retained microseconds. Same-second candidate
  timestamps were truncated earlier than the cursor and excluded by `after`.
- The EXIT trap removed every allowlisted row and local worker output.
  Independent preflight reports residue zero; the owner-only running marker is
  the sole partial-state evidence. Tenant, service, identity, object, and
  container state are unchanged.
- Corrected setup to record a whole-second cursor and cross the next clock
  second before candidate insertion. Python compilation, fourteen focused
  tests, diff checks, and an owned two-controller diagnostic pass with exact
  claims 2+1 followed by cleanup.
- Exact next action: commit the cursor-precision correction and rerun only the
  owned-partial reconciler `run`; require cleanup-before-resume, disjoint
  claims, real lease expiry and fencing, residue zero, final tenant/Galera
  acceptance, and idempotent replay.
- Preserved the correction in `83c223d` and resumed the owner-only partial
  run. Cleanup ran before setup; controller-1/controller-2 claimed 1+2 unique
  reservations with one bounded retry after a safe empty batch. Both worker
  IDs and all reservation/token values were distinct with no overlap.
- Controller-2 acquired and abandoned the separate real two-second lease.
  Controller-1 proved pre-expiry blocking, recovered with a different token
  after wall-clock expiry, fenced the old token with
  `StaleReconciliationClaim`, and restored quota with the replacement.
- Both helpers reported retry bound 3 and aggregate residue zero. The tenant
  database write/read/restore, manifest/blob, project-B denial, logs,
  Galera/ProxySQL, HAProxy, and RGW gates passed before the root-only completion
  marker was written.
- Repeated `run` skipped all worker mutation, reconfirmed both helpers clean,
  and retained identical inode/size/timestamp/ownership/group/mode metadata for
  owner and completion markers.
- Scope remains bounded: periodic reconciliation is still disabled and its
  production maintenance identity remains unresolved.
- Exact next action: inspect signing-key/JWKS materialization and token
  validation, then implement a bounded overlapping-key rotation with
  old/new-token evidence across all replicas, maximum-lifetime retirement,
  exact rollback material, log/secret hygiene, and final tenant acceptance.
- Added guarded `preflight|status|run|rollback` signing-key actions.
  Controller-1 retains root-only original/new RSA material and markers; only
  public overlapping/new-only JWKS is distributed. Each Kolla phase is
  serial-one, stays on the accepted update image, uses a mode-0600 overlay, and
  scans owner-only logs.
- Forward rotation deploys old+new trust, captures an old live tenant token,
  switches all API signers, and tests both keys at all three direct edges and
  registries. After the old token's full 300-second lifetime plus guard, it
  deploys new-only trust and requires a fresh new token to succeed and a
  still-current synthetic old-key token to fail.
- Edge verification uses an authenticated malformed manifest: 400 proves a
  trusted token reached validation without upstream/quota mutation, while 401
  proves retired-key denial. Distribution uses only HEAD against the retained
  digest. All token/bearer/expiry files are root-only and removed.
- Persistent globals may change only the token key ID; the temporary overlay
  may additionally retain the update image. The reverse action restores
  overlap, switches back, waits the new-token lifetime, and restores old-only
  trust from root-only original material.
- Sixty-one focused tests, Bash/ShellCheck, four refusal/forbidden contracts,
  scoped Gitleaks, and diff checks pass. Live mutation-free preflight confirms
  all three signers and six verifier recipients use old-only
  `stage5-20260724`, tenant service is healthy, and rotation state is absent.
- Exact next action: commit the guarded key-rotation harness and invoke only
  `poc/kolla-ha/run-coffer-key-rotation.sh run
  jh.byun@100.123.168.66`; require overlap, signer switch, old-token continuity,
  full-lifetime retirement, per-replica outcomes, zero token residue, final
  acceptance, and idempotent replay before image rollback.
- Preserved the harness in `e5b713d`. Its first run stopped after owner
  creation and original-input backup because the Kolla control venv does not
  install Coffer and the material generator imported `coffer.tokens`.
- Independent aggregate audit confirms no prepared/phase/completion marker,
  no temporary globals, old-key/old-only source and all three runtimes, nine
  healthy containers, and no Kolla action or token issuance. The only new
  state is the exact root-only owner, empty new/token/log directories, and
  owner-only original rollback inputs.
- Replaced the project import with local RSA JWK encoding using cryptography
  and made missing-prepared-marker state resume only after validating the
  exact owner. Bash/ShellCheck, focused tests, diff checks, and the live
  partial-state audit pass.
- Exact next action: commit this preparation-resume correction and rerun only
  key-rotation `run`; require full overlap/signer/lifetime/retirement,
  per-replica outcomes, zero token residue, final acceptance, and idempotent
  replay.

## Plan 0017 Completion

- Recovered the completed Stage 4 worktree and preserved its unpublished
  deployment fixes, execution plan, and reproducible AIO harness.
- Official upstream discovery still identifies signed Distribution v3.1.1 as
  the latest stable release. Kolla 2026.1 documents supported Ubuntu, Debian,
  Rocky, and CentOS image bases; the executable qualification is bounded to
  digest-pinned Ubuntu Noble ARM64.
- Added `poc/production-images/` with exact Kolla commit, Ubuntu platform,
  signed Distribution release/provenance, Trivy, Podman client, and
  `govulncheck` pins. Its source snapshot and generated 64-package production
  constraint set fail closed on repository or `uv.lock` drift.
- Coffer now builds directly on Kolla `base` into a root-owned application
  venv rather than inheriting `openstack-base`. `cryptography` is upgraded
  from 43.0.3 to 49.0.0. Temporary system pip/setuptools/wheel/venv tools are
  removed after `pip check`; the registry wrapper removes the same unused
  system packaging tools.
- The ARM64 images run as dedicated `coffer` and `registry` users and pass the
  complete Stage 2 runtime contract: installed commands, config/permissions,
  repeat Alembic bootstrap, API/token/JWKS, quota edge, OCI push/pull,
  restart digest preservation, reconciliation, logs, secret checks, and exact
  runtime cleanup.
- Final evidence reports Coffer at 0 Critical/0 High in both Docker Scout and
  Trivy, zero detected secrets, and 331 SPDX packages. The minimized registry
  wrapper reports 8 Critical/10 High in Scout, 0 Critical/22 High in Trivy,
  zero detected secrets, and 363 SPDX packages.
- `govulncheck` v1.6.0 finds three reachable source call paths in signed
  Distribution v3.1.1 and 37 vulnerable symbol groups in its Go 1.25.9 release
  binary. The remaining `x/crypto` 0.49.0, `x/net` 0.52.0, gRPC 1.80.0, and
  Go standard-library findings cannot be closed by a wrapper rebuild.
- `qualification.json` sets `production_candidate=false` with exact blockers.
  ADR 0006 remains fail-closed; no private fork, waiver, image/evidence
  publication, commit, or push was made.
- The final harness is host-portable across the intended macOS/Linux control
  paths: it resolves `go` from `PATH` and selects `sha256sum` or `shasum`
  without a Homebrew-only executable path.
- Final repository regression and residue verification passed as recorded in
  plan 0017. Exact candidate images, containers, networks, and volumes are
  absent; retained evidence is ignored under
  `work/production-image-remediation/`.
- Exact next action: none. When a newer signed supported Distribution release
  exists, start with `poc/production-images/pins.env` and rerun the unchanged
  qualification plus native Referrers and malformed-reference protocol gates.

## Plan 0016 Completion

- The exact autostart-disabled `coffer-kolla-aio-stage4` VM ran with 8 vCPUs,
  32 GiB RAM, an isolated 180 GiB root overlay, and two dedicated interfaces.
  It and its exact volumes were destroyed after acceptance; existing
  shared-host domains and services remain untouched.
- Ubuntu Noble was SHA-256 pinned and Kolla-Ansible 2026.1 was pinned to
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`.
- Kolla `bootstrap-servers`, `prechecks --use-test-images`, `pull`, and
  `deploy` passed. The final deploy recap was `ok=404`, `changed=259`,
  `failed=0`, `unreachable=0`; the VIP Keystone endpoint returned HTTP 200 and
  all healthchecked containers were healthy.
- The AIO used Kolla's explicitly acknowledged test-only Quay images. This is
  functional Stage 4 evidence, not production image qualification.
- Coffer and the unmodified Distribution were built from published commit
  `dc145ff04bedff189ab751ba80791727b743a97e` through the independent bootstrap
  path. Companion precheck/deploy/reconfigure passed; API, edge, and registry
  are healthy.
- The exact disposable RGW identity and bucket `coffer-kolla-aio-stage4` passed
  an authenticated private sentinel round trip. The external TLS VIP returns
  the expected OCI `401` and Coffer Bearer challenge; API and registry HAProxy
  frontends remain internal-only.
- The disposable backend CA generator now emits critical CA constraints and
  signing key usage. This corrected Python 3.13 edge verification while
  retaining verified HAProxy and Distribution trust. Owner-only secret inputs
  remain only in the guests.
- The functional image scans still report unresolved Critical/High findings;
  Stage 4 does not clear production promotion.
- Kolla post-deploy and the proposed catalog contract passed. Two finite
  project identities proved Docker push/pull for project A and non-disclosing
  denial of project B control lookup, pull, push, tags, cross-mount,
  overwrite, and delete. The accepted digest was
  `sha256:7a3ebe5bfd1a4a19797d20b0c0bb39d44393e9a03fd852c0865b0f540d868df0`.
- API, edge, Distribution, and HAProxy restart preserved that digest and
  Alembic revision `0004_inventory_import`. Two consecutive companion
  reconfigures reported only the intentional one-shot bootstrap change;
  post-reconfigure behavior and secret/JWT log scans passed.
- Trivy 0.72.0 reports Coffer at 6 Critical/34 High and the registry wrapper
  at 6 Critical/54 High. These functional images remain production-blocked.
- Both finite Keystone fixtures and the exact Stage 4 RGW bucket/identity were
  removed. The final host audit found zero Stage 4 domains or volumes, all 18
  original domains intact, and `coffer-rgw-poc` still running with autostart
  disabled. Local temporary and known-host residue is absent.
- Final regression passed: 52 companion-role contract checks; 232 Python tests
  on each of Python 3.11, 3.12, and 3.13; lock, compile, eight installed CLIs,
  Go format/test/vet, six Compose models, 58 Make dry-runs, Coffer-scoped
  production-profile Ansible lint, 38 YAML and 12 Jinja parses, 66
  Bash/ShellCheck files, 65 Markdown files, 44 local links, project-owned
  Gitleaks over 311 files, explicit secret/address/residue scans, and diff
  checks.
- Stage 4 is a completed local work package and has not been committed or
  pushed. The user-authorized atomic publication included only completed
  Stages 1 through 3.

## Completed

- Initialized the repository.
- Added durable agent rules, model configuration, compaction guidance, and a pre-compaction Git snapshot hook.
- Added an execution-plan template, operating guide, and reusable long-horizon prompt.
- Started `docs/exec-plans/0001-product-discovery.md` and launched three read-only Ultra research tracks.
- Mapped ECR, Azure Container Registry, and Google Artifact Registry expectations into a proposed Coffer MVP, deferred scope, and explicit non-goals in `docs/product-discovery.md`.
- Verified the current OpenStack landscape, including the active OpenStack-Helm registry chart, OCI-consuming projects, historical false friends, and the absence of a verified first-class registry service/type in the researched official sources.
- Selected an unmodified Distribution v3.1.1+ data plane, a Keystone application-credential token broker, immutable project-ID namespaces, a regional Ceph RGW S3 bucket, bounded soft quotas, and coordinated read-only GC as proposed ADR baselines.
- Expanded the follow-up PoC plan with real Keystone/RGW, role/scope attack, conformance, encryption, quota, HA, and GC acceptance gates.
- Added a top-level `README.md` that introduces Coffer, records the naming contract, summarizes the architecture baseline, and routes readers to the durable documents.
- Completed cross-document verification after the rename: 47/47 external links returned HTTP 200 after retrying one transient OpenDev 500, both Mermaid diagrams rendered and were visually inspected with Coffer labels, 18 Markdown files passed structure/local-link checks, the documented PoC Bash parsed, and Gitleaks found no leaks.
- Accepted `coffer` as the project codename, `OCI Registry service` as the descriptive service name, proposed `oci-registry` as the future service type, and retained `registry` as the CLI noun. The decision is recorded in accepted ADR 0005.
- Renamed the canonical local repository directory to `/Users/byeonjaehan/projects/personal/coffer`; retained a compatibility symlink at the legacy path so the active Codex workspace remains usable.
- Accepted architecture ADRs 0001–0004 under the user's instruction to proceed and activated the thin vertical PoC plan.
- Pinned Distribution v3.1.1 and the M0 fixture images by digest, recorded the image vulnerability gate, and added a loopback-only unmodified Distribution plus MinIO compatibility environment under `poc/m0/`.
- Passed the M0 functional path: Docker push/pull by digest, persistence across a registry restart, ORAS artifact attach/discover, fallback referrer discovery, and S3 object presence.
- Completed the M0 upstream compatibility baseline: full OCI conformance 68/7/4, supported-capability conformance 59/1/19, exact image security and reachability scans, token/GC contract documentation, and visual inspection of both reports.
- Added proposed ADR 0006 to keep Distribution v3.1.1 PoC-only and gate any production candidate on security, supported-capability conformance, native Referrers or explicit fallback acceptance, and real RGW evidence.
- Accepted ADR 0007 after a Python 3.11–3.13 compatibility spike: Falcon 4.3.1 WSGI is the control API framework and Gunicorn 26.0.0 native `gthread` workers are the reference process model.
- Added a locked Python package and the first Coffer-owned vertical seam: repository create/get/list with Keystone project UUID ownership, reader/member `oslo.policy` rules, and `oslo.db` persistence.
- Added nine negative/positive API tests covering project/domain/system/unscoped/invalid/expired tokens, duplicate names across projects, cross-project non-disclosure, and identity-header spoofing.
- Added a request-local Keystone application-credential authenticator and bounded Basic parser. The code retains no submitted secret in Coffer state, principal objects, logs, exceptions, or persistence.
- Added and then accepted ADR 0008 after real lifecycle evidence confirmed that a standard authentication token cannot prove the credential record's configured expiry while Keystone enforces expiration, role removal, owner disablement, and deletion.
- Completed the hardened local M2 token contract with a separate Basic-auth realm, explicit control-database repository authority, `oslo.policy` action reduction, RS256/JWKS offline verification, five-minute maximum tokens, request/audit correlation, and no refresh token.
- Corrected three security gaps found by read-only parallel review: application-credential access rules now fail closed, dependency exception graphs and request locals no longer retain the Basic secret on expected failures, and unregistered repositories receive no registry grant.
- Added a two-project Docker/Distribution black-box fixture with direct post-restart blob checksum, reader/member/delete/missing/cross-project denials, positive and denied mounts, negative JWTs, overlapping two-key JWKS, log scans, and full secret/container/volume cleanup.
- Added `docs/runbooks/real-keystone-rgw-poc.md` for real TLS/lifecycle/credential-helper/RGW/SSE-KMS/audit acceptance without placing credentials in the repository.
- Added process liveness, database readiness, optional bounded Prometheus metrics, token-decision metrics, and the local multi-worker limitation record.
- Completed the final local verification matrix across Python 3.11–3.13, Docker/Distribution, documentation, runtime configuration, cleanup, and secret hygiene.
- Added a pinned, secret-safe `poc/devstack` harness for a Lima Ubuntu 24.04 guest, Keystone, MySQL, TLS, duplicate-domain identities, finite application-credential lifecycle, and Coffer's real authenticator seam.
- Bootstrapped the independent `coffer-devstack` Lima VM and passed strict CA trust, duplicate-domain/project/user isolation, project-scoped token, finite application-credential authentication/deletion, and host-side production authenticator checks against real Keystone.
- Corrected Coffer's empirical deleted-credential mapping: Keystone's `NotFound` response now becomes `InvalidApplicationCredential`, with no dependency exception graph or submitted secret retained.
- Proved real Keystone rejects finite credentials after configured expiration, delegated-role removal, owner disablement, and explicit deletion; accepted ADR 0008's provisioning-and-lifecycle enforcement boundary.
- Proved reader/member/admin effective-role mapping, service-role exclusion from registry roles, and domain/system nonproject isolation with real Keystone; temporary roles, users, and credentials are removed after verification.
- Passed real project/domain/system tokens through Coffer's production control middleware; proved project-only admission, incoming service-token role enforcement, a two-second revoke-cache bound, and 503 fail-closed behavior during a bounded Keystone outage.
- Reclaimed the explicitly approved retired `openstack-ebpf-controller-1` and `openstack-ebpf-compute-1` domains and their VM-specific disks and cloud-init files while preserving their shared Ubuntu base image, storage pool, and libvirt networks.
- Created the `coffer-rgw` libvirt directory pool on the local `/srv/nfs` XFS filesystem and bootstrapped `coffer-rgw-poc` with 8 x86_64 vCPUs, 24 GiB RAM, a 60 GiB root overlay, a separate 200 GiB raw OSD device, reserved NAT address `192.168.122.200`, and autostart disabled.
- Installed Ceph Tentacle 20.2.2 from a SHA-256-verified `cephadm` artifact, pinned the exact Ceph container manifest digest, bootstrapped without dashboard or monitoring, and added only `/dev/vdb` as the single `up`/`in` OSD.
- Deployed one cephadm-managed `rgw.coffer` Beast frontend on `192.168.122.200:8443`, validated its cephadm-signed certificate and SANs through an SSH tunnel, and proved that untrusted TLS and plaintext HTTP fail.
- Created a non-system registry identity and separately owned denial identity with no admin capabilities and one-bucket limits; proved private object round trip, anonymous denial, cross-owner denial, and extra-bucket denial without printing either key.
- Ran unmodified pinned Distribution v3.1.1 against real RGW with verified TLS and no redirects; preserved digest `sha256:7a3ebe5bfd1a4a19797d20b0c0bb39d44393e9a03fd852c0865b0f540d868df0` across Distribution/RGW restarts and online PG merges.
- Joined real DevStack Keystone, Coffer's production application-credential/repository-policy/RS256 seam, unmodified Distribution, and real RGW in `poc/integration`; project A passed Skopeo and Podman push/pull and preserved the Skopeo digest across Distribution and Coffer restarts, while project B received 401 and a failed push for project A.
- Repeated the complete real integration harness from the restored clean state; stable identities, digest/restart results, and 200/401 authorization outcomes matched while independent request IDs differed, and the second cleanup again restored the pre-integration lab state.
- Completed a write-stopped Distribution GC dry-run against real RGW: 19 objects remained 19, zero deletion candidates were reported, three selected referenced manifests preserved their digests after restart, and no destructive collector was run.
- Bound the real integration broker to production `/healthz`, `/readyz`, and `/metrics`; both process generations were healthy/ready, issued-token observations existed, metrics were free of tenant/request/credential/repository/secret/JWT values, and local aggregate decision time was recorded without making a production benchmark claim.
- Completed the quota enforcement spike: token-only, notification-only, and shared-bucket storage controls cannot bound project logical bytes; it introduced the private-edge manifest admission seam later accepted for PoC implementation in ADR 0009.
- Proved two pinned Distribution processes can share RGW upload state and the persistent HTTP secret: a 2 MiB upload started on replica 1, replica 1 stopped after 1 MiB, replica 2 finalized with 201, and both endpoints returned the completed blob/selected manifest after restart.
- Inspected Tentacle 20.2.2 KMS support read-only: Barbican/Vault/KMIP are viable SSE-KMS backends, testing is inadmissible, SSL is required by default, no KMS option is configured, and the current DevStack has no Barbican service.
- Published the fully verified baseline as root commit `f437995` to `jaehanbyun/coffer` `main` with an atomic push.
- Enabled exact Barbican commit `586152c223b9e1373f5e422276bcaa152686b761` plus RabbitMQ in the disposable DevStack, forced Barbican `host_href` and catalog endpoints to verified HTTPS, and passed strict-CA health checks.
- Created a dedicated `coffer-rgw-kms-poc` project/user with only the exact effective Barbican `creator` assignment and a server-stored random 256-bit AES/CBC secret; its password and key UUID remain guest-root mode `0600`, while retained host evidence contains only non-secret identity IDs and metadata, never the key UUID or secret values.
- Streamed the RGW caller binding directly between guest-root contexts with no Mac-side credential file, installed the public CA, redeployed `rgw.coffer` with a read-only CentOS libcurl CA bundle mount, and passed strict-TLS Barbican/Keystone probes from both the RGW host and daemon container.
- Completed the hardened Barbican SSE-KMS matrix: direct S3 plus five repository and three global novel OCI objects reported `aws:kms` with the selected key; new and pre-KMS digests survived fresh processes; random wrong-key and combined Keystone/Barbican outage writes failed with zero novel objects and multipart uploads; recovery passed; 17 isolated objects were removed; bucket-wide selected-key residue is zero; Ceph/Distribution returned to non-KMS baseline; DevStack and the tunnel are stopped.
- Implemented the ADR 0009 shared-SQL quota core and bounded manifest admission resource. Twelve focused tests pass for unique descriptor accounting, cross-project charging, concurrent one-winner admission, retry idempotency, conservative pending/release recovery, exact JWT/repository authorization, byte-for-byte forwarding, and Distribution-compatible 401/400/413/429/503 outcomes.
- Completed the private-edge quota black box with pinned Docker 29.5.3, Podman 5.6.0, and Skopeo 1.20.0. Distribution had no host binding; concurrent manifests returned one 201 and one 429; retry returned 201 without a second charge; missing quota returned 503; and an unpublished blob changed S3 objects from 28 to 30 while logical usage remained unchanged.
- Corrected a real Docker compatibility gap by merging repeated scopes for the same canonical repository before policy reduction. Forty-eight targeted token/quota tests pass, and the fixture cleanup removed every container, volume, credential, private key, generated JWKS, and JWT-shaped value.
- Completed the Ultra-review quota corrections: authoritative Distribution descriptor sizes, explicit media-type shapes, encoded-path rejection, SQLAlchemy 503 handling, valid retry state transitions, and project-row serialization now close the discovered admission/ledger bypasses.
- Reran the quota black box on isolated client/backend/storage networks. Docker, Podman, and Skopeo could reach only the edge and received no signing/cross-project secrets; forged-size and encoded-path requests returned 400; concurrent publication returned 201/429; retry returned 201; missing quota returned 503; staging remained physically separate; cleanup passed.
- Completed the hardened Barbican rerun with secret-free helper arguments, exact effective creator assignment, a rotated registry S3 key, deterministic novel OCI config/layer payloads, eight selected-key Distribution objects, positive-size multipart-copy compatibility, explicit zero-byte fail-closed evidence, wrong-key and combined identity/KMS outage closure, recovery, 17-object cleanup, and zero selected-key/multipart residue.
- Completed final regression and publication: 91 tests passed on each supported Python version; all Bash/ShellCheck, compile, lock, Gunicorn, Compose, Make, Markdown, Mermaid, external-link, diff, and secret scans passed; the lab safe state was rechecked; the milestone was committed once and atomically pushed to `jaehanbyun/coffer` `main`.
- Activated plan 0004 and completed its first milestone: Alembic revision `0001_quota_ledger` now owns the production quota schema; named constraints, foreign keys, and reconciliation indexes are explicit; production construction rejects missing/unversioned schema; test-only `create_all()` requires `bootstrap_schema=True`; 22 focused migration/quota/admission tests pass.
- Completed plan 0004's shared-SQL milestone: pinned PostgreSQL 17.10 and MariaDB 11.4.12 image indexes and SQLAlchemy drivers; both engines passed empty/repeated Alembic upgrade, drift detection, named database constraints, distinct backend connections, concurrent one-winner quota admission, idempotent retry/commit/release, downgrade/re-upgrade, and zero container/volume/network/credential residue through `poc/quota-sql/`.
- Completed plan 0004's reconciliation implementation and Distribution fixture: monotonic reservation versions reject reordered probe results; bounded deterministic cursor pages cover pending, release-pending, and periodic committed candidates; exact matching 200 commits/refreshes, exact 404 releases, and every auth/dependency/header/transport ambiguity leaves quota charged. Focused tests and pinned unmodified Distribution proved lost/duplicate/reordered handling, shared-descriptor deletion refund, final zero usage, and complete cleanup.
- Completed plan 0004's documentation and final regression: ADR 0009, architecture, research, README, real-lab runbook, and the new quota schema/reconciliation operator boundary now record Alembic and exact-probe authority plus the remaining lease/ingress gates. Python 3.11–3.13 each pass 108 tests; static/runtime/documentation/secret checks and both disposable integration harnesses pass with zero residue.
- Corrected an order-dependent logging regression discovered by the full matrix: Alembic's `fileConfig()` disabled existing Coffer loggers. The environment now sets `disable_existing_loggers=False`, and a focused test proves migration cannot silence application audit logs.
- Activated plan 0005 and added Alembic revision `0002_reconciliation_claims`, a separate expiring claim table, bounded shared-SQL claim/release APIs, reservation-version plus opaque-token fencing, and fixed-cardinality reconciliation outcomes. Thirty-six focused migration/quota/reconciliation/observability tests pass.
- Proved probe I/O occurs after the short claim transaction: a replacement worker can reclaim during a simulated slow probe, while the original late result is rejected as `stale_claim`. Indeterminate observations retain both quota charge and claim until lease expiry.
- Extended the PostgreSQL/MariaDB harness with three-candidate contention and an actual spawned claimant process that exits with status 17 after its claim commits. PostgreSQL divides the first call 2+1; MariaDB safely returns 0+2 under range-lock contention and a post-contention bounded retry claims the final item. Both engines recover the abandoned lease, reject the old token, end at zero usage, remove all fixture resources/secrets, and leave Podman stopped.
- Activated plan 0006 and added the installed `coffer-reconcile` process with bounded oslo.config options, exact schema/origin startup checks, safe lease-versus-sequential-batch validation, fixed aggregate summaries, 0/75/78 exit classes, and no command-line secret input.
- Added bounded cursor-preserving cycles, serial periodic execution, monotonic interruptible waits, symmetric jitter, capped/resettable failure backoff, and restored SIGTERM/SIGINT handlers. Fourteen runner tests pass, including config-instance isolation, secret-free missing-config exit 78, and an installed subprocess that exact-404 reconciles a real migrated SQLite reservation without logging its project, digest, or database path.
- Documented the operator config, exit, cursor/snapshot, lease, signal, retry, credential, and remaining production-gate contract in the quota runbook, README, architecture, ADR 0009, observability notes, quota research, and real-lab runbook.
- Completed plan 0006 regression: 128 tests pass on each of Python 3.11, 3.12, and 3.13; lock, compile, Alembic head, installed entry point, Gunicorn, Bash/ShellCheck, five Compose models, all Make dry-runs, 43 Markdown files, 21 local links, diff checks, private-key/JWT shapes, and Gitleaks over 184 project-owned files pass.
- Published plan 0006 as commit `5500e36` to `jaehanbyun/coffer` `main`; local and remote heads match.
- Activated plan 0007 after mapping the legacy repository schema, Alembic metadata, production constructors, fixture bootstraps, and PostgreSQL/MariaDB downgrade/re-upgrade harness.
- Added shared schema revision validation and online revision `0003_repository_metadata`. Fresh databases create repository metadata; exact legacy tables are adopted without row rewrites; incompatible columns, primary key, or project/name uniqueness and offline SQL generation fail before revision 0003 is claimed.
- Normal `RepositoryStore` construction now requires the exact Alembic revision and table. Unit and disposable fixtures declare `bootstrap_schema=True`; API, token, admission, and reconciliation runtime paths no longer create repository tables implicitly.
- Verified PostgreSQL 17.10 and MariaDB 11.4.12 preserve one exact legacy repository row through adoption, non-destructive downgrade, and re-adoption while all prior quota concurrency, process-abandonment, recovery, fencing, drift, and cleanup checks still pass. Podman is stopped.
- Added accepted-for-PoC ADR 0010 and updated README, architecture, schema/reconciliation runbook, ADR 0009, and the real-lab runbook. The boundary explicitly does not inventory OCI content or authorize production migration.
- Completed plan 0007 final regression: 134 tests pass on each of Python 3.11, 3.12, and 3.13; lock, compile, Alembic head, installed entry point, migrated-schema Gunicorn, Bash/ShellCheck, five Compose models, all Make dry-runs, 45 Markdown files, 25 local links, diff checks, private-key/JWT shapes, and Gitleaks over 188 project-owned files pass.
- Published plan 0007 as commit `6d36ed7` to `jaehanbyun/coffer` `main`; local and remote heads match.
- Activated plan 0008 as a read-only completeness and cutover-discovery package. Ledger imports, quota enablement, object mutation, credentials, and production access remain explicitly excluded.
- Established the plan 0008 completeness boundary from primary v3.1.1 sources: standard catalog/tags/known-reference APIs and best-effort in-memory notifications cannot reconstruct digest-only history, while the GC path uses repository and manifest revision enumerators independently of tags.
- Added `coffer-inventory-verify`, strict storage-evidence and control-authority schemas, bounded page/hash/two-scan validation, exact canonical repository authority, manifest/index graph validation, and deterministic output stripped of repository names, tags, payloads, URLs, credentials, tokens, and timestamps. Seventeen focused tests pass.
- Added a pinned Go 1.25.1 helper compiled against Distribution v3.1.1 and a stopped-registry filesystem fixture. The tags API exposed one tagged manifest while storage enumeration exposed it plus one digest-only untagged index; both scans matched, four descriptors resolved, registry/control hashes were unchanged, both digests survived restart, and all resources/state were removed. Podman is stopped.
- Added proposed ADR 0011, the existing-content inventory research/runbook, and architecture/README/quota-boundary updates. The filesystem helper is PoC evidence only; production RGW support, credentials, packaging, import, backup, cutover, and rollback remain unimplemented and unauthorized.
- Completed plan 0008 final regression: 151 tests per Python 3.11/3.12/3.13; Go test/vet; the final pinned fixture with explicit snapshot-drift rejection; lock/compile/Alembic/CLI; 58 Bash/ShellCheck files; six Compose models; ten Make dry-runs; 50 Markdown files and 29 local links; 99 external links; 204 project-owned Gitleaks files; key/JWT, whitespace, and diff checks. Podman is stopped and no fixture state remains.
- Published completed plan 0008 as commit `65bdace` to `jaehanbyun/coffer` `main`; local and remote heads match.
- Activated plan 0009 for a one-time empty-ledger import contract: canonical artifact hash binding, exact authority, one transaction, immutable baseline marker, exact-replay no-op, different-baseline/non-empty-ledger refusal, and honest over-limit usage. Production access and admission remain excluded.
- Added strict canonical `coffer.inventory/v1` parsing and expected SHA-256 binding. Nine focused parser tests recompute every redundant aggregate and reject noncanonical bytes, hash/fact/index drift, missing project summaries, and unknown secret-shaped fields before database access; all 17 inventory tests still pass.
- Added revision/model `0004_inventory_import` and the one-transaction empty-ledger import. Focused SQLite evidence proves committed graphs/reference counts, exact and concurrent replay, different-baseline/non-empty-ledger/authority refusal, downgrade guard, full rollback after a forced second-row failure, and honest over-limit usage with new-byte denial; migration/inventory/import tests total 46 passes.
- Added installed `coffer-import-inventory` with environment-only database URL input and aggregate-only output. PostgreSQL 17.10 and MariaDB 11.4.12 both prove forced second-row rollback, concurrent one-writer/exact-no-op convergence, different-baseline rejection, and honest over-limit accounting; a discovered MariaDB marker deadlock now has a three-attempt retry limited to known MySQL/PostgreSQL transaction codes. Focused tests total 49; the shared-SQL fixture and cleanup pass; Podman is stopped.
- Added proposed ADR 0012 and completed the production refusal/cutover boundary across README, architecture, ADRs 0009–0011, inventory/quota runbooks, and the shared-SQL guide. The importer is verified PoC evidence only and does not authorize production data access, maintenance, SQL writes, or admission enablement.
- Completed plan 0009 regression: 174 tests pass on each Python 3.11.14, 3.12.2, and 3.13.14; lock, compile, Alembic head, installed CLIs, Go, 58 Bash/ShellCheck files, six Compose models, 54 Make dry-runs, 54 Markdown files, 32 local links, 99 external links, diff, and secret-safety checks pass. The successful shared-SQL run removed every disposable resource and generated credential.
- The final inventory-fixture rerun was not repeated because Podman 5.6.0/libkrun began exiting immediately after reporting successful boot. Two non-destructive retries reproduced it; the machine is stopped and no VM/data was recreated. Plan 0008's live inventory fixture and plan 0009's successful PostgreSQL/MariaDB run remain the relevant completed evidence.
- Published plan 0009 as commit `5e9b02e` to `jaehanbyun/coffer` `main`; local and remote heads match and the worktree was clean.
- Activated plan 0010 to compare the immutable marker and complete imported ledger against the same canonical artifact from one read-only repeatable SQL snapshot. The result is bounded equality evidence, not cutover readiness or authorization.

## Decisions and Reasons

- Checked-in files are the source of truth because conversation summaries and experimental memories may be incomplete or stale.
- Semantic state is written manually to the active plan and this handoff; the hook captures only mechanical Git state to avoid guessing decisions or copying sensitive transcript data.
- The main implementation model is `gpt-5.6-sol` at `high`; plan mode uses `xhigh` for architecture and risk analysis without paying that cost for every implementation step.
- The automatic compaction threshold remains at the model default until real sessions show a reason to tune it.
- Three read-only `gpt-5.6-sol` Ultra agents were used for independent OpenStack, OCI data-plane, and identity/storage/security research; the primary agent verified and integrated their evidence.
- Coffer composes upstream Distribution instead of building/forking a registry or adopting Harbor/Quay as a component.
- OpenStack naming is separated by concern: project codename `coffer`, descriptive service name `OCI Registry service`, proposed service type `oci-registry`, and CLI noun `registry`.
- Finite restricted Keystone application credentials authenticate the broker; the broker issues short-lived Distribution JWTs and no non-expiring refresh token.
- Ceph RGW S3 is the single-region storage baseline. Project accounting is logical and bounded-soft, not byte-perfect physical quota.
- Barbican is the validated OpenStack-native SSE-KMS path for the pinned Tentacle PoC; owner-only bindings and deterministic rollback remain mandatory, and the disposable cross-host tunnel is not production topology.
- Tentacle 20.2.2 rejects encrypted-source ordinary `CopyObject`, so the Distribution S3 driver uses `multipartcopythresholdsize: 0` for positive-size payloads in this PoC. Zero-byte encrypted moves still fail closed and block production promotion until a released Ceph fix/backport or another proven backend/release closes the gap.
- ADR 0009 is accepted for PoC validation: only bounded manifest PUTs cross the admission seam, blob bodies stay streamed to unmodified Distribution, shared SQL is the logical quota authority, and physical staging remains a separate service-wide concern.
- One Alembic chain is the sole repository/quota control-schema upgrade authority; normal startup validates the exact revision and required tables, while `create_all()` is explicit unit/disposable fixture-only behavior.
- Revision `0003_repository_metadata` runs online and strictly creates or adopts the exact legacy repository table. Drift and offline conditional migration fail closed; downgrade retains repository identity because table provenance cannot be inferred safely. OCI payload inventory remains separate.
- Proposed ADR 0011 uses the exact qualified Distribution release's exported repository/manifest storage enumerators under write exclusion and two equal scans. HTTP tags, notifications, GC stdout, and direct backend-key parsing are not inventory authority; the resulting artifact still cannot authorize or perform a ledger import.
- Proposed ADR 0012 allows exactly one verified canonical baseline to populate an otherwise empty quota ledger in one transaction. It requires existing quota/repository authority, records honest over-limit usage, makes exact replay a no-op, and blocks different baselines; production cutover remains separately gated and unauthorized.
- Ledger-driven reconciliation uses immutable repository authority, exact digest HEAD probes, conservative indeterminate outcomes, and monotonic reservation-version compare-and-set. A separate expiring shared-SQL claim plus opaque fencing token now divides workers and rejects a result after reassignment; successful mutation consumes the claim transactionally.
- Reconciliation claims lock only selected reservation rows and release the transaction before network I/O. MariaDB may return an empty batch during range-lock contention, so schedulers perform a later bounded retry rather than interpreting an empty batch as durable backlog exhaustion.
- `coffer-reconcile` runs as a separate native synchronous process rather than inside Gunicorn or an Eventlet/oslo.service loop. Each process is locally serial; independent processes scale only through the shared claim table.
- A cycle drains bounded cursor pages and preserves an unfinished cursor across periodic runs. Its lease must cover `batch_limit * probe_timeout + 10 seconds`; fencing remains the correctness fallback if actual work still exceeds the lease.
- M0 remains unauthenticated and defers generated signing material to the M2 token-contract test; this keeps the upstream data-plane spike separate from Coffer authentication behavior.
- Host-side M0 clients use `127.0.0.1` because macOS AirPlay can own IPv6 `::1:5000` even when Docker publishes the registry only on IPv4 loopback.
- Distribution v3.1.1 is a functional PoC-only pin: its current Linux ARM64 image is blocked from production promotion by the recorded Scout findings.
- Coffer's HTTP stack is synchronous WSGI: Falcon plus a portable WSGI entry point, with Gunicorn pre-fork `gthread` workers and no Eventlet, Gevent, embedded `oslo.service` WSGI server, or ASGI bridge.
- Control requests require both confirmed middleware identity and `keystone.token_auth.user.project_scoped`; raw token data and AccessInfo objects are not retained in the application context.
- The app-credential exchange uses an ID-based `keystoneauth1` plugin and a one-call session with TLS verification, a finite timeout, and no catalog. Only project/user/roles/token-expiry/audit identifiers survive the call.
- Finite application-credential lifetime is a provisioning and lifecycle-regression contract, not a privileged per-login metadata query; ADR 0008 is accepted from real Keystone evidence.
- Docker's `offline_token=true` flag is accepted for compatibility, but Coffer never returns a refresh token.
- Registry authorization requires an explicit control-database repository plus same-project scope and `oslo.policy`; create-on-push is disabled.
- Application credentials carrying Keystone access rules are rejected until Coffer can enforce an exact `oci-registry` service/method/path contract against real Keystone.
- Token keys are RSA 2048 bits or stronger, PEM files must be owner-only, and token lifetime is bounded to 60–300 seconds. Static overlapping JWKS is proven; live multi-replica rotation is not.
- `/metrics` is disabled by default and process-local. It uses only fixed route/result/method labels; production requires operator-edge protection and a tested multi-worker aggregation design.
- Gatekeeper was not bypassed for the unnotarized Multipass package. Lima 2.1.4 with Apple Virtualization and `vzNAT` is the reproducible Mac lab provider, and existing Lima instances remain untouched.
- Guest negative TLS checks must use an isolated trust context because DevStack registers its CA in Ubuntu's system trust store; `curl --cacert` alone does not exclude those system anchors.
- A deleted or nonexistent application credential returned `keystoneauth1.exceptions.NotFound` in real Keystone. That response is an authentication rejection; connection, discovery, timeout, and unexpected client failures remain dependency-unavailable results.
- The `bb00` single-host VM is the M3-A functional RGW target. Its rotational directory-backed OSD proves compatibility, TLS, persistence, and failure behavior only; it is not HA, performance, or physical-failure-domain evidence.
- Immutable OpenStack IDs are validated but not reformatted at storage or authorization boundaries; compact 32-hex and hyphenated UUID spellings are both syntactically accepted namespace forms, but the exact Keystone project ID remains the authority key.
- The integration broker's private CA and SSH loopback tunnel are disposable protocol-test scaffolding, not a production endpoint topology. Distribution receives only the public JWKS; all private keys and finite client credentials are removed after each run.
- Accepted ADR 0014 fixes five Kolla roles: private `coffer-api`, sole-ingress
  `coffer-edge`, unmodified private `coffer-registry`, listenerless
  `coffer-reconcile`, and one-shot `coffer-bootstrap`. HAProxy owns
  VIP/FQDN/TLS/load balancing; the edge owns closed path dispatch and manifest
  admission.
- Preferred Barbican-backed secrets are materialized by an owner-controlled
  pre-deploy step into per-process read-only files; runtime hot paths do not
  fetch secrets. Alembic runs only in the one-shot bootstrap, and incompatible
  production rollback restores the approved database backup rather than
  blindly downgrading.
- `bb00` is a shared KVM host, not the Kolla target. A later plan must create a
  separately named isolated VM and must keep the bootstrap image registry
  independent from the tenant Coffer registry.

## Changed Files

- Architecture and state: `docs/architecture/mvp-baseline.md`, accepted ADRs 0001–0008, accepted-for-PoC ADR `docs/adrs/0009-add-private-edge-manifest-quota-admission.md`, active execution plan 0003, the real-environment runbook, and this handoff.
- M0 environment: `.gitignore`, `poc/m0/compose.yaml`, `poc/m0/registry-config.yml`, `poc/m0/Makefile`, `poc/m0/verify.sh`, `poc/m0/run-conformance.sh`, `poc/m0/scan-security.sh`, and `poc/m0/README.md`.
- M1 implementation: `pyproject.toml`, `uv.lock`, `src/coffer/`, `tests/`, and `README.md`.
- M2 and acceptance preparation: `src/coffer/authorization.py`, token/Keystone/policy/WSGI modules, related tests, `poc/m2/`, `docs/research/m2-token-contract.md`, `docs/runbooks/real-keystone-rgw-poc.md`, ADR 0002, README, the active plan, and this handoff.
- M3 local observability: `src/coffer/observability.py`, database/config/WSGI/token instrumentation, `tests/test_observability.py`, `prometheus-client` lock updates, `docs/research/m3-local-observability.md`, README, plan, and handoff.
- Mac identity lab: `poc/devstack/Makefile`, README, host bootstrap/export/verify scripts, guest install/verify scripts, host-side Coffer authenticator and control-middleware verifiers, `src/coffer/keystone.py`, `tests/test_keystone.py`, the M1 research notes, accepted ADR 0008, the active plan, and this handoff.
- RGW VM lab: `poc/rgw/bootstrap-vm.sh`, Ceph/RGW guest and host scripts under `poc/rgw/`, its Makefile/README, the active plan, and this handoff.
- Real vertical integration: `poc/integration/`, the two-project fixture extension in `poc/devstack/guest-verify.sh`, optional token/JWKS support in `poc/rgw/guest-run-distribution.sh`, ADRs 0002/0003, the active plan, and this handoff.
- GC acceptance: `poc/rgw/guest-verify-gc-dry-run.sh`, `poc/rgw/verify-gc-dry-run.sh`, its Make target/README guidance, ADR 0003, the active plan, and this handoff.
- Real observability: `poc/integration/real_broker.py`, `poc/integration/verify.sh`, its README, `docs/research/m3-local-observability.md`, the active plan, and this handoff.
- Quota implementation: `src/coffer/quota.py`, `src/coffer/quota_admission.py`, `src/coffer/registry_proxy.py`, token-scope compatibility, focused tests, `poc/quota/`, accepted-for-PoC ADR 0009, the active plan, and this handoff.
- Process-level HA: `poc/rgw/guest-verify-distribution-ha.sh`, `poc/rgw/verify-distribution-ha.sh`, its Make target/README guidance, the active plan, and this handoff.
- KMS capability: `docs/research/m3-rgw-kms-capability.md`, the active plan, and this handoff.
- Barbican KMS execution: `poc/barbican/`, RGW KMS-aware deploy/Distribution helpers, the real-environment runbook, active plan 0003, and this handoff.
- Shared-SQL migration baseline: `alembic.ini`, `migrations/`, quota schema enforcement in `src/coffer/quota.py`, `tests/test_migrations.py`, PostgreSQL/MariaDB package extras, `poc/quota-sql/`, active plan 0004, and this handoff.
- Quota reconciliation baseline: reservation candidate/version behavior in `src/coffer/quota.py`, `src/coffer/quota_reconciliation.py`, `tests/test_quota_reconciliation.py`, `poc/quota-reconciliation/`, active plan 0004, and this handoff.
- Quota operations and documentation: `docs/runbooks/quota-schema-reconciliation.md`, ADR 0009, architecture and quota research updates, README, completed plan 0004, and the Alembic logging regression in `migrations/env.py`/`tests/test_migrations.py`.
- Multi-worker reconciliation: migration `0002`, claim metadata/store/reconciler/metrics, focused tests, shared-SQL process-failure evidence, Distribution fixture worker identity, active plan 0005, and this handoff.
- Reconciliation runner: `pyproject.toml`, `uv.lock`, reconciliation options in `src/coffer/config.py`, new `src/coffer/reconciliation_runner.py`, focused runner/subprocess tests, active plan 0006, and this handoff.
- Unified control schema: `src/coffer/schema.py`, repository/quota/runner validation, Alembic revision `0003` and unified metadata, focused migration tests, explicit fixture bootstraps, `poc/quota-sql/`, ADR 0010, schema/architecture/runbook updates, active plan 0007, and this handoff.
- Existing-content inventory: `src/coffer/inventory.py`, `tests/test_inventory.py`, installed CLI metadata, `poc/inventory/`, `docs/research/m3-existing-content-inventory.md`, proposed ADR 0011, `docs/runbooks/existing-content-inventory.md`, architecture/README/quota-runbook/ADR 0009 updates, completed plan 0008, and this handoff.
- Transactional inventory import: `src/coffer/quota_import.py`, `migrations/versions/0004_inventory_import.py`, quota/schema metadata, `tests/test_quota_import.py`, migration tests, the shared-SQL fixture, proposed ADR 0012, inventory/quota/architecture documentation, completed plan 0009, and this handoff.
- Kolla topology Stage 1: `README.md`,
  `docs/adrs/0014-fix-kolla-deployment-topology.md`,
  `docs/architecture/kolla-deployment-topology.md`,
  `docs/architecture/mvp-baseline.md`,
  `docs/exec-plans/0013-kolla-deployment-topology.md`, and this handoff.
- Kolla runtime/images Stage 2: packaged migrations, `src/coffer/runtime.py`,
  `src/coffer/api_runner.py`, `src/coffer/edge_runner.py`, the closed proxy and
  configuration changes, focused tests, `docker/`, `poc/kolla-runtime/`,
  `etc/coffer.conf.sample`, README/topology updates, completed plan 0014, and
  this handoff.
- Kolla-Ansible Stage 3 local contract: `ansible/` companion wrapper,
  playbook, role and exact pin; `poc/kolla-ansible-role/` lifecycle harness;
  `src/coffer/config_validator.py`, its installed entry point and focused
  tests; active plan 0015; and this handoff.

## Verification

- Parsed `.codex/config.toml` with Python `tomllib`: passed.
- Parsed `.codex/hooks.json` with Python `json`: passed.
- Compiled `.codex/hooks/pre_compact_snapshot.py`: passed.
- Ran the hook with a representative `PreCompact` payload: passed and wrote the expected snapshot.
- Confirmed `.codex/state/precompact-snapshot.md` is ignored by Git.
- Rendered both Mermaid blocks in `docs/architecture/mvp-baseline.md` with local Chrome after the rename: passed; both outputs were visually readable and used Coffer labels.
- Checked all 47 unique external Markdown URLs with redirected parallel HTTP requests: passed with HTTP 200 after one transient OpenDev 500 passed three immediate retries.
- Checked balanced Markdown fences, local link targets, and trailing whitespace across 18 files: passed.
- Parsed the documented PoC Bash block with `bash -n`: passed.
- Ran `gitleaks dir . --redact --no-banner --exit-code 1`: passed with no leaks.
- Verified `git rev-parse --show-toplevel` resolves to `/Users/byeonjaehan/projects/personal/coffer` from both the canonical directory and the temporary compatibility link.
- `codex features list` in the already-running environment still reports `memories=false`; trust the project and start a new task before validating the project-level feature override.
- Parsed the M0 Bash scripts with `bash -n` and the Compose model with `docker compose config --quiet`: passed.
- Ran `make verify`: passed with subject digest `sha256:8050eefb54ecfbc909bb9937862ed100e9d361e3181a46b4d79a124f8d279d34`; the digest remained pullable after restart and the bucket contained 23 registry objects.
- ORAS v1.3.3 artifact attach/discover passed through the fallback tag scheme; the native Referrers endpoint returned 404.
- Ran the full OCI v1.1.1 profile: 68 passed, 7 failed, 4 skipped. Five failures are native Referrers, one is optional automatic cross-mount, and one is the malformed-reference core failure.
- Ran the supported-capability profile: 59 passed, 1 failed, 19 skipped. The remaining malformed-reference request returns 500 rather than 400/404.
- Visually inspected both generated HTML reports in the in-app browser: summary counts and failure cards rendered correctly without layout clipping at the default 1280x720 viewport.
- Docker Scout reported 8 Critical and 9 High findings on the exact Linux ARM64 image; `govulncheck` v1.6.0 with Go 1.25.9 found eight symbol-reachable vulnerabilities.
- Ran the six-check Falcon/Keystone/Oslo compatibility spike on Python 3.11.14, 3.12.2, and 3.13.14: all passed.
- Ran the durable repository API suite on Python 3.11, 3.12, and 3.13: 9 passed on each version. Python 3.11/3.12 emitted only WebOb's expected `cgi` deprecation warning.
- Ran Gunicorn `--check-config` for `coffer.wsgi:create_application()` with two `gthread` workers and four threads: passed; an expected warning remains until a real Keystone public URI is configured.
- Ran the hardened complete local suite on Python 3.13: 63 passed. Coverage includes access-rule fail-closed behavior, secret-free exception graphs, explicit repository/`oslo.policy` grants, request IDs/audit IDs, key/lifetime/file-mode bounds, and middleware-path separation.
- Ran `make -C poc/m2 verify`: passed. Unmodified Docker and Distribution proved challenge/login, member push/pull, reader reduction, denied delete/missing/cross-project access, direct post-restart blob SHA-256, positive same-project mount, equal denial/non-disclosure for existing and nonexistent cross-project mount sources, six negative JWT classes, and two accepted JWKS `kid` values.
- Confirmed M2 cleanup: no running Compose services or named volume; private keys, fixture secrets, bearer cases, SQLite database, downloaded blob, and temporary Docker credential config are absent. Retained logs were scanned for all fixture secrets and JWT-shaped values.
- Parsed the M2 Bash and Python sources and both M0/M2 Compose models: passed. The final M2 cross-version Python 3.11/3.12 rerun remains to be performed after observability changes.
- Ran the final complete suite on Python 3.11.14, 3.12.2, and 3.13.14: 69 passed on each version. Python 3.11/3.12 emitted only WebOb's expected `cgi` deprecation warning.
- Reran `make -C poc/m2 verify` after M3 instrumentation: passed, with complete cleanup confirmed.
- Ran Gunicorn configuration, Python compilation, Bash syntax, both Compose model, and lock checks: passed; only the expected missing real Keystone public URI warning remains in the default smoke configuration.
- Checked 30 Markdown files, 12 local links, 18 Bash/sh blocks, and 81 external Markdown link targets: passed.
- Ran scoped Gitleaks and private-key/JWT-shaped value scans over project-owned files: passed.
- Parsed every `poc/devstack` Bash script with `bash -n` and ShellCheck, compiled its Python verifier, and dry-ran all Make targets: passed.
- Bootstrapped Lima 2.1.4 instance `coffer-devstack`: Ubuntu 24.04 ARM64, four CPUs, 8 GiB RAM, 50 GiB disk, VZ/vzNAT, DevStack `stable/2026.1` commit `da2f4d73f5ad74fc8ecfbe15bd7e20f6b0982dbb`.
- `make -C poc/devstack verify`: passed against `https://192.168.64.6/identity/v3`; strict CA accepted the exported chain and rejected an unrelated CA; Coffer authenticated reader/member/admin/service effective roles; service had no registry role; domain/system-only identity could not gain project scope or create an application credential; Keystone rejected credentials after expiration, role removal, owner disablement, and deletion; the real control middleware enforced project and incoming service-token scope; revoked-token cache exposure ended after two seconds; and a bounded Keystone outage returned 503.
- Confirmed Apache and MySQL are active, the host HTTPS probe succeeds without `-k`, the test user has zero residual application credentials, retained `work/devstack` evidence contains no secret-shaped field, and generated CA/binding files are owner-only.
- Added the real deleted-credential regression and ran the full suite sequentially: 70 passed on Python 3.11.14, 3.12.2, and 3.13.14. Python 3.11/3.12 emit only WebOb's known `cgi` deprecation warning.
- Reran Bash syntax, DevStack-scoped ShellCheck, both Compose models, and `uv lock --check`: passed. Project-owned Gitleaks scans found no leaks; the whole-tree scan's 55 redacted findings were confined to ignored upstream/M2 files under `work/`.
- `poc/rgw/bootstrap-vm.sh` passed Bash syntax and ShellCheck; its Make targets dry-ran successfully.
- `coffer-rgw-poc` passed cloud-init, x86_64/KVM, 8-vCPU, 24-GiB, root-resize, empty 200-GiB OSD device, qemu-guest-agent, reserved DHCP, ProxyJump SSH, autostart-disabled, and normal-reboot persistence checks. After boot, `bb00` reported about 61 GiB available RAM and 896 GiB free in the pool filesystem.
- The Ceph installer passed Bash syntax and ShellCheck, verified the pinned artifact and image digest, recovered safely from a Tentacle device-list schema mismatch, and exited successfully on retry. Ceph reports monitor quorum, two running managers, and one 20.2.2 OSD that is `up` and `in`; the disposable cluster config records pool size and minimum size one.
- The RGW deploy target passed idempotently. `rgw.coffer` runs on port 8443; CA-verified HTTPS returned 200; the certificate contains the expected DNS and IP SANs; untrusted TLS and plaintext failed; all five size-one pools and 129 PGs are active and clean. The stale bootstrap warnings are gone, leaving only the expected `POOL_NO_REDUNDANCY` warning.
- S3 provisioning passed: the registry identity owns only `coffer-registry-poc`, the denial identity owns only `coffer-denial-poc`, a private sentinel round trip succeeded, and anonymous/cross-owner/extra-bucket operations returned 403/403/400. Secret-bearing guest and ignored host files are mode 0600.
- Distribution/RGW persistence passed with eight bucket objects, direct non-redirected blob digest verification, secret-free logs, private TLS on both hops, and Mac-side tunnel validation. Lab PG tuning removed `TOO_MANY_PGS`; only `POOL_NO_REDUNDANCY` remains by design.
- `make -C poc/integration verify` passed from a clean state: real finite Keystone credentials completed the standard TLS Bearer challenge through unmodified Skopeo and Podman; project A received 200 and project B received 401 for project A; the Skopeo digest survived Distribution and Coffer restarts; request IDs matched project/audit/grant decisions; retained logs contained no credential secret or JWT; cleanup removed credentials/private runtime state, stopped DevStack, and restored the unauthenticated registry fixture.
- The same final integration harness passed a second clean run. A structured comparison proved stable repository/digest/restart/authorization results and different request IDs; second-run cleanup left DevStack stopped, no host private runtime file, no guest integration directory, and the restored registry returning HTTP 200.
- The RGW GC dry-run wrapper passed after its cleanup correction: writes were stopped, objects stayed 19, candidate counts were zero, baseline/integration/Podman digests survived restart, retained logs were secret-free, and remote public evidence was removed.
- The observability-enabled real integration rerun passed: health/readiness and bounded metrics were captured before and after broker restart, first/second process decision counts were 18/4 with aggregate decision time 0.2166/0.0481 seconds, expected denial/probe failures were classified, and no forbidden identifier or secret appeared in metrics.
- The two-replica Distribution harness passed: the first 1 MiB and second 1 MiB of one blob crossed different processes around a primary stop, finalize returned 201, both endpoints returned the blob and selected manifest, logs were secret-free, and the temporary replica was removed.
- Final consistency checks passed: `uv lock --check`, 70 tests, Python compilation, Bash syntax, full PoC ShellCheck, both Compose models, all Make target dry runs, 36 Markdown files and 13 local links, three rendered and visually inspected Mermaid diagrams, scoped Gitleaks/private-key/JWT scans, and trailing-whitespace checks.
- Final lab-safety checks passed: DevStack is stopped; only the baseline Distribution container runs; its CA-verified `/v2/` returns 200; guest integration and temporary evidence state is absent; Ceph reports only the expected one-OSD no-replica warning; no KMS option is configured; private integration credentials, keys, and SQLite state are absent.
- The hardened Barbican rerun passed: eight novel Distribution objects and the direct S3 proof used the selected key; wrong-key and fresh-process combined identity/KMS outage writes failed closed; the zero-byte encrypted-move limitation failed closed; recovery passed; 17 isolated objects were removed; selected-key residue and incomplete multipart uploads are zero.
- The final KMS safe-state check passed: all nine Ceph KMS options and Distribution KMS settings are absent, the CA-verified non-KMS `/v2/` endpoint returns 200, the pre-KMS digest remains readable, DevStack and its tunnel are stopped, and exact temporary OCI layouts are absent.
- Final repository regression passed: 91 tests on each of Python 3.11.14, 3.12.2, and 3.13.14; `uv lock --check`; Python compilation; all PoC Bash/ShellCheck; Gunicorn config; three Compose models; every Make target dry run; 39 Markdown files and 16 local links; 99 external links; three rendered and visually inspected Mermaid diagrams; trailing-whitespace, Gitleaks, private-key/JWT, and diff checks.
- Final host/lab residue passed: Podman machine and DevStack are stopped, Docker is not running, no quota resource or secret remains, RGW has zero Ceph/Distribution KMS settings and temporary layouts, the baseline Distribution alone returns CA-verified 200, and Ceph reports only `POOL_NO_REDUNDANCY`.
- `make -C poc/quota-sql verify` passed on PostgreSQL 17.10 and MariaDB 11.4.12: each used two distinct backend connections, admitted exactly one of two concurrent reservations, denied the other, preserved retry/release idempotency, finished at zero used/reserved bytes, passed migration drift and downgrade/re-upgrade checks, and removed every labeled runtime resource and generated password.
- Reconciliation focused verification passed: 24 migration/quota/reconciliation tests cover deterministic stale pages, CAS, lost/duplicate/reordered results, exact 200/404, 401/403/5xx/transport ambiguity, and shared-descriptor refunds. The isolated pinned Distribution fixture committed the present digest, released unpublished/deleted digests, retained shared bytes to the last reference, ended at zero usage, and removed every runtime resource and SQLite state file.
- Plan 0004 final regression passed: 108 tests on each of Python 3.11, 3.12, and 3.13; lock and compilation; Alembic head; all PoC Bash/ShellCheck; Gunicorn; five Compose models; every PoC Make target dry run; 45 Markdown files and 18 local links; three rendered and visually inspected Mermaid diagrams; diff, project-owned Gitleaks, private-key, and JWT-shaped scans.
- The final PostgreSQL/MariaDB and Distribution reruns passed after documentation and logging corrections. Labeled containers, volumes, networks, generated database passwords, and reconciliation SQLite state all ended at zero.
- The disposable Podman machine used for the final database and Distribution reruns is stopped.
- Plan 0005 focused verification passed: 36 migration/quota/reconciliation/observability tests; PostgreSQL 17.10 and MariaDB 11.4.12 migration drift/downgrade/re-upgrade; disjoint claim batches; process exit 17; expiry/reclaim; stale-token fencing; zero usage and runtime/credential residue. Podman is stopped.
- Plan 0005 final regression passed: 114 tests on each of Python 3.11, 3.12, and 3.13; lock, compile, Alembic head, Bash/ShellCheck, Gunicorn, five Compose models, all PoC Make dry-runs, 42 Markdown files and 19 local links, diff checks, and Gitleaks over 180 project-owned files. The final Distribution rerun passed and removed all runtime/state residue.
- Plan 0006 focused verification passed: 14 runner tests and 67 combined runner/token/reconciliation tests cover strict config/schema startup, independent oslo.config instances, secret-free parser/config exit 78, installed one-shot exact-404 reconciliation, fixed aggregate summary, temporary-failure exits, cursor and scan-snapshot continuation, serial execution, bounded jitter/backoff reset, monotonic wait, active-page signal stop, and handler restoration.
- Plan 0006 final verification command corrections are recorded in the plan: a wrong Gunicorn module, zsh list-expansion mistakes, and use of zsh's special `path` variable were corrected without changing repository or lab state. The substantive missing-config traceback/exit-1 failure was fixed and regression tested.
- Plan 0007 focused verification passed: 10 SQLite migration tests, 56 migration/API/token/quota tests, and the full 134-test Python 3.13 suite. PostgreSQL 17.10 and MariaDB 11.4.12 adopted, retained, and re-adopted exact legacy repository metadata while existing quota/claim checks and zero-residue cleanup passed.
- Plan 0007 final verification passed after tightening MySQL Boolean reflection: 10 SQLite migration tests reject four drift classes; 134 tests pass per Python version; both shared-SQL engines and isolated Distribution reconciliation pass again; Podman and all labeled runtime/credential/state residue are absent.
- Plan 0008 focused verification passed: 17 inventory tests cover bounded pages and summaries, start/end drift including tag state, empty-repository/exact authority, unsupported/digest/size/aggregate-bound failures, descriptor conflicts, nested-index children, unknown-field secret exclusion, deterministic output, and atomic exclusive mode-0600 output creation.
- `make -C poc/inventory verify` passed against pinned unmodified Distribution v3.1.1: API tags=1, storage manifests=2 including one digest-only untagged index, snapshot scans equal, four descriptors, registry/control hashes unchanged, both digests readable after restart, zero labeled/runtime/state residue, and Podman stopped.
- Plan 0009 import verification passed on SQLite, PostgreSQL 17.10, and MariaDB 11.4.12: forced second-row failure leaves no marker or ledger state; concurrent exact import converges to one writer and one no-op; a different baseline fails; exact graph counts are 2 reservations, 5 edges, 2 manifests, and 4 descriptors; used/reserved bytes are 220/0 at limit 10; all disposable resources and credentials are removed.
- Plan 0009 final regression passed with 174 tests per Python 3.11/3.12/3.13, only expected WebOb warnings on 3.11/3.12, Alembic head `0004_inventory_import`, three installed CLI helps, lock/compile, Go format/test/vet, 58 Bash/ShellCheck files, six Docker Compose models, 54 Make dry-runs, 54 Markdown files, 32 local links, 99 external links, and diff checks.
- The first Python 3.11/3.12 commands lacked installed console scripts in disposable ignored environments; editable installation of the current checkout and explicit venv `PATH` corrected the command and all 174 tests passed. The final live fixture retry initially appeared blocked because the local Podman 5.6.0/libkrun machine exited after startup. Plan 0010 proved this was the noninteractive command lifecycle terminating the VM child, not VM corruption; a persistent PTY required no recreation or data reset.
- Plan 0010 focused verification passes 38 import/comparison tests covering exact state, marker false positives, all ledger classes including timestamp drift, extra claims/rows, allowed empty authority, absence of DML, one snapshot across a concurrent commit, fixed secret-safe CLI output, and environment-only database configuration. The concurrency test exposed sqlite3's deferred `BEGIN`; the comparator now explicitly fixes the SQLite read-only snapshot before its first SELECT.
- Plan 0010 shared-SQL verification passed on PostgreSQL 17.10 and MariaDB 11.4.12: each accepted exact imported state, rejected a released-manifest mutation, accepted the restored ledger, retained all prior import/concurrency/reconciliation/adoption checks, and ended with zero runtime and credential residue. The Podman machine is stopped.
- Plan 0010 final regression passed with 189 tests on each Python 3.11.14, 3.12.2, and 3.13.14; lock, compile, Alembic head, four installed CLIs, Go, 58 Bash/ShellCheck files, six Compose models, 54 Make dry-runs, 54 Markdown files, 33 local links, 99 external links, private-key/JWT scans, and diff checks all pass. The final shared-SQL rerun ended with zero residue and Podman `Running:false`.
- Published plan 0010 as commit `d0580cc` to `jaehanbyun/coffer` `main`; local and remote heads match and the worktree was clean before plan 0011 activation.
- Activated plan 0011 to resolve exact repository routes with the verified ledger in one read-only SQL snapshot and then require injected authentication for conservative live digest HEAD probes. The package explicitly defers the privileged production cross-project identity decision and does not authorize credentials, live data, or admission changes.
- Plan 0011 focused verification passes 48 import/SQL/live tests: same-snapshot canonical route resolution issues no DML and retains the pre-rename route across a concurrent commit; injected authentication prepares before probes; all manifests are visited; exact present, absent, indeterminate, exception, malformed-provider, protected Bearer HTTP, and wrong-token behavior is aggregate-only, fail-closed, and secret-safe.
- Added proposed ADR 0013. It forbids anonymous fallback and command-line/environment credential contracts, requires per-repository injected authentication, and defers the production choice among per-project exchange, a reviewed maintenance principal, or an authenticated read-only proxy. No identity or credential was created.
- Plan 0011 shared-SQL verification passed on PostgreSQL 17.10 and MariaDB 11.4.12 with the extended same-snapshot route query and all existing import/migration/concurrency checks. Cleanup ended with zero containers, volumes, networks, and generated credentials; Podman is stopped.
- Plan 0011 final regression passed with 199 tests on each of Python 3.11.14, 3.12.2, and 3.13.14; lock, compile, Alembic head, four installed CLIs, Go, 58 Bash/ShellCheck files, six Compose models, 54 Make dry-runs, 56 Markdown files, 32 local links, 99 external links, private-key/JWT scans, project-owned Gitleaks, and diff checks all pass.
- Published plan 0011 as commit `b45fa32` to `jaehanbyun/coffer` `main`; local and remote heads match and the worktree was clean before plan 0012 activation.
- Activated plan 0012 to measure deterministic synthetic parse/import/exact-SQL/live-comparison scaling. The package explicitly excludes production workload claims, identities, credentials, endpoints, concurrency policy, tuning, and admission changes.
- Plan 0012's non-installed harness and two focused tests generate deterministic unique-descriptor artifacts, matching disposable authority, aggregate-only phase metrics, exact SQL statement/probe counts, and zero temporary-state residue. The fixed Make target runs 100, 1,000, and 5,000 manifest profiles.
- The first local Python 3.13 scale run completed all profiles. At 5,000 manifests the artifact was 4.71 MB, import took 3.642 seconds/15,032 statements, exact comparison took 2.085 seconds/11 statements/24.87 MB peak traced Python allocation, and the live core repeated 11 SQL statements plus exactly 5,000 zero-latency in-process probes in 1.968 seconds. Growth was approximately linear in this bounded SQLite topology; it is not a production capacity result.
- Plan 0012 final regression passed with 201 tests on each of Python 3.11.14, 3.12.2, and 3.13.14; lock, compile, Alembic head, four installed CLIs, Go, 58 Bash/ShellCheck files, six Compose models, 55 Make dry-runs, 58 Markdown files, 33 local links, 99 external links, private-key/JWT scans, project-owned Gitleaks over 222 files, and diff checks all pass.
- Activated plan 0013 and completed a secret-safe read-only inventory through
  the user-supplied direct Tailscale SSH address. It reaches `bb00`; the legacy
  alias points to an unavailable LAN address. `bb00` is a shared Ubuntu 24.04
  x86_64 KVM host with substantial free capacity but no Kolla/Ansible install,
  active host HAProxy on ports 80/443, a separate Harbor 2.14 deployment,
  17 running VM domains, and the existing autostart-disabled
  `coffer-rgw-poc`. No remote state or secret-bearing content was read or
  changed, and direct host deployment is excluded.
- Accepted ADR 0014 and completed plan 0013. The deployable contract is
  `coffer-api` on private service port 8787, sole-ingress `coffer-edge` on
  8788, unmodified private Distribution as `coffer-registry` on 8789,
  listenerless `coffer-reconcile`, and one-shot `coffer-bootstrap`.
- Fixed the Kolla endpoint, TLS, HAProxy, secret-recipient, Barbican
  materialization, Alembic/rollback, isolated-lab, and independent bootstrap
  registry boundaries in `docs/architecture/kolla-deployment-topology.md`.
  Stage 1 changed documentation only; no image, role, VM, identity, credential,
  or deployment was created.
- Plan 0013 final documentation verification passed: 61 Markdown files and 40
  local links, four rendered and visually inspected Mermaid diagrams, four
  Kolla primary URLs with HTTP 200, changed-file Gitleaks and
  private-key/JWT/access-key/SSH-target scans, `git diff --check`, and manual
  scoped diff review.
- Plan 0013 corrected three non-destructive local failures: one combined patch
  was rejected atomically on a line-wrap mismatch, an `rg` expression needed
  `--` before a leading-hyphen pattern, and one Mermaid label needed
  punctuation simplified. The corrected checks passed and the supplied SSH
  user/address is not retained in project documentation.
- Plan 0014 fixed the image strategy against pinned Kolla `stable/2026.1`
  source: final artifacts are `openstack-base` Jinja templates with
  service-level `USER`, while a pinned-script contract image supplies honest
  local evidence because no public 2026.1 base reference was available.
  Distribution remains unmodified and will use its official release binary
  with an architecture-specific checksum rather than the blocked runtime
  image.
- Plan 0014 installed the complete Alembic environment in the Python wheel and
  added repeat-safe `coffer-bootstrap` plus `coffer-api` on private port 8787.
  Thirty-three focused tests, wheel-content inspection, Alembic head, installed
  help, compile, lock, and diff checks pass.
- Plan 0014 added `coffer-edge` on 8788 with separate verified API/Distribution
  origins, exact non-bypassable manifest admission, closed operational/unknown
  paths, deterministic 503 transport closure, and bounded streaming. Fifty-six
  focused tests pass, including CA trust, hostname mismatch, untrusted TLS,
  both routed backends, JWKS/schema startup, CLI help, compile, and diff checks.
- Plan 0014 added Kolla Jinja artifacts, read-only per-role configuration
  examples, and a pinned-script local contract harness. Kolla
  `stable/2026.1` lists and renders both images; the ARM64 local application
  and Distribution builds, installed command helps, exact Distribution v3.1.1
  checksum, and version check pass.
- The first Stage 2 live run stopped only at Docker Scout's rejection of an
  absolute archive reference after it indexed the image. Exact cleanup and
  Podman shutdown passed; the harness now uses the documented repository-local
  archive reference for the bounded rerun.
- The corrected scanner run reached the live edge and exposed a strict
  certificate failure: the Python 3.13 image's OpenSSL requires Authority Key
  Identifier, which the disposable leaf certificates lacked. The generator
  now emits matching CA/leaf SKI and AKI extensions; all failed runs removed
  exact runtime resources and stopped Podman.
- The next strict-TLS run passed service health, API readiness, the edge
  challenge, non-root UID, copied configuration owner/mode, read-only source
  configuration, custom CA installation, private Distribution exposure, and
  empty reconciliation. Its authenticated blob finalize correctly failed
  because Distribution received zero bytes. Direct curl `--data-binary`
  reproduced the failure and disproved the initial curl-config hypothesis.
  A one-run bounded diagnostic proved curl uploaded 37 bytes and edge
  forwarded declared/actual totals of 37/37. The actual defect was the
  client's default `application/x-www-form-urlencoded` media type:
  Distribution's Go form/query handling consumed the body before blob
  finalization. The harness now sets `application/octet-stream`; temporary
  proxy/debug instrumentation was removed. It still verifies source digest and
  curl byte count, ignores ambient curlrc, and keeps bearer material only in a
  mode-0600 config file. Named secret-safe assertions, Bash parsing,
  ShellCheck, cleanup, and Podman shutdown pass.
- The corrected default Stage 2 run passed end to end. Both ARM64 contract
  images rebuilt; all five process-role contracts ran non-root; Kolla
  owner/mode, read-only source configuration, custom CA, private Distribution,
  API readiness, edge challenge, authenticated blob/manifest, all-service
  restart with digest preservation, repeat-safe bootstrap, reconciliation,
  log hygiene, exact cleanup, and Podman shutdown passed. The failure summary
  is absent.
- Saved SBOM evidence records 261 Coffer packages and 293 Distribution-wrapper
  packages. The current bounded scan reports Coffer at 1 Critical/4 High and
  the wrapper at 9 Critical/12 High, so functional completion does not clear
  the production image gate.
- Plan 0014 final verification passed with 222 tests on each of Python
  3.11.14, 3.12.13, and 3.13.14; lock, compilation, Alembic head, seven
  installed CLIs, wheel assets, Go 1.25.3 format/test/vet, 58 Bash/ShellCheck
  files, six Compose models, every PoC Make target dry-run, pinned Kolla list
  and render, ten config JSON renders, 65 Markdown files, 42 local links,
  Gitleaks over 252 project-owned files, explicit key/JWT patterns, cleanup,
  and diff checks passed.
- The final matrix corrected four local command problems without weakening
  acceptance: shared-venv collisions from parallel `uv`, wrong Go module and
  old host toolchain selection, missing Docker/source context in isolated
  Kolla invocation, and a Gitleaks false positive on a literal API container
  name. All authoritative checks were rerun with corrected commands. A
  separate byte-identity helper for moved migrations also lacked `set -e`;
  its output was rejected, and actual diffs confirmed only docstrings/future
  annotations while the full migration tests and wheel inspection passed.
- Plan 0015 pins the official Kolla-Ansible `stable/2026.1` source at commit
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc` in the ignored disposable
  checkout `work/kolla-ansible-stage3`. Current custom-playbook CLI,
  representative service, database/Keystone/bootstrap, HAProxy, logging,
  Prometheus, handlers, and precheck/container/pull/stop contracts were
  inspected without changing upstream source.
- The Stage 3 integration strategy is a Coffer-owned wrapper, custom playbook,
  and companion role. The wrapper discovers the installed Kolla data path
  and exposes its pinned roles/modules/action plugins/filters; the normal
  Kolla lifecycle action is passed through the custom playbook. Coffer reuses
  the generic Kolla contracts rather than copying or reimplementing them.
- A fresh read-only capacity check found 64 logical CPUs, about 251.5 GiB
  total RAM with about 125.6 GiB available, about 896 GiB free in the
  XFS-backed Coffer pool, and 18 running domains with 82 allocated vCPUs and
  244 GiB maximum guest memory. `coffer-rgw-poc` remains running,
  autostart-disabled, with eight vCPUs and 24 GiB RAM. No VM or host state was
  changed. One command containing an accidental autostart-changing clause
  was rejected before execution; the corrected read-only query confirmed the
  existing setting is unchanged.
- The Stage 3 companion role now implements the accepted five-process model,
  owner-only secret inputs, database plus repeat-safe bootstrap ordering,
  proposed `oci-registry` catalog registration, verified-TLS HAProxy with
  edge-only external routing, observability extension inputs, configuration
  validation, handlers, and every required lifecycle action.
- `make -C poc/kolla-ansible-role verify` passed 48 isolated checks: seven
  lifecycle syntax checks, disabled no-op, six fail-closed prechecks,
  bootstrap-failure rollout blocking, database/bootstrap/process ordering,
  Keystone service/endpoints, HAProxy TLS/routing, secret recipients,
  config validation, idempotent reconfigure/pull/stop, and exact generated
  state cleanup. Production-profile Ansible lint, Jinja/YAML parsing, Python
  compilation, and 19 focused product tests also pass.
- Executable contract testing corrected a JWKS field/method collision,
  macOS-only network-fact incompatibility in the harness, standalone
  Fluentd/logrotate defaults and raw-template handling, and the stop variable
  normally injected by the Kolla CLI. One sandboxed readiness wait was
  interrupted cleanly and rerun with bounded loopback access; no VM, host,
  identity, credential, publication, commit, or push was performed.
- The isolated Linux contract passed on a separately named
  `coffer-kolla-stage3` Ubuntu 24.04 x86_64 VM with eight vCPUs, 24 GiB RAM,
  120 GiB root overlay, a static default-NAT address, and autostart disabled.
  Upstream Kolla Linux address filtering plus precheck/deploy/reconfigure/
  pull/upgrade/stop passed; bootstrap preceded process start, materialized
  sensitive configs were mode 0600, and remote root/user temporary state was
  removed.
- The validation VM was destroyed and undefined after evidence collection,
  and its exact seed/root/base volumes plus temporary known-host files were
  deleted. The final audit found no Stage 3 domain or volume residue, retained
  18 original domains, kept `coffer-rgw-poc` running with autostart disabled,
  and found about 125 GiB available RAM and 878 GiB free in `/srv/nfs`.
- Bounded failures were cleanup-safe: an unsupported cross-pool backing path
  failed before domain creation; public-key selection required one exact VM
  recreation using only the jump account's already allowed public keys; and
  the remote contract corrected Linux temp ownership plus base-role directory
  prerequisites before passing. No existing VM, DHCP entry, host service,
  identity, credential, published artifact, commit, or push changed.
- Plan 0015 final regression passed with 232 tests on each Python 3.11.14,
  3.12.2, and 3.13.14; offline lock, compile, Alembic head, eight CLI helps,
  Go format/test/vet, six Compose models, 58 Make dry-runs, production-profile
  Ansible lint, Jinja and 25 YAML parses, 61 Bash/ShellCheck files, the
  48-check local role contract, and the isolated Linux lifecycle all pass.
- Final documentation and security checks passed over 65 Markdown files,
  44 local links, and 299 existing project-owned Gitleaks inputs. Explicit
  private-key, JWT-shaped, supplied SSH-target, Stage 3 residue, and diff
  checks pass. The wrapper now has an exact action-order contract and refuses
  destructive or unrelated Kolla actions.
- Stage 3 changed `ansible/`, `poc/kolla-ansible-role/`,
  `src/coffer/config_validator.py`, `tests/test_config_validator.py`,
  `pyproject.toml`, README, architecture, plan 0015, and this handoff. The
  inherited uncommitted Stage 1/2 work remains preserved; no commit or push
  was requested or performed.
- Stage 4 deployed the pinned Kolla 2026.1 AIO and Coffer companion role,
  proved the proposed catalog contract, two-project Docker isolation,
  edge-only ingress, restart persistence, repeat-safe schema and reconfigure
  behavior, and removed every exact disposable identity, bucket, container,
  domain, volume, temporary file, and known-host entry. It added the
  `poc/kolla-aio/` harness, completed plan 0016, strengthened the runtime role
  contracts, and passed the final regression/security/documentation matrix.
- Added `poc/load-soak/collector/rgw_live_adapter.py`. Its owner-only contract
  requires an explicit verified-HTTPS endpoint and CA hash, v4/path-style S3,
  finite timeouts, exact target/window/config bindings, and credentials plus
  the Barbican key ID only through fixed runtime environment variables.
- The healthy path is dependency-safe zero/positive put, head/get,
  zero/positive copy, and multipart listing. Only the `during` phase may add
  externally evidenced wrong-key and KMS-outage puts. Unexpected success,
  KMS errors, or other storage failures are retained as nonzero evidence.
- Bounded explicit multipart pagination, fixed safe error classes, canonical
  step/probe/capture schemas, dynamic boto3 loading, and owner-only atomic
  outputs pass 32 focused tests. The related load/observability matrix passes
  719 tests and the full Python regression passes 1264. This is fake-client
  local evidence: no credential, boto3 runtime, endpoint, RGW, KMS, Barbican,
  container, VM, or remote state was used.
- Added the qualified disposable-pilot schedule renderer. It binds canonical
  released readiness to the exact load-plan versions, revisions, and evidence
  hash; emits three live RGW configs and 53 ordered actions atomically; and
  refuses any state below `candidate-qualified`.
- The exact `during` sequence now proves wrong-key failure, key recovery,
  KMS-outage failure, and KMS recovery. Every phase performs complete
  multipart capture, exact-prefix cleanup with zero object/upload residue,
  collector-input rendering, and atomic phase preparation. Sixteen schedule
  plus 32 adapter tests pass locally. The expanded load/observability matrix
  passes 735 tests and the full Python regression passes 1280.
- A fresh official metadata read still classifies signed Distribution v3.1.1
  and Ceph Tentacle v20.2.2 as `blocked`. The renderer created no runtime
  directory and used no credential, endpoint, S3, KMS, Barbican, OpenStack,
  container, VM, or remote state.
- Added the fixture-only checkpoint executor for all 53 scheduled actions. It
  independently revalidates readiness, schedule/result/config hashes, exact
  actions and paths, and cleanup contracts before creating the exact
  owner-only runtime state.
- Pending is persisted before each adapter call. Exact failure-before-apply
  resumes at that action; apply-before-response is reconciled without a
  duplicate; complete reruns execute nothing. A stable nonblocking lock,
  source-bound state, and fixed tamper failures pass 17 executor and 65
  combined executor/schedule/adapter tests. The load/observability matrix
  passes 752 tests and the full Python regression passes 1297.
  Non-synthetic adapters are explicitly refused and no external state was
  used.
- Added the exact-prefix RGW cleanup adapter. It completely scans current
  objects, versions, delete markers, and multipart uploads; rejects pagination
  or prefix drift; aborts/deletes exact identities in bounded batches; and
  emits only after a complete re-scan proves all four counts are zero.
- The initial 22 cleanup and 87 combined cleanup/executor/schedule/adapter
  tests passed. The corresponding load/observability matrix passed 774 tests
  and the full Python regression passed 1319. Retained output contains only
  counts and provenance hashes. No boto3 dependency, credential, endpoint,
  S3, KMS, Barbican, container, VM, or remote state was used.
- Added the non-synthetic RGW schedule-action adapter for phase open, every
  indexed probe step, probe compilation, multipart capture, exact-prefix
  cleanup, and separate zero-residue verification. Owner-only outputs are
  never overwritten; reconciliation revalidates them without repeating a
  storage call.
- Cleanup results now have an independent retained-result validator. Fifteen
  action, 29 cleanup, and 109 combined focused tests pass with injected fake
  clients. The load/observability matrix passes 796 tests and the full Python
  regression passes 1341. The default future path is verified-HTTPS boto3,
  but no dependency, credential environment, endpoint, S3, KMS, Barbican,
  container, VM, or remote state was used.
- Fault apply/recover, collector-input rendering, atomic phase preparation,
  and phase completion are still explicitly unsupported. No execution CLI or
  full non-synthetic pilot adapter exists yet.
- Added the external wrong-key/KMS-outage controller seam. Apply/recover
  observations must bind exact fault/state/evidence/times; recovery revalidates
  the retained apply evidence. Read-only controller observation resolves
  apply-before-output interruptions without repeating an external mutation.
- Twenty fault-action and 129 combined focused tests pass with a fake
  controller. The load/observability matrix passes 816 tests and the full
  Python regression passes 1361. No Kolla, service restart, credential,
  endpoint, S3, KMS, Barbican, container, VM, or remote state changed. A real
  fault-controller implementation and full adapter composition do not exist
  yet.

## Blockers and Risks

- Project hooks must be reviewed and trusted in Codex before they run.
- Local memories are experimental and must never replace checked-in project state.
- Completed Stage 4 now constitutes a functional single-node Kolla AIO tenant
  OCI acceptance test. It does not constitute a multinode/HA or production
  deployment and does not qualify the test-only or vulnerability-blocked
  images for promotion.
- `bb00` is a shared virtualization host with occupied host 80/443 and unrelated
  HAProxy/Harbor/VM workloads. Direct installation and implicit reuse are
  excluded; later Kolla work requires a separately named isolated VM and
  explicit address/storage allocation.
- Coffer's product scope and architecture baseline are accepted for the PoC; empirical PoC failures may amend them through new ADR evidence.
- The real identity, storage, integrated token path, repeated clean run, GC dry-run, same-VM Distribution shared state, Barbican SSE-KMS, bounded quota admission, shared-SQL schema, exact-digest reconciliation, and database-backed multi-worker claims are complete. Production promotion still requires existing-data rollout/backups, authenticated TLS reconciliation in the integrated RGW topology, production scheduling/metric aggregation, and separate-host/load-balancer HA.
- `POOL_NO_REDUNDANCY` is intentionally retained as an honest warning for the one-OSD functional lab. No durability, HA, performance, or physical-failure-domain conclusion may be drawn from it.
- Native OCI 1.1 Referrers remain an empirical gate. SSE-KMS and logical-versus-physical quota behavior now have bounded PoC evidence; destructive reclamation remains a separately approved maintenance test.
- Ceph Tentacle 20.2.2 cannot finalize an encrypted zero-byte Distribution blob through ordinary `CopyObject`. The positive-size multipart-copy workaround is verified, but production SSE-KMS promotion requires a released Ceph fix/backport or a separately proven release/backend that closes the zero-byte path.
- The pinned Distribution v3.1.1 Linux ARM64 image has 8 Critical and 9 High Docker Scout findings. Production use is blocked pending an upstream-patched supported image or complete reachability/VEX resolution.
- Distribution v3.1.1 has one core supported-profile conformance failure: a malformed digest-like manifest reference returns 500. Native Referrers and optional automatic cross-mount are not supported.
- The active Codex workspace still enters through a compatibility symlink. Reopen it from `/Users/byeonjaehan/projects/personal/coffer`, then remove the legacy symlink; the Git root already resolves to the canonical Coffer path.
- The Mac lab closes real Keystone HTTP/TLS, duplicate-name isolation, reader/member/admin/service mapping, domain/system isolation, finite credential lifecycle, real control middleware, incoming service-token enforcement, bounded cache, and outage behavior. Shared production SQL/memcache and multi-worker consistency remain deployment gates.
- Keystone authentication proves current credential validity but does not reveal whether the credential record has a non-null future `expires_at`; accepted ADR 0008 therefore requires explicit provisioning expiry plus the verified lifecycle regression matrix.
- The runbook's identity, private RGW bucket, Distribution TLS, single-process integrated auth, GC dry-run, shared upload state, Barbican KMS, shared-SQL quota, and isolated reconciliation paths now have evidence. Routine production credential helpers, existing-data upgrade, integrated authenticated reconciliation, multi-worker scheduling, and separate-host HA remain deployment gates.
- Application-credential access rules currently fail closed rather than being supported. Exact service/method/path semantics need a later accepted design if users require them.
- The static two-key fixture does not prove per-replica trust rollout, signer transition, old-key retirement, rollback, or Distribution key reload without restart.
- Broker decision logs correlate request/JTI/Keystone audit IDs and reductions with explicit Distribution 200/401 outcomes, and single-process bounded metrics are verified. Multi-worker and multi-replica aggregation remains open M3 work.
- Local bounded Prometheus metrics now exist, but process-local counters cannot be considered correct under the reference two-worker Gunicorn model until aggregation/restart semantics are selected and tested.
- MariaDB 11.4.12 can return an empty safe claim batch to one caller while another transaction range-locks part of the backlog. The verified bounded retry recovers the remaining work, but production scheduler cadence, jitter, deadlock retry, and Galera behavior remain gates.
- Multipass 1.16.3 was not installed. Its checksum matched Homebrew and its Canonical Developer ID signature was valid, but Gatekeeper rejected it as unnotarized. No bypass was attempted; preinstalled Lima 2.1.4 is the selected VM provider.
- Podman 5.6.0/libkrun must stay attached to a persistent PTY in this app for disposable live harnesses; completing the noninteractive cell terminates its VM child. Plan 0010 passed both shared-SQL engines this way with zero residue, so VM recreation or data reset is neither needed nor authorized.

## Exact Next Action

Implement collector-input, phase-preparation, and phase-completion
materializers, then compose the RGW and fault adapters under one
non-synthetic checkpoint adapter. Actual invocation remains release-gated.

## After This Work Package

Stage 6 converges only after released dependency, identity, data-protection,
observability, GC, and load gates pass. Official Kolla upstream/governance
work remains a later stage.
