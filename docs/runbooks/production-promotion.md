# Production Promotion Runbook

This runbook operates two compatible but intentionally different promotion
ledgers:

- ledger v1 preserves the original ten-gate all-surfaces transaction;
- ledger v2 independently judges Registry core, storage backend,
  RGW/Barbican KMS, Horizon, Skyline, and Referrers.

Neither ledger converts a functional preview, synthetic fixture, untracked
patch, merged-but-unqualified fix, or locally authored status into production
evidence. Ledger v2 permits only the exact official, approved-vendor, and
Coffer-minimal-patch lineages defined by ADR 0018, under the same product
security threshold.

## Ledger v2 workflow

### 1. Capture v1 provenance without changing v1

Create the additive migration record:

```text
make -C poc/production-promotion migration-v2
```

It validates the canonical v1 ledger and release result, embeds their exact
bytes, records their raw digests and source hashes, and creates:

```text
work/production-promotion/migration-v2.json
```

The migration is negative-first. A legacy blocker remains blocked. A pending
or passed legacy gate remains pending until a v2-native verifier independently
re-runs or revalidates its original payload. The record preserves the exact
legacy evidence reference but cannot use it as a v2 pass.

For an upgrade transaction that must remain eligible for exact-v1 rollback,
capture a signed pre-upgrade checkpoint and the exact archived trust policy
before changing deployment state:

```text
make -C poc/production-promotion migration-v2 \
  MIGRATION_V2_CHECKPOINT=/operator/evidence/checkpoint.json \
  MIGRATION_V2_CHECKPOINT_POLICY=/operator/evidence/trust-policy.json
```

Both values are required together. Supplying neither is valid for analysis,
but the output reports checkpoint `missing` and rollback ineligible.

### 2. Qualify provider inputs

Production policy is
`poc/production-promotion/trust-policy-v2.json`. It is fail-closed and uses
exact catalogs for authorities, vendors, release verification adapters,
lifecycle observers, scope adapters, support, replacements, and revocations.
Adding trust is a reviewed policy change, not a command-line option.

For each provider, produce a signed source-bound input result through
`input_lineage.py`. It must qualify as exactly one of:

- signed official upstream stable release;
- approved vendor backport; or
- Coffer-maintained minimal patch release.

Every class must pass the same conformance, runtime, multi-architecture,
vulnerability, persistence, upgrade, rollback, and teardown threshold.
Vendor and Coffer inputs also require independent rebuild, upstream mapping,
support, lifecycle observation, and bounded retirement evidence. Fixture
policy and fixture results are test-only and cannot be consumed by the
production compiler.

Compile the available provider results:

```text
make -C poc/production-promotion provider-inputs-v2 \
  DISTRIBUTION_INPUT_V2=/operator/evidence/distribution.json \
  CEPH_INPUT_V2=/operator/evidence/ceph.json \
  OSLO_MESSAGING_INPUT_V2=/operator/evidence/oslo-messaging.json
```

An omitted input remains pending unless the migrated v1 observation contains
an explicit blocker. The output is:

```text
work/production-promotion/provider-inputs-v2.json
```

### 3. Compile independent scope evidence

Each scope result is produced by `scope_evidence.py` using its fixed gate set,
mode, provider bindings, exact backend compatibility data, current source
closure, non-synthetic policy-selected adapter, expiry, and signed evidence.
Callers do not supply a final status.

The six inputs are independent:

```text
REGISTRY_CORE_SCOPE_V2=/operator/evidence/registry-core.json
STORAGE_BACKEND_SCOPE_V2=/operator/evidence/storage-backend.json
RGW_BARBICAN_KMS_SCOPE_V2=/operator/evidence/rgw-barbican-kms.json
HORIZON_SCOPE_V2=/operator/evidence/horizon.json
SKYLINE_SCOPE_V2=/operator/evidence/skyline.json
REFERRERS_SCOPE_V2=/operator/evidence/referrers.json
```

Compile the machine-readable decision:

```text
make -C poc/production-promotion ledger-v2 \
  REGISTRY_CORE_SCOPE_V2=/operator/evidence/registry-core.json \
  STORAGE_BACKEND_SCOPE_V2=/operator/evidence/storage-backend.json
```

Add only the selected optional profile inputs to that invocation. A missing
scope is reported as pending unless a required provider has explicit negative
evidence, in which case it is blocked. The owner-only result is:

```text
work/production-promotion/promotion-ledger-v2.json
```

Every migration, provider, scope, ledger, checkpoint, and rollback payload is
strictly bounded; no path may exceed the 16 MiB hard ceiling. Results are
mode 0600 and immutable. Archive a prior transaction in protected storage or
use distinct output paths; never overwrite it to refresh evidence. Each Make
target revalidates only its named stage against the persisted upstream
artifact. It does not silently rebuild an earlier stage or require that
stage's variables again. If the same output path exists, the command succeeds
only when its exact canonical bytes match the requested inputs and current
source/policy; otherwise it fails without changing the file.

### 4. Enforce the intended deployment

`production_candidate=true` means only that Registry core is qualified. It is
not sufficient for a running service. Enforce core plus the selected profiles
with the ledger CLI:

```text
uv run python poc/production-promotion/ledger_v2.py \
  --provider-inputs work/production-promotion/provider-inputs-v2.json \
  --registry-core /operator/evidence/registry-core.json \
  --storage-backend /operator/evidence/storage-backend.json \
  --output /operator/evidence/promotion-ledger-v2.json \
  --require-core \
  --require-profile storage_backend
```

Exit `3` means a requested production decision is unmet; exit `2` means the
evidence or contract is invalid. Requiring core and storage also enforces the
exact tested Distribution-lineage compatibility. Requiring
`rgw_barbican_kms` additionally enforces backend identity and exact core
Distribution input compatibility. Horizon, Skyline, and Referrers are
enforced only when the deployment enables them.

### 5. Downgrade and rollback boundary

There is no v2-to-v1 projection. Exact-v1 replay requires all of:

- the exact embedded v1 bytes and digest;
- a signed pre-upgrade checkpoint;
- a frozen verifier bundle still admitted by the current registry and
  revocation policy;
- matching database, storage, deployment generation, and backup checkpoint;
- separately signed writer fence and rollback authorization;
- one policy-resolved logical destination; and
- a deployment-wide shared-CAS lease and completion store.

The transaction is `claimed -> publishing -> completed`; destination
resolution, authorization, claim, payload, and receipt are digest-bound.
Local output and receipt files are caches only.

Plan 0030 intentionally configures neither a production verifier-registry
entry nor a production shared-CAS adapter. Therefore
`rollback.py` refuses production execution. Its injected fixtures validate
the protocol, concurrency, drift, retry, and outage behavior only. Do not
enable rollback until an operator-owned shared-state adapter, key lifecycle,
and disaster-recovery rehearsal receive a separate deployment decision.

## Legacy ledger v1 decision boundary

The original v1 promotion order is fixed:

```text
release readiness
  -> immutable images on amd64 and arm64
  -> released RGW and Barbican SSE-KMS
  -> maintenance identity lifecycle
  -> backup/import/cutover/rollback/restore
  -> observability and controlled GC
  -> load/soak/fault qualification
  -> fresh Kolla multinode pilot
  -> audited teardown and release closure
```

Stop at the first failed or missing checkpoint. Evidence from a later
checkpoint cannot compensate for an earlier failure.

## Canonical ledger v1

Refresh the complete decision surface with:

```text
make -C poc/production-promotion ledger
```

The command first refreshes release readiness, then consumes only
schema-specific specialist results whose source hashes still match the
checked-in verifiers. It accepts no caller-supplied gate status. The canonical
mode-0600 result is:

```text
work/production-promotion/promotion-ledger.json
```

Every one of the ten fixed gates is exactly one of:

- `passed`: a dedicated verifier accepted current source-bound evidence;
- `blocked`: a prerequisite verifier reported a failed gate; or
- `pending`: the required live specialist evidence is absent.

A local fixture, preview observation, plan checkbox, manually authored
`passed`, or success in another gate cannot change that classification. Use
`make -C poc/production-promotion require-promotion` as the final enforcement
target; it remains nonzero until the ledger itself derives
`production_candidate=true`.

The approved disposable filesystem GC result can be refreshed independently
with:

```text
make -C poc/gc-retention/filesystem promotion-evidence
```

It is emitted only after two equal dry runs, one consumed authorization,
destructive collection, survivor/reclaim/restore verification, and zero
fixture residue. Its filesystem scope does not satisfy RGW/KMS, data
protection, or load gates.

## V1.1 Refresh released inputs

Run:

```text
make -C poc/production-promotion check
make -C poc/production-promotion require-qualified
```

The first command records the current fail-closed observation. The second is
the pipeline gate and fails until Distribution, Ceph, and the OpenStack UI
dependency are all `candidate-qualified` (`readiness.py` itself exits `3` for
an unmet gate). The owner-only result is:

```text
work/production-promotion/release-readiness.json
```

Every invocation reads current official Distribution/Ceph GitHub metadata,
PyPI `oslo.messaging` release files, and OpenDev stable constraints, tag,
source, and bounded history data. It rejects redirects, oversized or malformed
payloads, an ambiguous constraint/artifact set, a tag that does not resolve to
one commit, or a selected release lacking the exact stable patch and source
probe. The checked-in UI JSON remains the reviewed policy and baseline; live
observation happens in memory and is bound into the owner-only result.

Do not continue with an unreleased branch, private wheel, mutable image tag,
unreviewed VEX, or a result whose UI metadata is older than one day.

## V1.2 Qualify immutable images

For the exact released versions and revisions in the readiness result:

1. build the Coffer, Distribution, Horizon, and Skyline images independently
   on native amd64 and arm64;
2. bind source revision, release provenance, image manifest digest, image
   configuration digest, SBOM, and scanner inputs in one transaction;
3. run the Coffer runtime contract and OCI supported-profile conformance;
4. record malformed-reference and Referrers behavior; and
5. require zero unresolved reachable Critical/High and zero secret findings.

Never combine evidence from different image names, architectures, source
revisions, archives, SBOM identities, or scanner database transactions.

After both native transactions finish, stage only owner-mode-0600 specialist
inputs under `work/production-promotion/artifacts/` as documented in
`poc/production-promotion/README.md`, then run:

```text
make -C poc/production-promotion artifact-result
make -C poc/production-promotion ledger
```

The artifact compiler checks release readiness before it opens an image result.
It refuses the current blocked release input without reading stale ARM-only or
partial x86 evidence. A final result requires exact amd64/arm64 core and UI
qualification, zero Critical/High and secret findings, zero Distribution
govulncheck findings, immutable image IDs, and equal cross-architecture
source/wheel identities.

## V1.3 Qualify RGW and Barbican SSE-KMS

Use a disposable released Ceph/RGW target with verified private TLS and the
exact qualified Distribution image. Require:

- positive-size and zero-byte encrypted moves;
- correct-key success and wrong-key/KMS-outage fail-closed behavior;
- recovery, overlapping key rotation, and restart persistence;
- complete multipart cleanup;
- dedicated bucket credentials with least privilege; and
- zero credential, key, object, version, multipart, and tunnel residue.

The merged Ceph source fix alone is not evidence. The selected official
release must contain it and pass the live matrix.

The specialist input is one canonical owner-mode-0600
`work/production-promotion/rgw-kms-evidence.json`. It binds the exact release
readiness digest, Distribution/Ceph versions and revisions, three live phase
completions, fault, rotation, restart, least-privilege, and cleanup evidence
hashes, plus the current pilot/runtime source hashes. It deliberately contains
no endpoint, bucket, credential, KMS key ID, object, upload, or error text.

Compile and bind it to the ledger with:

```text
make -C poc/production-promotion rgw-kms-result
make -C poc/production-promotion ledger
```

The compiler validates release readiness before opening the evidence path. The
current blocked release therefore exits before any endpoint, credential, KMS,
S3, or fault input is read. A later result passes only if zero-byte copy,
wrong-key and outage recovery, overlapping rotation, RGW and Distribution
restart persistence, cleanup of at least one incomplete multipart upload, and
zero operational or secret residue all validate against the same release
observation consumed by the ledger.

## V1.4 Qualify maintenance identity and data protection

Run the maintenance lifecycle with one expiring owner-controlled application
credential, per-replica mTLS, private ingress, bounded SQL authority, rotation,
revocation, audit, and teardown. Public ingress must not forward the
maintenance path.

Stage its redacted terminal evidence at
`work/production-promotion/maintenance-identity-evidence.json`, then run:

```text
make -C poc/production-promotion maintenance-identity-result
make -C poc/production-promotion ledger
```

The compiler refuses to open identity evidence until the exact release,
multi-architecture artifact, and RGW/KMS specialist results qualify. It
accepts only a non-synthetic OpenStack adapter execution covering all fixed
workloads, exact finite authority, private-mTLS denials, two-generation
overlap and revocation, the bounded failure matrix, audit/log scans, terminal
teardown, and zero secret or operational residue. The fixture-only lifecycle
model cannot promote this gate.

On a representative disposable copy, then prove:

- writer exclusion and no active upload;
- restorable SQL plus RGW versioned backup;
- exact-release logical inventory;
- transactional import and authenticated comparison;
- atomic admission cutover;
- rollback without divergent writes;
- backup recovery and the fixed failure matrix; and
- unchanged unrelated resources with all owned residue counts at zero.

Production tenant data is never a rehearsal target.

## V1.5 Qualify operations, GC, and load

Verify direct per-replica API, edge, registry, reconciliation, database, RGW,
KMS, HAProxy, and host signals. Counters must remain correct across process and
container restarts; labels must stay bounded. Record alert rules, logs, SLOs,
and failure budgets.

Run coordinated write-stopped upstream Distribution GC only with the accepted
one-shot authorization. Keep `--delete-untagged` disabled. Restore referenced
content and treat RGW physical version cleanup as a separate operation.

The representative load transaction must include the accepted real-client
matrix, monolithic/chunked/resumed uploads, cross-mount, artifacts, quota
contention, Galera retries/deadlocks, reconciler fencing, replica/dependency
faults, saturation, and the full soak window. All recovery deadlines,
availability/latency limits, data invariants, and residue checks must pass.

## V1.6 Run the fresh Kolla multinode pilot

Create a new isolated three-controller and three-storage-node topology only
from the qualified immutable artifacts. Use independent failure domains,
generally trusted or explicitly operator-managed production PKI, Galera,
HAProxy, released Ceph/RGW, and private maintenance ingress.

Run deploy, tenant isolation, client acceptance, replica loss, fencing,
signing-key rotation, rolling upgrade, compatible rollback, backup, restore,
and reconfigure idempotency. Then remove the exact pilot and independently
audit that all owned identities, credentials, secrets, buckets, objects,
databases, containers, VMs, volumes, networks, routes, and temporary trust
material are absent.

Do not promote the retained same-host UI preview or reuse its owner-local CA
as this pilot.

## V1.7 Close the release

Stage the redacted independent-review evidence at
`work/production-promotion/operator-release-evidence.json`, then run:

```text
make -C poc/production-promotion operator-release-result
make -C poc/production-promotion require-promotion
```

The compiler validates all first nine result files before it opens the review
evidence. It also recomputes the source-tree, operator-documentation, plan,
handoff, dependency-lock, and ADR hashes. Any source or documentation change
after review invalidates the result and requires a new review transaction.

The final reviewer must match every checked Stage 6 criterion to its canonical
evidence and verify:

- the evidence source revision equals the release revision;
- every artifact identity and digest is immutable;
- all specialist verifiers passed without waiver;
- repository regression, secret scanning, and documentation checks pass;
- no external or disposable residue remains; and
- `HANDOFF.md`, ADRs, release notes, install/upgrade/rollback/backup/restore/GC
  procedures, known limitations, and SLOs match the evidence.

All ADRs must have a final `accepted`, `rejected`, or `superseded`
disposition. `proposed`, `accepted for PoC validation`, or another qualified
status is unresolved and fails the gate. The compact result must contain no
reviewer identity, local path, credential, endpoint, log, or staged-artifact
content. The source-bound `docs/release-notes/v0.1.0.md` promotion status must
remain `blocked` until the first nine results qualify; the final review changes
it to `production-candidate` and binds that exact digest into the tenth result.

Only then may the plan status become `completed` and the result set
`production_candidate=true`. Official Kolla/OpenStack upstream inclusion is a
separate governance phase.
