# M3 Local Observability Baseline

- Date: 2026-07-21
- Scope: process health, database readiness, bounded Prometheus metrics, and token-decision correlation
- Outcome: local implementation and real single-process integration passed; multi-worker aggregation remains open

## Endpoint Contract

The WSGI dispatcher routes these exact operational paths outside tenant Keystone middleware:

| Endpoint | Default | Meaning |
|---|---|---|
| `GET /healthz` | enabled | process liveness only; no dependency call |
| `GET /readyz` | enabled | current database `SELECT 1` readiness |
| `GET /metrics` | disabled | process-local Prometheus text exposition |

All responses set `Cache-Control: no-store`. Health responses use neutral status values and never include connection strings, exception classes, hostnames, credentials, SQL, or dependency response bodies. Database failure returns 503 with `database=unavailable`; success returns 200 with `database=ready`.

`/healthz` deliberately remains alive when the database is unavailable. A supervisor should restart a dead process, while a load balancer should remove a process whose readiness fails. Keystone and RGW are not currently probed by `/readyz`: per-request Keystone failure already produces a neutral 503 at the token realm, while RGW belongs to the Distribution data plane. Real dependency health and failure budgets remain runbook evidence.

## Metrics Contract

The selected OpenStack constraints contain `prometheus-client==0.25.0`, which is now locked. Coffer uses a private collector registry rather than the process-global default registry.

Exposed metric families are:

- `coffer_build_info{version}`;
- `coffer_http_requests_total{component,route,method,status}`;
- `coffer_http_request_duration_seconds{component,route,method}`;
- `coffer_token_decisions_total{result}`;
- `coffer_token_decision_duration_seconds`;
- `coffer_readiness_checks_total{result}`;
- `coffer_quota_reconciliation_outcomes_total{result}`.

Cardinality is bounded:

- route labels use Falcon templates such as `/v1/repositories/{repository_id}`, never concrete IDs;
- components are fixed by application construction;
- HTTP methods use a fixed standard set and collapse everything else to `OTHER`;
- status is the finite HTTP status code;
- token and readiness results are fixed code paths;
- reconciliation result is one of `present`, `absent`, `indeterminate`, `stale_version`, or `stale_claim`;
- project IDs, user IDs, repository names, credential IDs, request IDs, JTI values, audit IDs, URLs, and exception strings never become labels.

The detailed request ID, JTI, Keystone audit IDs, normalized requested repository/actions, reduced grants, and result remain structured log fields. Logs provide trace-level correlation; metrics provide aggregate health without unbounded tenant labels.

## Exposure Boundary

`[observability] metrics_enabled=false` is the default. Enabling `/metrics` does not add tenant authentication; operators must restrict it with the management listener, service mesh, firewall, or edge policy appropriate to their deployment. The endpoint contains only bounded service metrics, but it is still operational information and should not be exposed as an anonymous public product API.

Health and metrics use the same WSGI process in the current PoC. A later deployment may bind operational endpoints to a dedicated listener without changing their resource contract.

## Multi-Worker Limitation

The current collector is process-local. With the reference two-worker Gunicorn configuration, a scrape reaches one worker and cannot represent the other worker's counters or histograms. This is acceptable only for the local implementation seam and is not a production metrics claim.

Before M3 acceptance, choose and prove one of:

1. Prometheus client's supported multiprocess mode with a correctly initialized and cleaned shared directory for every Gunicorn lifecycle;
2. an external OpenTelemetry/StatsD/Prometheus aggregation path;
3. a dedicated metrics process receiving bounded events from workers.

The acceptance test must exercise worker restart, stale-series cleanup, concurrent increments, and direct scrapes of every replica. Do not sum process-local `/metrics` responses at a load balancer without defined semantics.

## Verification

The local suite proves:

- liveness is independent of database failure;
- readiness returns 200/503 for successful/failing database probes with a neutral body;
- metrics can be disabled and then return 404;
- Prometheus content type and build/readiness samples render correctly;
- concrete resource IDs never appear in route labels;
- unknown method tokens collapse to `OTHER`;
- issued and invalid token decisions increment fixed result classes without including the Basic secret;
- `/healthz`, `/readyz`, `/metrics`, and `/auth/token` bypass tenant `auth_token` middleware while `/v1` remains protected.

The current repository suite passes 114 tests on each supported Python version. Gunicorn configuration and the disposable integration fixtures are verified separately in the completed execution evidence.

## Multi-Worker Reconciliation Evidence — 2026-07-23

Plan 0005 adds only the fixed `coffer_quota_reconciliation_outcomes_total{result}` family. Worker ID, project, repository, manifest digest, reservation ID, claim token, request ID, and dependency response never become metric labels. The focused verifier rejects an unknown result class before the Prometheus client can create a new series.

Scheduling correctness does not depend on these process-local counters. PostgreSQL 17.10 and MariaDB 11.4.12 independently proved database-backed expiring claims, spawned-process abandonment, lease recovery, and old-token fencing. The metrics describe the local process's outcomes only; the existing restart/multiprocess aggregation limitation still applies.

## Real Single-Process Evidence — 2026-07-22

The real integration harness now composes these exact resources with the production application-credential authenticator and token authorizer. Before and after an intentional broker restart, `/healthz` reported the process alive, `/readyz` completed a real SQLite `SELECT 1`, and `/metrics` contained build, readiness, token-decision, and duration samples.

The pre-restart process observed 18 token decisions and 0.2166 aggregate decision seconds: 13 issued, two expected invalid-credential probes, and three expected invalid request shapes. The post-restart process observed four decisions and 0.0481 aggregate seconds: three issued and one expected invalid-credential probe. Roughly 12 ms per observed decision is a lab-only aggregate that mixes result classes; it is not a production benchmark, percentile, or SLO.

The verifier rejected either metrics snapshot if it contained a real project ID, request ID, repository name, application-credential ID/secret, or JWT-shaped value. Detailed immutable IDs and Keystone audit correlation remained only in redacted broker logs. The counters reset after restart, confirming rather than resolving the documented process-local limitation.

## Remaining M3 Evidence

- shared production SQL, KMS, cache, and complete TLS failure-budget behavior;
- Distribution push/pull outcome metrics beyond log-level request-ID correlation;
- multiprocess and multi-replica aggregation;
- rate, latency, and error observation under representative load;
- bounded soft-quota admission/state/lag metrics and restart-correct reconciliation aggregation;
- GC and storage-maintenance metrics;
- operator alert thresholds and retention policy.

The M3 plan item stays open until those real operational checks pass.

## Primary References

- [Prometheus Python client](https://prometheus.github.io/client_python/)
- [Prometheus multiprocess mode](https://prometheus.github.io/client_python/multiprocess/)
- [OpenStack requirements at the selected commit](https://opendev.org/openstack/requirements/src/commit/1244391f2eb1a5b626c84ea9623d631ce5820ff7/upper-constraints.txt)
