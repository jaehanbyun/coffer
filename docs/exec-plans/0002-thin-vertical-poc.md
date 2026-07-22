---
title: "Keystone-to-OCI thin vertical proof of concept"
status: active
updated: 2026-07-22
owner: primary-agent
depends_on: docs/exec-plans/0001-product-discovery.md
---

# Objective

Prove the smallest end-to-end Coffer path with a real Keystone test environment and unmodified OCI clients: a user in project A creates a repository, authenticates the registry token realm with a finite role-restricted Keystone application credential, receives a short-lived Distribution JWT, and pushes/pulls through upstream Distribution backed by Ceph RGW, while a user scoped only to project B is denied access to project A.

## Done Criteria

- [x] The control API validates real scoped Keystone tokens; the token broker validates finite Keystone application credentials and records no credential secret.
- [x] The `/v2/` challenge and token realm produce a short-lived, repository/action-scoped JWT accepted by an unmodified Docker or Podman client.
- [x] Upstream Distribution stores image content in a Ceph RGW-compatible S3 backend; the final acceptance run uses Ceph RGW rather than only a local S3 substitute.
- [x] Project A can push and pull by digest after service restart; project B receives a denied response for project A's repository.
- [x] Invalid, expired, and wrong-audience tokens are rejected; over-scoped requests are reduced to authorized grants or denied by Distribution.
- [ ] Audit logs and metrics show repository creation, token decisions, push/pull outcomes, dependency health, and request IDs without leaking credentials.
- [x] The implementation and runbook document every command needed to repeat the PoC without checking secrets into Git.

## Non-goals

- Production HA, rolling upgrade, global replication, online GC, or strict physical-byte quota enforcement.
- Vulnerability scanning, signing, provenance policy, pull-through cache, lifecycle rules, UI, billing, and public access.
- Kolla-Ansible, OpenStack-Helm, or governance packaging.
- Building or forking an OCI Distribution implementation.

## Preconditions

- A disposable OpenStack environment with two domains containing deliberately colliding project/user names and finite, role-subset application credentials scoped independently to those project UUIDs.
- A disposable Ceph RGW S3 endpoint and service credential, supplied outside the repository.
- Docker or Podman, `curl`, `jq`, OpenStack CLI, and an OCI inspection tool such as `skopeo` or `crane`.
- TLS certificates suitable for the test environment; plaintext registry mode is not an acceptance path.

## Proposed Implementation Slice

1. **Control resource:** `POST /v1/repositories` accepts `X-Auth-Token`, validates Keystone project context, applies policy, and stores `{project_id, repository_name, immutable_tags}`.
2. **Bearer token realm:** `/auth/token?service=<service>&scope=repository:p/<project-id>/<repo>:pull,push` authenticates a finite Keystone application credential supplied through Basic auth, resolves an explicit control-plane repository, intersects requested actions with `oslo.policy`, and signs an approximately five-minute Distribution JWT without issuing a refresh token.
3. **Data plane:** upstream Distribution validates the JWT offline and handles `/v2/` against its S3 driver.
4. **Evidence:** structured logs, request IDs, metrics, and a black-box test script capture allow/deny behavior without preserving secrets.

## Milestones and Tasks

### M0 — Upstream compatibility spike

- [x] Start from Distribution v3.1.1 or a newer supported security release; pin the exact digest and record its license, CVEs, token-claim contract, S3/RGW configuration, conformance result, artifact/referrer behavior, and GC constraints.
- [x] Start unmodified Distribution with S3-compatible storage. Defer the generated signing key to M2, where the Distribution token-claim contract is exercised; M0 is intentionally an unauthenticated, IPv4-loopback-only data-plane compatibility test.
- [x] Prove push/pull of an OCI image and artifact/referrer before adding Coffer code.

### M1 — Keystone control and token broker

- [x] Select the minimal Python HTTP framework while retaining `keystoneauth1`, `keystonemiddleware`, `oslo.config`, `oslo.log`, `oslo.policy`, and `oslo.db` compatibility.
- [x] Implement repository create/get/list with project-ID ownership.
- [x] Authenticate finite Keystone application credentials at the token realm without storing their secrets; retain project/user/role/expiry/audit context only for the request and redacted audit record.
- [x] Add policy and negative project-scope tests.
- [x] Prove reader/member/admin mappings, service/system/domain-role isolation, duplicate names across domains, and application-credential deletion/role-removal/owner-disable behavior.

### M1-Lab — Disposable Mac/DevStack identity environment

- [x] Add a secret-safe, reproducible Lima bootstrap for pinned Ubuntu 24.04 and DevStack `stable/2026.1`.
- [x] Deploy only Keystone, MySQL, and the DevStack TLS proxy; do not add Nova, Neutron, Cinder, or Ceph to the first lab.
- [x] Verify the generated CA from macOS, real project-scoped tokens, duplicate names across domains, finite application-credential authentication, and post-deletion rejection.
- [x] Exercise Coffer's real `keystoneauth1` application-credential seam against the VM without retaining the credential secret.
- [x] Record the remaining difference between this identity lab and the final Ceph RGW/TLS/KMS acceptance environment.

### M2 — Standard registry auth path

- [x] Implement the Bearer token realm and exact Distribution JWT claim contract.
- [x] Configure offline signature verification, issuer, audience/service, and overlapping-key rotation metadata. Live multi-replica rotation remains an operational acceptance gate.
- [ ] Document `docker login --password-stdin` with an OS credential helper and dedicated finite application credentials; do not introduce a Coffer refresh-token store.
- [x] Prove pull-only, push/pull, denied delete, unregistered and cross-project repositories, and expired token cases in the local fixture.
- [x] Reject wrong issuer/audience/algorithm/service, altered signatures, not-yet-valid JWTs, duplicate repository/action scopes, encoded traversal after query decoding, and unauthorized cross-repository mounts in local unit and black-box tests. Multiple unique scopes remain supported for legitimate mounts.

### M3 — RGW persistence and operational evidence

- [x] Run the final object-store test against Ceph RGW with a service-only least-privilege credential.
- [x] Restart Coffer and Distribution instances and pull the original digest. Multi-replica shared-runtime failover remains a separate HA gate.
- [x] Emit and inspect audit events, health, and Prometheus-compatible metrics for the single-process PoC. Multi-worker aggregation remains a deployment gate.
- [x] Document logical deletion and a non-production GC dry run; do not automate destructive GC.
- [ ] Measure bounded soft-quota overshoot and reconciliation under concurrent/chunked uploads; do not claim byte-perfect enforcement.
- [ ] Verify private-bucket least privilege, redirect disablement, TLS failure behavior, and selected-release SSE-KMS encryption.

### M4 — Acceptance and decision update

- [x] Run the complete black-box verification twice from a clean client state.
- [x] Record latency and failure observations without turning them into an unsupported production benchmark.
- [ ] Update ADR decisions, architecture risks, and the next MVP implementation plan based on evidence.

## Verification Commands

The exact CLI shape can change during M1, but the final runbook must support an equivalent sequence. Values are placeholders and secrets are supplied through the operator's approved credential mechanism.

```bash
# Confirm the OCI challenge.
curl --fail-with-body --include https://registry.example.test/v2/

# Confirm each test identity is scoped to a different immutable project ID.
COFFER_PROJECT_A_ID="$(openstack --os-cloud coffer-project-a token issue -f json | jq -r '.project_id')"
COFFER_PROJECT_B_ID="$(openstack --os-cloud coffer-project-b token issue -f json | jq -r '.project_id')"
test "$COFFER_PROJECT_A_ID" != "$COFFER_PROJECT_B_ID"
COFFER_IMAGE_REF="registry.example.test/p/${COFFER_PROJECT_A_ID}/demo"

# Create the project-A repository and configure the standard client login.
openstack --os-cloud coffer-project-a registry repository create demo
printf '%s' "$COFFER_APP_CRED_SECRET_A" | docker login registry.example.test \
  --username "$COFFER_APP_CRED_ID_A" --password-stdin

# Push and inspect by digest using an unmodified OCI client.
docker build -t "${COFFER_IMAGE_REF}:poc" tests/fixtures/tiny-image
docker push "${COFFER_IMAGE_REF}:poc"
COFFER_VERIFIED_DIGEST="$(skopeo inspect "docker://${COFFER_IMAGE_REF}:poc" | jq -r '.Digest')"
oras repo tags "$COFFER_IMAGE_REF"

# Pull after restarting service processes; object data must persist.
docker pull "${COFFER_IMAGE_REF}@${COFFER_VERIFIED_DIGEST}"

# Project B must not receive project A content.
printf '%s' "$COFFER_APP_CRED_SECRET_B" | docker login registry.example.test \
  --username "$COFFER_APP_CRED_ID_B" --password-stdin
docker pull "${COFFER_IMAGE_REF}@${COFFER_VERIFIED_DIGEST}"

# Inspect dependency health, metrics, and redacted logs.
curl --fail-with-body https://registry.example.test/healthz
curl --fail-with-body https://registry.example.test/metrics
rg -n -i 'authorization:|x-auth-token|password|private key' "$COFFER_CAPTURED_LOGS"
```

Expected negative commands must be wrapped by the acceptance script so a non-zero exit is asserted rather than treated as an unexplained failure.

## Verification Matrix

| Check | Evidence | Required result |
|---|---|---|
| OCI compatibility | Docker/Podman push; Skopeo/Crane digest inspection | Same digest is readable after restart |
| Project isolation | Project-B pull of project-A digest | Denied before manifest/blob disclosure |
| Scope reduction | Request push with a pull-only role | Issued token lacks push or request is denied |
| Token validation | Expired/not-yet-valid, wrong issuer/audience/algorithm/service, forged signature | All rejected and audited |
| Role and scope matrix | Reader/member/admin/service/system/domain tests plus malformed and repeated scopes | Only project-scoped standard-role grants succeed |
| Cross-repository mount | Unauthorized source/target and cross-project mount attempts | Denied without revealing blob existence |
| RGW persistence | RGW object listing plus post-restart digest pull | Content persists; storage endpoint is not client-accessible |
| Quota behavior | Concurrent/chunked uploads against tiny logical and RGW guardrails | Overshoot bound is measured and reconciled; correct `429`/`503` behavior |
| Encryption and least privilege | S3 key, anonymous access, other-bucket access, SSE-KMS and failure tests | Only service bucket is reachable and accepted objects are encrypted |
| GC safety | Logical delete, all-replica read-only, dry run, collection, shared-layer pull | Referenced content survives; unreferenced content is reclaimed |
| Secret hygiene | Log scan and repository secret scan | No credential or signing material present |
| Observability | Health, metrics, correlated request IDs | Auth and data-plane outcomes diagnosable |

## Decisions to Resolve During PoC

| Decision | Evidence needed |
|---|---|
| HTTP framework and process model | OpenStack middleware compatibility, testability, async value, packaging |
| Application-credential UX and future federated flow | Docker credential-helper behavior, finite expiry/rotation, interactive MFA requirements |
| Project roles and repository overrides | Standard-role positive/negative tests and operator expectations |
| Repository policy overrides | Explicit-resource denial is fixed; per-repository override semantics still need operator evidence |
| Quota overshoot and accounting definition | Deduplication, reservation races, reconciliation accuracy, RGW guardrails |
| GC operating mode | Selected Distribution release and RGW consistency behavior |
| RGW credential source and encryption mode | Native versus Keystone EC2 key rotation/outage; stable Ceph SSE-KMS behavior |

## Progress Log

### 2026-07-21 — Mac DevStack identity lab authorized

- Scope: Build a disposable Ubuntu 24.04 VM on the Apple Silicon Mac and run pinned Keystone, MySQL, and TLS only. Keep Coffer and OCI clients on the host, and leave Ceph RGW as a separate final acceptance gate.
- Host evidence: `arm64` macOS with 24 GiB RAM and 260 GiB available disk; Homebrew is present and Multipass is not yet installed.
- Safety boundary: Generated passwords remain only inside the disposable VM; no credential, private key, `clouds.yaml`, or generated `local.conf` may enter the repository or durable handoff.
- Next exact action: Create `poc/devstack/README.md`, `Makefile`, and host/guest bootstrap and verification scripts, then validate their syntax before installing Multipass.

### 2026-07-21 — Mac DevStack harness completed; package install awaiting local authorization

- Completed: Added `poc/devstack` host/guest bootstrap, public-CA export, real Keystone identity/lifecycle checks, and a host-side Coffer `ApplicationCredentialAuthenticator` check. Generated passwords remain inside the guest; the one credential needed by the host crosses only an execution-time `mktemp` directory and is deleted on exit.
- Evidence: All five Bash scripts pass `bash -n` and ShellCheck; the Python verifier compiles; and all Make targets dry-run.
- Host blocker: Homebrew downloaded Multipass 1.16.3, but its signed macOS package installer requires an administrator password. The unattended install was cancelled before any password was entered or captured.
- Next exact action: The user runs `brew install --cask multipass` in a local terminal and completes the macOS administrator prompt, then the primary agent runs `make -C poc/devstack bootstrap`.

### 2026-07-21 — Unnotarized Multipass package rejected; Lima fallback selected

- Evidence: The downloaded Multipass 1.16.3 PKG SHA-256 exactly matched the Homebrew cask value and the package carried a valid timestamped `Developer ID Installer: Canonical Group Limited` signature, but `spctl` rejected it as `source=Unnotarized Developer ID`.
- Decision: Do not bypass Gatekeeper or remove quarantine metadata. Reuse the already-installed official Homebrew Lima 2.1.4 formula with Apple Virtualization Framework, `vzNAT`, and a fresh Ubuntu 24.04 instance. This changes only the host VM manager; the pinned guest, DevStack services, TLS checks, and Coffer acceptance scope remain unchanged.
- Preservation: Existing stopped Lima instances, including `openstack-devstack`, are not modified. The harness creates a separate `coffer-devstack` instance.
- Next exact action: Run `make -C poc/devstack bootstrap` with the revised Lima provider and inspect the first guest deployment result.

### 2026-07-21 — Plan activated

- Completed: Reviewed and accepted ADRs 0001–0004 under the user's instruction to proceed, activated this plan, and bounded the first implementation milestone to the upstream compatibility spike.
- Evidence: Product discovery, architecture baseline, official upstream references, and the required PoC gates recorded in the four ADRs.
- Changed files: ADRs 0001–0004, this execution plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Inspect local OCI tooling and current official Distribution release metadata, then pin the exact image digest and create the secret-free M0 compatibility environment.

### 2026-07-21 — M0 local functional path passed

- Completed: Pinned Distribution v3.1.1 and all local fixture images by multi-platform digest; created an unmodified Distribution plus MinIO environment bound only to IPv4 loopback; proved Docker push/pull by digest before and after a registry restart; attached and discovered an OCI artifact with ORAS v1.3.3; and confirmed registry objects in the S3-compatible bucket.
- Evidence: `make verify` passed with subject digest `sha256:8050eefb54ecfbc909bb9937862ed100e9d361e3181a46b4d79a124f8d279d34` and 23 objects in the test bucket. The native OCI 1.1 Referrers endpoint returned 404, while ORAS successfully used the fallback tag scheme.
- Security gate: Docker Scout reported 8 Critical and 9 High findings for the pinned Linux ARM64 image. The image remains limited to the isolated M0 spike and is blocked from production promotion pending a patched supported release or complete reachability/VEX disposition.
- Failures resolved: `localhost:5000` reached macOS AirPlay on IPv6 `::1` and returned 403, so host-side scripts now use `127.0.0.1`; ORAS absolute-path validation and the current `mc find` CLI shape required two script corrections.
- Changed files: `poc/m0/compose.yaml`, `poc/m0/registry-config.yml`, `poc/m0/Makefile`, `poc/m0/verify.sh`, `poc/m0/run-conformance.sh`, `poc/m0/README.md`, `.gitignore`, this execution plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Run `make conformance` against the pinned OCI Distribution Spec v1.1.1 commit and retain its generated report under ignored `work/` state.

### 2026-07-21 — M0 compatibility baseline completed

- Completed: Ran full and supported-capability OCI Distribution Spec v1.1.1 profiles, classified every failure and skip, reproduced the image security posture with Docker Scout and symbol reachability with `govulncheck`, recorded the v3.1.1 token contract and GC constraint, and visually inspected both generated HTML reports.
- Evidence: Full profile 68 passed, 7 failed, and 4 skipped. Supported profile 59 passed, 1 failed, and 19 skipped. The remaining core failure is a malformed manifest reference returning 500 instead of 400/404. `docs/research/m0-upstream-compatibility.md` contains the full classification.
- Decision: Distribution v3.1.1 remains an isolated PoC fixture and is blocked from production promotion. Proposed ADR 0006 defines the release gates; it does not replace or fork the upstream data plane.
- Changed files: Added `docs/research/m0-upstream-compatibility.md`, `docs/adrs/0006-gate-production-distribution-release.md`, and `poc/m0/scan-security.sh`; updated the M0 harness, README, Makefile, this plan, and `.codex/state/HANDOFF.md`.
- Verification: `make verify` passed; both conformance profiles generated valid JUnit and HTML reports while preserving their expected non-zero status; the full report rendered 68/7/4 and seven failure cards, and the supported report rendered 59/1/19 and one failure card.
- Next exact action: Select and document the minimal M1 Python HTTP/process model by exercising Keystone middleware compatibility before creating service code.

### 2026-07-21 — M1 framework and repository API seam completed

- Completed: Selected Falcon 4.3.1 WSGI with a server-neutral application and Gunicorn 26.0.0 `gthread` reference process; accepted ADR 0007; added the locked Python package; and implemented repository create/get/list with immutable Keystone project-ID ownership, reader/member policy, and `oslo.db` persistence.
- Evidence: The six-check framework spike passed on Python 3.11.14, 3.12.2, and 3.13.14. The durable nine-test API suite passed on all three versions and covers project/domain/system/unscoped/invalid/expired identity boundaries, per-project duplicate names, cross-project non-disclosure, and spoofed identity headers.
- Security boundary: The application requires `keystone.token_auth.user.project_scoped` before policy or database access and does not retain raw token info or the AccessInfo object. `service_token_roles_required=true` and the `service` role are explicit defaults. The fixture token cache is disabled.
- Process boundary: Eventlet, `oslo_service.wsgi.Server`, Gevent, and ASGI bridging are rejected. Multi-worker acceptance requires a shared SQL database, shared token cache, finite dependency timeouts, and post-fork client/engine initialization.
- Changed files: `pyproject.toml`, `uv.lock`, `src/coffer/`, `tests/`, `docs/research/m1-framework-selection.md`, ADR 0007, `README.md`, `.gitignore`, this plan, and `.codex/state/HANDOFF.md`.
- Verification: `uv run --group test pytest -q` passed 9 tests on Python 3.13; the same suite passed on Python 3.11 and 3.12; Gunicorn accepted the WSGI factory with two `gthread` workers and four threads under `--check-config`.
- Next exact action: Implement the finite Keystone application-credential authentication seam in `src/coffer/keystone.py` and prove that the supplied secret is request-local, redacted, and never persisted or logged.

### 2026-07-21 — M1 local application-credential seam completed

- Completed: Added a bounded/redacted Basic credential parser and a request-local `keystoneauth1.identity.v3.ApplicationCredential` authenticator with TLS verification, finite timeout, no catalog request, fail-closed error mapping, and a non-secret principal containing only project/user/roles/expiry/audit context.
- Evidence: Seven authenticator tests and ten parser tests prove correct plugin/session inputs, secret-free retained state/logs/exceptions, invalid/incomplete/unscoped identity rejection, Keystone outage mapping, strict Base64/UTF-8 parsing, colon-preserving secrets, and input-size bounds. The complete suite passes 26 tests.
- Gap found: A successful Keystone authentication token exposes the application-credential ID but not the credential record's own `expires_at`. Proposed ADR 0008 treats finite lifetime as a provisioning plus real-acceptance contract instead of adding a privileged per-exchange metadata lookup.
- Changed files: `src/coffer/keystone.py`, `src/coffer/credentials.py`, `src/coffer/config.py`, corresponding tests, `docs/research/m1-application-credential-authentication.md`, proposed ADR 0008, this plan, README, and handoff.
- Remaining M1 acceptance: The token-realm HTTP path and real Keystone lifecycle matrix remain open; fixture/injected access data cannot close them.
- Next exact action: Build the separately composed `/auth/token` WSGI path and M2 Distribution JWT issuer around the request-local authenticator without placing `keystonemiddleware.auth_token` in front of that path.

### 2026-07-21 — M2 local registry token contract completed

- Completed: Implemented the separately composed Basic-auth token realm, exact RS256 Distribution JWT claims, strict service/scope parsing, explicit control-database repository lookup, `oslo.policy` action reduction, request/audit correlation, five-minute maximum lifetime, no refresh token, and static overlapping-JWKS verification.
- Security corrections: The first implementation granted any canonical repository in the caller's project, ignored Keystone application-credential access rules, and chained dependency errors whose request body could retain the submitted secret. The final local boundary requires an explicit repository, rejects access-rule-bearing credentials, removes the Authorization header before authentication, contains and discards dependency exceptions, and deletes secret-bearing locals before returning a decision.
- Evidence: The 63-test suite passes. `make -C poc/m2 verify` exits 0 with a synthetic two-project realm and proves Docker login, member push/pull, reader reduction, denied delete and missing/cross-project repository access, direct post-restart blob checksum, positive same-project mount, equal 401/404 treatment of existing and nonexistent cross-project mount sources, negative issuer/audience/algorithm/signature/time cases, two distinct accepted `kid` values, decision logs, and secret cleanup.
- Key boundary: A signing key must be RSA 2048 bits or stronger, its PEM must not be group/world accessible, and configured JWT lifetime is bounded to 60–300 seconds. The two-key test proves overlap metadata only; live signer transition and replica retirement remain open.
- Limits: Identity is synthetic, object storage is MinIO, transport is loopback HTTP, the client is Docker only, Distribution v3.1.1 remains security-gated, and neither real Keystone lifecycle nor an OS credential helper is accepted.
- Changed files: `src/coffer/authorization.py`, repository/policy/token/Keystone/WSGI modules, related tests, `poc/m2/`, ADR 0002, `docs/research/m2-token-contract.md`, README, this plan, and handoff.
- Next exact action: Create `docs/runbooks/real-keystone-rgw-poc.md` with credential-helper-safe provisioning, real Keystone lifecycle/TLS checks, Ceph RGW prerequisites, evidence capture, and cleanup commands without embedding credentials.

### 2026-07-21 — Real-environment acceptance runbook prepared

- Completed: Added a secret-safe, phase-gated operator runbook for real Keystone/TLS identity, finite credential provisioning, OS credential helpers, role/access-rule/lifecycle/outage tests, explicit repository creation, clean-client digest persistence, Ceph RGW least privilege and SSE-KMS, correlated evidence, redaction, and cleanup.
- Safety boundary: The runbook requires a disposable non-production region and bucket, immutable target IDs, verified TLS, external secret stores/profiles, no shell tracing, redacted evidence only, and explicit operator approval before destructive identity/storage cleanup.
- Evidence status: The procedure is written but not executed. It cannot close M1 or M3 until the user identifies a disposable OpenStack/Ceph environment and the operator supplies non-secret bindings through an approved channel.
- Changed file: `docs/runbooks/real-keystone-rgw-poc.md` plus this plan and handoff.
- Next exact action: Implement local `/healthz` and Prometheus-compatible `/metrics` endpoints with bounded labels and focused readiness/decision metrics before binding the runbook to real infrastructure.

### 2026-07-21 — M3 local observability seam completed

- Completed: Added unauthenticated exact-path `/healthz` liveness, `/readyz` database readiness, optional `/metrics`, process-local Prometheus counters/histograms, fixed token-decision result classes, and route-template HTTP metrics.
- Security/cardinality boundary: Metrics are disabled by default, contain no tenant/resource/request identifiers, collapse arbitrary methods to `OTHER`, and must be protected at the operator edge. Health failures expose a neutral dependency state without exception or connection detail.
- Evidence: The complete Python 3.13 suite passes 69 tests; operational routes bypass tenant middleware, `/v1` remains protected, DB readiness succeeds/fails correctly, concrete IDs do not become labels, and token secrets do not appear in metrics.
- Limit: The registry is process-local. Gunicorn multi-worker aggregation, Keystone/RGW/KMS probes, Distribution request outcomes, quota, and GC metrics remain open, so the M3 checklist item is not marked complete.
- Changed files: `src/coffer/observability.py`, configuration, WSGI/token instrumentation, database ping, tests, locked `prometheus-client`, `docs/research/m3-local-observability.md`, README, this plan, and handoff.
- Next exact action: Rerun the complete suite on Python 3.11, 3.12, and 3.13, the authenticated M2 Docker fixture, structural documentation checks, and project-owned secret scans; then stop at the external Keystone/RGW environment gate if all local checks pass.

### 2026-07-21 — Hardened local verification matrix completed

- Completed: Reinstalled the changed package into Python 3.11 and 3.12 environments; ran the complete suite on Python 3.11.14, 3.12.2, and 3.13.14; reran the authenticated Docker/Distribution fixture; validated Gunicorn, Python, Bash, Compose, lock state, documentation structure/links, cleanup, and secret hygiene.
- Evidence: 69 tests passed on each Python version. `make -C poc/m2 verify` passed after M3 instrumentation. Thirty Markdown files, 12 local links, and 18 shell blocks passed structure/syntax checks; 81 external Markdown link targets returned HTTP 2xx/3xx; scoped Gitleaks and private-key/JWT-shaped value scans passed.
- Expected warnings: Python 3.11/3.12 emit only WebOb's known `cgi` deprecation warning. Gunicorn's default smoke configuration warns that a real Keystone public URI is not yet configured.
- Cleanup: No M2 service or volume remains. Fixture private keys, credential environment, bearer cases, SQLite database, downloaded blob, and temporary Docker credential config are absent.
- Blocker: No safe local action can substitute for real Keystone/RGW/TLS/KMS/operator evidence. The next action requires the user or environment owner to identify a disposable test environment and approve the non-secret runbook bindings.
- Next exact action: Bind Phase 0 of `docs/runbooks/real-keystone-rgw-poc.md` to the approved disposable environment by supplying the named cloud contexts, immutable project IDs, TLS endpoints, private RGW bucket/profile, and optional KMS key ID through an approved non-repository channel.

### 2026-07-21 — Mac DevStack identity lab completed

- Completed: Created the independent `coffer-devstack` Lima 2.1.4 VM with Apple Virtualization, Ubuntu 24.04 ARM64, four CPUs, 8 GiB RAM, and a 50 GiB disk. Pinned DevStack `stable/2026.1` at `da2f4d73f5ad74fc8ecfbe15bd7e20f6b0982dbb` and deployed only Keystone, MySQL, and the TLS proxy at `https://192.168.64.6/identity/v3`.
- Identity evidence: A strict private trust context accepted the exported DevStack CA and rejected an unrelated CA. Two domains with colliding project and user names produced distinct immutable IDs and correctly scoped tokens. Finite member-role application credentials authenticated and were rejected after configured expiration, delegated-role removal, owner disablement, and explicit deletion. A domain/system-only user could obtain those nonproject token shapes but could neither obtain a project token nor create an application credential.
- Coffer evidence: The host exercised the production `ApplicationCredentialAuthenticator` over verified TLS for role-restricted reader, member, admin, and service credentials. Effective roles were respectively `reader`; `member,reader`; `admin,manager,member,reader`; and `service`. The verifier proved `service` contributes no registry role, while existing authorizer tests prove reader pull, member pull/push, admin pull/push/delete, and service denial. A second host verifier passed real project/domain/system tokens through Coffer's production `keystonemiddleware`: project scope created a repository, domain/system scope received 403, a real incoming `service` token passed, and a member token substituted as a service token received 401. Real Keystone exposed a deleted/nonexistent credential as `keystoneauth1.exceptions.NotFound`; Coffer now maps that response to `InvalidApplicationCredential` instead of a dependency outage, with a redaction regression test.
- Failures resolved: DevStack installs its CA in the guest system trust store, so `curl --cacert` did not isolate the negative trust anchor; the guest test now uses an isolated Python TLS context. The OpenStack admin `openrc` also leaked project-scope variables into the first application-credential CLI request; the helper now explicitly removes incompatible scope variables. The failed credential was deleted before rerunning, and the final test user has no residual application credentials.
- Verification: `make -C poc/devstack verify` passed with control-API middleware, incoming service-role enforcement, a two-second revoke-cache bound, Keystone-outage 503, application-credential role mapping, domain/system isolation, deletion, expiration, delegated-role removal, and owner-disable invalidation. Apache and MySQL are active; the host HTTPS probe passed without `-k`; all DevStack scripts pass Bash syntax and scoped ShellCheck; the complete suite passes 70 tests on Python 3.11.14, 3.12.2, and 3.13.14; both Compose models and `uv lock --check` pass; project-owned Gitleaks scans report no leaks. Final cleanup left only the member project-role assignment and no test token fixture, application credential, service/scope user, or temporary database.
- Decision: Accepted ADR 0008. Finite lifetime remains a provisioning and acceptance contract because the standard authentication response cannot prove the credential record's configured expiry, while the real lifecycle matrix shows Keystone enforces expiration, role removal, owner disablement, and deletion without a privileged Coffer metadata lookup.
- Boundary: This closes M1-Lab, the M1 application-credential role/lifecycle matrix, and real control-API token validation. The measured cache is intentionally single-process and does not replace shared production memcache/SQL evidence. Ceph RGW, SSE-KMS, quota, HA, Distribution TLS/outcome correlation, shared runtime state, and GC remain M3 acceptance gates.
- Next exact action: Bind Phase 0 of `docs/runbooks/real-keystone-rgw-poc.md` to an approved disposable Ceph RGW/KMS environment and execute the storage/TLS persistence slice.

### 2026-07-22 — Disposable x86_64 RGW VM baseline completed

- Completed: Reclaimed the retired `openstack-ebpf-controller-1` and `openstack-ebpf-compute-1` libvirt domains and their dedicated volumes after explicit user authorization, then created a separate `coffer-rgw` directory pool on the local `/srv/nfs` XFS filesystem and bootstrapped `coffer-rgw-poc` from the existing Ubuntu 24.04 cloud image.
- VM boundary: The domain has 8 host-passthrough vCPUs, 24 GiB RAM, a 60 GiB qcow2 root overlay, a distinct 200 GiB sparse raw OSD disk, reserved default-NAT address `192.168.122.200`, and autostart disabled. The rotational host filesystem is acceptable for functional persistence and outage evidence, not performance or physical-failure-domain claims.
- Evidence: Ubuntu 24.04.3 x86_64 booted under KVM; cloud-init completed without errors; the root filesystem expanded to 58 GiB; `/dev/vdb` is an unused 200 GiB device; qemu-guest-agent is active; SSH through `bb00` succeeds; and a normal guest reboot preserved the address, root filesystem, OSD device, and guest agent. `bb00` retained about 61 GiB available memory and 896 GiB free in the pool filesystem after creation.
- Changed files: Added `poc/rgw/bootstrap-vm.sh`, `poc/rgw/Makefile`, and `poc/rgw/README.md`; updated this plan and `.codex/state/HANDOFF.md`.
- Next exact action: Verify and pin the current stable Ceph release, add a secret-free guest install harness, and bootstrap a single-host cluster with exactly `/dev/vdb` as its OSD device.

### 2026-07-22 — Pinned single-host Ceph baseline completed

- Completed: Installed Ceph Tentacle 20.2.2 with a SHA-256-verified `cephadm` artifact and an exact `quay.io/ceph/ceph` manifest digest, bootstrapped the cluster with dashboard and monitoring disabled, and added only `/dev/vdb` as `osd.0`.
- Evidence: The monitor has quorum, both manager daemons run, and `osd.0` is `up` and `in` with about 200 GiB raw capacity. All four Ceph daemons report 20.2.2. The cluster config records `osd_pool_default_size=1` and `osd_pool_default_min_size=1` for this disposable one-OSD lab.
- Recovery behavior: The first run stopped safely before disk consumption when the Tentacle device-list JSON proved nested rather than flat. The installer now validates the pinned existing cluster and resumes idempotently; the second run created the OSD and exited successfully.
- Warning resolution: Immediately after bootstrap, the health cache reported the former default replica count and classified the bootstrap monitor and first manager as stray. A shortened supported cephadm recheck cleared the stray entries; restarting the two managers loaded the live size-one default and cleared `TOO_FEW_OSDS` without touching the OSD or object data.
- Changed files: Added `poc/rgw/guest-install-ceph.sh` and `poc/rgw/install-ceph.sh`; updated `poc/rgw/Makefile`, `poc/rgw/README.md`, this plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Inspect Tentacle's installed RGW service-spec schema and deploy one cephadm-managed RGW with a verified HTTPS endpoint.

### 2026-07-22 — Cephadm-managed RGW HTTPS baseline completed

- Completed: Applied a validated `rgw.coffer` service spec for one Beast frontend bound only to `192.168.122.200:8443`. Cephadm generated the server key and certificate under its cluster-local CA; no private key entered the repository or host evidence.
- TLS evidence: The leaf SANs contain `DNS:coffer-rgw-poc` and `IP Address:192.168.122.200`. A request using the exported public CA returned HTTP 200, the same request without that trust anchor failed, and plaintext HTTP on the TLS port failed. The host-side check passed through ProxyJump and a local SSH tunnel without `-k`.
- Storage evidence: RGW created five pools with `size=1` and `min_size=1`; all 129 PGs are `active+clean`. The stale stray and too-few-OSD health entries are gone. The remaining `POOL_NO_REDUNDANCY` warning is expected and retained for this explicitly non-durable one-OSD lab.
- Changed files: Added `poc/rgw/guest-deploy-rgw.sh`, `poc/rgw/deploy-rgw.sh`, `poc/rgw/export-rgw-ca.sh`, and `poc/rgw/verify-rgw.sh`; updated the RGW Makefile/README, this plan, and `.codex/state/HANDOFF.md`.
- Verification: All RGW harness scripts pass Bash syntax and ShellCheck; the deploy target completed idempotently with no service change on dry-run; and `make -C poc/rgw verify-rgw` passed.
- Next exact action: Create a service-only RGW user, private registry bucket, and separately owned denial-test bucket while keeping all generated S3 secrets outside the repository and command output.

### 2026-07-22 — Private RGW service identity and bucket boundary completed

- Completed: Created ordinary non-system RGW users `coffer-registry-poc` and `coffer-denial-poc`. Each has zero admin capabilities, exactly one S3 key, and `max-buckets=1`; each owns exactly one private bucket with the corresponding name.
- Access evidence: The registry identity completed a put/get/delete sentinel round trip in `coffer-registry-poc`. Anonymous access returned 403, the registry identity received 403 for the separately owned denial bucket, and an additional bucket request returned 400 because the one-bucket limit was exhausted.
- Secret boundary: User JSON and keys exist only in root-owned mode-0600 guest files. The registry key pair was copied without printing into ignored host `work/rgw/distribution.env` with mode 0600. No denial-user key was exported.
- Failure resolved: Tentacle requires `--generate-key=true` rather than the help text's apparent flag-only form. The first attempt stopped before user creation; the corrected idempotent script removes protected temporary files on failure and passed on retry.
- Changed files: Added `poc/rgw/guest-provision-s3.py`, `poc/rgw/guest-provision-s3.sh`, `poc/rgw/provision-s3.sh`, and `poc/rgw/export-s3-profile.sh`; updated the RGW Makefile/README, this plan, and `.codex/state/HANDOFF.md`.
- Verification: Bash syntax, ShellCheck, Python compilation, Make dry-runs, user/bucket metadata checks, and the full access matrix passed. Ruff was unavailable because the repository has no locked Ruff executable.
- Next exact action: Run the pinned unmodified Distribution v3.1.1 data plane against `coffer-registry-poc` over verified RGW TLS and prove digest persistence across Distribution and RGW restarts.

### 2026-07-22 — Unmodified Distribution-to-real-RGW persistence completed

- Completed: Ran the pinned unmodified CNCF Distribution v3.1.1 x86_64 image against the private `coffer-registry-poc` bucket through the upstream S3 driver, SigV4, path-style addressing, verified RGW TLS, and redirect disablement. Distribution itself served `/v2/` over a separate private lab CA on guest port 5443.
- Persistence evidence: Skopeo copied the pinned BusyBox fixture and read subject digest `sha256:7a3ebe5bfd1a4a19797d20b0c0bb39d44393e9a03fd852c0865b0f540d868df0`. The same digest remained pullable after a Distribution restart, an RGW restart, and online PG merges. A direct blob request returned 200 with no `Location` header and matched its SHA-256 digest; the RGW bucket contained eight registry objects.
- Security evidence: Untrusted client TLS and plaintext OCI requests failed; Mac-side `/v2/` validation passed through ProxyJump and an SSH tunnel with the exported public CA. Distribution logs matched none of the two S3 values or the persistent HTTP secret. Credentials, HTTP secret, CA private key, and leaf private key remain root-only guest state.
- Lab tuning: RGW's defaults created 290 PGs on one OSD. Rather than increasing `mon_max_pg_per_osd`, the harness set `mon_target_pg_per_osd=50`, reduced the bulk data pool online from 128 to 64 PGs, and fixed the small non-EC pool at 16 with autoscaling off. The final cluster has at most 241 active-clean PGs and only the explicit `POOL_NO_REDUNDANCY` warning; the digest remained readable after the merges. These values are disposable one-OSD lab settings, not production recommendations.
- Failures resolved: Skopeo requires a digest-only image reference instead of `tag@digest`; Go's TLS server correctly returns HTTP 400 to plaintext rather than dropping the TCP connection; and the final health gate exposed excessive default PGs before the lab-specific reduction.
- Changed files: Added Distribution run, verification, CA-export, and host-tunnel scripts under `poc/rgw/`; updated the RGW Makefile/README, Ceph bootstrap defaults, ADR 0003, this plan, and `.codex/state/HANDOFF.md`.
- Verification: All shell scripts pass Bash syntax and ShellCheck. Guest persistence and host TLS verification passed, and no runtime secret appears in captured Distribution logs.
- Next exact action: Bind the real Keystone/Coffer token broker and repository authority to this RGW-backed Distribution endpoint, then prove project-A push/pull and project-B denial with correlated audit outcomes.

### 2026-07-22 — Real Keystone/Coffer-to-RGW vertical slice completed

- Completed: Added `poc/integration/`, which creates two finite member application credentials in the real DevStack projects, starts Coffer's production Keystone authenticator/repository-policy/token-issuer seam behind an ephemeral TLS endpoint, trusts only its public JWKS in unmodified Distribution, and joins the Mac and RGW guest over an SSH reverse tunnel.
- Authorization evidence: Project A pushed and pulled `p/<project-a-id>/real-rgw` through both unmodified Skopeo and Podman clients. Project B authenticated successfully but received an empty cross-project grant; its project-A read returned 401 and its push failed. Explicit token responses produced distinct `X-Openstack-Request-Id` values that matched broker lines containing the correct immutable project ID, Keystone audit ID, requested actions, and granted or empty access result.
- Persistence evidence: Skopeo preserved digest `sha256:7a3ebe5bfd1a4a19797d20b0c0bb39d44393e9a03fd852c0865b0f540d868df0` across Distribution and Coffer broker restarts. Podman completed its independent login/push/pull round trip; its client-rewritten manifest was verified against the digest returned by its own push rather than incorrectly compared with Skopeo's source manifest.
- Security and cleanup: TLS without either private lab CA failed. Application-credential secrets and registry JWTs matched none of the broker, Distribution, denied-push, or tunnel logs. Cleanup deleted both Keystone credentials, guest auth/JWKS state, local private keys/database/client credentials, and Skopeo/Podman auth state; it stopped the previously stopped DevStack VM and restored the unauthenticated RGW persistence fixture.
- Failures resolved: The first run stored normalized hyphenated UUIDs while Keystone used compact 32-hex project IDs, so explicit repository lookup correctly returned no grant; the runtime now validates UUID syntax without changing the immutable identifier. The first Podman assertion also incorrectly required its rewritten manifest to equal Skopeo's preserved source digest; it now compares Podman's reported push and re-pull digests.
- Verification: The expanded full integration harness passed once from a clean credential/client state. All changed Bash parses and passes scoped ShellCheck, the Python integration modules compile, and `git diff --check` passes.
- Changed files: Added the real integration Makefile, README, broker runtime, ephemeral key/database preparer, RGW guest preparation, client/restart verification, and host orchestration under `poc/integration/`; extended the DevStack guest fixture for two-project credentials and made the RGW Distribution runner optionally consume a token realm and public JWKS.
- Boundary: This is a single Coffer process and single Distribution instance restarted in place, not multi-replica HA or shared SQL/cache/key-rollout evidence. KMS, bounded quota races, GC, full metrics/outcome aggregation, and credential-helper guidance remain open.
- Next exact action: Run `make -C poc/integration verify` a second time from the restored clean state, compare the redacted result with the first successful run, and close only the repeated clean-client acceptance item if it passes.

### 2026-07-22 — Repeated clean-client acceptance completed

- Completed: Ran the final `poc/integration` harness a second time after the first run had deleted credentials/private runtime/client auth state, stopped DevStack, and restored the unauthenticated registry fixture.
- Comparison: Both runs reported the same real Keystone/RGW/Distribution identities, client set, immutable project-A repository, Skopeo digest, post-Distribution and post-Coffer restart digests, project-A 200, project-B 401, and denied project-B push. The token request IDs differed across runs as required for independent exchanges.
- Cleanup: The second run again removed all finite application credentials and private runtime files, returned `coffer-devstack` to `Stopped`, removed guest integration state, and restored an HTTP 200 unauthenticated `/v2/` storage fixture.
- Acceptance: M4's two clean-client black-box executions are complete for the single-process/single-Distribution topology. This does not close HA, shared state, KMS, quota, metrics aggregation, or GC.
- Next exact action: Add a non-destructive RGW-backed Distribution garbage-collection dry-run that stops writes, records object counts, runs the pinned image with `garbage-collect --dry-run`, restarts Distribution, and proves all selected referenced digests remain pullable without executing deletion.

### 2026-07-22 — RGW-backed Distribution GC dry-run completed

- Completed: Added `make -C poc/rgw verify-gc-dry-run`. The harness requires redacted successful integration evidence, verifies the restored unauthenticated fixture, stops the only Distribution instance to exclude writes, and runs the exact pinned image's `garbage-collect --dry-run` command against the real RGW configuration.
- Evidence: RGW reported 19 objects before and after each dry-run; the collector reported zero blob and zero manifest deletion candidates. After Distribution restarted, the baseline manifest, integrated Skopeo manifest, and integrated Podman manifest all remained pullable with their pre-run digests.
- Safety: The harness never enables `--delete-untagged` and never runs a non-dry collector. Its exit trap restarts Distribution on both success and failure. Runtime S3/HTTP secrets and JWT-shaped values matched none of the retained collector log, and public temporary evidence is removed from the guest after export.
- Failure resolved: The first functional dry-run passed, but host cleanup attempted to remove root-owned `/tmp` evidence as the unprivileged guest user. Cleanup now uses `sudo rm -f` on three exact public evidence paths; the wrapper rerun passed.
- Changed files: Added the GC guest and host verifiers, a Make target, and RGW README guidance; updated ADR 0003, this plan, and the handoff.
- Boundary: Zero current candidates proves dry-run correctness and referenced-content retention for this dataset, not real deletion behavior or shared-blob retention after destructive collection. A real collection remains a separately approved maintenance action.
- Next exact action: Enable Coffer's existing bounded metrics in the real integration broker, capture `/healthz`, `/readyz`, and `/metrics` before and after the intentional broker restart, and prove fixed-cardinality token-decision observations contain no project, request, credential, or JWT values.

### 2026-07-22 — Real single-process observability evidence completed

- Completed: Composed the existing production health/readiness/metrics resources into the real integration broker. The harness captured `/healthz`, SQLite-backed `/readyz`, and Prometheus text before and after the intentional Coffer restart.
- Evidence: Both process generations returned healthy/ready. The first observed 18 token decisions in 0.2166 aggregate seconds (`issued=13`, expected unauthenticated readiness probes `invalid_credential=2`, and expected malformed/unsupported client retry shapes `invalid_request=3`); the restarted process observed four decisions in 0.0481 aggregate seconds (`issued=3`, `invalid_credential=1`). These approximately 12 ms aggregate per-decision observations are local functional-lab data, not a latency SLO or production benchmark.
- Cardinality/security: Both metric snapshots used only fixed result labels. Neither snapshot contained either project ID, either token request ID, the repository name, either application-credential ID or secret, or a JWT-shaped value. Detailed project/audit/request/grant correlation remained in logs rather than labels.
- Failure observations: The broker produced no unexpected error/fatal/timeout event. Distribution's one logged 404 was the client's normal pre-push blob existence probe, and the Skopeo fatal line was the intentionally denied project-B push. The explicit cross-project read remained 401.
- Boundary: Metrics reset across the process restart by design. This closes the single-process M3 observation item and explicitly demonstrates why the current collector cannot represent multi-worker or multi-replica totals.
- Changed files: Updated the integration broker composition, verifier, and README; updated the M3 observability research note, this plan, and the handoff.
- Next exact action: Write a bounded-soft-quota implementation spike that identifies the smallest enforceable admission point around unmodified Distribution, defines reservation/reconciliation state and failure codes, and stops before adding a proxy or notification dependency unless the design is accepted.

### 2026-07-22 — Bounded-soft-quota enforcement spike completed

- Finding: Token-time reservation cannot bound bytes because a standard reusable push JWT carries neither expected size nor a one-use upload identity. Notification-only reconciliation cannot deny before publication, and a shared RGW bucket has no project-level storage identity.
- Proposed seam: `docs/research/m3-quota-enforcement-spike.md` defines project logical usage as unique reachable OCI descriptor bytes and proposes a private-edge manifest admission hook. Blob bodies remain streamed to unmodified Distribution; a bounded manifest is admitted only after an atomic shared-SQL reservation, with conservative pending states across ambiguous failures and 429/503 outcomes.
- Physical boundary: Unpublished/chunked blob staging is not project logical usage and remains controlled by service-wide RGW quota, upload purging, request limits, and GC. The product must not call that a per-project hard physical-byte quota.
- Decision record: Added proposed ADR 0009. It explicitly rejects token-only, notification-only, shared-bucket RGW quota, and a Distribution fork as bounded project admission. It remains proposed because the edge body-handling seam changes the earlier no-manifest-proxy assumption.
- Implementation gate: No proxy, gateway plugin, notification consumer, or quota schema was added. Accepting ADR 0009, removing the bounded quota promise, or choosing project-isolated registry/storage topology requires an explicit architecture decision.
- Next exact action: Add a second local Distribution replica with the identical real-RGW config and HTTP secret, then prove a blob upload started on replica 1 can continue on replica 2 after replica 1 stops and that selected manifests remain readable from both endpoints. Do not claim host-level HA from a same-VM test.

### 2026-07-22 — Same-VM Distribution replica state sharing completed

- Completed: Added `make -C poc/rgw verify-distribution-ha`, which starts a temporary second pinned Distribution process on port 5444 with the exact same RGW configuration, public TLS material, and persistent HTTP secret as the primary process.
- Upload-resume evidence: Uploaded the first 1 MiB of a unique 2 MiB blob through replica 1, received the upstream signed upload Location state, stopped replica 1, changed only the Location authority to replica 2, and finalized the remaining 1 MiB there with HTTP 201. The blob returned 200 on replica 2 and on replica 1 after restart.
- Visibility evidence: Before the interrupted upload, the selected integrated manifest returned the same expected digest from both replica endpoints. Cross-process resume proves that the shared HTTP secret and RGW upload state are compatible for this pinned release.
- Security/cleanup: Logs from both processes matched none of the S3/HTTP-secret values or JWT shapes. The second container is removed on every exit and the primary is restarted on failure. The unique unreferenced test blob remains in the disposable bucket for the next GC observation; no destructive cleanup was run.
- Boundary: Both processes share one VM, network, filesystem, and RGW endpoint and were manually selected rather than placed behind a load balancer. This is process-level shared-state evidence, not separate-host, load-balancer, RGW-HA, or physical-failure-domain acceptance.
- Changed files: Added the guest/host HA verifiers and Make target, updated the RGW README, this plan, and the handoff.
- Next exact action: Inspect the installed Ceph Tentacle 20.2.2 RGW encryption/KMS configuration schema and running daemon support read-only, then document the exact backend/key/TLS bindings that require operator approval before changing the security boundary.

### 2026-07-22 — Tentacle RGW KMS capability inspection completed

- Live evidence: Tentacle 20.2.2 exposes SSE-KMS backends `barbican` (default), `vault`, `kmip`, and `testing`; `rgw_crypt_require_ssl` defaults true. The filtered live config contains no KMS/Barbican/Vault/KMIP override. The pinned release does not expose the later `rgw_crypt_sse_algorithm` selector.
- Distribution seam: The upstream S3 driver supports `encrypt: true` and `keyid`, while the existing RGW path already enforces verified HTTPS, SigV4, path-style requests, a private bucket, and no client redirects.
- Decision framing: `docs/research/m3-rgw-kms-capability.md` recommends Barbican for OpenStack-native evidence, Vault only as generic RGW encryption evidence, and KMIP only with an existing approved PKI/service. The `testing` backend is inadmissible.
- Safety: This inspection read only option names/help and filtered configured option names; it printed no config values or secrets and changed no daemon, endpoint, key, credential, or security boundary.
- Blocker: Barbican is absent from the deliberately Keystone-only DevStack, and no approved Vault/KMIP endpoint or key exists. Selecting/deploying a backend, handling its credentials, restarting RGW, and inducing outage/key failures require explicit operator approval.
- Next exact action: Obtain the user's backend decision and deployment authority: choose Barbican for OpenStack-native M3-B evidence, Vault for a narrower RGW functional test, or provide an existing KMIP endpoint. Do not create a KMS service/key or alter RGW until that choice is explicit.

### 2026-07-22 — Final consistency and lab-safety verification completed

- Code and configuration: `uv lock --check`, the 70-test suite, Python compilation, all PoC Bash syntax, full PoC ShellCheck, both Compose models, and all Make target dry runs passed. Three pre-existing ShellCheck findings and one trailing space were corrected without changing harness behavior.
- Documentation and hygiene: 36 Markdown files passed balanced-fence and local-link checks; all three Mermaid diagrams rendered through local Chrome and were visually inspected; repository-owned paths passed Gitleaks and private-key/JWT scans; no trailing whitespace remains.
- Restored lab state: `coffer-devstack` is stopped. The RGW guest has no integration directory, temporary GC container, or second Distribution container; the baseline Distribution alone is running and returns CA-verified HTTP 200. Ceph reports only the deliberate one-OSD no-replica warning, and no KMS option is configured.
- Private runtime state: finite Keystone credentials, signing and TLS private keys, the integration SQLite database, and guest auth/JWKS integration state are absent. Retained redacted evidence and public CA/JWKS material remain only under ignored `work/` paths.
- Next exact action: Obtain the user's KMS backend/deployment authorization and quota ADR 0009 decision. No KMS service, key, RGW encryption setting, quota gateway, destructive GC, commit, or push was performed.

## Failures, Blockers, and Risks

- The disposable real Keystone, Ceph/RGW, integrated token, GC dry-run, and same-VM Distribution shared-state evidence is complete. An approved real KMS backend/key and separate-host/shared-control-state evidence remain required for broader acceptance.
- Docker credential storage behavior requires an OS credential helper before the application-credential path is considered safe for routine use.
- Distribution/RGW compatibility and GC semantics may force version constraints or a narrower production topology.
- Strict physical-byte quota enforcement may require storage isolation or a later gateway design; the MVP promises only a measured bounded soft quota.
- The pinned Distribution v3.1.1 Linux ARM64 image currently fails the prospective production vulnerability gate with 8 Critical and 9 High Scout findings.
- Distribution v3.1.1 does not expose the OCI 1.1 native Referrers endpoint in this configuration; client fallback works, but native API support remains an upstream/version selection gate.
- The Mac lab proves the real control-API middleware, token-broker HTTP/TLS, service-token enforcement, outage handling, and complete role/lifecycle matrix. Its Coffer database and two-second cache are process-local fixtures; shared production SQL/memcache and multi-worker consistency remain deployment gates.
- A standard application-credential auth response cannot prove that the underlying credential has a configured future expiration. Accepted ADR 0008 keeps this as a provisioning and lifecycle-regression gate rather than expanding Coffer's Keystone privileges.
- Application credentials with Keystone access rules fail closed in the PoC. Supporting them requires exact `oci-registry` service/method/path enforcement and real-environment evidence; role checks must never override those delegated restrictions.
- The local overlapping-JWKS check does not prove multi-replica trust rollout, signer transition, old-key retirement, or rollback. Distribution v3.1.1 requires a restart or recreation to reload local trusted keys.

## Handoff

- Current state: Active; the real Keystone-to-Coffer-to-Distribution-to-RGW vertical slice, repeated clean execution, single-process observability, GC dry-run, and same-VM cross-process upload resume have passed. The lab is restored to its secret-free baseline.
- Exact next action: Obtain a KMS path decision and deployment authority, then review proposed quota ADR 0009 before implementing either security-boundary or edge-path change.
- First file or command after approval: follow the selected binding checklist in `docs/research/m3-rgw-kms-capability.md`; do not alter RGW before the backend, endpoint/CA, key, and credential-delivery boundary are explicit.
- Questions requiring user input: choose Barbican, Vault, or an existing KMIP service for KMS evidence; accept ADR 0009, remove the bounded quota promise, or choose project-isolated registry/storage topology.
