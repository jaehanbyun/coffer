# Production Promotion Release Readiness

This harness is the first fail-closed checkpoint for Stage 6. It combines the
official release state for CNCF Distribution, Ceph Tentacle, and the
OpenStack `stable/2026.1` `oslo.messaging` dependency. All three must reach
`candidate-qualified` before a production image, RGW/KMS, load, or fresh
multinode pilot may be treated as promotion evidence.

Run the read-only refresh from the repository root:

```text
make -C poc/production-promotion check
```

The result is written mode `0600` under ignored
`work/production-promotion/release-readiness.json`. A blocked result is a
successful observation and exits zero. A promotion pipeline must instead run:

```text
make -C poc/production-promotion require-qualified
```

The underlying Python gate exits `3` until every exact release input has
already passed its specialist qualification; `make` reports that nonzero gate
as a failed target. It does not build an image, contact the retained preview,
create a credential, start a VM, or mutate an OpenStack service.

The UI observation is deliberately allowed to be at most one day old. Refresh
the checked-in observation only from official PyPI and OpenStack
`stable/2026.1` constraints metadata. An old observation fails as invalid
evidence instead of silently reporting the last known state.

`release_inputs_qualified=true` is only permission to begin the remaining
Stage 6 sequence. The aggregate always keeps `production_candidate=false`;
the final production decision additionally requires image, RGW/KMS,
maintenance identity, data protection, observability, GC, load/soak, fresh
Kolla multinode, teardown, and operator-release evidence.

## Canonical promotion ledger

Run:

```text
make -C poc/production-promotion ledger
```

This refreshes official release readiness, validates any retained GC result
through its dedicated verifier, and writes the mode-0600 canonical ledger to
`work/production-promotion/promotion-ledger.json`. The ledger has ten fixed,
ordered gates:

1. official release inputs;
2. immutable multi-architecture artifacts;
3. RGW/Barbican SSE-KMS;
4. the expiring maintenance identity;
5. backup/import/cutover/rollback;
6. production observability;
7. coordinated GC/restore;
8. representative load/soak/faults;
9. fresh Kolla multinode plus audited teardown; and
10. operator release and supply-chain review.

The command accepts no caller-supplied gate status. A gate can become `passed`
only through a schema-specific validator over a source-bound specialist result.
Absent live evidence remains `pending`; failed release readiness remains
`blocked`. Local fixtures, preview observations, a plan checkbox, or a manually
authored `passed` value cannot promote another gate.

The immutable-artifact specialist command is:

```text
make -C poc/production-promotion artifact-result
```

It validates release readiness before opening any image evidence. The current
blocked Distribution, Ceph, or oslo.messaging result therefore exits `3`
without reading the expected artifact paths or writing an output. After
release qualification, the command requires owner-mode-0600 core and UI
qualification results for native Linux amd64 and arm64 under:

```text
work/production-promotion/artifacts/
  amd64/core/{qualification.json,images.json}
  amd64/ui-qualification.json
  arm64/core/{qualification.json,images.json}
  arm64/ui-qualification.json
```

Both architectures must independently have runtime/provenance, immutable image
IDs, SBOMs, zero secrets, zero Critical/High findings, and zero Distribution
govulncheck findings. Kolla/Horizon/Skyline revisions and UI wheel hashes must
match across architectures. Only then is the mode-0600
`artifact-result.json` created and eligible for the ledger. The older ARM-only
blocked results and partial x86 UI transaction cannot be reused as qualified
evidence.

The RGW/Barbican specialist command is:

```text
make -C poc/production-promotion rgw-kms-result
```

It also validates candidate-qualified release readiness before opening its
expected evidence file. With the current Ceph Tentacle v20.2.2 result, it exits
`3` without reading an endpoint, credential, KMS key, S3 configuration, or
`rgw-kms-evidence.json`, and it creates no output.

Once an official Ceph release contains the encrypted-copy fix and all release
inputs qualify, the non-synthetic disposable pilot must write one canonical
mode-0600 evidence document at:

```text
work/production-promotion/rgw-kms-evidence.json
```

The document is bound to the exact release-readiness digest and to the checked
in live-adapter, fault-controller, cleanup, schedule, executor, and collector
sources. It must prove:

- verified private TLS, S3 signature v4, path-style addressing, bucket
  versioning, Barbican SSE-KMS, and denied over-privileged operations;
- positive-size and zero-byte put/copy plus head/get;
- wrong-key and KMS-outage fail-closed behavior followed by recovery;
- zero unexpected KMS or storage errors across the bounded phase set;
- overlapping two-generation key rotation and old-key retirement;
- Distribution and RGW restart persistence for zero- and positive-size
  objects;
- cleanup of a real incomplete multipart upload, objects, versions, and delete
  markers; and
- zero retained object, multipart, selected-key, credential, configuration,
  log, host, or runtime-file residue.

Operational identities and secrets are not accepted by the result schema.
Only their evidence hashes survive in
`coffer.production-promotion-rgw-kms-result/v1`. The ledger also requires this
specialist result to name the exact current release-readiness digest; a valid
result from another release observation cannot pass the gate.

The maintenance-identity specialist command is:

```text
make -C poc/production-promotion maintenance-identity-result
```

It validates release readiness, the immutable-artifact result, and the RGW/KMS
result—in that order—before opening
`work/production-promotion/maintenance-identity-evidence.json`. The current
release block therefore exits `3` before any missing downstream result,
endpoint, credential, certificate, Barbican secret, Kolla recipient, or
identity evidence is read.

After all prerequisites qualify, the evidence must be a non-synthetic
OpenStack execution of the checked lifecycle contract. It binds the exact
prerequisite digests and current lifecycle, token broker, SQL authority,
private HAProxy, Kolla precheck, and reconciler sources. A result requires:

- all three fixed workloads, both non-overwritten generations, exact roles and
  access rule, restricted finite application credentials, disabled runtime
  password, and pull-only server-authorized registry JWTs;
- verified private mTLS plus denial of the public internal path, wrong
  certificate, fingerprint, workload, method, and path;
- overlap lasting at least the Keystone cache/registry-token bound, followed
  by old credential, mapping, and secret revocation;
- the bounded dependency, authority, certificate, replica, and Distribution
  failure matrix;
- a torn-down `coffer.maintenance-identity-evidence/v1` terminal state,
  nonempty audit/log scans, zero unexpected errors and known-secret matches;
  and
- zero identity, credential, secret, mapping, materialization, session,
  process, environment, and temporary-file residue.

The compact specialist result omits invocation, target, immutable resource,
certificate, project, user, credential, secret, token, endpoint, and log
identities. The canonical ledger passes this gate only when the exact release,
artifact, and RGW/KMS evidence digests all match the same ledger transaction.
The local fixture lifecycle is useful contract coverage but can never satisfy
the required `non_synthetic=true`, `adapter=openstack` boundary by itself.

The data-protection specialist command is:

```text
make -C poc/production-promotion data-protection-result
```

It validates the exact release, immutable-artifact, RGW/KMS, and maintenance
identity specialist results before opening
`work/production-promotion/data-protection-evidence.json`. The evidence must
come from one non-synthetic, disposable OpenStack transaction and bind all
four prerequisite digests plus the checked-in backup, inventory, import,
quota, lifecycle, and topology sources. The current release block exits `3`
before any missing backup, credential, endpoint, or runtime evidence is read.

A qualified result requires:

- writer exclusion with zero active uploads or unknown listeners, denied write
  canaries, successful digest reads, and a stable source signature;
- SQL and versioned SSE-KMS RGW backups restored into an isolated target, with
  equal inventory and no incomplete multipart uploads;
- `coffer.inventory/v3`, equal repeated scans, atomic import, idempotent replay,
  conflicting-replay refusal, zero partial rows, and a closed pull-only private
  TLS live-comparison session;
- forced quota-edge cutover, closed direct Distribution access, tenant
  isolation, accounted new writes, quota `429`, dependency `503`, restart
  persistence, and reconciliation;
- writer-fenced rollback and backup recovery that remove exactly the
  post-cutover writes, retain the original digest, and repeat authenticated
  comparison and admission checks;
- all 22 fixed backup, RGW/KMS, import, maintenance, dependency, cutover,
  rollback, and replica-loss failure cases;
- a terminal 14-phase `torn-down` lifecycle, unchanged unrelated state, and
  zero identity, credential, session, bucket, object-version, multipart,
  database, container, file, volume, network, lock, or known-secret residue.

The compact result intentionally omits invocation IDs, endpoints, resource
identities, project/repository names, credentials, object keys, and secrets.
The canonical ledger passes `data_protection` only when its prerequisite
digests equal the same release, artifact, RGW/KMS, and maintenance-identity
results already validated in that ledger transaction. The existing fixture
or the retained UI preview cannot satisfy this live boundary.

The production-observability specialist command is:

```text
make -C poc/production-promotion observability-result
```

It validates the exact release, artifact, RGW/KMS, maintenance-identity, and
data-protection results before opening
`work/production-promotion/observability-evidence.json`. A valid evidence
document must bind those five digests and the checked-in runtime collectors,
direct-target topology, registry metrics proxy, Prometheus targets/rules,
Grafana dashboard, and runbook. Current blocked release readiness exits `3`
before any missing target, monitoring credential, or downstream evidence is
read.

The live disposable OpenStack proof must include:

- every API, edge, reconciler, and registry replica scraped directly through
  verified backend TLS, with the public FQDN and VIP refused and at least two
  API, edge, and registry replicas;
- operator-network-only metrics, public operational-path denial, loopback-only
  Distribution debug, an allowlisted metrics proxy, and denied profiling;
- the exact bounded label, six recording-rule, eight alert, and eight dashboard
  row contracts, one worker per API/edge container, a process-start metric,
  valid reset semantics, stale-series removal, and zero duplicate healthy
  series;
- rolling restart, upgrade, and rollback across every component without loss
  of service/rule continuity;
- firing and recovery evidence for all eight fixed alerts, native dependency
  correlation, and the accepted 30-day pull/publish/control/reconciliation
  objective plus fast/slow burn and work-freeze behavior;
- nonempty sample, alert-evaluation, and log scans with zero forbidden labels,
  known secrets, unexpected errors, and runtime/monitoring residue.

Only bounded counts, booleans, and evidence digests survive in the compact
result; target addresses, hostnames, projects, repositories, request IDs,
credentials, tokens, and log contents do not. The local observability fixtures
and retained same-host preview prove implementation contracts only and cannot
produce this `adapter=openstack`, `non_synthetic=true` specialist result.

The disposable filesystem harness remains the first GC step:

```text
make -C poc/gc-retention/filesystem promotion-evidence
```

That mode-0600 result is deliberately fixed to its exact Distribution version,
revision, image, collector, authorization, survivor, restore, and teardown
sources. It is not consumed directly by the promotion ledger. Bind it to the
candidate-qualified release and immutable-artifact transaction with:

```text
make -C poc/production-promotion gc-retention-result
```

The wrapper exits `3` before reading missing artifact or GC paths while release
readiness is blocked. It also refuses a perfectly valid older filesystem
result when its Distribution version or revision differs from the qualified
release. This prevents the currently accepted v3.1.1 fixture from remaining a
passed production gate after a future Distribution release transition. The
filesystem harness and its exact pin must be updated and rerun for that release
before `gc_retention` can pass again.

The final enforcement target is:

```text
make -C poc/production-promotion require-promotion
```

It exits nonzero until every fixed gate is independently validated and the
ledger itself derives `production_candidate=true`. The current stable release
inputs fail before that point by design.
