# Disposable Existing-Data Protection and Cutover Rehearsal

This directory owns the Stage 6 disposable proof that existing Distribution
content can be inventoried, backed up, imported, compared, admitted, rolled
back, restored, and removed without touching production data. It converges the
read-only inventory, transactional import, ledger comparison, authenticated
live comparison, maintenance identity, and Kolla ingress contracts already
proven separately.

This document fixes the phase and ownership contract before an RGW/S3 helper,
backup adapter, database, bucket, identity, credential, certificate, endpoint,
container, or remote resource is created.

## Exact-Release Inventory Helper

The existing `poc/inventory` helper is deliberately filesystem-only. It
constructs `filesystem.New` directly and therefore cannot qualify RGW or a
production Distribution configuration.

The Stage 6 helper must be built from the exact selected, signed Distribution
source release and use the same exported construction seam as that release:

1. blank-import the selected release's `s3-aws` storage driver so its factory
   registers the `s3` and `s3aws` names;
2. parse one owner-only Distribution configuration with the release's
   `configuration.Parse`;
3. require one exact `s3` or `s3aws` storage type and obtain only
   `Storage.Type()` plus `Storage.Parameters()`;
4. require verified TLS (`secure=true`, `skipverify=false`) and an HTTPS RGW
   endpoint, exact bucket/root prefix, path-style disposition, region, and
   finite client timeouts;
5. construct the driver with `factory.Create`, then the namespace with
   `storage.NewRegistry`;
6. assert `distribution.RepositoryEnumerator` and
   `distribution.ManifestEnumerator`, then reuse the canonical two-scan
   evidence and Coffer verifier; and
7. record the Distribution version, source revision, module sums, helper
   digest, storage type, non-secret configuration digest, bucket/root hashes,
   and enumerator identity.

The helper must not start `registry.NewRegistry` or `handlers.NewApp`, because
those paths also configure HTTP handlers, upload purging, cache, events,
middleware, and health state. It must not enable delete, execute garbage
collection, list raw RGW keys as registry authority, parse human GC output, or
call Coffer SQL. Repository and manifest enumerators are the selected
release's read-only logical storage seam.

Storage middleware is refused in the first production qualification. The
helper cannot reproduce the application's unexported middleware assembly and
must never silently enumerate a different view. Proxy/pull-through mode,
multiple drivers, insecure transport, ambient AWS credentials, instance
metadata credentials, an empty bucket/root, or a configuration whose digest
does not match the stopped registry are also refused.

The owner passes the mode-0600 configuration by file descriptor or exact
read-only file mount. Secrets never enter arguments, environment variables,
stdout, retained evidence, image layers, SBOMs, or process inspection. The
helper container receives network access only to the exact verified-TLS RGW
endpoint and runs with no registry listener, SQL endpoint, Keystone
credential, Barbican controller credential, registry signing key, or host
socket.

## Owned Disposable Topology

Every rehearsal uses one lowercase 26-character invocation ULID and the prefix
`coffer-cutover-<invocation-id>`. Exact immutable IDs returned by creation are
stored in an ignored owner-only state file. Names or prefixes are never
mutation or deletion targets.

The rehearsal may own only:

- one source project/repository fixture and its finite tenant credential;
- one source RGW user, bucket, root prefix, and stopped Distribution instance;
- one backup bucket or owner-only backup tree plus a backup manifest;
- one restored RGW user/bucket/root and Distribution instance;
- one source, one cutover, and one restore SQL database;
- one maintenance comparison session and its fixture-bound identity material;
- one private ingress mapping and one admission toggle for the exact target;
- exact containers, networks, volumes, configuration trees, locks, and
  evidence declared by the topology; and
- generated test manifests, blobs, indexes, tags, and untagged revisions under
  the invocation's project/repository only.

The harness refuses an existing name without matching retained immutable IDs,
an unexpected writer, bucket owner, database, endpoint, listener, container,
network, volume, SQL schema revision, Distribution version/revision,
configuration digest, or RGW/Ceph release.

## State and Phase Model

State lives only under:

```text
work/data-protection/<invocation-id>/
  state.json
  lock
  materialized/
  backup/
  evidence/
```

The directory is owner mode `0700`; state, configuration, backup, and
materialized secret files are regular single-link mode `0600`. State is
atomically replaced under a nonblocking per-invocation lock. It retains
immutable IDs, hashes, counts, transitions, and fixed failure categories, not
credentials, secret UUIDs, payload keys, repository names, tenant paths,
Authorization headers, tokens, private keys, SQL rows, object bytes, or raw
logs.

The ordered phases are:

```text
preflight
  -> source-created
  -> fixture-populated
  -> writers-excluded
  -> backups-verified
  -> inventory-verified
  -> baseline-imported
  -> live-comparison-verified
  -> admission-cutover
  -> cutover-verified
  -> rollback-verified
  -> restore-verified
  -> failures-verified
  -> torn-down
```

Every mutating phase records `started` before its first mutation and
`completed` only after its exit checks. An exit trap can remove only immutable
resources recorded as created by that invocation. Resume requires the exact
before-state and previous phase; a partial phase either converges its exact
resources or rolls them back before retry.

## Rehearsal Phases

### 1. Preflight and source fixture

Preflight is read-only and records:

- selected signed Distribution and released Ceph/RGW versions and revisions;
- helper image/binary digest and module-sum lock;
- exact cloud, cluster FSID, RGW endpoint/certificate, bucket/root, SQL
  endpoint/schema, Kolla deployment, VIP, and ingress configuration hashes;
- absence of every generated name;
- current unrelated identity/bucket/database/container/network/volume sets;
  and
- capacity for two independent object copies, three disposable databases, and
  retained evidence.

The source fixture then creates deterministic OCI coverage through unmodified
clients: tagged image manifests, an untagged manifest, nested indexes,
cross-repository shared blobs, zero-byte and positive-size blobs, multipart
uploads, artifacts/Referrers according to the selected release disposition,
and a bounded over-quota repository. It records only canonical content hashes
and counts.

### 2. Writer exclusion

The harness must block every write path before backup or inventory:

- public `/v2/` `POST`, `PUT`, `PATCH`, and `DELETE`;
- direct/private registry ingress;
- upload continuation and mount paths;
- Coffer repository/admission mutations;
- reconciliation or GC workers that could change ledger/content state; and
- any fixture client or external writer credential.

Reads remain available for the comparison proof. Writer exclusion is evidence,
not a boolean supplied by the caller. It binds the exact ingress/config
digests, running replica set, disabled workers, zero active uploads, database
writer fence, start time, and later release time. A canary write through every
known ingress must fail while a digest read succeeds. Any unknown listener,
replica, active upload, changing object/SQL signature, or unaccounted writer
fails the phase.

### 3. Restorable SQL and RGW backup

After exclusion:

1. take a transactionally consistent SQL backup with server/version/schema,
   GTID or equivalent recovery coordinates, tool version, checksum, size, and
   exact database ownership;
2. restore it immediately into the isolated restore database and run schema,
   row-count, baseline-marker, repository, reservation, and comparison checks;
3. stream every source bucket object/version plus required metadata into an
   owner-only logical backup or dedicated backup bucket;
4. verify a canonical manifest of key hashes, versions, sizes, ETags,
   checksums, metadata hashes, encryption disposition, multipart absence, and
   total bytes; and
5. restore into the isolated restore bucket/root and compare the exact
   Distribution inventory plus bounded client pull digests.

The logical RGW adapter must use exact object identifiers obtained from a
versioned listing and never infer registry authority from those keys. It is
backup transport only. Restore writes use the selected KMS policy and prove
plaintext content digests without retaining payloads. A Ceph/RGW
operator-native snapshot or multisite backup may replace the logical adapter
only through an ADR and the same restore checks.

No backup is accepted merely because the command exited zero. Both SQL and RGW
copies must be restored and read before import or cutover proceeds.

### 4. Exact inventory, import, and authenticated comparison

With writers still excluded:

1. run the exact-release RGW helper twice against the stopped source registry;
2. require identical repository, record, descriptor, and artifact hashes;
3. validate it with the installed `coffer-inventory-verify`;
4. import the exact artifact into the empty cutover database with its digest
   and idempotency request;
5. replay the same import as a no-op and reject a conflicting digest;
6. run the SQL ledger comparison;
7. open one finite maintenance comparison session bound to the inventory
   digest and writer-exclusion evidence; and
8. use private verified TLS and pull-only registry tokens to prove every
   imported live manifest before closing the session.

Missing authority, an unsupported reference/media type, scan drift, SQL
conflict, over-limit usage, stale claim/session, wrong workload, failed live
HEAD, or a changed source signature blocks cutover.

### 5. Admission cutover and rollback

Cutover changes only the disposable target:

- place the verified imported database behind API/edge/reconciliation;
- force `/v2/` through the quota edge with direct Distribution ingress closed;
- release only the exact admission writer fence;
- verify existing pulls and new push/finalize accounting;
- verify project isolation, over-quota 429, dependency 503, restart
  persistence, and reconciliation; and
- retain a cutover marker bound to all backup, inventory, import, comparison,
  image/config, and writer-exclusion hashes.

Rollback takes a second write fence, proves no active uploads, restores the
pre-cutover routing/database/content authority, and verifies the original
digests and denial boundary. It cannot merge divergent writes. If a post-
cutover write occurred, the harness either removes only its exact disposable
objects under a recorded rollback manifest or restores the isolated backups;
an ambiguous difference stops rollback.

### 6. Recovery and failure matrix

Recovery destroys only the disposable cutover database and restored bucket,
then recreates both from the accepted backups. The exact inventory, SQL
comparison, authenticated live comparison, pull digests, and admission checks
must pass again.

Bounded failures cover:

- SQL backup interruption, corrupt/truncated backup, and restore failure;
- RGW listing pagination drift, object read failure, corrupt backup object,
  incomplete multipart state, KMS/wrong-key outage, and restore interruption;
- source signature change during the two scans;
- helper release/configuration mismatch or insecure TLS;
- import transaction failure, conflicting replay, deadlock, and restart;
- maintenance identity/private frontend/API/Distribution outage;
- admission cutover partial failure and rollback interruption; and
- one API, edge, registry, database, RGW, and load-balancer replica loss.

Each failure restores the dependency before the next case, changes no
production or unrelated state, and emits a fixed secret-safe result.

## Teardown and Residue

Teardown is idempotent and uses immutable IDs in this order:

1. reapply the exact writer fence and stop fixture clients/workers;
2. close/revoke the exact maintenance session and private mapping;
3. restore pre-rehearsal ingress/admission configuration;
4. remove cutover/restore Distribution instances and databases;
5. remove restored, backup, and source object versions plus multipart uploads;
6. remove exact RGW users, tenant/maintenance credentials, identities, and
   assignments;
7. remove exact materializations, configuration copies, containers, volumes,
   networks, locks, and temporary files; and
8. prove all owned resource/residue counts are zero and every unrelated
   before-state immutable-ID set is unchanged.

Lost state, a mismatched immutable ID, referenced backup, unknown object
version, nonempty multipart upload, active writer, or changed unrelated
signature stops deletion. No prefix, wildcard, bucket purge, database pattern,
container label query, or `--remove-all-storage` operation is an allowed
mutation target.

Retained terminal evidence contains only schemas, component
versions/revisions, configuration/helper/artifact/backup hashes, aggregate
counts and bytes, timings, fixed failure outcomes, before/after set hashes, and
zero-residue results.

## Implementation Sequence

The exact-release helper adapter milestone completed steps 1 through 4:

1. extract the current canonical scan/evidence logic from
   `poc/inventory/main.go` without changing its filesystem result;
2. add an exact-release `s3`/`s3aws` configuration adapter using
   `configuration.Parse` and `factory.Create`;
3. reject middleware, proxy, insecure TLS, ambient credentials, and mismatched
   release/config evidence before driver construction;
4. add fixture tests for configuration and secret-safe failures;
5. preserve filesystem fixture regression before any live RGW execution.

The implementation now shares the namespace scan core between filesystem and
S3, parses the selected Distribution configuration, constructs only the
registered S3 driver/namespace, refuses the prohibited configuration and
ambient credential paths, and bounds both scans with one context. Seven Go
configuration tests, Go vet, the existing filesystem Podman fixture, and its
zero-residue cleanup pass. That original milestone made no RGW connection.
On 2026-07-28 a later anticipatory read-only invocation connected the same
helper to the retained preview RGW over verified TLS, produced equal scans,
preserved compatible Docker/OCI blob aliases in inventory v3, passed
disposable SQLite import/replay/verification, and removed all remote transient
material. It did not exclude writers or exercise backup, restore, cutover, or
rollback.

The provenance/image milestone is also complete locally. S3 evidence v2 binds
the exact Distribution revision, canonical module graph, helper binary,
configuration, storage type, endpoint, bucket, and root hashes. The verifier
preserves those values in inventory v2 and the importer validates them before
the artifact digest is accepted; filesystem evidence/inventory v1 remains
unchanged.

The helper image uses a digest-pinned Go 1.25.3 builder and a scratch final
stage containing only the static helper and CA bundle. It runs as
`65532:65532`, has no shell, server binary, listener, command override, or
exposed port, and accepts only the helper entry point. A local ARM64 build and
no-network CLI inspection passed, then the exact image and Podman VM were
removed.

The pure topology and state-machine milestone is complete locally. The model
pins every disposable resource, phase, failure case, cleanup dependency, and
residue category. It accepts a transition only when the preceding phase,
phase-specific evidence set, canonical history, stable source signature,
restored SQL/RGW manifests, equal exact-release inventory scans,
provenance-bound cutover marker, exact rollback manifest, complete failure
matrix, and unchanged unrelated-resource signature all agree.

The model also refuses incomplete or renamed resources, duplicate immutable
IDs, out-of-order transitions, partial writer fences, unrestored backups,
multipart residue, inventory drift, incomplete import/live/cutover/rollback
proofs, partial cleanup targets, partial residue reports, tampered histories,
extra phase evidence, and secret-bearing retained payloads. Terminal state
requires all fixed residue categories to be explicit zeroes.

The fixture-only lifecycle command milestone is also complete locally.
Read-only `preflight`, `status`, and hashed cleanup planning cannot select an
adapter. Every mutating phase requires the exact `fixture` adapter, target and
unrelated signatures, topology, and fixture artifact. State is atomically
replaced as an owner-only mode-0600 regular file under a nonblocking
invocation lock and a mode-0700 directory. Unsafe existing paths, modes,
links, concurrent actions, phase skips, fixture drift, target drift, partial
residue evidence, and secret-bearing fixtures fail with one fixed category
without exposing details or changing the accepted state.

The complete fixture flow reaches all 14 phases, emits cleanup targets only
with hashed immutable IDs, tears down to the complete zero-residue terminal
state, and repeats teardown idempotently. It imports no external service
client and has no network adapter.

The canonical SQL/RGW backup verifier milestone is complete locally. The
versioned bundle binds the exact invocation, target, topology, fixture adapter,
tool and server versions, SQL schema/recovery coordinate, logical-content and
artifact digests, and an isolated SQL restore. RGW evidence requires complete
version pagination, canonically ordered unique key/version hashes, zero- and
positive-size SSE-KMS object versions, delete markers, checksums, ETags,
metadata and KMS-policy hashes, zero multipart residue, and an isolated
bucket/root whose inventory, metadata, aggregate counts/bytes, and client-pull
digests match the source.

The verifier emits only canonical hashes, counts, versions, and booleans.
Its CLI accepts only an owner mode-0600 regular single-link input and can
atomically write to a pre-existing owner mode-0700 evidence directory. It does
not create or repair unsafe directories. The lifecycle now derives its SQL and
RGW phase evidence only from this verifier; an unverified bundle cannot enter
`backups-verified`.

The no-network backup adapter milestone is complete locally. Typed MariaDB and
versioned-S3 seams expose only inspection, backup/copy, and isolated-restore
observations. The implementation accepts only the exact in-process fixture
client classes; a lookalike or future real client is rejected until a separate
disposable target contract exists. It enforces SQL inspect/backup/restore
ordering, bounded nonempty S3 pagination with cursor-cycle refusal, an exact
version-set copy digest, isolated restore ordering, canonical verification,
and byte-for-byte reconstruction of the accepted fixture bundle.

The adapter API and results contain no credential parameters or fields and the
module imports no network, subprocess, S3, SQL, or HTTP runtime. The lifecycle
now reaches `backups-verified` only through this ordered adapter and the
canonical verifier.

Live MariaDB and RGW backup/restore adapters and the full disposable rehearsal
remain deferred until an explicit target contract and acceptable released
dependency inputs can be bound to a fresh isolated pilot. The read-only preview
inventory observation is not a substitute for that rehearsal. This
data-protection boundary must not be weakened when live clients are added.
