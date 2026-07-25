# Coffer observability runbook

This runbook covers the bounded Coffer alert set installed by the companion
Kolla-Ansible role. Prometheus scrapes each Coffer replica directly over
verified backend TLS; the public registry FQDN and HAProxy VIP are not scrape
targets. The `Coffer Operator` Grafana dashboard is the first triage surface.

Do not paste tokens, application-credential secrets, private keys, repository
names, project identifiers, manifest digests, SQL rows, or object keys into an
incident, command line, metric label, or retained evidence. Preserve a failing
replica and its bounded logs before restarting it.

## CofferTargetDown

1. Identify the exact `job` and `instance` from the alert.
2. Check the matching Coffer container, private metrics listener, backend
   certificate validity, and controller-to-replica route.
3. Query `/healthz` and `/metrics` only through the direct backend address with
   the operator CA. A successful VIP request does not close this alert.
4. If only one replica is down and HAProxy still has healthy backends, retain
   evidence and use the normal Kolla reconfigure/restart path for that service.

## CofferNoHealthyBackend

1. Treat this as a service outage and stop maintenance, upgrade, GC, and
   cutover work.
2. Compare direct-target `up` with Kolla HAProxy backend state and container
   health on every expected replica.
3. Check shared causes first: certificate expiry, CA mismatch, network policy,
   image/config drift, and dependency outage.
4. Restore one known-good replica through the declared Kolla configuration;
   do not expose Distribution directly as a bypass.

## CofferErrorBudgetFastBurn

1. Identify whether pull, publish, or control-plane good-event ratio is
   consuming the budget.
2. Split bounded `5xx` outcomes by component and route, then correlate them
   with HAProxy, MariaDB/Galera, RGW, KMS, and Keystone health.
3. Freeze deployments and risky maintenance while the fast-burn condition is
   active.
4. Acknowledge recovery only after the short window clears and direct replica
   targets remain healthy.

## CofferErrorBudgetSlowBurn

1. Inspect the six-hour trend and the affected SLI; avoid treating a single
   quiet interval as recovery.
2. Correlate recurring error windows with reconciliation, credential
   rotation, backup, storage latency, or rolling maintenance.
3. Open a bounded corrective work item before the remaining budget reaches the
   production promotion threshold.

## CofferReconciliationStalled

1. Confirm that the periodic reconciler is intentionally enabled and that at
   least one direct `coffer-reconcile` target exists.
2. Inspect its last successful cycle, dependency signal, backlog, active
   claims, and stale claims.
3. Check verified private TLS, maintenance identity generation, SQL authority,
   and Distribution token-broker reachability without printing secret values.
4. Do not delete or rewrite claim rows manually. Recover through the declared
   fencing/session lifecycle and verify a new successful cycle.

## CofferStaleClaims

1. Identify affected worker and lease evidence from bounded application logs;
   never add project, repository, or digest data to metrics.
2. Verify database time, worker fencing, and whether the previous worker is
   still alive before reclaiming work.
3. Use the reconciliation lifecycle to expire/reclaim claims. Direct SQL
   deletion is not an accepted recovery procedure.

## CofferDependencyUnavailable

1. Use the fixed `dependency` label to select database, Keystone, registry,
   RGW, KMS, or HAProxy triage.
2. Compare the Coffer dependency signal with that system's native exporter and
   health endpoint.
3. Preserve fail-closed behavior; do not weaken TLS verification, reuse an
   administrative credential, or bypass quota admission to restore traffic.
4. After dependency recovery, verify direct targets, SLI recovery, and one
   normal operation before closing the incident.

## CofferMetricsSchemaMismatch

1. Compare the running image digest and generated configuration across all
   replicas of the affected job.
2. Verify that `/metrics` exposes the required process-start family and that
   the target has the stable `job` and `instance` labels.
3. Run the repository artifact contract and `promtool check rules` against the
   deployed revision.
4. Reconfigure or roll back to one immutable, qualified image digest. Do not
   silence the alert by removing the schema check.

## Deployment and validation

The role requires Kolla Prometheus, Alertmanager, and Grafana when
`coffer_enable_metrics` is true. It installs:

- `prometheus/prometheus.yml.d/15-coffer.yml`
- `prometheus/coffer.rules`
- `grafana/dashboards/coffer-operator.json`

Run the normal Kolla reconfigure flow for Prometheus and Grafana after changing
these controller-side artifacts. Validate the rule file with `promtool check
rules`, then verify all direct targets, the eight Coffer alerts, the six
recording rules, and the eight dashboard rows. Disabling Coffer metrics removes
only these exact Coffer-owned files and the registry metrics sidecar.
