# Stage 6 Maintenance Secret Delivery

- Date: 2026-07-25
- Status: fixture-only Kolla contract implemented; no real identity or secret
  created
- Scope: accepted ADR 0015 identity material, per-workload mTLS, Kolla
  materialization, rotation, revocation, and residue
- Related ADRs: `docs/adrs/0008-finite-application-credentials-as-provisioning-contract.md`,
  `docs/adrs/0014-fix-kolla-deployment-topology.md`,
  `docs/adrs/0015-use-expiring-maintenance-identity.md`
- Related plan: `docs/exec-plans/0019-stage6-production-promotion.md`

## Outcome

The existing companion role has a usable owner-controlled file boundary, but
it is not yet a maintenance-identity implementation. The recommended next
contract is:

1. the deployment owner creates one dedicated maintenance service user and
   role assignment, then one finite restricted application credential per
   reconciler replica or approved one-shot comparison job;
2. the owner stores each one-time credential secret and private client key in
   separate owner-only Barbican records;
3. a pre-deploy owner action retrieves and atomically materializes exact
   per-host files under the ignored Kolla custom-config tree;
4. Kolla validates those source files and copies them only into the declared
   `coffer-reconcile` replica or the bounded comparison job;
5. a private HAProxy frontend validates the distinct client certificate,
   strips any caller workload header, and supplies a server-derived workload
   identity to the API; and
6. the worker exchanges its application credential for a Keystone token, asks
   the internal broker for one repository pull token, and retains both tokens
   only in memory.

The local fixture contract now implements the recipient and frontend shape
using generated disposable placeholders. It creates no Keystone object,
Barbican secret, ACL, consumer, real certificate, endpoint, or remote state.
`coffer_enable_reconcile` remains false.

## Implemented Fixture Boundary

The companion role now has an opt-in
`coffer_enable_maintenance_identity=false` default. The isolated contract
harness turns it on only for generated files and proves:

- the declared workload hosts exactly cover the `coffer-reconcile` group, with
  unique bounded workload IDs, application-credential IDs, and client
  certificates;
- host-addressed secret directories are owner-only mode `0700`; exact
  credential ID/secret and client-key files are regular, nonempty,
  single-link mode-`0600` files;
- each mode-`0644` client certificate verifies against the exact maintenance
  CA and matches its own private key;
- disabled reconciler `config.json` receives only the exact credential
  ID/secret and client certificate/key paths; no API, edge, registry, or
  bootstrap recipient receives those values;
- a private internal-VIP HAProxy frontend requires the exact client CA, maps
  the SHA-256 fingerprint of each declared certificate to one workload,
  accepts only `POST /v1/internal/maintenance/registry-token`, and verifies
  backend TLS;
- the ordinary internal API frontend removes the workload header and denies
  `/v1/internal/`, while the public edge retains its application-level
  internal-namespace denial; and
- the API adapter deletes any incoming header and preexisting WSGI context,
  accepting a mapped workload only when the direct peer is an allowlisted
  HAProxy address and the workload is configured.

The product builder can assemble the accepted SQL authority, policy, broker,
resource, and adapter when `[maintenance] enabled=true`. The production Kolla
default remains false, the reconciler remains disabled, and the worker still
has no runtime Keystone-token or broker-token provider.

## Current Role Boundary

The current role already proves these reusable properties:

- secret source paths live under
  `{{ node_custom_config }}/coffer/secrets`, not ordinary inventory values;
- prechecks run on the deployment controller, require a regular nonempty file
  with the configured owner and exact mode `0600`, and use `no_log`;
- rendered per-process configuration and Distribution configuration are mode
  `0600`;
- `kolla_start` copies declared inputs read-only into the container with an
  exact owner and mode;
- the registry signing private key goes only to `coffer-api`;
- RGW keys and the Distribution HTTP secret appear only in the private
  Distribution configuration;
- public JWKS goes only to edge and registry; and
- the reconciler currently receives only its mode-0600 config, registry CA,
  system CA inputs, database access, and no Distribution credential.

The current precheck intentionally refuses `coffer_enable_reconcile=true`.
There is no maintenance user/role, application-credential file, per-replica
client certificate, client CA, private mTLS frontend, trusted workload adapter,
token provider, or live-comparison job. The existing backend TLS key is a
server key copied to listener processes and must not be reused as a maintenance
client key.

## Required Material and Exact Recipients

| Material | Secret | Source authority | Runtime recipient | Forbidden recipients |
|---|---:|---|---|---|
| Maintenance user/project/role IDs | No | Keystone and deployment metadata | API policy config; deployment evidence | Registry claim, tenant artifact |
| Application-credential ID | No, but audit-sensitive | Keystone | One exact reconciler replica or comparison job | Edge, registry, bootstrap |
| Application-credential secret | Yes | One-time Keystone response stored in Barbican | Same exact replica/job as its ID | API, edge, registry, bootstrap, other replicas |
| Maintenance client certificate | No | Operator PKI | Exact replica/job; HAProxy trust evidence | Tenant origin |
| Maintenance client private key | Yes | Operator PKI stored in Barbican | One exact replica/job only | API, edge, registry, bootstrap, other replicas |
| Maintenance client CA | No | Operator PKI | Private HAProxy frontend | Worker as a private key, tenant origin |
| Registry signing private key | Yes | Existing owner source | API only | Every maintenance worker |
| Registry/Keystone/backend CA bundles | No | Existing operator trust inputs | Exact validating clients | Secret stores unless operator policy requires |

Use distinct application credentials and client keys per replica. A shared
maintenance user and role keep policy stable; per-replica material makes one
worker independently revocable and lets the API audit application-credential
ID plus mTLS-derived workload ID. A one-shot comparison job receives a separate
credential/key only for its approved session window.

## Proposed Controller File Contract

The source layout should be host-addressed and contain no values in inventory:

```text
{{ node_custom_config }}/coffer/secrets/maintenance/
  <inventory-hostname>/
    application-credential-id
    application-credential-secret
    client.key

{{ node_custom_config }}/coffer/public/maintenance/
  <inventory-hostname>/
    client.crt
  client-ca.crt
```

The application-credential ID is not a secret, but keeping the pair in the same
root-owned `0700` directory simplifies exact recipient and cleanup checks.
Secret files and directories are root-owned, directories are `0700`, and files
are `0600`; public certificates are regular nonempty `0644` files. Symlinks,
group/world write, unexpected hard links, empty files, and unresolved host
entries fail precheck.

The future Kolla config should copy only these files into
`coffer-reconcile`:

```text
/etc/coffer/maintenance-application-credential-id
/etc/coffer/maintenance-application-credential-secret
/etc/coffer/maintenance-client.crt
/etc/coffer/maintenance-client.key
```

The Coffer config contains file paths, never the secret or a Bearer token.
`coffer-api`, `coffer-edge`, `coffer-registry`, and `coffer-bootstrap` must not
declare those source files in `config.json`. The live-comparison job uses a
separate one-shot config directory and mount that is removed after the approved
session; it must not reuse a long-running reconciler directory.

## Barbican and Materialization Contract

- Store the application-credential secret and client private key as separate
  secrets with `project-access=false`.
- Restrict read ACLs to the exact deployment owner. Do not grant the runtime
  maintenance user access to retrieve its own secret.
- Register consumers for the intended deployment/replica as audit metadata.
  Consumer registration is not a deletion lock and never replaces an ACL or
  reference check.
- Retain only non-secret secret UUID, application-credential ID, owner ID,
  replica ID, creation/expiration, and consumer metadata in deployment
  evidence. Do not put secret UUIDs in public logs or metrics.
- The deployment controller, not the runtime container, authenticates to
  Barbican over verified TLS. Runtime containers never receive that controller
  credential and never call Barbican on the token path.
- Retrieve into a controller-local `umask 077` temporary file on the same
  filesystem, validate nonempty size and expected encoding, set exact owner and
  mode, atomically rename, and remove the temporary file on success or failure.
  Secret bytes must not cross command arguments, ordinary Ansible variables,
  callback output, facts, diffs, or retained task results.

The disposable RGW/Barbican PoC proves a narrower pattern—guest-root streaming,
mode-0600 installation, verified CA use, and secret-free retained evidence. It
does not prove Barbican ACL/consumer behavior or controller-to-Kolla
materialization for maintenance credentials and cannot be cited as that
evidence.

## Private mTLS Frontend and Trusted Workload Context

ADR 0015 requires a private frontend separate from the tenant origin. The
candidate frontend uses a collision-checked operator port, requires a client
certificate issued by the maintenance client CA, maps the exact certificate to
one configured workload ID, removes any incoming workload-identity header, and
sets the verified value before forwarding only
`POST /v1/internal/maintenance/registry-token`.

The current local API deliberately reads
`coffer.maintenance_workload_id`, a WSGI server-side value, and ignores an HTTP
`X-Coffer-Maintenance-Workload` header. Production integration therefore needs
a small trusted proxy adapter that converts only the HAProxy-verified identity
to that WSGI value. Merely enabling an HTTP header is not sufficient.

The ordinary internal/public edge and control frontends must deny the internal
namespace. Direct API backend reachability must be restricted to the intended
load balancer/service peers. Even if network or workload identity is
misconfigured, the exact restricted application credential, user, project,
roles, live SQL claim/session, and pull-only token reduction remain mandatory.

The exact frontend port and certificate-to-workload mapping format are not
selected here. They require Kolla/HAProxy implementation review and collision
prechecks before acceptance.

## Rotation, Revocation, and Teardown

Credential and client-certificate rotations are independent and use overlap:

1. Create B with the same exact roles, access rule, explicit future expiration,
   and a new per-replica client key/certificate when rotating both layers.
2. Store B in new Barbican records and atomically materialize new filenames
   alongside A. Never overwrite A in place.
3. Roll one replica at a time to B. Prove Keystone authentication, mTLS
   workload mapping, one server-resolved pull token, wrong-scope denial, and
   secret-free logs.
4. After every replica uses B, wait at least the measured Keystone cache bound
   plus the maximum registry-token lifetime. Delete application credential A,
   revoke its client certificate or remove its mapping, then prove both are
   rejected.
5. Under exact owner/reference checks, remove A's controller files, host config
   copies, Barbican consumers, and Barbican secrets. Repeating finalization is
   safe.

Emergency revocation removes the `registry_maintenance` role or disables the
maintenance user, removes the affected certificate mapping, waits the bounded
token/cache window, and proves denial. Revoking one per-replica credential/key
is preferred when the remaining replicas are trustworthy.

Teardown must inventory and remove exact maintenance credentials, role
assignments, user, certificates, HAProxy mapping, session rows according to
their audit-retention policy, Kolla config copies, controller materializations,
Barbican consumers/secrets, temporary files, and container mounts. It must scan
host/container logs and retained evidence for credential values, Bearer tokens,
Authorization headers, and private keys. Ordinary `stop` is not residue
cleanup.

## Required Prechecks and Evidence

Before `coffer_enable_reconcile=true` is permitted:

- exact maintenance user/project/role IDs and a finite expiration are supplied;
- each enabled replica has one unique credential ID/secret and client key;
- owner, mode, regular-file, nonempty, no-symlink, and expected certificate/key
  pairing checks pass;
- the restricted access rule is exactly `oci-registry`, `POST`, and the
  internal broker path;
- the private mTLS frontend and certificate-to-workload allowlist validate;
- public and ordinary internal frontends still deny `/v1/internal/`;
- the claim lease leaves at least the registry token's 60-second compatibility
  floor after Keystone/broker exchange, or deployment is refused;
- rotation overlap contains both valid generations and no undeclared
  recipient;
- rendered configs, Ansible output, process environment, arguments, logs,
  metrics, and container inspection contain no secret value or token; and
- reconfigure, restart, rollback, credential expiration/deletion, role
  removal, user disablement, wrong client certificate, Keystone/API outage, and
  exact residue teardown pass in a disposable region.

## Changes Requiring Separate Approval

The following would cross the approved design-only boundary and require
explicit authorization before implementation:

- adding the real maintenance role/user/application-credential lifecycle;
- materializing any real application credential, client key, or certificate;
- applying the private frontend or network policy to a remote environment;
- adding Barbican retrieval/materialization or consumer/ACL mutations;
- enabling `coffer-reconcile` or installing a live-comparison job; and
- creating, rotating, revoking, or deleting any real identity, secret,
  certificate, endpoint, or remote resource.

## Recommendation

Prepare the disposable lifecycle harness next without executing it. The harness
must own exact create/rotate/revoke/teardown allowlists, finite expiry and
access-rule assertions, private-TLS failure cases, log/residue scans, and an
abort-safe cleanup path. Execution with real finite credentials, certificates,
Barbican objects, or a remote deployment remains a separate boundary.
