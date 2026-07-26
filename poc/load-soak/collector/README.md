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
