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

## Native source parser boundary

`native_surfaces.py` is the next adapter seam. It adds a direct, no-proxy HTTPS
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

The implementation contract was checked against these primary sources:

- [Prometheus 3.12 HTTP API](https://prometheus.io/docs/prometheus/3.12/querying/api/)
- [HAProxy native Prometheus exporter at inspected revision](https://github.com/haproxy/haproxy/blob/30db9764d844977515a4a46d5e01f317f54c16f2/addons/promex/README)
- [mysqld-exporter v0.19.0 global status collector](https://github.com/prometheus/mysqld_exporter/blob/v0.19.0/collector/global_status.go)
- [Ceph Tentacle v20.2.2 Prometheus module](https://github.com/ceph/ceph/blob/v20.2.2/src/pybind/mgr/prometheus/module.py)
- [Ceph daemon and RGW monitoring metrics](https://docs.ceph.com/en/latest/monitoring/)
- [node-exporter v1.11.1 collectors](https://github.com/prometheus/node_exporter/tree/v1.11.1/collector)

This seam is not selected by the existing
`coffer.load-telemetry-target/v1`. The current target still proves the
normalized HTTPS/state transaction. A later versioned target must bind exact
native URLs, PromQL text/hashes, target allowlists, auxiliary evidence URLs,
and per-source content types before the parser can replace that adapter in a
pilot. Until then this remains local parser evidence, not production
telemetry qualification.
