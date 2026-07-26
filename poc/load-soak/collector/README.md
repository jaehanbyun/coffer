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
reconciliation claims still require their correctly scoped read-only
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
