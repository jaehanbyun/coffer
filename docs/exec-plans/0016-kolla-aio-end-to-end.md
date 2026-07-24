---
title: "Kolla AIO end-to-end tenant OCI acceptance"
status: completed
updated: 2026-07-24
owner: primary-agent
---

# Objective

Complete Stage 4 by deploying one disposable, isolated x86_64 Kolla-Ansible
2026.1 AIO and the Coffer companion role, then prove the real catalog,
database/bootstrap, HAProxy/edge, Keystone identity, external Ceph RGW, and OCI
client path as one repeatable system. The acceptance result must demonstrate
two-project isolation, edge non-bypass, restart persistence, repeat-safe
migration, idempotent reconfiguration, secret-safe evidence, and exact cleanup.

## Done Criteria

- [x] Pin the AIO to the recorded Kolla-Ansible 2026.1 commit and deploy only
      into a separately named, autostart-disabled VM with dedicated storage and
      address allocation. Existing `bb00` services, HAProxy, Harbor, ports,
      networks, and unrelated domains remain unchanged.
- [x] Kolla `bootstrap-servers`, `prechecks`, and `deploy` complete, and the
      resulting AIO has working Keystone, MariaDB, HAProxy, container runtime,
      and the minimum supporting OpenStack control-plane services required by
      the deployment profile.
- [x] Kolla-compatible x86_64 Coffer and unmodified Distribution artifacts are
      built or resolved from pinned inputs, scanned, and deployed through the
      companion role without using the tenant Coffer registry as its own
      bootstrap image source.
- [x] The proposed Keystone `oci-registry` service and public/internal/admin
      endpoints exist; API and Distribution backends are private, the external
      path crosses `coffer-edge`, and a tenant-reachable direct-backend bypass
      test fails.
- [x] Two finite Keystone project identities exercise Docker, Podman, or ORAS:
      project A creates a repository and pushes/pulls one deterministic OCI
      artifact; project B cannot read, mount, overwrite, or delete project A's
      repository. No credential or bearer token enters Git or retained logs.
- [x] The accepted artifact digest survives restart of API, edge,
      Distribution, and relevant Kolla infrastructure; repeat migration is a
      no-op; two consecutive Coffer/Kolla reconfigure runs report no
      unintended change; service catalog and client behavior remain correct.
- [x] Failure attempts, disposable identities, generated keys/configuration,
      client auth state, containers, networks, VM, volumes, temporary files,
      and known-host entries are removed exactly. Focused and repository-wide
      regression, documentation, secret, residue, and diff checks pass.

## Non-goals

- Multinode or HA topology, replica loss, Galera failover, rolling upgrade,
  key-overlap rotation, backup/restore, destructive GC, load testing, or
  production promotion.
- Reusing host HAProxy/Harbor, exposing host ports 80/443, changing
  `coffer-rgw-poc`, or installing Kolla/Coffer packages directly on `bb00`.
- Upstream Kolla/Kolla-Ansible changes, Zuul jobs, governance proposals,
  issues, pull requests, releases, or production image publication.
- Treating unresolved Distribution/Ceph/KMS findings or locally built images
  as production-approved artifacts.

## Context and Evidence

- Accepted ADR 0014 defines the five-process topology, sole-ingress edge,
  proposed service type, TLS/secret recipients, database/bootstrap order, and
  deployment isolation.
- Completed plan 0014 provides product entry points, packaged Alembic
  revisions, Kolla templates, and local image-contract evidence. Completed plan
  0015 provides the companion role and local/isolated Linux lifecycle evidence.
- The companion contract is pinned to official Kolla-Ansible `stable/2026.1`
  commit `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`.
- `bb00` is a shared KVM host. It is only a virtualization substrate. The
  existing external `coffer-rgw-poc` endpoint may be consumed only without
  mutating its service, identity, or current data.
- Kolla's bootstrap image registry and Coffer's tenant registry are separate.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Use one fresh, autostart-disabled x86_64 VM named `coffer-kolla-aio-stage4` | It isolates a destructive AIO lifecycle from shared host services and from the removed Stage 3 target | Direct host install; reuse of an unrelated domain | 2026-07-24 |
| Use an explicit non-production AIO backend profile while retaining TLS at the client origin and RGW boundary | ADR 0014 permits private AIO backend HTTP, while full backend TLS remains a production-stage gate | Claiming production TLS from a disposable single-node lab; exposing backend ports | 2026-07-24 |
| Build or import Coffer artifacts through a bootstrap registry path independent of the tenant registry | It avoids a circular dependency where Coffer must serve the image needed to start itself | Configuring Kolla to pull Coffer from the not-yet-running tenant registry | 2026-07-24 |
| Destroy the AIO after retained aggregate evidence passes | AIO is validation infrastructure, not a retained production service, and exact cleanup is an exit criterion | Leaving a privileged control plane or generated credentials running | 2026-07-24 |

## Tasks

- [x] Recheck shared-host capacity, namespace, network/address, and storage
      read-only; qualify exact AIO and Coffer image inputs.
- [x] Add a secret-safe reproducible Stage 4 provision/deploy/verify/cleanup
      harness with fail-closed cleanup.
- [x] Provision and bootstrap the isolated AIO VM, then deploy the pinned Kolla
      control plane.
- [x] Build/import Coffer artifacts and run the companion role through
      precheck/deploy/reconfigure.
- [x] Run catalog, two-project OCI, bypass, restart, migration, idempotency,
      secret, and residue acceptance.
- [x] Destroy exact Stage 4 resources, run final regressions, and close the
      plan and handoff.

## Progress Log

### 2026-07-24 — Stage 4 activated

- Completed: Published completed Stages 1 through 3 to `jaehanbyun/coffer`
  `main` as three scoped commits: topology `1d0e2f3`, runtime/images
  `85d8307`, and companion role `dc145ff`.
- Evidence: The active GitHub identity was `jaehanbyun`; local and remote
  `main` both resolved to `dc145ff` after the atomic push; the worktree was
  clean before this plan was created.
- Decision: Use a fresh `coffer-kolla-aio-stage4` target and destroy it after
  acceptance. Do not mutate the retained RGW VM or shared host services.
- Changed files: This plan and `HANDOFF.md`.
- Next exact action: Run a read-only `bb00` audit for the exact domain name,
  address, network, storage, CPU/RAM capacity, retained RGW endpoint, and
  current host service bindings; make no mutation until every target is free.

### 2026-07-24 — Isolated Kolla AIO deployed

- Completed: Audited the shared host; reserved only the free Stage 4 namespace;
  created autostart-disabled `coffer-kolla-aio-stage4` with 8 vCPUs, 32 GiB
  RAM, a 180 GiB root overlay, static management address, and a dedicated
  unnumbered external interface; pinned Ubuntu Noble by SHA-256 and
  Kolla-Ansible to commit
  `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`.
- Completed: Ran Kolla `bootstrap-servers`, `prechecks --use-test-images`,
  `pull`, and `deploy`. The final deploy recap was `ok=404`, `changed=259`,
  `failed=0`, `unreachable=0`; the Keystone, MariaDB, HAProxy, Glance,
  Placement, Nova, Neutron, Heat, RabbitMQ, Open vSwitch, logging, and support
  containers were running, and every container with a configured healthcheck
  was healthy.
- Evidence: The internal VIP was bound only inside the disposable guest;
  `GET /v3/` through that VIP returned HTTP 200. The official
  `quay.io/openstack.kolla` 2026.1 test image set was used only after the
  required explicit precheck acknowledgement; it is not a production image
  qualification.
- Bounded failures corrected: installed the Docker Python SDK and Ubuntu
  `dbus` path into the Kolla virtualenv, forced a supported `C.UTF-8` locale,
  and used `--use-test-images` only on `prechecks`, because `pull` and `deploy`
  do not accept that option. The long Neutron bootstrap was verified as an
  active Alembic migration rather than treated as a hang.
- Changed files: Added the Stage 4 VM provisioner, AIO globals, and operator
  README under `poc/kolla-aio/`; updated this plan and `HANDOFF.md`.
- Next exact action: Clone published Coffer commit
  `dc145ff04bedff189ab751ba80791727b743a97e` into the AIO, build the pinned
  x86_64 Coffer/Distribution artifacts from the independent bootstrap path,
  create owner-only Stage 4 role inputs and a dedicated disposable RGW
  identity/bucket, then run the companion prechecks and deploy.

### 2026-07-24 — Coffer companion deployment completed

- Completed: Built the Coffer and unmodified Distribution artifacts from
  published commit `dc145ff04bedff189ab751ba80791727b743a97e` without using
  the tenant registry. Companion prechecks, deploy, and reconfigure passed;
  the final corrected reconfigure recap was `ok=72`, `changed=11`,
  `failed=0`, `unreachable=0`.
- Completed: Created only the disposable RGW identity and bucket
  `coffer-kolla-aio-stage4`, verified an authenticated private sentinel
  round trip, and retained exact purge ownership for cleanup. Coffer API,
  edge, and Distribution are healthy. The external TLS VIP now returns the
  expected OCI `401` with a Coffer Bearer challenge while API and registry
  remain internal-only HAProxy frontends.
- Evidence: Repeated schema bootstrap completed safely; verified TLS spans
  HAProxy-to-Coffer, edge-to-API/Distribution, and Distribution-to-RGW.
  Coffer and registry image scans remain above the production severity gate,
  so this is functional AIO evidence only.
- Bounded failures corrected: installed the pinned Kolla collection
  dependencies; exported Kolla module utilities from the companion wrapper;
  URL-encoded reserved database-password characters; declared Kolla log
  directories; used the installed API health client; installed the backend
  CA into HAProxy and process trust; registered the HAProxy restart handler
  statically; created the missing private RGW bucket; and regenerated the
  disposable backend CA with critical CA `basicConstraints` and certificate-
  signing `keyUsage`, which Python 3.13 requires.
- Next exact action: Generate the post-deploy client configuration without
  exposing its password, verify the proposed `oci-registry` catalog record,
  create two finite disposable Keystone project identities, and run the
  project A push/pull plus project B denial matrix through the external edge.

### 2026-07-24 — Tenant OCI and repeatability acceptance passed

- Completed: Kolla post-deploy produced root-only client configuration. The
  catalog contains one `coffer` service of proposed type `oci-registry`, with
  internal/admin `http://192.168.122.203:8788/v1` and public
  `https://192.168.122.220:8788/v1` endpoints.
- Completed: Two two-hour, member-only application credentials were generated
  only in root-owned guest state. Project A created `stage4-proof` through the
  external edge and Docker pushed/pulled digest
  `sha256:7a3ebe5bfd1a4a19797d20b0c0bb39d44393e9a03fd852c0865b0f540d868df0`.
  Project B received non-disclosing 404/401 behavior for control lookup,
  pull, push, tags, cross-mount, overwrite, and delete.
- Completed: External VIP ports for the private API and Distribution backends
  were unreachable. API, edge, Distribution, and HAProxy were restarted;
  the same digest and external challenge recovered. Alembic remained at
  `0004_inventory_import`.
- Completed: Two consecutive companion reconfigure runs each reported
  `ok=69`, `changed=1`, `failed=0`; the only change was the intentional
  one-shot schema bootstrap. The service password update switch was disabled
  in the disposable globals so configuration drift was not masked by Kolla's
  default password rewrite. Post-reconfigure digest/catalog behavior and
  secret/JWT log scans passed.
- Production block retained: pinned functional image IDs are
  `sha256:6f4d7c332d22cfca5570bd9109d3976092b9d25e33f98d7c07dd9634571f0b94`
  and
  `sha256:74eb5b3a67d60455c5df9fb9c00b8786d3f2a0311e6559c2df6d79fd2c68ac02`.
  Trivy 0.72.0 reported Coffer at 6 Critical/34 High and the registry wrapper
  at 6 Critical/54 High, so neither artifact is production-promotable.
- Next exact action: Remove both finite Keystone fixtures, purge only the
  dedicated Stage 4 RGW identity/bucket, destroy the exact AIO domain and
  volumes, remove temporary known-host state, verify the original host
  inventory, then run the final local regression/security/documentation
  matrix.

### 2026-07-24 — Exact cleanup and Stage 4 closure completed

- Completed: Removed both finite Keystone fixtures and verified their exact
  project/user/application-credential names absent. Purged only the dedicated
  `coffer-kolla-aio-stage4` RGW bucket and identity, stopped and removed the
  three Coffer runtime containers, destroyed and undefined the exact
  autostart-disabled AIO domain, and deleted only its seed, root, and copied
  base volumes.
- Evidence: The corrected final host audit found zero Stage 4 domains and
  volumes, retained all 18 original domains, retained `coffer-rgw-poc` running
  with autostart disabled, and left approximately 124.5 GiB host memory and
  877 GiB pool capacity available. Local Stage 4 temporary paths and the
  generated known-host entry are absent.
- Completed: The companion contract now passes 52 checks. The full Python
  suite passes 232 tests on each of Python 3.11.14, 3.12.13, and 3.13.14.
  Lock, compilation, eight installed CLI helps, Go format/test/vet, six
  Compose models, 58 Make dry-runs, production-profile Coffer-role Ansible
  lint, 38 YAML and 12 Jinja parses, 66 Bash/ShellCheck files, 65 Markdown
  files, 44 local links, project-owned Gitleaks over 311 files, explicit
  private-key/JWT/address/residue scans, and diff checks pass.
- Bounded checks corrected: Rejected an unsupported `virsh vol-list --name`
  cleanup audit and reran the exact pool audit with supported output parsing;
  rejected Python runs that omitted the test dependency group; scoped
  Ansible lint away from unrelated upstream Kolla roles using Kolla's own
  lint configuration; replaced a whole-tree Gitleaks run that included
  ignored upstream/cache content with an exact project-owned archive; and
  corrected the restart verifier from an invalid request-HEAD form to curl's
  real HEAD mode. Every authoritative replacement passed.
- Decision: Stage 4 closes functional single-node Kolla AIO acceptance only.
  It does not clear the test-only Kolla image, vulnerable Coffer/Distribution
  image, one-OSD RGW, multinode/HA, backup/restore, upgrade, or production
  promotion gates. Stage 4 changes remain an unpublished local atomic work
  package; the user-authorized publication boundary preceded this plan.
- Next exact action: None. A multinode/HA pilot or production-image
  remediation must begin in a new execution plan.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Publication boundary | Three scoped commits, verified GitHub identity, atomic push, local/remote equality | passed |
| Shared-host and image preflight | Read-only virsh/network/storage/listener and pinned image/source inspection | passed |
| Kolla AIO | bootstrap-servers, prechecks, deploy, service/catalog health | passed |
| Coffer deployment | companion prechecks/deploy/reconfigure and runtime health | passed |
| Tenant OCI acceptance | two projects, push/pull/isolation/bypass/restart/digest | passed |
| Repeatability and cleanup | repeat migration/reconfigure, exact identity/VM/volume/temp removal | passed |
| Full regression and docs | Python/Ansible/shell/Markdown/secret/residue/diff | passed |

## Failures, Blockers, and Risks

- Official/public Kolla 2026.1 test images became available from
  `quay.io/openstack.kolla` and enabled the functional AIO. Kolla explicitly
  labels them test-only, so this closes the functional dependency but not the
  production image qualification gate.
- Distribution v3.1.1 and prior wrapper scans contain unresolved Critical/High
  findings. Functional AIO success cannot promote them to production.
- Full Kolla AIO installation is network-, disk-, and time-intensive. Every
  retry must remain bounded and leave the exact isolated target recoverable.
- The external RGW functional lab is one-OSD and non-durable. Stage 4 may read
  or write only through a dedicated disposable Coffer bucket/identity contract
  and cannot claim HA or durability.

## Handoff

- Current state: Completed. Deployment, catalog, two-project Docker isolation,
  backend non-bypass, restart persistence, repeat migration/reconfigure,
  secret-log acceptance, exact cleanup, and the final local regression matrix
  passed.
- Exact next action: None for plan 0016.
- First file or command: Create a new execution plan before starting either
  the multinode/HA pilot or production-image remediation.
- Questions requiring user input: Selection and authorization of the next work
  package, plus separate authorization before publication or production
  resources.
