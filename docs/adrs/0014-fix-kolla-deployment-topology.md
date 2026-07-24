# ADR 0014: Fix the Kolla Deployment Topology and Operating Contract

- Status: accepted
- Date: 2026-07-23
- Decision owners: Coffer maintainers and deployment operators
- Related plan: `docs/exec-plans/0013-kolla-deployment-topology.md`
- Related ADRs: `docs/adrs/0001-compose-cnc-distribution.md`, `docs/adrs/0002-keystone-application-credential-token-broker.md`, `docs/adrs/0003-rgw-s3-single-region-storage.md`, `docs/adrs/0007-use-falcon-wsgi-and-gunicorn.md`, `docs/adrs/0009-add-private-edge-manifest-quota-admission.md`, `docs/adrs/0010-adopt-repository-metadata-into-alembic.md`, `docs/adrs/0013-require-explicit-authentication-for-live-comparison.md`
- Deployment contract: `docs/architecture/kolla-deployment-topology.md`

## Context

Coffer has separate implemented seams for its control/token WSGI application,
private manifest admission, upstream Distribution proxying, reconciliation, and
Alembic schema. The private edge is still a PoC fixture rather than an installed
service. Kolla image and role work would therefore encode accidental fixture
boundaries unless the deployable topology is fixed first.

ADR 0009 also requires a non-bypassable registry edge. Sending non-manifest
traffic directly from a public load balancer to Distribution would leave a
second public `/v2/` route that could later diverge from the admission path.

Kolla-Ansible 2026.1 provides the following relevant contracts:

- [Adding a new service](https://docs.openstack.org/kolla-ansible/2026.1/contributor/adding-a-new-service.html)
  separates database/user bootstrap from a one-shot table-bootstrap container
  and requires deploy, reconfigure, pull, upgrade, registration, configuration,
  logging, and handler integration.
- [Kolla Images API](https://docs.openstack.org/kolla/2026.1/admin/kolla_api.html)
  defines `kolla_start` and the read-only
  `/var/lib/kolla/config_files/config.json` file-copy, ownership, permission, and
  command contract.
- [Kolla TLS](https://docs.openstack.org/kolla-ansible/2026.1/admin/tls.html)
  distinguishes internal/external VIP TLS from service-backend TLS.
- [Kolla external Ceph](https://docs.openstack.org/kolla-ansible/2026.1/reference/storage/external-ceph-guide.html)
  makes the deployer consume an existing Ceph deployment and credentials rather
  than provision Ceph through Kolla-Ansible.

A read-only inventory on 2026-07-23 established that `bb00` is a shared KVM
host, not a Kolla target. Its host ports 80/443, HAProxy, Harbor deployment, and
existing VM domains are already in use. It has sufficient capacity for a later
isolated VM, but this decision neither allocates that VM nor changes the host.

## Decision

### 1. Fix five deployable roles

| Role | Lifetime and listener | Responsibility |
|---|---|---|
| `coffer-api` | Long-running; private backend port `8787` | Existing `/v1/` control API, `/auth/token`, process health/readiness, and optional protected metrics. It is the only Coffer process that receives the registry signing private key. |
| `coffer-edge` | Long-running; internal/public backend port `8788` | Sole ingress for the Coffer origin. It routes `/v1/` and `/auth/token` to `coffer-api`, streams every `/v2/` request to Distribution, and intercepts manifest/index PUT for ADR 0009 admission. |
| `coffer-registry` | Long-running; private backend port `8789` | Unmodified upstream CNCF Distribution. It owns OCI protocol state and RGW access and has no direct public or tenant-reachable listener. |
| `coffer-reconcile` | Long-running or scheduled; no listener | Runs the installed bounded reconciliation loop against shared SQL and the authenticated private Distribution route. |
| `coffer-bootstrap` | One-shot; no listener | Runs `alembic upgrade head`, validates the exact head, and exits before a fresh deploy or application rollout proceeds. |

The three ports are defaults, remain operator-overridable, and had no exact
match in the 166 port declarations inspected at Kolla-Ansible
`stable/2026.1` commit `4d39a81d392f608a04b69cfae9afaa92d65ea388`.
Stage 3 prechecks must still validate them against the actual inventory and
host bindings.

The four Coffer-owned roles may initially use one immutable Coffer runtime image
with different commands. `coffer-registry` remains a separately pinned upstream
Distribution image. The exact image split is a Stage 2 implementation decision;
the process and privilege boundaries above are not.

### 2. Make `coffer-edge` the only tenant ingress

The canonical external OCI origin is
`https://<coffer_external_fqdn>/`. In the production profile,
Kolla-Ansible's single external frontend maps that FQDN on port 443 to the
`coffer-edge` backend. A non-443 high-port endpoint is allowed only for a
declared disposable lab.

The edge accepts only these public surfaces:

| Path | Edge action |
|---|---|
| `/v2/` and descendants | Stream to private `coffer-registry`; run manifest admission before forwarding manifest/index PUT |
| `/auth/token` | Forward to private `coffer-api` without logging or retaining the Basic credential |
| `/v1/` and descendants | Forward to private `coffer-api` |

Every other path fails closed. `/healthz`, `/readyz`, and `/metrics` are
backend/operator surfaces and are not exposed on the tenant origin.

This deliberately keeps path routing in the Coffer edge rather than injecting
service-specific path ACLs into Kolla's shared external HAProxy frontend.
HAProxy and Keepalived still own VIP failover, TLS termination, FQDN selection,
load balancing, and backend health. The edge owns only Coffer path dispatch,
streaming, and the non-bypassable admission boundary.

`coffer-registry` binds only to the private service network. Security groups,
host firewall rules, inventory groups, and HAProxy configuration must make
ports `8787` and `8789` unreachable from tenant/external networks. Tests must
prove that a client able to reach the public FQDN cannot address Distribution
directly.

In a multi-replica deployment, edge-to-API and edge/reconciler-to-Distribution
requests use private internal HAProxy service frontends on ports `8787` and
`8789`; they do not embed an ad hoc replica list. The service containers listen
on their corresponding backend address/port. An AIO can collapse those hops
without changing the addressing contract.

### 3. Use one proposed Keystone service with explicit endpoints

The proposed service type remains `oci-registry`; this ADR does not claim that
it is registered in the OpenStack service-types authority.

The service catalog describes the control API:

- public: `https://<coffer_external_fqdn>/v1`
- internal: `https://<coffer_internal_fqdn>:8788/v1`
- admin: the internal endpoint; Coffer has no separate admin API listener

The control API returns or documents the canonical OCI origin. OCI clients use
that origin's `/v2/` Bearer challenge and the same origin's `/auth/token`
realm. The internal catalog endpoint is not a second canonical OCI origin.

Kolla's shared external VIP and single external frontend are preferred; no
Coffer-specific VIP is required. Deployments not using that frontend may expose
the edge's configured high port, but that is not the production product
profile.

### 4. Separate frontend, backend, and dependency TLS

- External TLS on the canonical FQDN is mandatory.
- Internal VIP TLS is mandatory for a production profile.
- Verified backend TLS is mandatory for production traffic from HAProxy to
  `coffer-edge`, from `coffer-edge` to `coffer-api` and
  `coffer-registry`, and from `coffer-reconcile` to
  `coffer-registry`.
- Distribution uses verified HTTPS to RGW, and Coffer uses verified HTTPS to
  Keystone and Barbican where applicable.
- A disposable, network-isolated AIO may use backend HTTP only when it is
  labelled non-production and the direct backend ports remain unreachable from
  tenant networks.

The current `RegistryEdgeProxy` and `HTTPManifestUpstream` accept only one
plaintext HTTP origin. Stage 2 must add verified HTTPS, CA, hostname, timeout,
and bounded connection behavior before the backend-TLS profile can pass.

Public CA bundles are read-only inputs. TLS private keys are delivered only to
the HAProxy or backend process that terminates the corresponding connection.

### 5. Materialize secrets before process start

Barbican is the preferred OpenStack-native secret authority, consistent with
the completed disposable Barbican/RGW PoC. Coffer processes do not synchronously
retrieve a secret from Barbican on every request. An owner-controlled
deployment or pre-deploy step retrieves or receives the exact secret, writes a
root-owned host file with mode `0600`, and mounts/copies it read-only through
the Kolla container configuration contract. Secret values never belong in this
repository, ordinary inventory variables, execution plans, handoffs, command
lines, or logs.

| Material | Runtime recipients |
|---|---|
| Registry JWT signing private key | `coffer-api` only |
| Overlapping public JWKS | `coffer-edge`, `coffer-registry` |
| Distribution shared HTTP secret | All `coffer-registry` replicas only |
| RGW access and secret key | All `coffer-registry` replicas only |
| Control database credential | `coffer-api`, `coffer-edge`, `coffer-reconcile`, `coffer-bootstrap` |
| Keystone service credential | `coffer-api` only |
| Reconciliation Distribution read credential | `coffer-reconcile` only; provider remains a production gate |
| Backend TLS private key | Only the terminating API, edge, registry, or HAProxy process |
| Public CA bundles | Only clients that validate the corresponding dependency |

The deployment controller's Barbican authentication and the exact Kolla
materialization helper are Stage 3 decisions. They must use an operator-owned,
audited, bounded mechanism and must not leave a runtime Barbican credential in
the five service containers.

ADR 0013's production live-comparison identity and the reconciliation
Distribution identity remain unresolved production gates. This ADR does not
create, select, or deliver either credential; an eventual live-comparison
credential belongs to its owner-controlled maintenance job, not these five
runtime roles.

### 6. Give migrations one explicit owner

The Kolla/Ansible control plane creates the database and database user but does
not create application tables. `coffer-bootstrap` is the sole schema-upgrade
owner:

1. confirm that an operator-approved database backup exists for an upgrade that
   can change schema;
2. run one leader-elected or `run_once` bootstrap container;
3. execute `alembic upgrade head` and validate the exact expected revision;
4. on success, roll or start API, edge, reconciler, and registry services;
5. on failure, stop the rollout and retain the prior serving version when the
   schema remains compatible.

Normal Coffer processes validate schema and never auto-upgrade or create tables.
Repeated bootstrap at the same revision must be safe.

Production rollback does not run an automatic Alembic downgrade. If the new
schema is backward-compatible, operators may restore the prior image and
configuration after verification. If it is not, they enter maintenance, restore
the pre-upgrade database backup, restore the prior images/configuration, and
validate schema and OCI digests before reopening traffic. A committed inventory
marker under ADR 0012 can intentionally make downgrade invalid; the documented
restore path takes precedence.

Distribution/RGW object changes, existing-content import, writer exclusion,
backup/restore rehearsal, and destructive GC are separate operating procedures
and are not authorized by the schema bootstrap.

### 7. Keep bootstrap and tenant registries independent

Kolla must pull the Coffer and Distribution images from an already available
bootstrap registry. Coffer must not be configured as its own image source
during initial deployment. The Harbor instance observed on `bb00` is a possible
later bootstrap source, not an accepted dependency and not changed by this ADR.

Later Kolla validation must run in a separately named VM with its own networks
and addresses. It may consume the existing `coffer-rgw-poc` only through a
separately approved external-RGW test contract. It must not install on `bb00`
or reuse its current HAProxy, Harbor, or unrelated domains.

## Consequences

- All tenant OCI and control traffic crosses `coffer-edge`; blob bodies are
  streamed and never buffered into Coffer SQL, but the edge becomes a
  throughput and availability component that needs at least two replicas in HA.
- The edge requires a small additional `/v1/` and `/auth/token` reverse-proxy
  implementation in Stage 2. This avoids a custom path-routing modification to
  Kolla's shared external frontend and keeps Distribution non-bypassable.
- The signing private key, RGW credential, and Distribution HTTP secret have
  disjoint recipients, reducing blast radius.
- Backend TLS cannot be claimed until the current HTTP-only edge is replaced by
  the product entry point and verified.
- Kolla role work can now derive inventory groups, service definitions,
  HAProxy health checks, configuration files, and bootstrap ordering from a
  stable contract.
- This decision does not close the Distribution release-security gate, Ceph
  zero-byte SSE-KMS gate, authenticated live-comparison identity, Galera/HA,
  backup/cutover, observability, load, or governance gates.

## Alternatives Rejected

- **Deploy Harbor as Coffer:** it introduces a different control plane and does
  not preserve the selected thin OpenStack-native composition.
- **Expose Distribution directly for non-manifest paths:** it creates a bypass
  and splits the security boundary.
- **Fork or modify Distribution for admission:** it abandons the unmodified
  upstream data-plane decision.
- **Put all roles in one process/container:** it spreads signing, database,
  storage, and HTTP secrets across one failure and privilege boundary.
- **Add a separate token container now:** the existing API/token WSGI process
  is sufficient; a split can be reconsidered only with measured scaling or
  security evidence.
- **Put Coffer-specific path ACLs in the shared Kolla external frontend:** it
  couples a companion role to global HAProxy routing when a bounded edge router
  can own its own path contract.
- **Fetch Barbican secrets in every runtime request:** it adds a secret-service
  availability and latency dependency to the hot path.
- **Auto-migrate from application startup:** concurrent replicas can race and a
  failed migration becomes indistinguishable from normal startup.
- **Install directly on `bb00` or reuse existing workloads:** it risks
  collisions and changes unrelated shared-host state.
- **Use Coffer to bootstrap its own images:** it creates a circular dependency
  and couples control-plane recovery to the tenant registry.

## Validation and Follow-up

This decision is accepted because it reconciles the implemented seams, the
Kolla 2026.1 contracts above, the no-bypass quota decision, and the read-only
target inventory. It is not deployment evidence.

Stage 2 must productize the API, edge, reconciliation, and bootstrap entry
points; add verified edge-to-backend TLS; define health checks and structured
logging; and create Kolla-compatible images. Stage 3 then implements the
operator-local Kolla-Ansible role. A fresh execution plan is required before
either stage begins.
