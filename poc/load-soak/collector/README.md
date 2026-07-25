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
