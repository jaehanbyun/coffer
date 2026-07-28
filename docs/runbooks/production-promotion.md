# Production Promotion Runbook

This runbook promotes a Coffer operator-local release only after every Stage 6
gate has passed. It never converts a functional preview, synthetic fixture,
merged-but-unreleased fix, or locally patched dependency into production
evidence.

## Decision boundary

The promotion order is fixed:

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

## Canonical gate ledger

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

## 1. Refresh released inputs

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

Do not continue with an unreleased branch, private wheel, mutable image tag,
unreviewed VEX, or a result whose UI metadata is older than one day.

## 2. Qualify immutable images

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

## 3. Qualify RGW and Barbican SSE-KMS

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

## 4. Qualify maintenance identity and data protection

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

## 5. Qualify operations, GC, and load

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

## 6. Run the fresh Kolla multinode pilot

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

## 7. Close the release

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
