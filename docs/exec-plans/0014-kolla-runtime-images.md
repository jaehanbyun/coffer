---
title: "Kolla runtime entry points and images"
status: completed
updated: 2026-07-24
owner: primary-agent
---

# Objective

Complete Stage 2 of the Kolla journey by turning the existing Coffer API,
quota-edge, reconciliation, and Alembic seams into installed product entry
points and locally verified Kolla-compatible image artifacts. Implement the
accepted ADR 0014 process, port, routing, TLS, privilege, configuration,
health, logging, and secret-recipient boundaries without creating a VM,
installing a Kolla-Ansible role, using production credentials, publishing an
image, or deploying on `bb00`.

## Done Criteria

- [x] Installed `coffer-api`, `coffer-edge`, `coffer-reconcile`, and
      `coffer-bootstrap` commands have stable configuration and exit contracts;
      API and edge bind to the ADR 0014 default ports and normal startup
      validates the current Alembic schema.
- [x] `coffer-edge` is a closed router: `/v1/` and `/auth/token` reach only the
      API upstream, `/v2/` reaches only unmodified Distribution, manifest PUT
      cannot bypass admission, encoded/unknown/operational public paths fail
      closed, and streamed bodies/responses remain bounded.
- [x] Edge-to-API and edge-to-Distribution HTTPS validate CA and hostname;
      plaintext requires an explicit loopback-only fixture switch. TLS,
      transport, SQL, and malformed-configuration failures are deterministic,
      secret-safe, and fail closed.
- [x] A Coffer-owned Kolla image template runs all four Coffer commands as a
      non-root `coffer` user through `kolla_start` and the read-only
      `/var/lib/kolla/config_files/config.json` contract, with explicit file
      ownership/modes, stdout logging, health checks, CA injection, and no
      baked credential.
- [x] An unmodified Distribution artifact strategy is pinned to an official
      supported release and Kolla runtime contract without silently accepting
      the previously blocked upstream image; exact digest, vulnerability, and
      functional results are recorded honestly.
- [x] The locally available architecture builds and starts the generated
      artifacts, proves non-root identity, read-only configuration,
      health/readiness, bootstrap repeat safety, TLS routing, graceful restart,
      and zero secret/runtime residue. Cross-architecture and extra-distro
      claims are limited to what was actually verified.
- [x] Focused and full Python tests, lock/compile, installed CLI, container
      template/build, Markdown/local-link, secret, residue, and final diff
      checks pass; README, architecture, this plan, and `HANDOFF.md` agree.

## Non-goals

- Creating or modifying any VM, libvirt domain, remote host, Kolla-Ansible
  inventory, role, HAProxy configuration, Keystone service/user/endpoint,
  MariaDB database/user, RGW bucket/credential, Barbican secret, or production
  identity.
- Pushing images, commits, branches, issues, or reviews; publishing SBOMs,
  signatures, releases, packages, or registry content externally.
- Claiming x86_64, multi-distro, multinode, Galera, production load, key
  rotation, backup/restore, GC, SSE-KMS, or official Kolla upstream support
  without separate executed evidence.
- Closing the Distribution/Ceph production gates, choosing ADR 0013's
  live-comparison identity, or implementing the Stage 3 Kolla-Ansible role.

## Context and Evidence

- Accepted ADR 0014 fixes `coffer-api:8787`, sole-ingress
  `coffer-edge:8788`, private unmodified `coffer-registry:8789`,
  listenerless `coffer-reconcile`, and one-shot `coffer-bootstrap`.
- `src/coffer/wsgi.py` already composes control, token, and operational APIs,
  but only through an environment-selected WSGI factory and a hard-coded
  development Gunicorn file.
- `src/coffer/registry_proxy.py` streams registry traffic and isolates manifest
  admission, but accepts only one plaintext HTTP origin and is assembled only
  by `poc/quota/fixture_server.py`.
- `coffer-reconcile` is already installed. Alembic revision
  `0004_inventory_import` is the exact production schema authority; normal
  stores fail closed when it is absent or stale.
- Kolla's 2026.1 image contract uses `kolla_start` plus a read-only
  `/var/lib/kolla/config_files/config.json` to select the command and copy
  files with declared owner and permissions. Kolla supports custom external
  image templates derived from `openstack-base`.
- The local host is Apple ARM64. Docker is stopped; the existing Podman 5.6.0
  machine is stopped and has previously required a persistent PTY. Stage 2 may
  start and stop that existing disposable local runtime but must not recreate,
  reset, or mutate remote infrastructure.
- CNCF Distribution v3.1.1 remains the latest official stable release at plan
  activation. Its official image is still blocked by the recorded
  vulnerability findings, so latest-version status alone is not an acceptance
  result.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Keep Stage 2 local and artifact-focused; defer VM and Ansible integration to Stage 3/4 | Runtime and image defects should be isolated before deployment automation encodes them | Building the Kolla role or allocating a VM before product entry points exist | 2026-07-23 |
| Preserve one Coffer application image for API, edge, reconciliation, and bootstrap unless build evidence requires a split | The roles share one locked Python package while Kolla commands and mounted secret files preserve process/privilege separation | Four near-identical Python images; one container running multiple roles | 2026-07-23 |
| Keep Distribution code unmodified and evaluate a Kolla wrapper/build artifact separately from the blocked official runtime image | It preserves the data-plane decision while allowing an honest OS/package security boundary | Treating the current official image as production-safe because the tag is latest; forking Distribution | 2026-07-23 |
| Ship Kolla `Dockerfile.j2` templates as the deployable contract and use a separate disposable local contract image for Stage 2 evidence | The Coffer application derives from Kolla `openstack-base` and the minimal registry wrapper from Kolla `base`; no public 2026.1 base manifest was available to this checkout, while a local image can still exercise the exact `kolla_start`/`kolla_set_configs` contract without claiming an official Kolla build | Blocking all runtime evidence on an unpublished base tag; presenting a generic Containerfile as the Kolla artifact | 2026-07-23 |
| Install the official Distribution v3.1.1 release binary by architecture and verify its published checksum inside a Kolla wrapper | The official runtime image remains blocked by recorded findings, while the release binary keeps Distribution code unmodified and lets the wrapper OS/package set be scanned independently | Copying the binary from the blocked runtime image; rebuilding a fork; accepting an unverified download | 2026-07-23 |
| Set `USER coffer` and `USER registry` in the final templates | Kolla's `kolla_start` elevates only its configuration and CA-copy helpers with `sudo`; the final command then executes as the image user | Keeping the long-running process root and attempting an ad hoc command wrapper | 2026-07-23 |

## Tasks

- [x] Inspect Kolla `stable/2026.1` custom-image mechanics, current base-image
      manifests, Distribution release artifacts, and the local container
      runtime; record a minimal build strategy.
- [x] Add common WSGI process handling plus product API and bootstrap entry
      points with focused configuration/schema/exit tests.
- [x] Productize the edge factory, closed path router, separate API/registry
      upstreams, verified TLS contexts, health/readiness, and focused tests.
- [x] Add Kolla custom templates/config examples and a deterministic local
      build/smoke harness for Coffer and the pinned Distribution artifact.
- [x] Run focused container evidence and the full regression/documentation/
      secret/diff matrix, update durable docs, and close the plan.

## Progress Log

### 2026-07-23 — Stage 2 activated

- Completed: Recovered `AGENTS.md`, completed plan 0013, ADR 0014, the handoff,
  current dirty worktree, implementation seams, template, and local runtime
  state; activated a fresh Stage 2 plan before code changes.
- Evidence: Stage 1 changes remain uncommitted and pass `git diff --check`.
  Docker is unavailable, the existing Podman machine is stopped, and no remote
  or runtime mutation has occurred in this stage.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Inspect the OpenStack Kolla `stable/2026.1` custom-image
  source contract and the exact multi-architecture manifests for candidate
  Kolla base and Distribution v3.1.1 images, without pulling or building yet.

### 2026-07-23 — Runtime artifact strategy fixed

- Completed: Inspected Kolla `stable/2026.1` at commit
  `686c6d13dc1c31092b22c6c481e16a7329e935ea`, including its external
  `Dockerfile.j2` source-archive flow, `configure_user`, `kolla_start`,
  `kolla_set_configs`, CA installation, and service `USER` patterns.
- Evidence: Kolla's start script performs only configuration/project/CA setup
  through `sudo` and then executes `/run_command` as the image user. The
  operator contract remains the read-only
  `/var/lib/kolla/config_files/config.json`. Candidate public 2026.1
  `openstack-base` references returned authorization/not-found responses, so
  Stage 2 will validate the same pinned scripts in a disposable local contract
  image and will not claim a successful official-base build.
- Distribution evidence: v3.1.1 is still the latest stable release. Its OCI
  index is
  `sha256:bca24727f4002e51f959c18c42e816e4d1078198081a9837e16b8b7d7e43ebf8`;
  the `linux/amd64` and `linux/arm64` manifests are respectively
  `sha256:866e54060c8186016c0b8ea2a2dd35e86a561ef814d07b93d959d555ed625e80`
  and
  `sha256:2adb9970cf82a515f710f39a42d6cb350feadff425ba04f098ce545400fc9552`.
  The official image still defaults to root and remains security-blocked.
  The wrapper will instead verify the official release-tar checksum for the
  build architecture and retain the binary unchanged.
- Local runtime evidence: the host is Apple ARM64; Docker is unavailable and
  the retained Podman 5.6.0 machine is stopped. Live image checks will use one
  retained PTY and will stop the existing machine without recreation or reset.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Move the Alembic environment into the installed `coffer`
  package, update every source reference, and implement the repeat-safe
  `coffer-bootstrap` command with focused tests.

### 2026-07-23 — Installed schema bootstrap and API entry point complete

- Completed: Moved the complete Alembic environment under
  `src/coffer/migrations`, included its template and revisions in the wheel,
  and added installed `coffer-bootstrap` and `coffer-api` commands.
  `coffer-bootstrap` upgrades to the package's exact head, validates the whole
  repository/quota schema, is repeat-safe, and uses sysexits-compatible 75/78
  dependency/configuration outcomes without logging exception content.
- API contract: `coffer-api` builds the production control/token/operational
  application, defaults to private `127.0.0.1:8787`, and runs Gunicorn
  `gthread` through a common in-package server contract with fixed worker,
  timeout, graceful-shutdown, keepalive, stdout-error-log, no-access-log, and
  mode-027 defaults.
- Evidence: 33 focused API/bootstrap/migration/token/observability tests pass;
  Alembic reports `0004_inventory_import` as head; a built wheel contains
  bootstrap plus every migration asset; both installed command helps pass;
  compile, lock, and diff checks pass.
- Changed files: `alembic.ini`, `pyproject.toml`, `etc/gunicorn.conf.py`,
  migrations moved into `src/coffer/migrations/`, `src/coffer/bootstrap.py`,
  `src/coffer/runtime.py`, `src/coffer/api_runner.py`, `src/coffer/config.py`,
  `src/coffer/wsgi.py`, three exact-path PoC helpers, the quota runbook,
  `tests/test_bootstrap.py`, `tests/test_api_runner.py`, this plan, and
  `HANDOFF.md`.
- Next exact action: Replace `src/coffer/registry_proxy.py`'s single plaintext
  origin with two validated HTTP(S) origins and implement a product
  `coffer-edge` factory that closes every path outside `/v1`,
  `/auth/token`, and `/v2`.

### 2026-07-23 — Closed product edge and backend TLS complete

- Completed: Added installed `coffer-edge` on private bind port 8788, separate
  API and Distribution origin contracts, exact manifest-PUT admission, and a
  closed path dispatcher. `/auth/token` and `/v1` can reach only API, `/v2`
  can reach only Distribution, malformed manifest paths cannot fall through,
  residual encoding is rejected, and unknown plus public operational paths
  return a local 404 without touching either backend.
- TLS and failure contract: HTTPS origins use Python's verifying default
  context with CA and hostname validation. Plaintext requires an explicit
  switch and literal loopback origin; CA files on HTTP and non-loopback
  downgrade are rejected. Transport failures return a deterministic,
  aggregate-only 503/Retry-After response. Token realm/service/header values
  and credential-bearing origins fail validation.
- Streaming evidence: a 512 KiB request and response crossed the generic path
  without whole-body reads and with response chunks at or below 64 KiB. Hop
  headers are filtered while the external Host and authorization request
  semantics are preserved transiently.
- Evidence: 56 focused edge/proxy/quota/token/API/bootstrap/migration tests
  pass, including CA success, untrusted-CA failure, hostname-mismatch failure,
  API and registry TLS routes, outage closure, schema/JWKS startup, installed
  CLI help, compilation, and diff checks.
- Changed files: `src/coffer/config.py`, `src/coffer/edge_runner.py`,
  `src/coffer/registry_proxy.py`, `pyproject.toml`, the explicit plaintext
  quota fixture assembly, `tests/test_edge_runner.py`,
  `tests/test_registry_proxy.py`, this plan, and `HANDOFF.md`.
- Next exact action: Add final Kolla `Dockerfile.j2` templates and read-only
  config examples, then add a deterministic local contract-image harness that
  stages the pinned Kolla start/config/CA helpers for runtime evidence.

### 2026-07-23 — Kolla templates and local contract harness complete

- Completed: Added final Kolla Jinja templates deriving the Coffer application
  from `openstack-base` and the unmodified Distribution wrapper from `base`,
  five read-only role configuration examples, and a disposable local runtime
  harness using the exact pinned Kolla start/configuration/CA helpers.
- Artifact contract: the application roles run as UID/GID 53002 and
  Distribution as UID/GID 53003; Kolla copies declared configuration and
  secret recipients with explicit owner/mode; API, edge, registry,
  reconciliation, and bootstrap remain separate processes.
- Evidence: Pinned Kolla `stable/2026.1` lists and template-renders both
  artifacts. Bash parsing and ShellCheck pass. The ARM64 local build completed
  for both artifacts, all four installed command helps passed, and the
  Distribution v3.1.1 release checksum and version passed.
- Corrected failure: the first live run stopped at Docker Scout because this
  client rejects an absolute `archive:///...` input even after indexing the
  tarball. Cleanup removed the exact images/resources and stopped the Podman
  machine. The harness now invokes Scout from the repository with its
  documented relative `archive://...` form.
- Changed files: `docker/`, `poc/kolla-runtime/`, this plan, and
  `HANDOFF.md`.
- Next exact action: Rerun `make -C poc/kolla-runtime verify` in one retained
  PTY and either correct the first bounded runtime failure or record the
  complete image, TLS OCI, restart, scan, and zero-residue evidence.

### 2026-07-23 — Strict fixture certificate failure diagnosed

- Completed: Added secret-safe phase diagnostics and reproduced the initial
  edge challenge failure with a direct in-container HTTPS connection.
- Finding: Python 3.13's OpenSSL rejected the generated server chain with
  `Missing Authority Key Identifier`. Distribution's repeated Go
  `bad record MAC` messages were the server-side result of the verified client
  abort, not evidence of transport corruption. Offline issuer and hostname
  checks had passed because the host OpenSSL did not enforce this extension.
- Correction: The disposable CA and every server certificate now carry
  matching Subject Key Identifier and Authority Key Identifier extensions.
  The harness also disables Distribution's default localhost trace exporter,
  retains a bounded secret-safe failure diagnostic, and keeps exact cleanup.
- Next exact action: Rerun `make -C poc/kolla-runtime verify` with the default
  60-attempt health bound and continue to the first remaining failure or full
  pass.

### 2026-07-23 — Runtime contract passed; blob upload failure isolated

- Completed: The corrected strict-TLS run passed all service health, API
  readiness, edge challenge, non-root UID, copied owner/mode, read-only source
  configuration, custom-CA, private-Distribution, and empty reconciliation
  checks.
- Finding: The first blob finalize reached authenticated Distribution but
  carried a zero-byte body. Distribution correctly returned 400 because the
  canonical empty digest did not match the declared fixture digest. Moving
  `data-binary` out of curl's generated config reproduced the same failure,
  disproving the initial harness-only hypothesis and isolating the defect to
  the live edge request-body path.
- Root cause: A one-run secret-safe diagnostic proved curl uploaded 37 bytes
  and edge forwarded declared/actual totals of 37/37. The request nevertheless
  reached Distribution as `application/x-www-form-urlencoded`; curl assigns
  that media type to `--data-binary` by default. Distribution's Go form/query
  processing consumed that body before blob finalization, so the stored
  canonical digest was the empty digest.
- Correction: The OCI client step now sets
  `Content-Type: application/octet-stream`, as required for arbitrary blob
  content. The temporary debug setting, byte counter, and unnecessary proxy
  experiment were removed after diagnosis. The harness retains source-digest
  and curl byte-count assertions, disables ambient curlrc input, and keeps the
  bearer token only in its mode-0600 configuration file.
- Next exact action: Rerun `make -C poc/kolla-runtime verify` with the explicit
  OCI blob media type and complete manifest, restart, digest, log hygiene, and
  zero-residue evidence.

### 2026-07-24 — Complete local Kolla runtime contract passed

- Completed: Reran the default Stage 2 harness after setting the OCI blob
  request to `application/octet-stream`. The ARM64 application and unmodified
  Distribution wrapper images built from scratch and the full strict-TLS OCI
  path passed.
- Runtime evidence: API, edge, registry, one-shot bootstrap, and
  reconciliation ran as their declared non-root users; Kolla copied
  configuration and CA files with the declared owner/mode from read-only
  sources; Distribution remained private; API readiness and the external edge
  challenge passed; authenticated blob and manifest publication succeeded;
  the manifest digest remained byte-identical after all long-running
  containers restarted; bootstrap was repeat-safe; and reconciliation
  completed against the current schema.
- Security and cleanup evidence: source digest and curl byte counts matched,
  logs contained none of the fixture secrets or JWT-shaped values, exact
  containers/volumes/network/images and generated secret material were
  removed, the failure summary is absent, and the retained Podman machine is
  stopped.
- Image evidence: the saved SBOMs contain 261 packages for Coffer and 293 for
  the Distribution wrapper. The bounded current scan reports 1 Critical and
  4 High findings for Coffer and 9 Critical and 12 High findings for the
  wrapper, so these artifacts remain production-blocked despite functional
  success.
- Next exact action: Run the complete Python 3.11/3.12/3.13 regression matrix,
  followed by lock, Alembic, CLI, Bash/ShellCheck, Kolla render, Compose/Make,
  Markdown, secret, and diff checks.

### 2026-07-24 — Stage 2 final verification and closure

- Completed: 222 tests passed independently on Python 3.11.14, 3.12.13, and
  3.13.14. Lock, compilation, Alembic head `0004_inventory_import`, all seven
  installed CLI helps, wheel migration assets/entry points, and Go
  1.25.3 format/test/vet passed.
- Artifact/static evidence: 58 Bash files passed syntax and ShellCheck; six
  Compose models parsed; every declared PoC Make target dry-ran; pinned Kolla
  commit `686c6d1` listed and rendered both final templates; five config
  templates rendered to ten valid CA-on/off JSON contracts; and the local
  runtime evidence remained clean with Podman stopped.
- Documentation/security evidence: 65 Markdown files and 42 local links
  passed, 252 project-owned files passed Gitleaks, explicit private-key,
  access-key, and JWT-shaped scans passed, generated build output was removed,
  and `git diff --check` passed.
- Corrected verification failures: parallel `uv run` calls collided on the
  shared `.venv`, so all Python versions were rerun sequentially; Go was first
  invoked from the wrong module/root and with the host's Go 1.19, then passed
  from `poc/inventory` with the already configured mise Go 1.25.3; Kolla's
  isolated invocation needed its Docker Python extra and source `PYTHONPATH`;
  and Gitleaks' only hit was the literal container name assigned to
  `API_CONTAINER`, resolved without an allow rule by renaming the internal
  variable to `CONTROL_CONTAINER`.
- Documentation now distinguishes local contract-image evidence from an
  unavailable official Kolla 2026.1 base build and keeps the current
  Critical/High findings as production blockers. No VM, remote host,
  credential, external publication, commit, or push was performed.
- Next exact action: None in this completed plan. If the user authorizes Stage
  3, create a new execution plan before implementing an operator-local
  Kolla-Ansible role.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 1 recovery | Sources of truth, Git status, recent commits, diff check | passed |
| Focused Python and installed CLIs | Pytest/compile/help/startup | API/bootstrap passed: 33 tests, wheel contents, Alembic head, two helps, compile/lock |
| Edge routing and TLS | In-process plus private TLS integration tests | passed: closed dispatch, non-bypass, bounded streaming, CA/hostname success/failure, 503 closure |
| Kolla source contract | Pinned read-only source inspection and manifest queries | passed at Kolla commit `686c6d1`; public 2026.1 base unavailable, local contract-image strategy recorded |
| Kolla template and image | Generate/build/start/non-root/config/health | passed: templates render, both ARM64 images build, all role contracts and strict-TLS OCI/restart flow pass |
| Distribution artifact | Release/image pin, wrapper build, scan, smoke | passed as functional/evidence generation: checksum/version, private runtime, blob/manifest/restart digest, 293-package SBOM; production blocked by 9 Critical/12 High scan findings |
| Full regression and docs | Cross-version tests, lock, Markdown, secret, diff | passed: 222 tests per supported Python; package/Go/Bash/Compose/Make/Kolla/JSON/Markdown/Gitleaks/diff matrix |
| Runtime residue | Local container engine state and generated secrets | passed: exact cleanup assertions, no failure summary, Podman stopped |

## Failures, Blockers, and Risks

- The Stage 1 worktree is intentionally uncommitted. Stage 2 must preserve and
  distinguish those documentation changes; no cleanup, reset, or unrelated
  rewrite is authorized.
- The local Podman lifecycle can terminate with a non-persistent shell. Use one
  retained PTY, stop it explicitly, and do not recreate or reset its VM.
- Distribution v3.1.1 being latest does not clear the existing image security,
  malformed-reference, native-Referrers, or Ceph zero-byte SSE-KMS gates.
- No public Kolla 2026.1 `openstack-base` manifest was available during source
  inspection. The final template can be syntax/render checked locally, but a
  real official-base build remains Stage 3 evidence unless a trusted base
  reference becomes available.
- `coffer-edge` is on the OCI streaming hot path. Accidental buffering,
  authorization-header retention, open proxying, TLS downgrade, or public
  operational endpoints are release-blocking defects.

## Handoff

- Current state: Complete; every Stage 2 done criterion and final verification
  row passes. Production and official Kolla/AIO claims remain explicitly
  blocked.
- Exact next action: None in Stage 2. If Stage 3 is authorized, first create a
  new execution plan for the operator-local Kolla-Ansible role.
- Questions requiring user input: Authorization is required before Stage 3,
  remote VM work, credentials, publication, commit, or push.
