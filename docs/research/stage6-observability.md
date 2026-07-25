# Stage 6 Restart-Correct Observability Baseline

- Date: 2026-07-25
- Status: implementation contract; ADR 0016 accepted for local architecture
- Scope: Coffer API, quota edge, Distribution, reconciliation, MariaDB,
  Ceph/RGW, Barbican/KMS, HAProxy, logs, metrics, alerts, dashboards, and
  initial service-level objectives
- External operations: none; this result comes from source/config inspection
  and official documentation

## Outcome

Coffer now has a bounded single-process API/edge/reconciliation metric schema,
a fail-closed one-worker runtime gate, direct API/edge scrape targets, and a
metrics-only Distribution proxy. The remaining Kolla topology is not yet
production-correct:

- `CofferMetrics` owns one private in-memory registry and process-start
  timestamp inside each process;
- API Gunicorn defaults to `openstack_service_workers`, so one scrape sees
  only the selected worker's copied registry unless the new metrics-enabled
  one-worker startup gate is satisfied;
- the quota edge records bounded request classes and exposes its private
  direct-backend scrape application when metrics are enabled;
- the reconciler creates process-local counters but exposes no scrape
  endpoint, and one-shot counters disappear at exit;
- Prometheus directly enumerates every API, edge, and registry backend rather
  than an FQDN/VIP;
- Distribution's debug mux is loopback-only and a verified-TLS allowlist
  proxy exposes only `/healthz` and `/metrics`;
- the role installs no Coffer alert rules, recording rules, Grafana
  dashboards, or explicit SLO/failure-budget policy; and
- Fluentd tails the logs, but the retained log contract is not validated as a
  bounded, correlated, secret-safe schema across every component.

The production-candidate baseline will use **one worker process per Coffer API
or edge container, multiple containers for horizontal availability, and
direct per-replica scrapes**. This avoids adopting Prometheus Python
multiprocess mode before Coffer can satisfy its directory lifecycle, dead
worker cleanup, custom-collector, and duplicate-registration constraints.
Threads remain available inside each process, and the representative load gate
must prove the initial worker/thread sizing. Increasing worker count later
requires a new accepted aggregation decision and restart/stale-series test.

ADR 0016 is now accepted for this architecture and pure local contract.
`poc/observability/topology.json` fixes the component, target, label, result,
rule, alert, dashboard, interval, and public-denial allowlists.
`poc/observability/contract.py` proves per-replica target generation,
one-worker and VIP refusal, restart/reset/stale transitions, and
secret-safe evidence. This is not deployed Prometheus, Grafana, runtime
endpoint, or pilot evidence.

## Current Surface Inventory

| Component | Current surface | Production gap |
|---|---|---|
| `coffer-api` | direct-backend `/healthz`, SQL `/readyz`, optional `/metrics`; process-start, bounded HTTP, token, readiness, and reconciliation counters; metrics-enabled worker count must be one; HAProxy operational-path denial | no dependency/session gauges; live multi-replica scrape not yet proven |
| `coffer-edge` | direct-backend `/healthz`, SQL `/readyz`, optional `/metrics`; bounded route/method/status, quota-admission outcome/duration, and process-start; HAProxy route denial | no generic upstream-result metrics; live multi-replica scrape not yet proven |
| Distribution | `/v2/` health through HAProxy; JSON logs; loopback debug mux; separate verified-TLS `/metrics` allowlist proxy; direct per-host scrape | live multi-replica scrape and failure recovery not yet proven |
| `coffer-reconcile` | aggregate cycle logs and process-local result counters | no scrape listener; counters disappear; no cycle/backlog/lease gauges |
| MariaDB/Galera | Kolla service health; existing exporter available when enabled | Coffer dashboard/alerts and transaction retry/deadlock correlation absent |
| Ceph/RGW | RGW service health; Ceph mgr Prometheus is an external-cluster option | no Coffer recording rules for RGW latency/errors/capacity/KMS symptoms |
| Barbican/KMS | dependency errors appear in bounded fixture evidence/logs | no production synthetic or error-budget signal |
| HAProxy | Kolla native Prometheus support and backend health | Coffer backend/frontend recording rules and alerts absent |
| Logs | JSON oslo logs plus Distribution JSON logs, Fluentd tail input | no complete field allowlist, cross-component request correlation, or leak gate |

## Restart-Correct Definition

Restart-correct does not mean a process counter can never reset. It means:

1. every live replica is scraped directly with stable `cluster`, `service`,
   and `instance` target labels;
2. a restarted process emits a new process-start timestamp and Prometheus
   counter-reset semantics remain valid for `rate()` and `increase()`;
3. a stopped replica becomes stale after the normal Prometheus interval and
   cannot remain as an apparently healthy duplicate series;
4. no load balancer randomly selects one replica or worker for a fleet metric;
5. current-state gauges come from current service/database/storage state, not
   accumulated process memory;
6. concurrent replicas cannot overwrite one textfile, Pushgateway group, or
   shared metric identity;
7. recording and alert rules aggregate across instances only after preserving
   component and failure-class meaning; and
8. restart, rolling update, rollback, and replica-loss tests prove those
   semantics with no stale or double-counted series.

## Accepted Collection Topology

```text
Prometheus
  |-- direct TLS scrape --> every coffer-api replica /metrics
  |-- direct TLS scrape --> every coffer-edge replica /metrics
  |-- direct TLS scrape --> every coffer-reconcile management endpoint
  |-- direct TLS scrape --> every Distribution metrics allowlist proxy
  |-- existing Kolla ----> HAProxy native Prometheus endpoint
  |-- existing Kolla ----> MariaDB exporter
  `-- external target ---> active Ceph mgr Prometheus endpoint

Fluentd
  |-- /var/log/kolla/coffer/*.log
  `-- /var/log/kolla/coffer-registry/*.log
```

The Coffer scrape fragment now uses inventory-derived static targets for each
API, edge, and registry backend address. It must not target
`coffer_internal_fqdn`, the public registry FQDN, or an HAProxy VIP.

All Coffer/Distribution targets use verified backend TLS and the operator CA.
Metrics paths are unavailable through public registry and public control
frontends. They are reachable only on the management/API network from the
Prometheus source addresses. The endpoint has no tenant authentication and
must fail the precheck if that network boundary cannot be expressed. The
current role also fails when Prometheus is disabled, workers are not exactly
one, CA/server-name inputs are missing, or a target equals either Kolla VIP.
This is locally rendered contract evidence; a fresh pilot must still prove
the actual network reachability and denial behavior.

Kolla's Prometheus server is itself protected with its supported HTTP
authentication. That protects the Prometheus UI/API; it does not replace the
target-side network and TLS boundary.

## Process and Replica Contract

### API and edge

- Stage 6 pins `workers=1` for API and edge when production metrics are
  enabled.
- API and edge retain bounded `gthread` concurrency and scale by adding
  service replicas.
- `coffer_process_start_time_seconds{component,version}` identifies resets.
- Every replica exposes the same schema but a distinct target `instance`
  label supplied by Prometheus, never by application input.
- Any configuration with production metrics enabled and workers greater than
  one fails the Kolla precheck until a later ADR accepts and proves another
  aggregation mode.

Prometheus Python multiprocess mode is rejected for this baseline. Its
official contract requires `PROMETHEUS_MULTIPROC_DIR` to be created outside
Python and wiped between Gunicorn runs, a request-local collector registry,
and dead worker cleanup; it also limits custom collectors, Info/Enum,
exemplars, label removal, and several Gauge modes. Coffer does not yet have
that lifecycle, and silently enabling the environment variable around the
current private registry would not be valid evidence.

### Reconciler

Production uses periodic mode, one process per replica, and a private
management listener. It exposes:

- process start and last completed cycle timestamps;
- cycle duration and fixed outcome counters;
- last scanned count;
- current SQL-derived pending/backlog, active-claim, stale-claim, and
  oldest-pending-age gauges; and
- dependency state for SQL and private verified-TLS Distribution.

One-shot mode remains an operator command and does not contribute to the
production time series. Its result stays in the structured log and retained
maintenance evidence. Scheduling correctness continues to come from SQL
claims/fencing, never from metrics.

### Distribution

Distribution v3.1.1 does not have a metrics-only debug server. Source
inspection confirms the debug server calls `http.ListenAndServe` with Go's
default mux while the registry command imports `net/http/pprof`. Enabling the
debug address directly on a backend interface would therefore expose
profiling.

The accepted implementation binds the upstream debug mux only to
`127.0.0.1`. A separate one-worker `coffer-registry-metrics` process on the
same host fetches one exact loopback HTTP `/metrics` URL and exposes only
`/healthz` and `/metrics` over backend TLS. It forwards no client headers,
bounds the response to 16 MiB, returns a fixed 503 for upstream failure or an
invalid response, and returns 404 for query strings, pprof, debug, and unknown
paths. Its dedicated mode-0600 configuration contains no database section and
receives no database, Keystone, RGW, Distribution HTTP, signing, or
maintenance secret.

The proxy has no HAProxy service entry. Prometheus targets its direct
per-registry-host backend port with the operator CA and fixed server name.
The ordinary Distribution service frontend still exposes only the registry
data plane; the upstream debug port is not reachable off-host.

Distribution documentation warns that the debug endpoint may expose sensitive
operational information. Network/TLS restriction and a metrics-only
configuration are release gates, not optional hardening.

### External dependencies

- Use Kolla's native HAProxy Prometheus endpoint, not the removed archived
  HAProxy exporter.
- Use Kolla's MariaDB exporter for Galera connection, transaction, and
  deadlock signals.
- Consume the external Ceph cluster's mgr Prometheus endpoint. Coffer/Kolla
  must not provision Ceph merely to obtain metrics.
- Record the Ceph mgr scrape interval and alert when cached metrics are stale.
- Barbican API availability, KMS/wrong-key failures observed by the registry,
  and the bounded disposable KMS synthetic are separate signals. A Barbican
  HTTP health check alone does not prove the RGW SSE-KMS path.

## Metric Schema

### Allowed labels

Application-controlled labels are limited to:

- `component`: `api`, `edge`, or `reconcile`;
- `route`: a fixed route template/route class;
- `method`: the fixed HTTP method allowlist plus `OTHER`;
- `status`: validated three-digit HTTP status or `OTHER`;
- `result`: a metric-family-specific fixed enumeration;
- `dependency`: `database`, `keystone`, `registry`, `rgw`, `kms`, or
  `haproxy`; and
- `state`: a metric-family-specific fixed enumeration.

Prometheus target discovery may add stable `cluster`, `service`, `instance`,
`region`, and `availability_zone` labels.

Project/user IDs, repository names or IDs, manifest/blob digests, references,
request IDs, audit IDs, JTI, claim/lease tokens, credential/secret IDs,
bucket/root names, endpoints, exception types/messages, status bodies, URLs,
and raw versions from a dependency response are forbidden labels.

### Coffer families

Retain and make label validation explicit for:

- `coffer_build_info{version}`;
- `coffer_process_start_time_seconds{component,version}`;
- `coffer_http_requests_total{component,route,method,status}`;
- `coffer_http_request_duration_seconds{component,route,method}`;
- `coffer_token_decisions_total{result}`;
- `coffer_token_decision_duration_seconds`;
- `coffer_readiness_checks_total{result}`; and
- `coffer_quota_reconciliation_outcomes_total{result}`.

Add:

- `coffer_dependency_up{component,dependency}`;
- `coffer_quota_admission_total{result}` with fixed
  `accepted`, `over_quota`, `missing_quota`, `invalid_manifest`,
  `unauthorized`, `upstream_unavailable`, and `internal_error`;
- `coffer_quota_admission_duration_seconds`;
- `coffer_edge_upstream_requests_total{upstream,result}` where upstream and
  result are fixed enums, not URLs or response text;
- `coffer_reconciliation_cycle_duration_seconds`;
- `coffer_reconciliation_last_success_timestamp_seconds`;
- `coffer_reconciliation_backlog`;
- `coffer_reconciliation_active_claims`;
- `coffer_reconciliation_stale_claims`;
- `coffer_reconciliation_oldest_pending_seconds`;
- `coffer_maintenance_sessions{state}` with fixed active/completed/revoked/
  expired states; and
- `coffer_inventory_comparison_total{result}` with a fixed result enum.

Do not copy arbitrary Distribution, Ceph, MariaDB, or HAProxy labels into
Coffer metrics. Recording rules normalize only the small set required by the
dashboards and alerts.

## Structured Log Contract

Every Coffer log entry uses JSON and contains:

- timestamp, severity, service/component, event, and fixed result;
- request ID when one exists;
- Keystone audit IDs only for the correlated authentication decision;
- JTI only in token decision audit events and never the token;
- repository/project identifiers only where the audit policy requires them,
  not on general dependency errors; and
- bounded aggregate counts for reconciliation, import, comparison, backup,
  GC, and teardown events.

Logs never contain Authorization, Basic/Bearer values, application credential
secrets, private keys, signing material, RGW keys, SQL URLs/passwords, raw
Barbican payloads, client certificate keys, full request/response bodies, or
exception text from a dependency. Fixed result categories replace exception
strings.

Request correlation crosses HAProxy, edge, API/token, and Distribution by
preserving a validated request ID. A generated edge request ID is preferred
when the client value is missing or invalid. Correlation IDs remain logs-only.

The Stage 6 leak test injects known canaries through token, push, wrong-key,
outage, backup, reconciliation, and GC failures, then scans metrics, logs,
exceptions, config, process arguments, and retained evidence.

## Initial SLO and Failure Budget

These are operator-candidate objectives for a 30-day window, not a public SLA:

| SLI | Good event | Objective | 30-day budget |
|---|---|---:|---:|
| authenticated pull availability | edge/registry responses succeed, excluding client 4xx | 99.90% | 43m 12s equivalent |
| manifest publication availability | authorized finalize returns accepted success; 429 is policy, not service failure | 99.50% | 3h 36m equivalent |
| control/token availability | valid control/token request avoids 5xx/dependency failure | 99.90% | 43m 12s equivalent |
| reconciliation freshness | accepted manifest ledger state converges within 5 minutes | 99.00% | 7h 12m equivalent |
| pull latency | successful manifest/digest pull completes within the accepted p95 threshold | measured in load gate | threshold pending |
| publication latency | successful manifest finalize completes within the accepted p95 threshold | measured in load gate | threshold pending |

User authentication failures, malformed requests, authorization denials,
quota 429 responses, and explicit maintenance writer fences are excluded from
availability bad events. Dependency-caused 503 and unexpected 5xx are bad
events. Exclusions must be recording-rule expressions, not dashboard filters
chosen ad hoc.

No durability SLO is claimed from request metrics. Durability requires the
separate backup/restore, Ceph failure-domain, and recovery gates.

## Alert Baseline

Required alerts and initial pending thresholds:

- any Coffer/Distribution target absent for 2 minutes;
- no healthy API, edge, or registry backend immediately;
- fast error-budget burn over 5m/1h and slow burn over 30m/6h;
- valid-request 5xx/dependency error ratio above the SLO recording rule;
- reconciliation last success older than 5 minutes;
- oldest pending reconciliation older than 5 minutes;
- stale claims greater than zero for two cycles;
- repeated Galera deadlocks/retry exhaustion;
- RGW/KMS/Barbican dependency unavailable or wrong-key failures;
- Ceph mgr metrics stale or Ceph health non-OK;
- registry storage errors, upload purge failures, or multipart residue;
- HAProxy has no healthy Coffer backend;
- capacity/headroom below the accepted load/backup margin; and
- metrics target, alert-rule, or dashboard schema mismatch after upgrade.

Every alert includes runbook, service, severity, and stable cluster/instance
labels. It includes no tenant/repository/digest or secret-bearing annotation.

## Dashboard Baseline

One operator dashboard has these rows:

1. SLO/error-budget status for pull, publication, control/token, and
   reconciliation freshness;
2. request rates, 4xx/429/5xx classes, and latency distributions by fixed
   component/route class;
3. API/edge/registry/reconciler target health and process starts;
4. token decisions, quota admission outcomes, maintenance sessions, and
   reconciliation backlog/age/outcomes;
5. HAProxy backend state and frontend/backend error/connection saturation;
6. MariaDB/Galera connections, transactions, lock waits, deadlocks, and
   retries;
7. Ceph/RGW health, latency/errors, capacity, multipart/upload cleanup, and
   KMS-related symptoms; and
8. deploy version, restart/rolling-upgrade annotations, active alerts, and
   backup/restore/GC rehearsal timestamps.

Dashboards use recording rules and fixed variables for cluster, region,
service, and instance only. Tenant and repository search do not belong in
Prometheus/Grafana; authorized audit tooling owns that workflow.

## Kolla Companion-Role Changes

The implementation milestone must:

1. add explicit production observability variables and fail-closed prechecks;
2. pin API/edge workers to one when metrics are enabled;
3. add edge and periodic-reconciler operational endpoints;
4. enable the Distribution metrics-only private debug listener;
5. render direct targets for every API, edge, reconciler, and registry host;
6. use verified TLS and the backend CA for every Coffer scrape;
7. deny operational paths/ports on all public and service frontends;
8. install Coffer recording and alert rules plus the operator dashboard;
9. keep Fluentd/logrotate integration idempotent;
10. validate Prometheus/Grafana configuration before restart; and
11. remove every Coffer-owned target/rule/dashboard file when disabled or
    destroyed.

The current `prometheus-coffer.yml.j2` VIP/FQDN target is replaced, not kept as
an additional target.

## Acceptance Matrix

Local/fixture evidence:

- exact metric-family and fixed-label allowlists;
- unknown components/routes/methods/status/results/dependencies refused before
  series creation;
- secret and high-cardinality canaries absent;
- single-worker production precheck;
- direct per-host target rendering with no VIP/public FQDN;
- public operational-path denial;
- alert and recording rule syntax plus fixed annotation labels;
- dashboard schema and query references;
- rolling restart model with start-time/counter-reset/stale-series fixtures;
- enable/reconfigure/disable/destroy idempotency.

Fresh pilot evidence:

- every service replica appears as a distinct healthy target;
- one API, edge, registry, reconciler, Prometheus, HAProxy, MariaDB, RGW, and
  Ceph mgr failure has the expected alert and recovery;
- worker/process/container restart produces a new start time, valid counter
  reset, and no stale duplicate after the bound;
- valid push/pull, 429, 503, wrong-key/KMS outage, reconciliation lag,
  deadlock/retry, backup, restore, and GC produce the expected bounded signal;
- dashboard and alert links resolve to the operator runbooks;
- rolling upgrade/rollback preserves query compatibility; and
- teardown leaves zero Coffer target/rule/dashboard/log-position residue.

## ADR 0016 Candidate

Accept:

- per-replica direct scrape;
- one API/edge worker per container for the initial production candidate;
- scale-out through service replicas;
- private verified-TLS operational endpoints;
- Distribution's separate private metrics listener;
- periodic reconciler metrics plus SQL-derived freshness gauges;
- Kolla-native HAProxy/MariaDB and external Ceph mgr exporters; and
- fixed SLO/alert/dashboard/label contracts from this document.

Reject for the initial candidate:

- scraping a VIP or public FQDN;
- summing randomly selected process-local `/metrics`;
- silently enabling Python multiprocess mode;
- Pushgateway for service-lifecycle metrics;
- tenant/repository/digest labels;
- parsing human logs as the sole availability/freshness signal;
- provisioning Ceph from the Coffer role; and
- declaring durability from request success metrics.

## Primary References

- Prometheus Python client multiprocess mode:
  <https://prometheus.github.io/client_python/multiprocess/>
- Kolla-Ansible Prometheus guide:
  <https://docs.openstack.org/kolla-ansible/2026.1/reference/logging-and-monitoring/prometheus-guide.html>
- Kolla-Ansible HAProxy guide:
  <https://docs.openstack.org/kolla-ansible/2026.1/reference/high-availability/haproxy-guide.html>
- Kolla-Ansible 2024.1 HAProxy native Prometheus migration:
  <https://docs.openstack.org/releasenotes/kolla-ansible/2024.1.html>
- CNCF Distribution configuration and private debug/Prometheus endpoint:
  <https://distribution.github.io/distribution/about/configuration/>
- Ceph mgr Prometheus module:
  <https://docs.ceph.com/en/latest/mgr/prometheus/>
- Kolla-Ansible external Ceph ownership:
  <https://docs.openstack.org/kolla-ansible/latest/reference/storage/external-ceph-guide.html>
