# Stage 6 Production Maintenance Identity

- Date: 2026-07-25
- Status: design research; architecture approved for pure local proof
- Scope: authenticated Distribution reads for reconciliation and existing-data
  live comparison
- Related ADRs: `docs/adrs/0008-finite-application-credentials-as-provisioning-contract.md`,
  `docs/adrs/0013-require-explicit-authentication-for-live-comparison.md`,
  `docs/adrs/0014-fix-kolla-deployment-topology.md`
- Related plan: `docs/exec-plans/0019-stage6-production-promotion.md`

## Outcome

The recommended design candidate is a **separate maintenance service user with
a finite, role-restricted Keystone application credential**, authenticated on
an internal-only Coffer token-broker route. Coffer, not Keystone, owns the
explicit cross-project authorization decision and issues one short-lived
Distribution `pull` JWT for one server-resolved repository at a time.

For the production profile, the caller should additionally cross a dedicated
HAProxy mTLS frontend with a per-service client certificate. mTLS establishes
the calling workload and network path; it never substitutes for Keystone
authentication or Coffer policy. The registry signing private key remains in
`coffer-api`, and the maintenance worker receives neither that key nor an RGW
credential.

The user approved this recommendation on 2026-07-25 for proposed ADR and pure
local contract proof. It creates a privileged cross-project boundary, a new
Keystone role/user/credential lifecycle, an internal route, and a
client-certificate lifecycle. That approval does not authorize creating or
delivering credentials, roles, certificates, endpoints, or Kolla secret
recipients; those remain separately approval-gated.

## Current Implemented Boundary

The current repository deliberately stops before a production provider:

| Surface | Implemented behavior | Production gap |
|---|---|---|
| Live inventory comparison | `AuthenticatedManifestProbe` must prepare every repository before the first HEAD; missing preparation fails before network I/O; output is aggregate and secret-safe | There is no installed CLI, provider, credential, or Kolla job |
| Reconciliation HTTP probe | Accepts injected headers and verified TLS; exact 200/digest, 404, and indeterminate behavior are implemented | The installed runner constructs the probe with no Authorization header |
| Reconciliation deployment | Kolla config supplies private HTTPS, CA, timeouts, leases, and batch limits | `coffer_enable_reconcile` defaults to false and was false throughout Stage 5 |
| Stage 5 reconciler evidence | Two workers proved shared-Galera claims, abandonment recovery, and fencing | It did not make an authenticated Distribution manifest request |
| Registry | Always verifies Coffer Bearer JWTs against the shared JWKS | A no-token internal HEAD returns 401, so private network placement is not authorization |
| Tenant token endpoint | Basic application credential is exchanged with Keystone, constrained to its immutable project, and converted to short-lived repository claims | It intentionally rejects application credentials carrying access rules and cannot grant a service-project subject access to tenant repositories |
| Control API | `/v1/` is protected by `keystonemiddleware`; `service_type=oci-registry` and required service-token role checks are configured | The tenant edge currently forwards all `/v1/`; a privileged internal route needs an explicit edge denial and private frontend |
| Kolla secrets | Owner-provided files are copied mode 0600 only to declared recipients | No maintenance application credential or client key contract exists |
| Backend TLS | API, edge, registry, HAProxy, and RGW server authentication passed Stage 5 | There is no client-certificate validation or per-maintenance-replica identity |

The existing `coffer` Keystone service user is not a suitable maintenance
caller. The companion role currently gives it `admin` in the service project
and materializes its password only to `coffer-api` for middleware operations.
Reusing it would combine middleware, cross-project registry, and signing-service
blast radii and would copy a static privileged password into another process.
Reducing or replacing this middleware credential is a related Stage 6
hardening task, not a reason to reuse it.

The first local proof now implements the recommended reconciliation boundary:
exact maintenance application-credential/access-rule/user/project/role policy,
trusted workload context, live SQL claim fencing, server-resolved route,
pull-only JWT reduction, and public-edge denial. The internal resource remains
optional and unconfigured. Live-comparison sessions, mTLS workload injection,
Kolla secret delivery, and real identity lifecycle evidence remain open.

## Authority Separation

Four authorities must remain distinct:

1. **Keystone authenticates the maintenance workload.** A project-scoped
   application credential proves the dedicated service user, delegated role
   subset, current validity, and audit chain. It does not itself authorize any
   tenant repository.
2. **Coffer authorizes the cross-project operation.** The internal broker
   verifies the exact maintenance role, operation mode, current SQL route, and
   reconciliation claim or approved inventory-comparison session. It never
   accepts a caller-supplied canonical repository name as authority.
3. **Coffer signs the short-lived registry claim.** The JWT has the existing
   audience, issuer, key ID, JTI, and expiry contracts and contains exactly one
   `repository:<canonical-name>:pull` grant. It has no push, delete, catalog,
   registry-wide, refresh, or offline authority.
4. **Distribution enforces the data-plane claim.** It verifies the signature,
   audience, issuer, subject, repository name, action, and expiry without
   Keystone or Barbican access.

A Keystone service token is supplemental identity context, not a
cross-project authorization grant. A system-scoped token is also insufficient:
each OpenStack service must define what system scope permits, while
Distribution understands only its Bearer claim. Network location or mTLS alone
likewise cannot decide repository authority.

## Candidate Evaluation

| Candidate | Least privilege | Rotation/revocation | Operational scale | Components/blast radius | Disposition |
|---|---|---|---|---|---|
| Per-project finite application credential | Strong project ownership and normal tenant token path | Native finite expiry and overlap, but one lifecycle per project | O(projects) secrets and partial-failure recovery; unsuitable for continuous global reconciliation | No new authority, but broad credential aggregation in one worker | Keep as an operator-assisted one-project fallback; reject as production default |
| Existing `coffer` service user/password | Broad current admin assignment; no repository restriction | Password replacement has immediate cutover risk | Simple | Reuses API middleware identity and copies static password to worker | Reject |
| New service user with finite application credential plus Coffer broker | Keystone privilege can be limited to `service` and proposed `registry_maintenance`; broker emits exact pull claim | Explicit expiry, owner/role disablement, deletion, and overlapping credentials | O(replicas), independent of tenant count | Adds an explicit cross-project Coffer policy boundary but no new data-plane component | Recommended candidate |
| Service token or system token alone | Does not map to Distribution repository claims; likely over-broad if treated as implicit admin | Keystone token expiry only; underlying service credential still required | Simple | Encourages hidden authorization by role/scope | Reject |
| Give signer key to `coffer-reconcile` | Worker can mint any trusted registry claim | Key rotation exists but compromise is registry-wide | Simple | Violates accepted secret recipients and merges authorization/signing with mutable worker | Reject |
| Operator-owned mTLS comparison proxy | Can expose HEAD-only paths | PKI rotation is possible | New HA service and policy plane | Proxy becomes a second cross-project authorization service | Reject as a separate component; reuse mTLS only as defense in depth on existing HAProxy |

## Recommended Candidate Contract

### Keystone objects

- Create a dedicated service user such as `coffer-maintenance`; do not reuse a
  human user or the API middleware user.
- Assign only the standard `service` role and a proposed
  `registry_maintenance` role in the service project. Do not grant `admin`,
  reader/member roles in tenant projects, domain scope, or system scope.
- Create a restricted application credential with:
  - an explicit future `expires_at`;
  - only the two required service-project roles;
  - `unrestricted=false`;
  - an access rule for service type `oci-registry`, method `POST`, and the exact
    internal broker path;
  - no authority to create another application credential.
- Treat finiteness as the accepted provisioning contract from ADR 0008. The
  runtime Keystone token expiry is not evidence that the underlying credential
  record has a future expiry.
- Use a dedicated service user because Keystone application credentials are
  user-owned. Disabling/deleting the owner or removing a delegated role must
  invalidate the credential and become part of the release regression.

Keystone documents that application credentials are bound to the creator's
current project, can delegate only an existing role subset, expose the secret
once, store it hashed, support an explicit expiration, and allow overlapping
credentials for graceful rotation. Access rules can restrict service, method,
and path when the target service configures `service_type`.

### Internal Coffer route

The proposed logical route is
`POST /v1/internal/maintenance/registry-token`; the exact path and port remain
provisional until an ADR is accepted.

- `coffer-edge` must reject `/v1/internal/` rather than forwarding it from the
  public tenant origin.
- A private HAProxy frontend admits only verified client certificates issued to
  `coffer-reconcile` and the one-shot inventory-comparison job, then forwards
  over the existing verified backend TLS path.
- The normal `keystonemiddleware` pipeline validates the caller's
  `X-Auth-Token` and application-credential access rule, then exposes the
  confirmed service-project scope, immutable user/project IDs, and roles.
  Required service-token role checking remains enabled for any separately
  supplied `X-Service-Token`; it does not replace primary-token policy.
- Coffer validates the project/user context and requires both `service` and
  `registry_maintenance`; `admin` does not imply this rule.
- The request carries an operation mode plus immutable control identifiers:
  - reconciliation: repository UUID, reservation UUID, claim token, and
    expected row version;
  - live comparison: approved maintenance-session ID, inventory artifact
    digest, and repository UUID.
- The server resolves project ID and canonical repository from its current SQL
  authority. It rejects caller-supplied project IDs, repository paths, actions,
  subjects, audiences, or arbitrary scope strings.
- Reconciliation issuance requires the caller to own a live, unexpired,
  version-matching claim. Live-comparison issuance requires a separately
  approved, unexpired, read-only maintenance session tied to the imported
  artifact and writer-exclusion window.
- One response contains one short-lived pull-only registry JWT. No refresh
  token is issued or stored.

The public edge denial is mandatory even though the route is authenticated.
This avoids exposing a privileged cross-project interface on the tenant origin
and keeps private mTLS enforceable.

### Worker behavior

- `coffer-reconcile` reads the application-credential ID/secret from owner-only
  files, obtains a Keystone token over verified TLS, and keeps both Keystone and
  registry tokens only in memory.
- It requests a repository JWT after claiming a row and before the Distribution
  HEAD. Token-exchange time must be included in the reconciliation lease and
  batch budget.
- Authentication, policy, Keystone, broker, TLS, or Distribution failure is
  indeterminate. It never converts these failures to absence and never releases
  logical usage.
- The one-shot live comparator prepares tokens for every route or fails before
  the first HEAD, preserving ADR 0013's existing all-or-nothing preparation
  contract.
- A bounded in-memory token cache may key on repository ID and token expiry.
  Tokens must never enter SQL, disk cache, environment variables, command
  arguments, metrics, exception messages, or retained evidence.

Distribution's token specification permits multiple resource scopes in one
JWT, but one repository per maintenance token is preferred. The smaller claim
limits replay impact and makes the broker's SQL authorization and audit record
unambiguous.

### Secret and certificate delivery

- The deployment controller creates or receives the application credential,
  stores the one-time secret in Barbican with `project-access=false`, and
  restricts read ACLs to the exact deployment owner. The repository stores only
  non-secret contract names.
- Barbican consumer registration records expected use but is not a deletion
  lock; teardown and rotation must still verify references before deletion.
- A pre-deploy owner step retrieves the secret and atomically materializes
  mode-0600 source files. Kolla copies them read-only only to
  `coffer-reconcile`; the one-shot comparison container receives them only for
  its approved maintenance window.
- Runtime containers never receive the deployment controller's Barbican
  credential and never fetch Barbican on the request path.
- Each maintenance replica receives a distinct client certificate/private key.
  Server and client keys are not reused. The private HAProxy frontend trusts
  only the maintenance client CA and does not forward caller-controlled
  certificate identity headers.

### Rotation and revocation

1. The owner creates credential B with the same restricted roles, exact access
   rule, and explicit expiration, and records only non-secret ID/expiry
   metadata.
2. The owner stores B under a new Barbican secret, materializes it alongside A,
   and rolls workers to B one at a time.
3. Every replica proves Keystone authentication, internal mTLS, broker policy,
   one exact pull token, wrong-scope denial, and secret-free logs.
4. After every replica uses B, wait at least the maximum Keystone token cache
   interval plus the registry JWT lifetime. Delete credential A, then remove
   its materialized file and Barbican secret under exact owner checks.
5. Prove A is rejected and B still works. Repeated rotation finalization must be
   idempotent.

Emergency revocation disables the maintenance user or removes the
`registry_maintenance` role, then invalidates all active credentials and waits
the bounded token/cache interval. Because already issued registry JWTs are
locally verified, revocation cannot be instantaneous; the accepted lifetime
and cache bound define the maximum residual window.

### Audit and observability

- Correlate a fixed maintenance request ID, Keystone audit IDs, application
  credential ID, maintenance-session or reconciliation-claim ID, registry JWT
  JTI, decision, and dependency result.
- Do not log secrets, Keystone tokens, registry JWTs, Authorization headers,
  client private keys, repository paths, manifest digests, or raw exceptions.
- Emit bounded result labels for authentication, policy, issuance, HEAD
  presence, expiry, revocation, and dependency outage. Tenant/repository IDs
  are audit fields, never metric labels.
- An issuance success does not mean content is present; the subsequent exact
  Distribution HEAD remains the authoritative observation.

## Required PoC and Production Evidence

Before proposed ADR 0015 can become accepted:

1. Add a proposed ADR fixing the principal, roles, access rule, internal route,
   mTLS frontend, SQL authority, token claim, recipients, and rollback
   contracts.
2. Implement pure local policy and token-broker tests first:
   - exact role/scope/access-rule admission;
   - edge denial of `/v1/internal/`;
   - no `admin` implication;
   - server-side route resolution;
   - live claim/version/session checks;
   - pull-only one-repository JWT;
   - wrong project/path/action/audience and stale claim denial;
   - aggregate, secret-safe output.
3. Extend the reconciler provider without writing tokens to configuration or
   logs. Keep `coffer_enable_reconcile=false` until authenticated end-to-end
   evidence passes.
4. Add Kolla contracts for the new user/role, owner-only Barbican
   materialization, exact recipients, private mTLS frontend, edge denial,
   rotation overlap, and cleanup.
5. In a disposable region, prove explicit expiry, access-rule enforcement,
   role removal, owner disablement, deletion, wrong credential, wrong client
   certificate, Keystone outage, API outage, signer rotation, and bounded cache
   behavior.
6. Run actual private-TLS Distribution HEAD through all registry/API replicas
   and HAProxy failover. Reconciliation must repair only exact admitted
   reservations; live comparison must remain read-only.
7. Scan every container and host log plus retained evidence for credentials,
   tokens, private keys, Authorization headers, repository paths, and manifest
   digests; then perform exact residue teardown.

## Approval Disposition

Approved for proposed ADR and pure local proof:

- explicit Coffer cross-project maintenance authority;
- a dedicated `registry_maintenance` role and service user;
- a private mTLS HAProxy frontend and edge-denied internal route; and
- finite, restricted application credentials as the identity contract.

Still requiring separate approval and measured evidence:

- creation or delivery of the user, role, credential, Barbican secret,
  certificate, endpoint, or Kolla recipient;
- deployment-controller materialization to approved workers; and
- maximum credential lifetime, rotation interval, Keystone cache interval,
  maintenance-session lifetime, and residual revocation window.

No credential, role, endpoint, ACL, certificate, secret recipient, policy, or
runtime setting was created or changed by this research.

## Primary References

- [Keystone application credentials](https://docs.openstack.org/keystone/latest/user/application_credentials.html)
- [Keystone guidance for service authentication, scope, and service tokens](https://docs.openstack.org/keystone/latest/contributor/services.html)
- [keystonemiddleware architecture and service-token controls](https://docs.openstack.org/keystonemiddleware/latest/middlewarearchitecture)
- [Barbican secret ACLs](https://docs.openstack.org/api-guide/key-manager/acls.html)
- [Barbican secret consumers API](https://docs.openstack.org/barbican/latest/api/reference/secret_consumers.html)
- [Distribution token authentication specification](https://distribution.github.io/distribution/spec/auth/token/)
- [Distribution token scope and access](https://distribution.github.io/distribution/spec/auth/scope/)
