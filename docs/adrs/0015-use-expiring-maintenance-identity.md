# ADR 0015: Use an Expiring Maintenance Identity for Registry Reads

- Status: proposed
- Date: 2026-07-25
- Decision owners: Coffer maintainers and deployment operators
- Related plan: `docs/exec-plans/0019-stage6-production-promotion.md`
- Related ADRs: `docs/adrs/0008-finite-application-credentials-as-provisioning-contract.md`, `docs/adrs/0013-require-explicit-authentication-for-live-comparison.md`, `docs/adrs/0014-fix-kolla-deployment-topology.md`
- Research: `docs/research/stage6-maintenance-identity.md`

## Context

Reconciliation and existing-data live comparison must read manifests across
tenant projects without receiving tenant credentials, registry signing keys, or
RGW credentials. Verified private TLS does not authorize a repository read, and
the existing `coffer` middleware service user is an unsuitable caller because
it currently combines an API middleware password with an `admin` assignment.

The implemented reconciliation probe can accept injected Authorization headers,
but the installed runner supplies none. The live comparator already requires
authentication preparation before its first network request, but has no
production provider. Stage 5 therefore proved shared-SQL claim and fencing
behavior, not authenticated Distribution reads.

This decision introduces a privileged cross-project authority. User approval on
2026-07-25 authorizes the architecture and pure local contract implementation
only. It does not authorize creating a credential, role, certificate, Barbican
secret, endpoint, remote deployment, or production-data operation.

## Proposed Decision

### Identity and network boundary

1. Use a dedicated `coffer-maintenance` Keystone service user. Do not reuse a
   human identity or the API middleware service user.
2. Assign only `service` and `registry_maintenance` in the service project.
   `admin`, tenant roles, domain scope, and system scope do not imply
   maintenance authority.
3. Provision a restricted application credential with an explicit expiration,
   `unrestricted=false`, only those roles, and one access rule for service type
   `oci-registry`, method `POST`, and
   `/v1/internal/maintenance/registry-token`.
4. Expose that route only through a private HAProxy frontend requiring
   per-worker mTLS. mTLS is defense in depth; Keystone identity plus Coffer
   policy remains the authorization boundary.
5. The public `coffer-edge` rejects `/v1/internal` and
   `/v1/internal/` descendants without forwarding them.

### Server-side authority and token reduction

The broker accepts only immutable control identifiers:

- reconciliation: repository UUID, reservation UUID, claim token, and expected
  row version;
- live comparison: repository UUID, approved session ID, and inventory artifact
  digest.

Coffer resolves the current project and canonical repository from SQL. It never
uses caller-supplied project IDs, repository names, subjects, actions,
audiences, or arbitrary scope strings as authority.

Reconciliation issuance requires a live, unexpired, version-matching claim
owned by the current worker. Live-comparison issuance requires an approved,
unexpired, read-only session tied to the exact artifact and writer-exclusion
window. Stale, mismatched, completed, or absent authority fails closed.

One successful exchange returns one short-lived Distribution JWT with exactly
one `repository:<server-resolved-name>:pull` grant. It contains no push, delete,
catalog, registry-wide, refresh, or offline authority. The existing API signer
issues it; `coffer-reconcile` never receives the private signing key.

### Secret lifecycle and failure behavior

- The deployment owner stores the one-time application-credential secret in
  Barbican with owner-only access and materializes mode-0600 files only to
  approved maintenance workers. Runtime requests never fetch Barbican.
- Each worker has a distinct mTLS private key. Signer, RGW, server TLS, and
  maintenance client keys have disjoint recipients.
- Credentials and tokens remain memory-only. They never enter SQL,
  configuration, environment variables, command arguments, disk caches,
  metrics, logs, exceptions, or retained evidence.
- Authentication, policy, TLS, Keystone, broker, signer, or Distribution
  failures remain indeterminate. They never become manifest absence or quota
  release.
- Rotation overlaps credentials, proves every replica on the new credential,
  waits the bounded Keystone-cache plus registry-token lifetime, then revokes
  and removes the old credential. Owner disablement, role removal, expiration,
  and deletion are required revocation tests.

## Acceptance Boundary

This ADR remains proposed until pure local evidence proves:

- exact service-project and dual-role admission, with `admin` explicitly
  rejected;
- public-edge denial without upstream I/O;
- server-side repository resolution and refusal of caller-selected authority;
- current claim/version/session enforcement and stale-authority denial;
- one-repository pull-only JWT claims, bounded expiry, and no refresh token;
- fixed secret-safe failures and output.

Acceptance of the local contract will not make the feature production-ready.
Credential creation/delivery and the Kolla recipient/frontend contract require
a separate explicit approval and disposable-region evidence. The reconciler
must remain disabled by default until authenticated private-TLS end-to-end,
rotation, revocation, outage, replica failover, log scan, and residue teardown
all pass.

## Local Proof Status

The first pure local implementation milestone is complete:

- the optional internal Falcon resource stays behind
  `keystonemiddleware.auth_token`;
- the middleware and resource require the exact `oci-registry`, `POST`,
  internal-path access rule and reject unrestricted or password-issued tokens;
- policy exact-matches the immutable maintenance user, service project,
  `service` plus `registry_maintenance` roles, and a trusted WSGI workload
  identity that cannot be supplied by an HTTP header;
- a read-only SQL query validates the reconciliation reservation, repository,
  worker, claim token, row version, state, and lease expiry;
- the broker resolves the current repository route server-side and emits only
  one short-lived `pull` claim bounded by both Keystone-token and authority
  expiry;
- the public edge returns a fixed 404 for the internal namespace without API or
  registry upstream I/O; and
- fixed denial/unavailable responses and decision logs omit caller-selected
  repository authority, claim tokens, and dependency exception text.

ADR 0015 remains proposed. The typed live-comparison request and authority seam
fail closed, but there is no approved-session SQL schema or lifecycle yet.
There is also no production configuration, trusted mTLS-to-WSGI adapter, real
credential, Kolla recipient, or secret materialization. Those gaps cannot be
represented by a permissive fake or by enabling the resource in
`build_product_application`.

## Consequences

- Coffer gains one explicit, auditable cross-project authorization boundary
  without distributing tenant credentials or the registry signing key.
- The broker stays in `coffer-api`; no second authorization proxy or signer
  service is introduced.
- The maintenance identity is independent of tenant count, but its compromise
  can request read claims across projects while live server-side authority
  exists. Short lifetimes, exact roles, claim/session checks, private mTLS, and
  one-repository reduction bound that risk.
- Application-credential access rules constrain API use but are not repository
  authorization. Coffer policy and SQL authority remain mandatory.
- Revocation of already issued locally verified registry JWTs is bounded rather
  than instantaneous; production qualification must measure and document the
  maximum residual window.

## Alternatives Rejected

- **Per-project credentials as the global default:** preserves tenant ownership
  but creates O(projects) secrets and complex partial-failure recovery. It may
  remain an operator-assisted single-project fallback.
- **Existing service password or `admin`:** merges middleware and maintenance
  blast radii and silently treats a broad role as cross-project authority.
- **Service/system token alone:** Distribution cannot derive exact repository
  authority from Keystone scope.
- **Network location or mTLS alone:** authenticates a path or workload but not a
  current repository claim/session.
- **Signer key in the worker:** lets a mutable worker mint arbitrary trusted
  claims.
- **A separate read proxy:** adds another HA authorization component when the
  existing API can perform the bounded reduction.
- **Runtime Barbican lookup:** places secret-service availability and a broader
  credential on every registry-read path.

## Follow-up Evidence

After local acceptance, a separately approved work package must add Kolla
objects and owner-only materialization, then prove explicit expiry, access-rule
enforcement, role removal, owner disablement, deletion, wrong credential,
wrong client certificate, dependency outages, overlapping rotation, API/HAProxy
failover, authenticated Distribution HEAD, aggregate secret-safe audit, and
exact residue teardown in a disposable region.
