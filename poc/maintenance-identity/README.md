# Disposable Maintenance Identity Lifecycle

This directory owns the Stage 6 disposable lifecycle proof for ADR 0015. It
must demonstrate that Coffer can create, rotate, revoke, and remove a
least-privilege maintenance identity without leaking a Keystone application
credential, Barbican payload, private key, Bearer token, or registry JWT.

This document fixes the harness contract before any identity, secret,
certificate, endpoint, Kolla recipient, or remote resource is created. The
initial implementation must support local model validation and read-only
preflight only. A later explicitly targeted disposable execution may use the
existing isolated Kolla/OpenStack lab, but it must not touch production data or
reuse a tenant, middleware, RGW, registry-signing, or human credential.

## Owned Resource Allowlist

The lifecycle owns only resources carrying one invocation ID generated as a
lowercase 26-character ULID. The canonical prefix is
`coffer-maint-<invocation-id>`. Every create, lookup, mutation, and delete must
use retained immutable IDs obtained from the original create response; a name
or prefix query is never a mutation target.

| Kind | Exact allowed shape | Cardinality | Retained value |
|---|---|---:|---|
| Keystone project | `coffer-maint-<id>-service` | 1 | immutable project ID |
| Keystone user | `coffer-maint-<id>-user` | 1 | immutable user ID |
| Keystone role | `registry_maintenance` | reuse 0 or 1 | immutable role ID and ownership flag |
| Role assignments | exact project, user, and `service`/`registry_maintenance` role IDs | 2 | assignment tuples |
| Application credential | `coffer-maint-<id>-<workload>-g<generation>` | one per workload/generation | immutable credential ID, expiry, access-rule digest |
| Barbican secrets | `coffer-maint-<id>-<workload>-g<generation>-{appcred,client-key}` | two per workload/generation | immutable secret UUIDs and owner-only consumer IDs |
| Client certificate | CN `coffer-maint-<id>-<workload>-g<generation>` | one per workload/generation | serial, SHA-256 fingerprint, expiry |
| HAProxy mapping | exact certificate fingerprint to exact workload ID | one per active certificate | mapping digest |
| Controller materialization | `<root>/<id>/<workload>/g<generation>/...` | one tree per workload/generation | file metadata and content digests excluding secrets |
| SQL comparison session | an exact session created by this invocation | optional, one per comparison workload | immutable session UUID and terminal state |

Allowed workload IDs are fixed by the disposable topology file and must match
`^[a-z][a-z0-9-]{0,31}$`. The initial topology admits
`reconcile-1`, `reconcile-2`, and `comparison-1`; an implementation may select
a nonempty subset, but it cannot accept an arbitrary workload from the command
line. Generation is the positive integer `1` or `2` in the first proof.

The harness must refuse:

- an invocation ID, project, user, credential, secret, certificate, mapping,
  materialization root, or session not recorded in its owner-only state;
- a role named `registry_maintenance` whose immutable ID differs from the
  preflight snapshot;
- an owned-name collision with an unrecorded immutable ID;
- any `admin`, `member`, tenant, domain, system, or inherited role assignment;
- wildcard, prefix, all-project, all-user, all-credential, or all-secret
  mutation targets;
- symlinks, multiple hard links, group/world-writable directories, or a
  materialization root outside the exact ignored work directory; and
- execution when the target endpoint, cloud, deployment marker, TLS trust,
  or disposable-region identifier differs from the preflight record.

## Fixed Authority Contract

Each application credential must be:

- owned by the exact maintenance user in the exact disposable service project;
- `unrestricted=false`;
- explicitly expiring between 15 and 120 minutes after creation;
- granted exactly the `service` and `registry_maintenance` roles;
- restricted by exactly one access rule with service type `oci-registry`,
  method `POST`, and path
  `/v1/internal/maintenance/registry-token`; and
- unique to one workload and one generation.

The maintenance user receives no password usable by a runtime worker. If a
bootstrap password is unavoidable for credential creation, it exists only in
owner process memory or an owner-only temporary descriptor and is rotated or
disabled before workload verification. The application-credential secret is
captured once and streamed directly into a project-private Barbican secret.
The runtime maintenance identity cannot retrieve that Barbican secret.

The private client key is generated independently for each workload and
generation, stored in a separate project-private Barbican secret, and never
reused as a server, registry-signing, RGW, tenant, or deployment-controller
key. The client certificate lifetime cannot exceed its application credential
lifetime. HAProxy maps the exact SHA-256 certificate fingerprint to the exact
workload ID and admits only the broker POST route.

## Owner-Only State and Evidence

Mutable state lives only in an ignored mode-`0700` directory:

```text
work/maintenance-identity/<invocation-id>/
  state.json
  lock
  materialized/<workload>/g<generation>/
  evidence/
```

`state.json` is mode `0600`, atomically replaced, and contains only immutable
resource IDs, non-secret metadata, state transitions, hashes, and cleanup
status. It must never contain:

- an application-credential secret or bootstrap password;
- a Barbican secret payload or secret-bearing URL;
- a private key, Authorization header, Keystone token, or registry JWT;
- a repository name, tenant path, manifest digest, or credential command
  transcript; or
- a shell command containing secret-bearing substitution.

Retained evidence is schema-versioned JSON. It may include resource counts,
immutable-ID hashes, role/access-rule comparisons, expiration bounds,
certificate fingerprints, file owner/mode/link checks, HTTP status classes,
fixed failure categories, log-scan counts, and residue counts. It may not copy
raw OpenStack, HAProxy, Ansible, container, or application logs.

Every action takes a nonblocking per-invocation lock. It records a `started`
transition before the first mutation and an atomic `completed` or `failed`
transition afterward. A failed action records the fixed failure category and
the exact next recovery action, not exception text that could contain a URL,
header, token, or payload.

## Lifecycle Actions

The eventual command surface is intentionally small:

```text
./lifecycle.sh preflight <ssh-target>
./lifecycle.sh create <ssh-target>
./lifecycle.sh verify <ssh-target>
./lifecycle.sh rotate <ssh-target>
./lifecycle.sh revoke-old <ssh-target>
./lifecycle.sh verify-failures <ssh-target>
./lifecycle.sh teardown <ssh-target>
./lifecycle.sh status <ssh-target>
```

`status` and `preflight` are read-only. All other actions require the exact
preflight record, prior transition, disposable-region marker, and owner
confirmation encoded in the topology—not an interactive prompt.

### Preflight

Preflight must:

1. verify the target host key, OpenStack cloud identity, service catalog,
   project/domain IDs, verified TLS, Kolla deployment marker, and private
   maintenance endpoint shape;
2. snapshot the exact existing `service` and `registry_maintenance` role IDs,
   recording whether the harness would own the latter;
3. prove every generated resource name is absent or belongs to the exact
   resumable invocation state;
4. prove the controller work root is ignored, owner-only, on one filesystem,
   and has no secret-bearing leftovers;
5. prove reconciliation remains disabled until the lifecycle create and
   private-TLS verification gates pass; and
6. emit only a non-secret readiness document and proposed immutable names.

### Create and Verify Generation 1

Create must converge one exact project/user/role boundary, two exact role
assignments, and one generation-1 credential/keypair per selected workload.
It stores secret payloads owner-only in Barbican, registers exact consumer
metadata, materializes with temporary mode-`0600` files plus atomic rename,
and renders the private fingerprint mapping. An exit trap removes only
resources created by the failing invocation in reverse dependency order.

Verify must prove:

- exact user, project, roles, finite expiry, and access rule;
- project-private Barbican ACL and exact consumer metadata;
- unique application credentials, private keys, certificates, and
  fingerprints across workloads;
- exact materialization recipients, modes, owners, links, certificate chains,
  and key pairing;
- public and ordinary API frontends deny `/v1/internal/`;
- wrong CA, wrong client certificate, wrong workload, wrong method, wrong
  path, wrong role, wrong project, and unrestricted credential fail closed;
- the correct workload can exchange in memory for one server-resolved,
  pull-only repository JWT only while its SQL claim/session is live; and
- logs, process arguments, environments, Ansible output, container
  inspection, metrics, retained state, and evidence contain no known secret
  value or token pattern.

### Overlap Rotation

Rotate creates generation 2 alongside generation 1. It never overwrites a
credential, Barbican secret, private key, certificate, materialized filename,
or fingerprint mapping in place. Replicas move one at a time to generation 2;
after each move, both the moved replica and one generation-1 replica must pass
the bounded broker/Distribution read proof.

The overlap gate records the measured Keystone validation-cache bound and the
maximum registry-token lifetime. `revoke-old` is refused until every selected
workload uses generation 2 and the later of those two bounds has elapsed.
`revoke-old` then deletes the immutable generation-1 application credentials,
removes their certificate mappings, proves both old layers fail, removes their
Barbican consumers and secrets, and removes only their exact materialized
files.

### Failure Matrix

`verify-failures` is bounded and restores each dependency before continuing:

1. expired and explicitly deleted application credential;
2. removed `registry_maintenance` role and disabled maintenance user;
3. wrong client key, unknown fingerprint, and expired certificate;
4. Keystone unavailable during exchange;
5. Barbican unavailable during owner materialization, with no partial file;
6. private HAProxy/API replica loss and surviving-replica success;
7. API unavailable after Keystone exchange;
8. stale, completed, revoked, or expired SQL authority;
9. Distribution TLS, timeout, 401, 403, 404, and 5xx responses; and
10. registry-token expiry followed by old-generation rejection.

Every unavailable or ambiguous case remains indeterminate/fail-closed. The
matrix cannot disable TLS verification, expose the API backend directly,
grant a broader role, lengthen credential/token lifetime, or fall back to a
tenant, admin, signer, RGW, or static Distribution credential.

## Abort-Safe Teardown

Teardown is idempotent and runs in dependency order:

1. disable the exact maintenance workers and comparison jobs;
2. close/revoke only the invocation's active SQL sessions;
3. remove only the invocation's HAProxy certificate mappings and revalidate
   the private frontend;
4. delete exact application credentials by immutable ID;
5. remove exact controller and container materializations;
6. delete exact Barbican consumers, then exact secrets by immutable UUID;
7. remove exact role assignments, user, and project by immutable ID;
8. delete `registry_maintenance` only when the ownership flag proves this
   invocation created it and a global read-only reference check is empty;
9. remove temporary files and keep only the redacted terminal evidence; and
10. prove zero owned identities, assignments, credentials, secrets,
    consumers, mappings, materializations, sessions, mounts, environment
    values, and processes remain.

If a destructive step cannot prove exact ownership or empty references,
teardown stops and reports the immutable resource kind plus fixed recovery
action. It never guesses from a name. Loss of the owner-only state changes the
allowed action to read-only forensic inventory; it does not permit prefix
cleanup.

Teardown retains enough non-secret terminal evidence to prove what was
removed, what pre-existed, and that unrelated resource counts and immutable-ID
sets are unchanged. It then removes known secret values from memory and scans
all harness-owned paths before allowing the invocation work directory to be
deleted.

## Implementation and Execution Gates

The next local milestone may add:

- a versioned topology and state schema;
- a pure state-machine/model implementation;
- fixture-driven command adapters;
- read-only preflight/status;
- deterministic cleanup planning; and
- secret-safe unit and shell-contract tests.

It must not create a Keystone object, Barbican secret, certificate, endpoint,
Kolla recipient, SQL session, VM, network, or remote file. Real execution is
permitted only after the model proves exact ownership, resume, rollback,
rotation, revocation, teardown, and secret-safe evidence, and the active plan
records the disposable target and its before-state signature.
