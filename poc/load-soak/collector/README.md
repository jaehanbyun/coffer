# Stage 6 live telemetry collector

`run.py` owns the three `before`, `during`, and `after` telemetry schedule
steps. Each owner-only invocation binds the exact compiled plan step, checked
collector source, CA, disposable target, shared state/lock/bundle paths, and a
distinct result path.

The target contract has seven explicit normalized-surface HTTPS URLs:

- Prometheus and direct Coffer/Distribution targets;
- the Kolla HAProxy exporter surface;
- the MariaDB/Galera exporter surface;
- the external Ceph mgr/RGW exporter surface;
- load quota evidence;
- reconciliation evidence; and
- controller/storage host evidence.

Every URL is credential-free, has an explicit port and path, and is covered by
one canonical target hash. The collector ignores ambient proxies, verifies the
configured CA and endpoint hostname, refuses redirects and content encoding,
and bounds each response, total bytes, JSON depth, object keys, arrays, and
strings. Each endpoint returns one canonical, versioned, phase-bound JSON
surface. The pilot adapter that exposes these views must itself be qualified
against the Prometheus API and named native exporters; the local transport
fixture is not that qualification.

The collector appends each semantic snapshot to an owner-only atomic state
with a replay-validated hash chain. A later phase cannot run before the prior
phase. Each schedule step emits a secret-safe collection result; the final
step also emits the existing `coffer.load-telemetry-bundle/v1`. The independent
telemetry verifier then checks replica counts, direct target resets, rules,
alerts, stale series, HAProxy, Galera, RGW/KMS, quota, reconciliation, and host
resource gates.

Fixture results are explicitly synthetic and exit 3. Pilot results use
`prometheus-export`, but remain `contract-only` until both architectures and
the fresh disposable multinode pilot qualify the exact adapter binary and
surface contract.

## Native source adapter boundary

`native_surfaces.py` adds a direct, no-proxy HTTPS
client with TLS 1.2-or-newer verification and strict JSON/OpenMetrics response
limits. Its parsers normalize:

- Prometheus v1 instant-vector/scalar and rules responses;
- native HAProxy `haproxy_server_status` series;
- stock mysqld-exporter `mysql_up`, numeric `wsrep_*`, and
  `mysql_galera_status_info` series;
- Ceph mgr `ceph_rgw_metadata`, ceph-exporter
  `ceph_daemon_socket_up`, and the pinned RGW ingress HAProxy backend;
- node-exporter memory, root-filesystem, file-descriptor, and timex gauges,
  combined with exact Prometheus CPU-rate and OOM-increase vectors; and
- the existing bounded quota and reconciliation evidence documents.

The parser ignores unrelated metric families but refuses missing, duplicate,
or extra series inside every selected target/proxy/daemon/instance allowlist.
It also refuses timestamps or exemplars on selected exporter series, nonfinite
values, unexpected labels, partial Prometheus warnings, unhealthy or
paginated rules, rule-set drift, Galera cluster splits, unknown RGW daemons,
and root-filesystem ambiguity.

The Galera reduction is intentionally conservative. Stock mysqld-exporter
converts `ON`/`OFF` values to numbers but does not expose a separate numeric
`Primary` string. A node therefore counts as primary/ready/synced only when
`mysql_up=1`, `wsrep_local_state=4`, local and cluster state UUIDs match, all
selected nodes share that cluster UUID, and `wsrep_cluster_size` equals the
selected topology. A one-point node-exporter scrape cannot yield interval CPU
usage or session OOM increments, so those two values must come from separate
allowlisted Prometheus instant queries.

Quota invariant/attempt evidence, reconciliation claim/fencing evidence, RGW
KMS errors, multipart residue, and workload unexpected-error totals do not
exist as equivalent native exporter metrics today. They remain explicit
auxiliary evidence inputs and are never inferred from a convenient but
different metric.

`native_target.py` owns the separately versioned
`coffer.load-telemetry-native-target/v1` contract. It leaves the normalized
target unchanged and binds all of the following into one canonical target
hash:

- the exact Prometheus instant-query URLs, PromQL text, and independent
  PromQL hashes;
- the filtered rules URL containing every required recording rule and alert;
- exact API, edge, reconciler, registry, HAProxy backend, Galera, RGW daemon,
  RGW ingress, controller, and storage identities;
- the expected JSON or Prometheus exposition content types for every source;
  and
- three distinct `before`, `during`, and `after` auxiliary-evidence URLs for
  secret scanning, unexpected errors, Galera attempts, KMS/multipart state,
  quota invariants, and reconciliation claims/fencing.

All URLs require HTTPS, an explicit port, no user information, and no
fragment. Prometheus URLs must carry one canonical URL-encoded allowlisted
query; the rules URL must carry exactly the repeated `rule_name[]` filters.
All source URLs are unique. Direct service host identities must agree with
the controller topology, Galera targets, HAProxy backends, node roles, RGW
daemon placement, and ingress membership.

The direct registry restart signal uses the upstream Prometheus client
`process_start_time_seconds`, and its monotonic activity signal uses
Distribution's debug-instrumented `registry_http_requests_total`. API and edge
use `coffer_http_requests_total`; reconciliation uses
`coffer_reconciliation_cycles_total`. Secret scanning remains phase-bound
auxiliary evidence because no equivalent Prometheus series exists.

`compose_phase_snapshot()` fetches one complete phase from the exact target
through the verified-TLS client and normalizes it into the existing seven
surface shapes. Auxiliary JSON is additionally bound to the target surface
and requested phase with
`coffer.load-telemetry-native-evidence/v1`. A mismatched phase, surface,
schema, PromQL, URL encoding, content type, identity, or target hash fails
before a snapshot is accepted.

The implementation contract was checked against these primary sources:

- [Prometheus 3.12 HTTP API](https://prometheus.io/docs/prometheus/3.12/querying/api/)
- [HAProxy native Prometheus exporter at inspected revision](https://github.com/haproxy/haproxy/blob/30db9764d844977515a4a46d5e01f317f54c16f2/addons/promex/README)
- [mysqld-exporter v0.19.0 global status collector](https://github.com/prometheus/mysqld_exporter/blob/v0.19.0/collector/global_status.go)
- [Ceph Tentacle v20.2.2 Prometheus module](https://github.com/ceph/ceph/blob/v20.2.2/src/pybind/mgr/prometheus/module.py)
- [Ceph daemon and RGW monitoring metrics](https://docs.ceph.com/en/latest/monitoring/)
- [node-exporter v1.11.1 collectors](https://github.com/prometheus/node_exporter/tree/v1.11.1/collector)

`collector/run.py` dispatches only the exact normalized or native target
schema and has no compatibility fallback. Its source hash covers
`native_target.py`, `native_surfaces.py`, the collector, and both telemetry
contracts. The normalized v1 path remains byte-compatible. A complete local
native before/during/after transaction performs 78 verified-TLS requests,
captures bounded dependency loss plus one service restart, and produces the
same independently verified canonical bundle transaction.

This is local adapter and transaction evidence, not production telemetry
qualification. The native target still needs to be rendered from the exact
disposable pilot inventory, all named sources and auxiliary views must exist
on that pilot, and both architecture lanes must qualify the bound runtime
before the load/soak gate can pass.

## Native target renderer

`render_target.py` is the no-network compiler for the pilot target. Its
versioned request contains only:

- the exact sorted controller, reconciler, storage, RGW daemon, and RGW
  ingress identities;
- canonical credential-free HTTPS origins with explicit ports for Prometheus,
  HAProxy, mysqld-exporter, Ceph mgr, ceph-exporter, RGW ingress,
  node-exporter, and the auxiliary-evidence adapter;
- the fixed load and observability topology hashes; and
- the exact adapter source hash.

The source hash covers `render_target.py`, `native_target.py`, and
`native_surfaces.py`. It can be obtained as canonical machine-readable output:

```text
uv run python poc/load-soak/collector/render_target.py source-hash
```

After the operator or harness creates a canonical mode-0600 request in a
mode-0700 directory, render the target with:

```text
uv run python poc/load-soak/collector/render_target.py \
  work/load-soak/native-target-request.json \
  work/load-soak/native-target.json
```

The renderer rejects aliases, links, unsafe ownership or modes, noncanonical
bytes, unsorted or incomplete inventory, role overlap, topology/hash drift,
URL credentials, HTTP, implicit ports, paths or query strings in origins, and
duplicate final source URLs. It writes through a mode-0600 temporary file,
fsyncs the file and parent, and does not rewrite a byte-identical target.
Success output contains only the result schema and target hash.

This renderer does not discover inventory, start exporters, fetch metrics,
compile the six phase-bound auxiliary evidence surfaces, or qualify a pilot.
Those are separate runtime gates.

## Phase-bound auxiliary evidence

`phase_evidence.py` converts six versioned owner-only source summaries into
the exact `coffer.load-telemetry-native-evidence/v1` documents expected by the
native collector:

| Surface | Required source summary | Retained payload |
|---|---|---|
| Prometheus | secret scan | `secret_leaks` |
| HAProxy | workload error aggregate | `unexpected_errors` |
| Galera | transaction-attempt aggregate | maximum attempts and unexpected errors |
| RGW | load-state aggregate | KMS errors, multipart residue, unexpected errors |
| quota | ledger aggregate | headroom, usage, invariant, attempts, stale claims, errors |
| reconciliation | claim aggregate | exactness, fencing, freshness, stale claims, worker counts |

Every summary binds its phase, surface, source class, window hash, normalized
payload, and summary hash. The compiler additionally binds the exact native
target bytes/hash, fixed load topology, and checked compiler source. The
atomic output bundle retains each document, document hash, and source-summary
hash plus one bundle hash. It contains no raw log, URL, project, repository,
credential, claim, object, or workload identity.

The compiler accepts bounded failure values such as nonzero errors or a false
invariant. It does not convert those values into success; the independent
telemetry verifier applies the phase gates later. Invalid types, nonfinite or
negative numbers, inconsistent quota percentages, topology drift, excessive
counts, cross-phase summaries, raw fields, and any hash drift fail closed.

Get the current compiler hash and compile one phase with:

```text
uv run python poc/load-soak/collector/phase_evidence.py source-hash
uv run python poc/load-soak/collector/phase_evidence.py \
  work/load-soak/before-summary-request.json \
  work/load-soak/native-target.json \
  work/load-soak/before-evidence-bundle.json
```

All three files use the same owner-only canonical/mode boundary as the target
renderer. Success output contains only the phase and bundle hash. This
compiler does not read SQL, RGW, Prometheus, logs, credentials, or the
network, and it does not yet serve the six documents.

## Private evidence server

`evidence_server.py` serves one validated phase bundle through the exact six
paths already bound into the native target. Its canonical owner-only
configuration binds:

- the exact target and evidence-bundle file paths plus raw SHA-256 values;
- one explicit loopback or private canonical IPv4 bind address, target TLS
  name, and explicit port;
- an owner-only server certificate and unencrypted private key with exact file
  hashes, matching public keys, current validity, non-CA basic constraints,
  server-auth extended usage, digital-signature usage, and an exact SAN;
- the current server/target/compiler/parser source hash; and
- concurrency from 1 through 32 plus a one- through 30-second request timeout.

`check` validates all files, bindings, routes, TLS material, and hashes without
opening a listener:

```text
uv run python poc/load-soak/collector/evidence_server.py source-hash
uv run python poc/load-soak/collector/evidence_server.py \
  check work/load-soak/evidence-server-before.json
```

`serve` binds only after the same validation:

```text
uv run python poc/load-soak/collector/evidence_server.py \
  serve work/load-soak/evidence-server-before.json
```

The listener requires exactly one Host header for the target name and port,
`Accept: application/json`, optional identity encoding, no transfer encoding,
and no request body. Only bodyless
`GET /v1/evidence/{surface}/{configured-phase}` succeeds. Other phases and
paths are not listed; methods, queries, duplicate headers, bodies, redirects,
wildcard/public binds, implicit ports, path or file aliases, and source/hash
drift fail closed. Responses contain canonical JSON, a fixed content type and
length, `no-store`, `nosniff`, and `Connection: close`; no product/version,
date, Location, raw path, or log output is emitted.

TLS is 1.2 or newer with compression disabled. Raw accepts receive a finite
timeout before handshake, successful handshakes enter a bounded request
semaphore, and shutdown closes the listener and worker threads. This is still
a disposable-pilot evidence adapter: it does not collect any source summary,
authenticate a public client, or expose a production endpoint.

## Source-summary acquisition

`source_summaries.py` converts six canonical dedicated collector artifacts
into the exact phase-evidence compiler request. It strengthens the source
summary to `coffer.load-telemetry-auxiliary-source-summary/v2`, which adds:

- the SHA-256 of the exact collector source contract; and
- the raw SHA-256 of the canonical owner-only source artifact.

Each `coffer.load-telemetry-source-artifact/v2` contains one exact phase,
surface, source class, target hash, window hash, collector-source hash,
input-set hash, positive bounded observation count, fixed aggregate, and
self-hash. It cannot contain a raw URL, log, identity, credential, repository,
claim, object, or other unbounded field. The acquisition configuration
separately pins every artifact path, raw file hash, collector hash, target
path/hash, phase, window, and acquisition source. Version 2 replaced the
unexercised v1 contract before pilot use because v1 did not retain a binding
to the files from which a collector calculated its aggregate.

```text
uv run python poc/load-soak/collector/source_summaries.py source-hash
uv run python poc/load-soak/collector/source_summaries.py \
  compile work/load-soak/source-summaries-before.json \
  work/load-soak/before-summary-request.json
```

The output is not a new intermediate dialect: it is the exact canonical
`coffer.load-telemetry-phase-evidence-request/v1` accepted by
`phase_evidence.py`, and acquisition validates it through a full in-memory
bundle compilation before writing. Raw artifact hashes survive indirectly in
each v2 summary hash; observation counts and artifact self-hashes stay in the
owner-only inputs. Output is atomic, mode 0600, idempotent, and secret-safe.

This seam does not fabricate artifacts or infer one subsystem from another.
Secret scan/workload, Galera attempts, RGW/KMS/multipart, quota ledger, and
reconciliation claims must still be produced by their correctly scoped
collectors.

## Local secret and workload artifacts

`local_artifacts.py` creates only the two auxiliary artifacts whose inputs
already exist locally:

- the Prometheus `secret_leaks` aggregate scans an explicit owner-only file
  allowlist for four fixed credential patterns and optional supplied one-way
  fingerprints; and
- the HAProxy `unexpected_errors` aggregate sums that exact field from
  canonical `coffer.load-profile-result/v1` and
  `coffer.load-fault-result/v1` files.

A supplied fingerprint contains only length, SHA-256, and a rolling prefilter.
The rolling value finds candidate byte windows, but SHA-256 must also match
before a hit is counted. The helper reads the exact bytes of one owner-only
file without echoing them:

```text
uv run python poc/load-soak/collector/local_artifacts.py \
  fingerprint /absolute/owner-only/value.bin
```

Compile one surface with:

```text
uv run python poc/load-soak/collector/local_artifacts.py source-hash
uv run python poc/load-soak/collector/local_artifacts.py \
  compile /absolute/owner-only/local-artifact-config.json \
  /absolute/owner-only/source-artifact.json
```

All source files are regular, single-link, owner/mode-0600 files from an
explicit canonical absolute path. The collector caps individual and total
bytes, binds every raw file hash into `input_set_sha256`, and writes an atomic
mode-0600 artifact under an owner/mode-0700 directory. Output retains only
hashes, counts, phase, surface, source class, target, and window.

Workload inputs must be nonsynthetic `pilot` results, use one plan hash, match
the fixed operation/fault topology, and be canonical. This boundary does not
claim that a local workload result is a native HAProxy metric; the surface
name is the existing downstream slot for a workload-error aggregate. It has
no network, SQL, exporter, subprocess, or remote adapter and never creates
Galera, RGW, quota, or reconciliation facts.

## Quota and reconciliation control artifacts

`control_artifacts.py` creates the quota and reconciliation v2 artifacts from
two owner-only captures around one phase window. A capture combines:

- one identity-free `QuotaStore.control_evidence_snapshot()` from the database;
- exact per-process quota-attempt histogram buckets;
- exact per-edge internal-error counters;
- exact edge/reconciler process-start gauges;
- exact reconciler `up`, database dependency, and last-success gauges; and
- the phase, target, window, collector source, observation times, and
  self-hash.

The live capture obtains the database URL and load-project ID only from
`COFFER_DATABASE_URL` and `COFFER_LOAD_PROJECT_ID`. They are never written to
the capture or final artifacts. The owner-only configuration pins the native
target and CA paths and hashes, phase/window, timeout, freshness threshold,
and current collector source hash. Prometheus query URLs are derived only
from the validated target's already-bound Prometheus origin and six fixed
source-hashed PromQL expressions.

Create a baseline at the start of a phase and a current capture at its end:

```text
uv run python poc/load-soak/collector/control_artifacts.py source-hash
uv run python poc/load-soak/collector/control_artifacts.py \
  capture /absolute/owner-only/control-config.json baseline \
  /absolute/owner-only/control-baseline.json
uv run python poc/load-soak/collector/control_artifacts.py \
  capture /absolute/owner-only/control-config.json current \
  /absolute/owner-only/control-current.json
```

Then compile the two final source artifacts:

```text
uv run python poc/load-soak/collector/control_artifacts.py \
  compile /absolute/owner-only/control-config.json \
  /absolute/owner-only/control-baseline.json \
  /absolute/owner-only/control-current.json \
  /absolute/owner-only/quota-artifact.json \
  /absolute/owner-only/reconciliation-artifact.json
```

The compiler reconstructs the maximum attempt actually observed from 1/2/3
histogram bucket deltas, sums only bounded edge internal-error deltas, computes
quota usage/headroom from the SQL snapshot, and reduces all required
reconciler replicas using the worst last-success age. It rejects missing,
duplicate, unknown, decreasing, partial-warning, stale, or hash-drifted
series. It also rejects any edge/reconciler process restart within the
baseline/current interval because an instant capture cannot prove the
pre-restart maximum attempt. Failure-state facts such as a false quota
invariant or unavailable reconciler are retained truthfully for the
independent phase gate; they are not converted into success.

Raw captures are disposable owner-only inputs and may contain bounded target
instance labels. The final v2 artifacts retain only numeric/boolean aggregates
and hashes—never a URL, instance, project, repository, SQL error, credential,
claim, or raw Prometheus response. Local tests qualify this contract and fake
adapter boundary only; a fresh pilot must still qualify the live database,
verified-TLS Prometheus path, and exact phase scheduling.

## Galera transaction artifact

`galera_artifacts.py` consumes the same owner-only control baseline/current
captures instead of pretending that mysqld-exporter cluster-health gauges are
application transaction attempts. It emits the Galera v2 source artifact with:

- the maximum Coffer SQL transaction attempt actually observed across every
  exact edge and reconciler process; and
- terminal `database_error` plus `conflict_exhausted` operation counts from
  the histogram's `+Inf` phase delta.

`rejected` outcomes are domain decisions, not Galera failures. Successful
retries contribute to the maximum attempt but not the error count. The
existing native Galera parser independently verifies all expected
mysqld-exporter nodes as Primary, Ready, and Synced; this auxiliary artifact
does not duplicate or reinterpret those node gauges.

Compile after the control baseline/current capture:

```text
uv run python poc/load-soak/collector/galera_artifacts.py source-hash
uv run python poc/load-soak/collector/galera_artifacts.py \
  compile /absolute/owner-only/galera-config.json \
  /absolute/owner-only/control-baseline.json \
  /absolute/owner-only/control-current.json \
  /absolute/owner-only/galera-artifact.json
```

The Galera configuration pins both collector source hashes, the native target
path/hash, phase, and window. Counter reset, process restart, absent attempts,
source/hash drift, unsafe files, and aliases fail closed. The final artifact
retains no process, operation, result, database node, project, URL, or error
text.

## RGW, KMS, and multipart artifact

`rgw_artifacts.py` compiles one RGW v2 source artifact from two canonical,
owner-only pilot inputs:

- one bounded RGW/SSE-KMS probe result with complete fixed-operation and
  fixed-result counts; and
- one complete bucket-scoped multipart listing reduced to count plus unique
  page hashes.

The probe always covers positive- and zero-size put/copy plus head, get, and
multipart listing. The `during` phase additionally requires both declared
wrong-key and Barbican-outage outcomes. Those expected fail-closed responses
must be observed but do not increment `kms_errors`; only
`unexpected_kms_error` does. Unexpected non-KMS S3/storage outcomes populate
`unexpected_errors` without being conflated with the separate end-client
workload aggregate.

Compile after a live adapter has produced the two canonical inputs:

```text
uv run python poc/load-soak/collector/rgw_artifacts.py source-hash
uv run python poc/load-soak/collector/rgw_artifacts.py \
  compile /absolute/owner-only/rgw-config.json \
  /absolute/owner-only/rgw-probe-result.json \
  /absolute/owner-only/rgw-multipart-capture.json \
  /absolute/owner-only/rgw-artifact.json
```

The configuration pins the native target, exact phase window, bucket scope,
RGW/KMS configuration, probe and multipart source hashes, required operation
counts, and expected fault counts. Probe and listing timestamps must stay
inside that window. Missing operations or expected faults, synthetic/fixture
inputs, incomplete/repeated multipart pages, cross-target/hash drift, unsafe
files, aliases, and unknown fields fail closed.

The final artifact retains only `kms_errors`, `multipart_uploads`,
`unexpected_errors`, bounded observation count, and provenance hashes. It
cannot retain an endpoint, bucket, object, upload, project, identity,
credential, certificate, KMS identifier, error text, or request content.

`rgw_live_adapter.py` is the bounded producer for those two inputs. Its
owner-only configuration requires:

- one explicit HTTPS endpoint with a port, pinned owner-only CA bytes/hash,
  S3 v4, path-style addressing, region, and finite timeout;
- exact target/window, RGW configuration, bucket-scope, and KMS-policy hashes;
- a fixed probe prefix and dependency-safe healthy order:
  zero/positive put, head/get, zero/positive copy, then multipart listing;
- one expected operation count for every step; and
- only in `during`, an exact wrong-key failure/recovery-success followed by
  KMS-outage failure/recovery-success sequence, with each fault bound to a
  non-empty external evidence hash.

Credentials and the selected Barbican key ID never enter that configuration.
The live boto3 factory reads only
`COFFER_RGW_EVIDENCE_ACCESS_KEY`,
`COFFER_RGW_EVIDENCE_SECRET_KEY`, and
`COFFER_RGW_EVIDENCE_KMS_KEY_ID` at runtime. boto3/botocore are dynamically
loaded by the disposable helper runtime; they are intentionally not assumed
to exist in the Coffer API/edge images.

The fault controller changes external state between step commands. The
adapter never accepts a caller-provided result:

```text
uv run python poc/load-soak/collector/rgw_live_adapter.py source-hash
uv run python poc/load-soak/collector/rgw_live_adapter.py \
  collect-step RGW-LIVE-CONFIG.json STEP-INDEX STEP-RESULT.json
uv run python poc/load-soak/collector/rgw_live_adapter.py \
  compile-probe RGW-LIVE-CONFIG.json STEP-0.json ... PROBE.json
uv run python poc/load-soak/collector/rgw_live_adapter.py \
  collect-multipart RGW-LIVE-CONFIG.json MULTIPART.json
```

Each expected fault must both have external evidence and return one fixed
fail-closed HTTP/error class. A fault that succeeds becomes an unexpected
storage error; an unplanned KMS or other storage failure remains nonzero.
Multipart collection follows explicit key/upload markers, rejects repeats or
incomplete/excessive pages, and reduces object/upload identities to one-way
page hashes plus a total count. Step, probe, and multipart files are canonical
owner-only inputs; retained artifacts contain none of their operational
identities.

The adapter core and low-level boto3 behavior are fake-client tested. A fresh
disposable pilot must still pin the boto3 runtime, deliver the three
environment values owner-only, coordinate wrong-key/outage/recovery, clean
the exact probe prefix, and prove zero credential/object/multipart residue.

## Qualified disposable-pilot schedule

`pilot_schedule.py` turns exact qualified upstream evidence, the load-plan
envelope, native target, RGW TLS/settings, three non-overlapping windows, and
two external fault-evidence hashes into one atomic owner-only schedule
directory:

```text
uv run python poc/load-soak/collector/pilot_schedule.py source-hash
uv run python poc/load-soak/collector/pilot_schedule.py \
  render /absolute/owner-only/pilot-schedule-request.json
```

Rendering is refused unless both released components and the overall
`coffer.upstream-readiness/v1` result are `candidate-qualified`. The load
plan's exact Distribution/Ceph versions, revisions, and readiness payload hash
must match that result. The current signed Distribution v3.1.1 and Ceph
Tentacle v20.2.2 inputs therefore cannot produce a schedule.

For an eligible release pair, the renderer emits three validated live RGW
configs and 53 ordered actions. Each phase begins with the seven-step healthy
SSE-KMS path. `during` then applies wrong-key, observes its fixed failure,
restores the key and proves success, applies the KMS outage, observes its fixed
failure, restores KMS and proves success. Every phase compiles the probe,
captures the complete multipart listing, cleans only its exact probe prefix,
requires zero objects and multipart uploads, renders the final collector
inputs, and invokes atomic phase preparation.

The schedule names only the three fixed runtime environment variables; it
contains no credential or KMS key value. Rendering creates no runtime
directory and performs no network, S3, KMS, Barbican, OpenStack, container,
VM, or remote operation.

`pilot_executor.py` is the checkpoint/recovery contract for those 53 actions.
Its current command is deliberately fixture-only:

```text
uv run python poc/load-soak/collector/pilot_executor.py source-hash
uv run python poc/load-soak/collector/pilot_executor.py \
  --fixture \
  --schedule /absolute/owner-only/pilot-schedule \
  --readiness /absolute/owner-only/upstream-readiness.json
```

The executor independently revalidates the qualified readiness payload,
schedule/result hashes, all three live configs, exact action sequence, cleanup
contract, and every input/output path. It creates only the exact mode-0700
runtime root and fixed mode-0600 lock, state, and result files. Before calling
an adapter it persists the next action as pending. A normal result advances
one checkpoint; an interrupted pending action must be reconciled by the
adapter before it may be retried or accepted. The stable lock inode is retained
so a failed concurrent opener cannot unlink and bypass an active lock.

The fixture adapter produces synthetic hashes only. Seventeen tests prove all
53 checkpoints, exact resume after a failure-before-apply, reconciliation
after an apply-before-response interruption, idempotent completion,
nonblocking locking, fixed CLI failures, and input/state/result tamper
rejection. The executor now also accepts exactly one non-synthetic
`coffer.stage6-pilot-action-adapter/v1` contract named `pilot`. Its source hash
is persisted with the checkpoint state. Phase runtime directories admit only
the scheduled files plus the fixed collector/config inputs, with mode-0700
directories and mode-0600 single-link files. Partial RGW, fault, or phase
adapters remain refused.

`rgw_cleanup.py` closes the exact-prefix deletion contract used by the
scheduled cleanup/verification pair:

```text
uv run python poc/load-soak/collector/rgw_cleanup.py source-hash
uv run python poc/load-soak/collector/rgw_cleanup.py \
  cleanup RGW-LIVE-CONFIG.json RGW-CLEANUP-RESULT.json
```

The runtime client completely paginates the configured prefix across current
objects, object versions, delete markers, and multipart uploads. Any returned
key outside `probe_prefix/`, malformed or repeated identity/page/cursor,
incomplete pagination, or bound overflow fails before removal. It aborts the
exact uploads, deletes versioned/delete-marker identities and remaining
unversioned keys in bounded batches, then repeats all three listings. A result
is emitted only when all four remaining counts are zero inside the phase
window.

The result retains only before/after counts, page-set and
source/target/window/config hashes. Endpoint, bucket, prefix, key, version,
upload, credential, KMS, and error identities remain in memory only.
Twenty-nine fake and low-level client tests cover pagination, prefix escape,
cursor failure, exact abort/delete calls, partial deletion, residual state,
owner-only composition, and fixed CLI failures. No S3 call was made.

`pilot_rgw_actions.py` composes the live probe, multipart, and cleanup modules
into the non-synthetic RGW subset of the 53-action schedule. It has no
execution CLI; only a source-hash command is exposed while the dependency gate
is closed:

```text
uv run python poc/load-soak/collector/pilot_rgw_actions.py source-hash
```

The adapter independently loads a qualified schedule and creates clients only
after that check. `open-phase`, every indexed `collect-rgw-step`,
`compile-rgw-probe`, `collect-rgw-multipart`, `cleanup-rgw-prefix`, and
`verify-rgw-cleanup` materialize canonical mode-0600 outputs beneath the exact
mode-0700 phase directory. Reconciliation revalidates the existing output and
returns the same non-synthetic action result without another S3 operation.
Existing, tampered, aliased, out-of-schedule, or unsupported action outputs are
never overwritten.

The default future runtime factory loads boto3 through the existing live
adapter and shares its verified-HTTPS S3 client with cleanup. Tests inject
fake clients and never read credential environment variables. Fifteen action
tests plus the expanded 29 cleanup tests cover all supported materializers,
during step indices, reconciliation, tamper, retention, readiness refusal, and
the source-only CLI. This partial adapter cannot run the full pilot by itself.

`pilot_fault_actions.py` defines the non-synthetic external controller seam for
the four `during` actions. It also exposes only a source-hash command:

```text
uv run python poc/load-soak/collector/pilot_fault_actions.py source-hash
```

Apply and recover are accepted only from the exact qualified schedule and
phase window. The controller must return a typed observation bound to the
fault, desired state, external evidence hash, and timestamps. Recovery first
revalidates the matching retained apply result and carries its external
evidence hash forward; the schedule's ordinary no-fault marker cannot replace
it. Output retains only controller/source, fault/state, target/window/schedule,
time, and evidence hashes.

If an external change completed but the process stopped before writing its
result, reconciliation calls the controller's read-only `observe` method.
Matching external state reconstructs the exact output without reapplying the
fault; absent state requests a safe retry. Existing or tampered outputs are
never overwritten. Twenty tests cover both faults, ordered recovery,
apply-before-output interruption, unobserved retry, observation drift,
window/evidence/state tamper, missing phase, readiness refusal, retention, and
the source-only CLI. Tests use a fake controller; no Kolla, RGW, Barbican, KMS,
service restart, credential, VM, or remote state changed.

`pilot_phase_actions.py` materializes the final three actions in every phase
and exposes only a source-hash command:

```text
uv run python poc/load-soak/collector/pilot_phase_actions.py source-hash
```

The externally rendered `collector-inputs.json` is an owner-only deployment
input contract until the Kolla renderer owns it. It contains no credential.
The materializer binds its exact source, the phase-preparer source, qualified
schedule, phase, window, and native target. It accepts only the six static
Prometheus, HAProxy, control, and Galera descriptors. At action time it derives
the RGW artifact configuration from the qualified live schedule and binds the
probe and multipart descriptors to the exact preceding runtime files.

`render-phase-preparation-request` validates every descriptor and emits the
existing preparation request at its scheduled path.
`prepare-phase-atomically` invokes the existing all-or-nothing six-surface
preparer and accepts only its scheduled `phase-evidence/result.json`.
`complete-phase` independently revalidates that result plus the exact-prefix
zero-residue verification before emitting a small self-hashed completion
document. Existing output is never overwritten; reconciliation revalidates
without rebuilding it. Twelve tests cover all three phases, repeat
reconciliation, static/dynamic/target/source drift, unsafe input mode,
cleanup tamper, output preservation, unsupported actions, and the source-only
CLI. Tests use only local fixtures and fake RGW clients.

`pilot_actions.py` is the sole non-synthetic adapter accepted by the
checkpoint executor:

```text
uv run python poc/load-soak/collector/pilot_actions.py source-hash
```

It loads the qualified schedule once, constructs the RGW, external-fault, and
phase adapters, rejects overlapping or missing routes, and converts each
independently validated sub-result into the single `pilot` checkpoint result.
Per-phase clocks are injectable for tests; the default uses wall time. The
module exposes no execution CLI while released dependencies remain blocked.

Thirteen tests execute all 53 actions through the real checkpoint loop with
fake S3 clients and a fake external controller. They prove completion and
idempotent rerun, exact resume after failure-before-action, RGW output
reconciliation without a duplicate storage call, fault apply reconciliation
through read-only external observation, adapter contract/name/source
enforcement, owner-only runtime enforcement, and the source-only CLI.

## Six-surface phase preparation

`phase_preparation.py` turns the separately validated collectors into one
all-or-nothing phase preparation transaction. One canonical owner-only request
binds:

- the native target and phase/window;
- Prometheus secret-scan and HAProxy workload-result configurations;
- control configuration plus baseline/current captures;
- Galera configuration over those same control captures;
- RGW configuration, probe result, and multipart capture;
- the future output directory; and
- the private evidence server certificate/key, bind, route, and source
  contract.

Prepare one phase only after every referenced input is complete:

```text
uv run python poc/load-soak/collector/phase_preparation.py source-hash
uv run python poc/load-soak/collector/phase_preparation.py \
  prepare /absolute/owner-only/phase-preparation-request.json
```

The preparer compiles all six v2 artifacts, the source-summary request, the
phase bundle, and the final private evidence-server configuration inside a
fresh mode-0700 staging directory. It validates an equivalent server
configuration without binding a socket, removes temporary compiler inputs,
builds a self-hashed result, atomically publishes the complete directory, and
revalidates the final paths. A late failure removes only the exact staging
directory created by that run; no partial final directory is published.

An exact repeat validates every retained file hash, mode, link count, source,
target, phase, window, bundle, server configuration, and result without
rewriting any inode. A changed request, input, source, retained file, extra
file, unsafe directory, or alias is refused and never overwritten. The
transaction performs no network request, SQL query, S3 call, listener bind,
credential creation, or remote operation; its inputs must already have been
collected by the bounded pilot adapters.
