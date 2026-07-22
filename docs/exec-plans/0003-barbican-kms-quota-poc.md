---
title: "Barbican-backed RGW encryption and private-edge quota proof of concept"
status: completed
updated: 2026-07-22
owner: primary-agent
depends_on: docs/exec-plans/0002-thin-vertical-poc.md
---

# Objective

Extend the proven Coffer vertical slice with two explicitly authorized boundaries: real Ceph RGW SSE-KMS through an OpenStack Barbican authority, and the ADR 0009 private-edge manifest-admission design for bounded project-logical quotas. Preserve unmodified OCI Distribution and clients, keep every credential and key outside Git, prove fail-closed behavior, and restore the disposable lab to a documented safe state.

## Done Criteria

- [x] Deploy a disposable Barbican service reachable by `rgw.coffer` over verified TLS, with a least-privilege service identity and key whose secret state is owner-only and absent from Git/logs.
- [x] Configure the pinned RGW and Distribution S3 driver for the selected Barbican key, restart `rgw.coffer`, and prove new registry objects carry selected-release encryption evidence while pre-KMS content remains readable.
- [x] Prove wrong-key and bounded Barbican-outage writes fail closed without plaintext fallback or secret leakage, then restore service and verify the original encrypted digest after RGW and Distribution restarts.
- [x] Restore or retain the disposable KMS state according to the cleanup section without leaving an indeterminate encryption configuration.
- [x] Change ADR 0009 from proposed to accepted-for-PoC and implement an atomic shared-SQL manifest admission core with bounded request bodies, exact project/repository authorization, conservative pending recovery, and 429/503 outcomes.
- [x] Exercise quota admission under concurrent/retried manifest publication and through at least Docker/Podman plus Skopeo-compatible Distribution requests; direct tenant writes must not bypass the edge in the PoC topology.
- [x] Update durable architecture, runbook, execution evidence, and `HANDOFF.md`; run focused and repository-wide verification; commit and atomically push the completed milestone.

## Non-goals

- Production Barbican deployment, production PKI, HSM-backed keys, or a general KMS operator.
- Retrofitting encryption onto objects written before this test or claiming a later Ceph AES-GCM mode for Tentacle 20.2.2.
- A per-project hard physical-byte quota, blob-body proxying, a Distribution fork, billing, or a production ingress/load-balancer design.
- Separate-host registry HA, destructive registry GC, or production performance/SLO claims.

## Context and Evidence

- Baseline commit: `f437995`, pushed to `https://github.com/jaehanbyun/coffer.git` on `main`.
- Identity lab: Lima `coffer-devstack`, DevStack `stable/2026.1`, with pinned Barbican, Keystone, RabbitMQ, MySQL, and TLS proxy active.
- Storage lab: x86_64 `coffer-rgw-poc` on `bb00`, Ceph Tentacle 20.2.2, one functional OSD, RGW HTTPS, unmodified Distribution v3.1.1.
- KMS capability record: `docs/research/m3-rgw-kms-capability.md`.
- Quota design spike: `docs/research/m3-quota-enforcement-spike.md` and ADR 0009.
- User authorization: deploy disposable Barbican identity/key, deliver secrets owner-only, restart `rgw.coffer`, run bounded wrong-key/outage tests, and use ADR 0009 as the quota PoC implementation target.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Use Barbican for M3-B | It validates the intended OpenStack-native KMS path exposed by the live Tentacle schema | Vault-only generic evidence; KMIP without an existing operator service; testing backend | 2026-07-22 |
| Keep credentials, private keys, and key material in owner-only runtime state outside Git | Required by the approved security boundary and existing project rules | Repository fixtures; command-line secret values; retained raw logs | 2026-07-22 |
| Accept ADR 0009 for PoC validation | Token requests, notifications, and a shared RGW bucket cannot synchronously bound project-logical bytes | Token-only reservation; notification-only enforcement; a Distribution fork | 2026-07-22 |
| Keep blob traffic on Distribution and admit only bounded manifest bodies | Preserves the upstream data path while creating an enforceable publication boundary | Proxy every blob; post-publication-only accounting | 2026-07-22 |
| Force positive-size Distribution moves through multipart copy for the Tentacle PoC | Tentacle 20.2.2 rejects server-side-encrypted source `CopyObject`; `multipartcopythresholdsize: 0` preserves the upstream driver while using RGW's supported decrypt-and-re-encrypt multipart path | Disable SSE-KMS; fork Distribution; claim zero-byte compatibility | 2026-07-22 |

## Tasks

- [x] Inspect the stopped DevStack guest and pinned branch for the smallest reproducible Barbican enablement path; record exact plugin/package versions before mutation.
- [x] Add secret-safe host/guest Barbican bootstrap, provisioning, and strict-TLS verification harnesses; RGW binding/rollback/cleanup remain in the next task.
- [x] Deploy Barbican, create the disposable service identity/key, and establish verified-TLS reachability from the RGW guest without printing credentials.
- [x] Apply RGW Barbican bindings and temporary Distribution encryption settings, run success/wrong-key/outage/recovery tests, and restore a deterministic lab state.
- [x] Implement the ADR 0009 quota ledger/admission API and private-edge manifest route with focused tests.
- [x] Add a black-box quota fixture and measure logical admission/physical staging behavior without destructive GC.
- [x] Run full verification, inspect the diff and runtime residue, update the handoff, commit, and atomically push.

## Progress Log

### 2026-07-22 — Work package authorized and baseline published

- Completed: Verified the correct GitHub account and empty target repository, committed the complete tested baseline as root commit `f437995`, and atomically pushed `main` to `jaehanbyun/coffer`.
- Evidence: GitHub reports non-empty repository `jaehanbyun/coffer` with default branch `main`; local `main` tracks `origin/main` with a clean worktree before this plan was created.
- Changed files: This execution plan; ADR 0009 and the handoff are updated in the same first post-baseline milestone.
- Next exact action: Start `coffer-devstack` and inspect its pinned DevStack checkout, service configuration, TLS topology, and current Barbican package/plugin availability before adding deployment scripts.

### 2026-07-22 — Pinned Barbican service and disposable key completed

- Completed: Added `poc/barbican`, enabled RabbitMQ and exact Barbican commit `586152c223b9e1373f5e422276bcaa152686b761` in the existing pinned DevStack, and corrected the plugin's HTTP-derived `host_href` plus all catalog interfaces to the verified HTTPS endpoint.
- Identity/key evidence: Created exact project/user `coffer-rgw-kms-poc`, granted only Barbican's legacy `creator` role for this pinned configuration, and stored/retrieved a random 32-byte AES/CBC secret without printing or retaining its payload outside Barbican/client memory.
- Security evidence: Barbican, retry, Keystone listener, and RabbitMQ are active; strict CA trust returns the expected unauthenticated 401 and an unrelated trust path fails. The RGW caller password/key UUID are guest-root mode `0600`; retained host JSON contains only IDs and non-secret metadata.
- Failure resolved: The first restack waited for an interactive RabbitMQ password because the Keystone-only local configuration had no `RABBIT_PASSWORD`. The harness now reuses the existing `ADMIN_PASSWORD` reference without copying its value. A second post-check expected an unauthenticated 300 and HTTPS catalog default; the live API returns 401 and the plugin initially publishes HTTP, so the harness now enforces and verifies HTTPS explicitly.
- Changed files: Added the Barbican Makefile, README, host/guest bootstrap, provisioner, Python runtime, and strict-TLS verifier; updated this plan, ADR 0009, plan 0002 status, and the handoff.
- Next exact action: Add an owner-only, no-host-disk binding transfer from DevStack to `coffer-rgw-poc`, establish a loopback reverse tunnel to the verified Barbican/Keystone TLS proxy, and prove the RGW daemon container can trust and reach both endpoints before setting KMS options.

### 2026-07-22 — Owner-only RGW binding and daemon trust completed

- Completed: Streamed the seven-field RGW caller binding directly from DevStack guest root to RGW guest root without a Mac-side credential file, installed it under `/etc/coffer-rgw` with directory mode `0700` and file mode `0600`, and copied only the public DevStack CA.
- Network/trust evidence: Established an SSH reverse tunnel bound only to RGW loopback port `19311`; Barbican returned 401 and Keystone returned 200 with the explicit CA, while an empty trust path failed. The same probes passed inside the cephadm RGW daemon after a read-only CA bundle mount.
- RGW evidence: Reapplied `rgw.coffer` through a successful dry run and controlled redeploy. The pinned CentOS-based Ceph image uses `/etc/pki/tls/certs/ca-bundle.crt`; the first Debian-path mount was reachable only from the host, so the harness now targets the observed libcurl path and verifies the mount is read-only.
- Secret hygiene: No password, key payload, or key UUID value was printed or copied to retained host evidence. A failed pre-install CA assertion left a narrow temporary candidate; it was immediately removed before retry, and no permanent binding existed at that point.
- Changed files: Added direct binding and tunnel harnesses, documented the image-specific trust path, and made the RGW service spec preserve the CA mount when the lab bundle exists.
- Next exact action: Add an owner-only RGW KMS configurator that loads the caller password without echoing it, sets only the documented Barbican/Keystone option names for `client.rgw.coffer`, restarts the service, and verifies authenticated key retrieval through an encrypted S3 write.

### 2026-07-22 — Barbican SSE-KMS success, failure closure, and rollback completed

This first bounded run is retained as historical evidence. The later hardened rerun supersedes its repository-only object coverage, outage scope, and cleanup counts.

- Success evidence: Applied nine documented option names for `client.rgw.coffer` without printing values, restarted `rgw.coffer`, and wrote/read a 37-byte direct S3 proof with `aws:kms` and a selected-key match. Unmodified Skopeo plus Distribution wrote five new repository objects; every HEAD reported `aws:kms` and the selected key, and both new and pre-KMS digests survived Distribution and RGW restarts.
- Wrong-key evidence: Restarted Distribution with a random missing UUID only for a new `kms-wrong-key` repository. The push failed, its client log contained no runtime secret, and its S3 repository prefix contained zero objects before the correct key was restored.
- Outage evidence: Stopped the loopback tunnel and restarted RGW to create a fresh process without a cached key. A write to a new `kms-outage` repository failed and left zero prefix objects. After restoring the tunnel and restarting RGW again, five new recovery objects plus the direct S3 proof passed encryption metadata and decrypted-read checks.
- Cleanup and final state: Verified and removed only 11 isolated KMS proof objects, removed all nine Ceph KMS options including the stored caller password, restarted RGW and the non-KMS Distribution baseline, stopped the tunnel and DevStack, and rechecked the pre-KMS digest plus `/v2/` status 200 without Barbican. The stopped disposable identity/key and owner-only bindings remain for an exact rerun; no retained object depends on them.
- Security evidence: Distribution/client/runtime log scans found no caller password, S3 credential, authorization header, or key payload. Key UUID values were used only in owner-only runtime/config paths and were not emitted in retained evidence.
- Next exact action: Implement the accepted-for-PoC ADR 0009 core: shared-SQL quota rows, idempotent manifest reservations, exact authorization, bounded manifest bodies, conservative pending recovery, and focused 429/503/concurrency tests before adding the private-edge black box.

### 2026-07-22 — ADR 0009 quota core and manifest admission seam completed

- Implemented: Added shared-SQL project quota, descriptor, reservation, reservation-edge, and manifest tables; project-row serialization; project-unique descriptor accounting; idempotent target reservation; pending/release-pending/committed/released transitions; conservative recomputation; and resolved child-graph checks for OCI indexes.
- Admission seam: Added exact RS256/JWKS issuer/audience/expiry verification, canonical project/repository plus `push` grant enforcement, 4 MiB manifest bounding, byte-for-byte upstream forwarding, digest-path matching, and Distribution JSON outcomes for 401/400/413/429/503.
- Concurrency/recovery evidence: Twelve focused tests pass. Concurrent SQLite PoC writers are serialized with `BEGIN IMMEDIATE` while production SQL uses row locking; exactly one of two over-limit requests commits, shared descriptors charge once per project, pending reservations stay charged across ambiguity, and a released charge is reassigned to another pending reservation instead of being lost.
- Failure resolved: Falcon's greedy `path` converter cannot have a trailing manifest segment, so the isolated admission app uses a bounded `/v2/` sink and exact manifest regex. The SQLite fixture uses an explicit immediate write transaction; production-capable engines retain `SELECT ... FOR UPDATE` semantics.
- Next exact action: Add a private-network edge proxy fixture around unmodified Distribution, wire the synthetic M2 token realm and quota store, and exercise Docker, Podman, Skopeo, concurrent 201/429, 503, retry, direct-bypass denial, and logical-versus-staging measurements.

### 2026-07-22 — Private-edge quota black box completed

- Client evidence: Pinned Docker 29.5.3, Podman 5.6.0, and Skopeo 1.20.0 each pushed through the Coffer edge. Docker ran in an ephemeral private Docker-in-Docker service; no host insecure-registry setting was changed. Distribution exposed no host binding.
- Admission evidence: Two same-size, distinct manifest requests competed with exactly one manifest of headroom and returned 429/201. Repeating the admitted request with the same request ID returned 201 without a second charge; project usage ended with zero reserved bytes and stayed within the limit. A separate project without a quota row returned the expected 503 envelope.
- Staging evidence: Both competing repositories received only authorized cross-repository blob mounts before publication. A later unpublished blob upload changed MinIO S3 object count from 28 to 30 while the logical quota snapshot remained byte-for-byte unchanged.
- Compatibility correction: Docker 29 requests repeated scopes for one repository. The token parser now merges actions for the same canonical repository before policy reduction while continuing to reject duplicate actions inside one scope.
- Security and cleanup: Generated credentials and signing material were mounted from owner-only ignored state rather than Compose environment metadata. Cleanup removed containers, volumes, Docker auth state, credentials, private key, and JWKS; retained logs contained no credential value or JWT-shaped token.
- Next exact action: Run the repository-wide lock, multi-version test, compile, Bash/ShellCheck, Compose, Markdown, Mermaid, and secret/residue verification matrix, then inspect the complete diff.

### 2026-07-22 — Ultra review corrections and hardened quota rerun completed

- Review findings corrected: Client-declared descriptor sizes are now compared with authoritative Distribution `HEAD` metadata; Content-Type selects an explicit image/index decoder and mixed shapes fail closed; residual encoded paths are rejected before generic proxying; SQLAlchemy failures map to 503; release-pending retries return to a committable state; committed retries never downgrade the ledger; and all ledger mutations serialize on the project quota row.
- Boundedness evidence: Signed-64-bit logical sizes, 4,096 descriptors, exact tag/digest references, and a four-MiB manifest body are enforced. Forty-four focused quota/token/proxy tests pass, including size mismatch, shape substitution, SQL failure, retry, definite rejection, and encoded-path regressions.
- Topology evidence: The edge bridges distinct client and backend networks; Distribution bridges only backend and storage; MinIO is storage-only. Docker, Podman, and Skopeo receive only one project-A client file, cannot resolve Distribution or MinIO directly, and cannot see the signing key or full server fixture.
- Build/cleanup evidence: Root `.dockerignore` excludes `work/` and Git/Codex state, the locked edge image builds before ephemeral credentials exist, and the prior Coffer quota image was removed without global cache pruning. The hardened black box passed Docker/Podman/Skopeo, authoritative-size and encoded-path 400s, concurrent 201/429, retry 201, missing-quota 503, and physical staging 28 to 30; cleanup removed all containers, volumes, credentials, signing material, and JWTs.
- Next exact action: Harden the Barbican harness so secrets never enter helper argv, novel Distribution config/layer blobs are checked under the selected KMS key, failure cleanup restores the correct KMS path before rollback, and a bucket-wide scan proves zero retained selected-key objects.

### 2026-07-22 — Hardened Barbican rerun and Tentacle CopyObject boundary completed

- Secret boundary: Replaced secret-bearing Ceph helper arguments with owner-only files read inside the RGW guest, restricted the disposable identity to its exact effective Barbican `creator` assignment, rotated the registry S3 key after detecting build-context exposure, and scanned host, guest, client, Distribution, and RGW evidence without placing secret values in process arguments.
- Positive evidence: A deterministic novel OCI layout forced new config and compressed-layer payloads. With Distribution's S3 `multipartcopythresholdsize` set to zero, five repository objects and three global payload blobs reported `aws:kms` with the selected key; the new digest and pre-KMS baseline survived fresh Distribution and RGW processes.
- Release boundary: Tentacle 20.2.2 deliberately returns 501 when Distribution finalizes an encrypted positive-size blob through ordinary `CopyObject`; the multipart threshold routes positive-size objects through RGW's supported multipart decrypt-and-re-encrypt path. A direct zero-byte encrypted registry blob still fails closed because the upstream driver keeps zero-byte moves on ordinary `CopyObject`; this is a production compatibility gate, not a successful feature claim.
- Failure/recovery evidence: A random wrong key and a fresh RGW process with both Barbican and Keystone unavailable failed closed with zero novel repository/global objects and zero incomplete multipart uploads. A unique recovery layout passed after restoring the correct key and endpoints.
- Cleanup and safe state: Removed exactly 17 isolated proof objects, proved bucket-wide selected-key residue and incomplete multipart uploads were both zero, removed all nine Ceph KMS options, restored the non-KMS Distribution baseline, re-read the pre-KMS digest, and stopped DevStack and its reverse tunnel. The disposable owner-only identity/key state remains for an exact rerun; no retained object depends on it.
- Infrastructure incident: An overlapping unattended package-maintenance restart stopped Ceph services and hit systemd start limits without rebooting the VM or damaging data. The lab recovered to active-clean PGs; the RGW restart helper now waits for a new container ID and a stability interval instead of trusting stale orchestrator state.
- Next exact action: Update the architecture, research, runbook, and harness documentation with the verified positive-size workaround and zero-byte production gate, then run the complete repository and runtime-residue verification matrix.

### 2026-07-22 — Final regression, safe-state audit, and publication completed

- Code/configuration: The locked suite passed with 91 tests on each of Python 3.11.14, 3.12.2, and 3.13.14. Python compilation, all PoC Bash syntax and ShellCheck, Gunicorn config, three Compose models, every Make target dry run, and `uv lock --check` passed.
- Documentation: Thirty-nine Markdown files and 16 local links passed structural checks; all 99 unique external links returned HTTP 2xx/3xx; three Mermaid diagrams rendered through the installed Chrome and were visually readable; trailing-whitespace and source-of-truth consistency checks passed.
- Security/residue: A scoped Gitleaks scan plus private-key/JWT pattern scan found no leak. DevStack and the Podman machine are stopped; Docker is not running; the quota fixture has no container, volume, secret, credential, signing key, or JWT residue.
- Storage safe state: The RGW guest reports zero Ceph KMS options, zero Distribution KMS/multipart settings, zero temporary KMS OCI layouts, one baseline Distribution process returning CA-verified 200, and only the deliberate `POOL_NO_REDUNDANCY` warning.
- Review: Reconciled the final diff with all three read-only Ultra reviews and confirmed that every in-scope P1/P2 finding is fixed and covered. Remaining production gates are recorded rather than silently expanded into this PoC.
- Publication: The complete Barbican/quota milestone is recorded as one Git commit and atomically pushed to `jaehanbyun/coffer` `main` under the verified `jaehanbyun` account.
- Next exact action: No action remains in this completed plan. If authorized, start a new execution plan for production shared-SQL migrations and quota reconciliation before separate-host ingress/HA validation.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Baseline repository | `git push --atomic -u origin main`; `gh repo view jaehanbyun/coffer` | passed at `f437995` |
| Barbican TLS/API | strict-CA service discovery, key create/get metadata, RGW host and daemon caller path | passed |
| SSE-KMS success | direct S3 plus five repository and three global novel OCI objects; selected-key metadata; new/pre-KMS digest after fresh processes | passed for positive-size payloads with forced multipart copy |
| SSE-KMS boundary/failure | zero-byte ordinary CopyObject, wrong key, and fresh-process identity/KMS outage fail closed; zero novel objects/uploads; recovery; 17-object cleanup | passed; zero-byte support remains a production gate |
| Quota core | atomic/concurrent/retry/crash-state tests plus token-scope compatibility | passed: 44 focused tests after review hardening |
| Quota clients | pinned Docker, Podman, and Skopeo through non-bypassable edge | passed: 429/201, retry 201, 503, objects 28 to 30 |
| Secret hygiene | Gitleaks plus runtime log/value scans and residue checks | passed: no project-owned leak or disposable quota/KMS residue |
| Repository regression | lock, Python 3.11–3.13 tests, compile, Bash/ShellCheck, Gunicorn, Compose, Make, Markdown, Mermaid, external links | passed: 91 tests per Python version; all structural checks passed |

## Failures, Blockers, and Risks

- The retained DevStack now includes the pinned Barbican plugin but is stopped. Its tunnel and the cross-host lab topology are test scaffolding, not a production endpoint design.
- Barbican key deletion can make retained ciphertext permanently unreadable. Use isolated disposable content and prove cleanup ordering before destroying key state.
- Positive-size Distribution payloads require forced multipart copy with the pinned Tentacle release. Zero-byte encrypted moves remain incompatible, so production promotion requires a released Ceph fix/backport or another proven backend/release combination.
- Manifest admission creates a synchronous SQL dependency and a private-edge network boundary; the PoC must not quietly expose direct write access to Distribution.

## Handoff

- Current state: Completed and atomically published. The hardened Barbican matrix and ADR 0009 quota core/private-edge black box passed; the lab is at its documented safe baseline. Positive-size encrypted Distribution objects require the documented multipart-copy setting; zero-byte encrypted moves remain a production gate.
- Exact next action: None in this completed plan. A new user-authorized plan should begin with production shared-SQL migrations and quota reconciliation before separate-host ingress/HA validation.
- First file or command for that future package: Create an execution plan from `docs/exec-plans/TEMPLATE.md` and start by defining the Alembic schema/migration and reconciliation authority boundaries.
- Questions requiring user input: select and authorize the next work package; no input remains for plan 0003.
