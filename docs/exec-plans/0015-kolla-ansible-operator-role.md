---
title: "Operator-local Kolla-Ansible role"
status: complete
updated: 2026-07-24
owner: primary-agent
---

# Objective

Complete Stage 3 by implementing a Coffer-owned companion Kolla-Ansible role
that encodes the accepted five-process topology and can exercise the normal
`prechecks`, `deploy`, `reconfigure`, `pull`, `upgrade`, and `stop` lifecycle
without modifying Kolla-Ansible itself. Validate database bootstrap, proposed
Keystone `oci-registry` registration, HAProxy routing, configuration and secret
recipient boundaries, logging, handlers, and exact cleanup in an isolated
non-production target. Do not install directly on `bb00`, reuse its existing
Harbor/HAProxy/VM workloads, publish artifacts, or claim the Stage 4 OCI
end-to-end gate.

## Done Criteria

- [x] Pin and record one exact Kolla-Ansible `stable/2026.1` source commit and
      derive the companion role layout from its current service contracts,
      including inventory, service definitions, common container tasks,
      HAProxy, database, Keystone registration, bootstrap, handlers, logging,
      and lifecycle actions.
- [x] The role has an explicit `enable_coffer` gate, Coffer inventory group,
      five service/process definitions, operator-overridable images/ports, and
      deterministic configuration validation. No tenant route can address
      `coffer-api:8787` or `coffer-registry:8789` directly.
- [x] Database/user creation and one-shot `coffer-bootstrap` are separated from
      normal process startup; bootstrap is repeat-safe, runs before new
      application processes, and failure stops the rollout without automatic
      Alembic downgrade.
- [x] The proposed Keystone `oci-registry` service and public/internal/admin
      endpoints, HAProxy frontend/backends and health checks, service
      configuration, Fluentd/logrotate/Prometheus inputs, handlers, and
      `deploy`, `reconfigure`, `pull`, `upgrade`, and `stop` actions render and
      execute through the pinned Kolla-Ansible contract.
- [x] Secret recipients remain disjoint. The role consumes owner-controlled
      mode-`0600` materialized files, never stores secret values in ordinary
      inventory or command lines, and does not create/select the unresolved
      production reconciliation/live-comparison identity.
- [x] Local syntax/lint/render/idempotency/negative prechecks pass, including
      disabled-mode no-op, port collision, missing file, unsafe permission,
      invalid endpoint/TLS, bootstrap failure, and direct-registry-bypass
      rejection.
- [x] Any live validation uses a separately named, autostart-disabled,
      non-production VM with dedicated resources and exact cleanup. It does
      not mutate `bb00` directly or reuse unrelated domains, host HAProxy,
      Harbor, or ports 80/443.
- [x] Focused and full repository regressions, documentation/local-link,
      secret, residue, and final diff checks pass; architecture, README, this
      plan, and `HANDOFF.md` agree on what Stage 3 does and does not prove.

## Non-goals

- Stage 4 two-project Docker/Podman/ORAS push/pull, restart persistence,
  idempotent full Kolla AIO deployment, or production catalog acceptance.
- Multinode/HA, Galera behavior, load testing, rolling key rotation,
  backup/restore, destructive GC, production SSE-KMS, or release promotion.
- Upstream changes to `openstack/kolla` or `openstack/kolla-ansible`, Zuul
  jobs, governance proposals, issues, pull requests, reviews, releases, image
  publication, commit, or push.
- Installing Coffer/Kolla packages directly on `bb00`, changing its existing
  HAProxy/Harbor configuration, or mutating `coffer-rgw-poc`, `dev11-*`, or any
  unrelated domain.
- Creating or selecting a production reconciliation/live-comparison identity
  or placing credentials in Git, plans, handoffs, command lines, logs, or
  ordinary inventory variables.

## Context and Evidence

- Accepted ADR 0014 fixes private `coffer-api:8787`, sole-ingress
  `coffer-edge:8788`, private unmodified `coffer-registry:8789`,
  listenerless `coffer-reconcile`, and one-shot `coffer-bootstrap`.
- Completed plan 0014 supplies installed product commands, packaged Alembic
  revisions, verified backend TLS, final Kolla templates/config contracts, and
  local non-root runtime evidence. Official Kolla-base builds and current
  Critical/High image findings remain explicit blockers for production.
- Stage 3 pins the refreshed official Kolla-Ansible `stable/2026.1` source at
  commit `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`. The ignored,
  disposable checkout is `work/kolla-ansible-stage3`; no upstream source is
  vendored into Coffer.
- `bb00` is a shared KVM host with occupied host 80/443 and unrelated
  workloads. It is only a virtualization substrate for a separately named VM,
  never the direct deployment target.
- Kolla's bootstrap image registry and Coffer's tenant registry remain
  independent. The existing Harbor deployment is not an implicit dependency.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Keep the role in the Coffer repository as an operator-local companion until its contract is proven | It permits rapid validation without coupling an unproven service to Kolla governance or release cadence | Editing Kolla-Ansible directly; opening upstream work before local lifecycle evidence | 2026-07-24 |
| Treat Stage 3 as role/lifecycle evidence and reserve tenant OCI behavior for Stage 4 | It preserves the accepted stage boundary while still requiring executable deployment automation | Claiming AIO/product completion from syntax-only checks; expanding directly into multinode/HA | 2026-07-24 |
| Require an isolated, autostart-disabled VM for any live execution | The shared host and its existing HAProxy/Harbor/domains must remain untouched | Direct host install; reusing an unrelated VM or host ports 80/443 | 2026-07-24 |
| Use Kolla's custom-playbook CLI contract with a Coffer-owned wrapper, playbook, and role | The 2026.1 CLI passes the normal lifecycle action into a user-supplied playbook; a wrapper can expose the pinned upstream roles, modules, action plugins, and filters without patching or vendoring Kolla-Ansible | Forking `site.yml`; copying generic roles into Coffer; requiring operators to hand-assemble Ansible search paths | 2026-07-24 |
| Reuse pinned generic roles for service prechecks, image pull, container comparison/stop, Keystone registration, and HAProxy generation | These are current Kolla contracts and keep the companion role small while preserving lifecycle behavior | Reimplementing Kolla container or OpenStack registration modules; shelling out to Docker/OpenStack CLIs | 2026-07-24 |

## Tasks

- [x] Inspect and pin the exact Kolla-Ansible `stable/2026.1` role contract,
      then record the minimal companion integration strategy.
- [x] Implement inventory/defaults/service definitions, prechecks,
      configuration, database/Keystone/bootstrap, HAProxy, logging, handlers,
      and lifecycle actions.
- [x] Add a deterministic local role-contract harness with positive,
      idempotency, and fail-closed negative cases.
- [x] If local gates pass, provision or select only the approved isolated
      validation VM and run bounded lifecycle evidence without Stage 4 claims.
- [x] Run the final regression/documentation/secret/residue/diff matrix and
      close the plan.

## Progress Log

### 2026-07-24 — Stage 3 activated

- Completed: Recovered `AGENTS.md`, completed plan 0014, the durable handoff,
  current uncommitted Stage 1/2 worktree, and the accepted topology; activated
  a separate Stage 3 plan after the user's approval.
- Evidence: No remote command, VM change, credential operation, publication,
  commit, or push has occurred in Stage 3.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Fetch the official Kolla-Ansible `stable/2026.1` source
  read-only into a disposable directory, pin its exact commit, and inspect the
  smallest representative services covering database, Keystone, HAProxy,
  bootstrap, logging, handlers, and every required lifecycle action.

### 2026-07-24 — Pinned Kolla contract and target capacity

- Completed: Cloned official OpenDev Kolla-Ansible `stable/2026.1` read-only
  into the ignored `work/kolla-ansible-stage3` checkout and pinned commit
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`. Inspected the custom-playbook
  CLI, current `cloudkitty` service role, generic precheck/container/image/
  stop/Keystone/HAProxy roles, logging and Prometheus extension points, and
  all required lifecycle action files.
- Decision: Ship one Coffer-owned wrapper that discovers the installed Kolla
  data path, sets the upstream role/module/plugin search paths, and invokes
  the normal `kolla-ansible` action with Coffer's custom playbook. The
  playbook loads pinned Kolla defaults before applying the companion role.
  No upstream source is copied or modified.
- Evidence: A fresh read-only host inventory found 64 logical CPUs, about
  251.5 GiB total RAM with about 125.6 GiB currently available, about
  896 GiB available in the XFS-backed Coffer pool, 18 running domains,
  82 allocated vCPUs, and 244 GiB maximum guest memory. The existing
  `coffer-rgw-poc` remains running with eight vCPUs, 24 GiB RAM, and
  autostart disabled. Capacity is sufficient for a bounded overcommitted
  lab candidate, but no VM was created, selected, stopped, or changed.
- Failure: One attempted read-only audit command accidentally contained an
  autostart-changing subcommand. The execution policy rejected the entire
  command before SSH ran. A corrected pure read-only query then confirmed
  the existing domain's autostart remains disabled.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Create `ansible/roles/coffer/defaults/main.yml` with the
  enable gate, five process definitions, images, ports, health checks,
  private/public HAProxy contract, database/Keystone models, disjoint secret
  source paths, and observability extension inputs.

### 2026-07-24 — Companion role and local lifecycle contract

- Completed: Added the Coffer custom playbook and wrapper, the operator-local
  role, fixed API/edge/Distribution/reconcile/bootstrap service model,
  database and proposed Keystone registration, verified-TLS HAProxy inputs,
  owner-only secret materialization, observability extensions, handlers, and
  all required lifecycle action files. Reconciliation remains explicitly
  disabled until an accepted production identity provider exists.
- Completed: Added a disposable local contract harness derived from the pinned
  Kolla modules and filters. It records only bounded safe events, normalizes
  macOS network facts outside the product role, and removes all generated
  credentials, certificates, configs, and state in a `finally` block.
- Evidence: `make -C poc/kolla-ansible-role verify` passed 48 checks. It
  covered seven lifecycle syntax checks, disabled-mode no-op, missing and
  mode-0644 secrets, plaintext RGW, disabled backend TLS, occupied port,
  direct-registry bypass, bootstrap failure before service rollout, successful
  database/bootstrap/process ordering, `oci-registry` plus three endpoints,
  edge-only external routing, verified backend TLS, per-process secret
  recipients, config validation, and idempotent reconfigure/pull/stop.
- Evidence: Ansible lint passed its production profile with zero failures and
  warnings; Jinja and 25 YAML files parsed; 19 focused config/API/edge/bootstrap
  tests passed; the contract work directory was absent after success and after
  the first intentionally failed harness run.
- Failures corrected: The executable contract exposed and closed a JWKS
  mapping-method collision, macOS/Linux network-fact difference, missing
  standalone Fluentd/logrotate defaults, premature logrotate Jinja rendering,
  and the direct-Ansible stop input normally injected by the Kolla CLI. One
  sandboxed HAProxy readiness wait was interrupted cleanly before rerunning
  with bounded loopback permission.
- Changed files: `ansible/`, `poc/kolla-ansible-role/`,
  `src/coffer/config_validator.py`, `tests/test_config_validator.py`, and the
  installed entry point in `pyproject.toml`, plus this plan and `HANDOFF.md`.
- Next exact action: Recheck the shared host and domain namespace read-only,
  then create a separately named, autostart-disabled Stage 3 validation VM
  only if the planned name, storage, network, and capacity remain isolated.

### 2026-07-24 — Isolated Linux lifecycle evidence

- Completed: Rechecked the shared host read-only, then created only
  `coffer-kolla-stage3` with eight x86_64 vCPUs, 24 GiB RAM, a 120 GiB
  writable overlay and dedicated base/seed volumes in the existing
  `coffer-rgw` pool, static default-NAT address, and autostart disabled. Host
  HAProxy, Harbor, ports 80/443, DHCP configuration, `coffer-rgw-poc`, and
  every unrelated domain were untouched.
- Evidence: Cloud-init completed; the guest reported x86_64, eight CPUs,
  about 23 GiB RAM, 116 GiB root, the intended static address, passwordless
  scoped sudo, and an active qemu guest agent.
- Evidence: `make -C poc/kolla-ansible-role verify-remote` passed from the Mac
  controller through the user-supplied jump path. It used upstream Kolla's
  Linux address filter, passed precheck, deploy, idempotent reconfigure, pull,
  upgrade and stop, proved bootstrap-before-process ordering and mode-0600
  target files, and removed both root-owned contract state and user-owned
  Ansible temporary state.
- Failures corrected: The first create attempt rejected a backing file outside
  the pool before defining a domain; cleanup left no residue, so the script
  now uploads a dedicated copied base. The first guest used only one of the
  jump account's allowed public keys and was recreated with the complete
  public-key list, without reading a private key. Three remote-contract tries
  then corrected a macOS remote-temp path, root/user temp ownership, and Kolla
  base-role HAProxy directory prerequisites. Every failed attempt ran exact
  scoped cleanup.
- Cleanup: Destroyed and undefined only `coffer-kolla-stage3`, deleted only its
  seed/root/base volumes, and removed temporary known-host files. A final
  read-only audit found no matching domain or volume, restored the domain
  count to 18, retained `coffer-rgw-poc` running with autostart disabled, and
  found about 125 GiB available host RAM and 878 GiB free in `/srv/nfs`.
- Changed files: Added the reproducible VM provision/destroy script and remote
  contract verifier under `poc/kolla-ansible-role/`, plus this plan and
  `HANDOFF.md`.
- Next exact action: Run the complete focused and repository-wide regression,
  documentation/local-link, secret, residue, and diff matrix, then reconcile
  README, architecture, plan, and handoff before closing Stage 3.

### 2026-07-24 — Stage 3 final verification and closure

- Completed: Hardened the operator wrapper to preserve Kolla's action-first
  CLI order, inject only the Coffer playbook and search-path variables, and
  refuse destructive or unrelated Kolla actions. The local contract now
  verifies both argument order and refusal behavior.
- Product evidence: 232 tests passed independently on Python 3.11.14,
  3.12.2, and 3.13.14. Offline lock validation, Python compilation, Alembic
  head `0004_inventory_import`, eight installed CLI helps, Go format/test/vet,
  six Compose models, and 58 Make target dry-runs passed.
- Role and documentation evidence: The 48-check local lifecycle contract,
  production-profile Ansible lint, Jinja and 25 YAML parses, and the already
  completed isolated Linux lifecycle passed. Bash syntax and ShellCheck passed
  for 61 files; 65 Markdown files and 44 local links passed structural checks.
- Security and cleanup evidence: Gitleaks passed over 299 existing
  project-owned files; explicit private-key, JWT-shaped value, and supplied
  SSH-target scans passed; local role work, Ansible temp, UV cache, validation
  VM, volumes, and known-host residue are absent; `git diff --check` passed.
- Corrected verification failures: The first wrapper smoke placed global
  Kolla options after the action and was replaced by an exact fake-binary
  argument contract. One private-key scan omitted the `--` pattern separator;
  that result was rejected and the corrected scan passed.
- Changed files: `ansible/`, `poc/kolla-ansible-role/`,
  `src/coffer/config_validator.py`, `tests/test_config_validator.py`,
  `pyproject.toml`, README, architecture, this plan, and `HANDOFF.md`.
- Next exact action: None in Stage 3. Stage 4 requires a new execution plan and
  explicit authorization before provisioning a full Kolla AIO tenant path.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Recovery and plan boundary | Sources of truth, Git status/log, completed Stage 2 plan | passed |
| Pinned Kolla-Ansible contract | Official `stable/2026.1` commit `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`; CLI and representative/generic role inspection | passed |
| Companion role | Production-profile Ansible lint; Jinja/YAML; 48-check contract harness | passed |
| Lifecycle | precheck/deploy/reconfigure/pull/upgrade/check/stop with failure and idempotency cases | passed |
| Registration and routing | Database/bootstrap order, proposed Keystone service/endpoints, edge-only HAProxy, verified TLS, observability | passed |
| Isolated target | Autostart-disabled x86_64 VM; upstream Linux-filter lifecycle; exact VM, volume, guest-temp and local-temp cleanup | passed |
| Full regression and docs | Python/Bash/Ansible/Markdown/secret/diff | passed: 232 tests per supported Python; 48 role checks; package/Go/Compose/Make/Ansible/Jinja/YAML/shell/Markdown/Gitleaks/residue/diff matrix |

## Failures, Blockers, and Risks

- The Stage 1/2 worktree is intentionally uncommitted. Stage 3 must preserve
  those changes and avoid destructive cleanup or unrelated rewrites.
- No public official Kolla 2026.1 base image was available during Stage 2, and
  the local contract artifacts have unresolved Critical/High findings.
  Role/lifecycle evidence must not be presented as production image approval.
- `coffer-edge` is the OCI hot path. HAProxy or inventory configuration that
  exposes API/registry backends, weakens backend TLS, or bypasses manifest
  admission is release-blocking.
- The production reconciliation credential/provider remains unresolved. Stage
  3 must not invent one to make the role appear complete.

## Handoff

- Current state: Complete; every Stage 3 done criterion and verification row
  passes. The isolated Linux target and all Stage 3 temporary state were
  removed exactly.
- Exact next action: None in Stage 3. If Stage 4 is authorized, create a new
  execution plan for full Kolla AIO deployment and tenant OCI acceptance.
- Questions requiring user input: Authorization is required before Stage 4,
  credentials, external publication, commit/push, or any new remote mutation.
