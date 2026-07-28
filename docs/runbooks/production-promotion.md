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

## 4. Qualify maintenance identity and data protection

Run the maintenance lifecycle with one expiring owner-controlled application
credential, per-replica mTLS, private ingress, bounded SQL authority, rotation,
revocation, audit, and teardown. Public ingress must not forward the
maintenance path.

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

The final reviewer must match every checked Stage 6 criterion to its canonical
evidence and verify:

- the evidence source revision equals the release revision;
- every artifact identity and digest is immutable;
- all specialist verifiers passed without waiver;
- repository regression, secret scanning, and documentation checks pass;
- no external or disposable residue remains; and
- `HANDOFF.md`, ADRs, release notes, install/upgrade/rollback/backup/restore/GC
  procedures, known limitations, and SLOs match the evidence.

Only then may the plan status become `completed` and the result set
`production_candidate=true`. Official Kolla/OpenStack upstream inclusion is a
separate governance phase.
