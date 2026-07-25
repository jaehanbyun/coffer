# ADR 0016: Use Direct Per-Replica Observability

- Status: accepted
- Date: 2026-07-25
- Decision owners: Coffer maintainers and deployment operators
- Related plan: `docs/exec-plans/0019-stage6-production-promotion.md`
- Related ADRs: `docs/adrs/0007-use-falcon-wsgi-and-gunicorn.md`,
  `docs/adrs/0014-fix-kolla-deployment-topology.md`
- Research: `docs/research/stage6-observability.md`

## Context

Coffer's current API collector is private and process-local. The Kolla
configuration normally starts multiple Gunicorn workers, while its Prometheus
fragment scrapes one internal FQDN/VIP. A scrape therefore selects one
replica and one worker rather than observing the fleet. The edge has no
operational application, the periodic reconciler has no scrape endpoint,
Distribution metrics are disabled, and no Coffer recording rules, alerts,
dashboard, or failure-budget contract exists.

Prometheus Python multiprocess mode is not a switch around the current
registry. It requires a directory initialized and wiped outside Python,
special collector construction, dead-worker lifecycle integration, and
acceptance of collector/Gauge/exemplar limitations. Coffer has not proved that
contract.

## Decision

### Collection and scale boundary

1. Scrape every API, edge, periodic reconciler, and Distribution replica
   directly on its backend address. Never scrape a public FQDN or load-balancer
   VIP for service metrics.
2. Run one Gunicorn worker per API/edge container in the initial production
   candidate. Retain bounded thread concurrency and scale horizontally with
   service replicas.
3. Fail the Kolla precheck if production metrics are enabled with more than
   one API/edge worker.
4. Treat a process counter reset as valid only with a newer process-start
   timestamp. Prometheus recording rules use per-instance `rate()`/`increase()`
   and then aggregate.
5. Mark a removed instance stale after the fixed scrape/missed-scrape bound;
   do not retain or synthesize an apparently healthy duplicate series.

### Exposure and dependency ownership

1. Coffer operational endpoints use verified backend TLS and are reachable
   only from the operator monitoring network. Public and ordinary service
   frontends deny `/metrics` and private debug paths.
2. Distribution binds its upstream debug mux only to host loopback. A
   Coffer-owned, one-worker allowlist proxy exposes only `/healthz` and
   `/metrics` over verified backend TLS. Profiling and every other debug path
   remain inaccessible.
3. The periodic reconciler exposes one private management endpoint with
   process/cycle counters and SQL-derived backlog, claim, and age gauges.
   One-shot mode reports only fixed structured logs/evidence.
4. Use Kolla's native HAProxy and MariaDB Prometheus surfaces.
5. Consume the external Ceph cluster's mgr Prometheus endpoint. The Coffer
   role does not provision or reconfigure Ceph merely to collect metrics.
6. Keep Barbican API health, registry KMS error signals, and the bounded
   disposable SSE-KMS synthetic distinct.

### Cardinality, logs, and service objectives

Application metric labels are fixed enums for component, route class,
method, status, result, dependency, and state. Target discovery may add stable
cluster/service/instance/region/availability-zone labels. Tenant, project,
user, repository, digest, reference, request/audit/JTI/claim/credential IDs,
URLs, exception strings, and dependency bodies never become metric labels.

Structured JSON logs retain request/audit correlation where policy requires
it, but never credentials, tokens, private keys, SQL URLs/passwords, RGW keys,
raw Barbican material, request/response bodies, or dependency exception text.

The initial 30-day operator objectives are:

- authenticated pull availability: 99.90%;
- authorized manifest publication availability: 99.50%;
- valid control/token availability: 99.90%; and
- reconciliation within five minutes: 99.00%.

Quota 429, client/auth failures, malformed requests, and explicit maintenance
fences are not availability failures. Dependency 503 and unexpected 5xx are.
Latency thresholds remain pending the representative load gate. Request
metrics do not establish durability.

## Rejected Alternatives

- VIP/public-FQDN scraping: randomly selects a replica and hides failures.
- Summing process-local metrics: worker/replica selection and reset semantics
  are undefined.
- Python multiprocess mode now: its required lifecycle and limitations are
  unproved.
- Pushgateway: service lifecycle does not match batch-job ownership and stale
  grouping cleanup would become another correctness boundary.
- Tenant/repository labels: unbounded cardinality and information disclosure.
- Logs as the sole SLI source: parsing and retention are not a restart-correct
  current-state signal.
- Coffer-owned Ceph provisioning: violates external Ceph ownership.

## Consequences

The initial container handles less process-level parallelism than the current
default, so the load gate must set worker/thread/replica limits honestly.
Horizontal scale and failure isolation are simpler, and every time series has
one replica owner. A future multi-worker decision requires a new ADR and
explicit directory, worker-death, stale-series, restart, and query tests.

The companion role must generate per-host targets, operational endpoint
denials, recording/alert rules, and dashboard content. Upgrade compatibility
now includes metric/rule/dashboard schema compatibility.

## Acceptance

This ADR was accepted after pure local proof of:

- exact target, label, result, rule, alert, dashboard, and SLO allowlists;
- one-worker enforcement and VIP/public target refusal;
- restart/counter-reset/stale-series transitions;
- public operational path denial;
- secret-safe retained evidence; and
- full repository regression.

Production acceptance additionally requires direct scrapes of every fresh
pilot replica, component/dependency fault alerts, rolling restart/upgrade/
rollback, representative load, canary leak scanning, and zero teardown
residue.

The accepted local evidence is the versioned topology and pure contract in
`poc/observability/`. Fifty-one focused tests prove the exact topology,
bounded application labels and results, public operational-path denial,
direct verified-TLS per-replica targets, one-worker and VIP refusal,
restart/counter-reset/stale-series transitions, and redacted evidence. This
accepts the architecture and local contract only; it does not claim that the
runtime endpoints, Kolla discovery, Prometheus rules, Grafana dashboard, or
fresh pilot evidence already exist.

The first runtime slice now binds API, edge, and reconciliation collectors to
the same allowlists, exports a process-start timestamp, collapses status codes
to bounded classes, removes raw edge paths from labels, and rejects
metrics-enabled API/edge processes with any worker count other than one.
The Gunicorn post-fork hook refreshes the timestamp inside each worker, so a
worker replacement cannot reset counters while retaining the old start time.
Manifest quota admission now emits exactly the accepted ADR result classes;
quota absence, internal database error, upstream failure, policy denial, and
client-invalid cases cannot create dynamic labels or retain request identity.
The API and edge now expose metrics on their direct verified-TLS backends
only when enabled. The companion role pins one worker, emits per-host
Prometheus targets with CA/server-name verification, refuses a VIP target,
and blocks operational/debug paths on the HAProxy service route. This still
does not expose a reconciler management endpoint or install recording rules,
alerts, or a Grafana dashboard.

Distribution v3.1.1 cannot provide a native metrics-only listener: its debug
server uses Go's default HTTP mux and the registry binary imports
`net/http/pprof`. The role therefore binds that mux to `127.0.0.1`, enables
only its Prometheus producer, and starts `coffer-registry-metrics` on the
direct backend address. The proxy accepts one exact loopback HTTP
`/metrics` upstream, forwards no client headers, bounds the response, maps
upstream failures to a fixed 503, and returns 404 for query, profiling, and
unknown paths. Its dedicated configuration receives no database, Keystone,
RGW, Distribution HTTP, signing, or maintenance secret. Prometheus now
scrapes each registry host through this verified-TLS proxy.
