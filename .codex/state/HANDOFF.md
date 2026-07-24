# Coffer Handoff

- Updated: 2026-07-24
- Status: plan 0017 completed locally; no active execution plan
- Completed execution plans: `docs/exec-plans/0001-product-discovery.md`, `docs/exec-plans/0003-barbican-kms-quota-poc.md`, `docs/exec-plans/0004-shared-sql-quota-reconciliation.md`, `docs/exec-plans/0005-multi-worker-reconciliation.md`, `docs/exec-plans/0006-reconciliation-runner.md`, `docs/exec-plans/0007-unified-control-schema.md`, `docs/exec-plans/0008-existing-content-inventory.md`, `docs/exec-plans/0009-transactional-inventory-import.md`, `docs/exec-plans/0010-post-import-ledger-comparison.md`, `docs/exec-plans/0011-authenticated-live-inventory-comparison.md`, `docs/exec-plans/0012-synthetic-inventory-scale-characterization.md`, `docs/exec-plans/0013-kolla-deployment-topology.md`, `docs/exec-plans/0014-kolla-runtime-images.md`, `docs/exec-plans/0015-kolla-ansible-operator-role.md`, `docs/exec-plans/0016-kolla-aio-end-to-end.md`, `docs/exec-plans/0017-production-image-remediation.md`
- Superseded execution plan: `docs/exec-plans/0002-thin-vertical-poc.md`
- Active execution plan: none

## Current Objective

Plan 0017 is complete with a reproducible fail-closed production-image
qualification baseline. Coffer-owned and wrapper-base Critical/High findings
are remediated; the signed Distribution v3.1.1 release binary is the explicit
upstream blocker. The recommended successor is a release-refresh work package
after a newer signed supported Distribution release exists, followed by the
unchanged image qualification and protocol gates. Publication, production
deployment, multinode/HA, and upstream changes remain unauthorized.

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

Implement `poc/production-images/` with immutable Kolla, Ubuntu, Distribution,
provenance, and scanner pins, then run its candidate build/security/runtime
qualification and verify that unresolved upstream binary findings fail closed.

## After This Work Package

Plan 0017 may accept a production-candidate image only if every ADR 0006 gate
passes. Otherwise it must close with a reproducible blocked baseline and exact
upstream dependencies. Multinode/HA and upstream integration remain later
independent packages.
