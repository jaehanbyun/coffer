# Stage 6 Quota and Reconciliation Evidence Sources

- Date: 2026-07-26
- Status: source mapping, read-only SQL snapshot, and transaction-attempt
  instrumentation implemented; Prometheus acquisition pending
- Scope: the quota and reconciliation auxiliary payloads consumed by
  `poc/load-soak/collector/phase_evidence.py`
- External operations: none; this result comes from current Coffer source,
  migrations, topology, and tests

## Outcome

The current product has enough direct state to build part, but not all, of
the quota and reconciliation artifacts. The read-only SQL boundary and
version-bound claim schema now supply charge, pending-delta, stale-claim, and
current claim-invariant facts. Private Prometheus surfaces now supply observed
quota transaction attempts in addition to worker/freshness and bounded
internal-error inputs. Exact phase-window acquisition and compilation remain
open.

`control_artifacts.py` must therefore not be implemented as a converter over
today's convenient metrics. Doing so would require one of three false claims:

- treating the configured transaction retry ceiling as the observed maximum;
- treating a schema uniqueness constraint as complete runtime claim/fencing
  evidence; or
- treating the expected reconciler replica count as observed availability.

The required implementation order is:

1. add one identity-free, read-only SQL evidence snapshot to `QuotaStore`
   (completed);
2. add direct observed transaction-attempt instrumentation at the quota write
   retry boundary (completed);
3. fix exact Prometheus query/result contracts for the required replicas and
   phase window; and
4. only then compile quota and reconciliation v2 source artifacts.

## Current Field Map

### Quota artifact

| Field | Exact current source | Disposition |
|---|---|---|
| `limit_usage_percent` | `project_quotas.limit_bytes`, `used_bytes`, and `reserved_bytes` for the one load-test project | Directly derivable in one read-only SQL snapshot as `(used + reserved) / limit * 100`; the zero-limit/zero-charge case is 0% and a positive charge with zero limit is an invariant failure |
| `headroom_percent` | Same quota row | Directly derivable as `100 - limit_usage_percent`; retain both only because the accepted verifier independently checks their sum |
| `stale_claims` | `QuotaStore.reconciliation_metrics_snapshot()` counts `quota_reconciliation_claims.expires_at <= observed_at` | Direct SQL source already exists; reuse the count from the same snapshot rather than issuing a second time-skewed query |
| `invariant` | `QuotaStore.control_evidence_snapshot()` independently recomputes committed and ordered pending charge without invoking mutating `_recompute()` | Implemented. Stored `used_bytes`, `reserved_bytes`, every pending `delta_bytes`, descriptor size consistency, and the configured limit are compared under one reader transaction |
| `max_transaction_attempts` | `coffer_quota_transaction_attempts` at the `_retryable_quota_write()` terminal boundary | Implemented as a histogram with exact integer buckets 1, 2, and 3 plus fixed operation/result labels. A reset-aware phase delta can reconstruct the maximum actually observed; the configured ceiling is never substituted |
| `unexpected_errors` | `coffer_quota_admission_total{result="internal_error"}` on each edge process | Existing metric source. Use a reset-aware phase delta across every exact edge replica; do not count expected `over_quota`, `invalid_manifest`, `unauthorized`, `missing_quota`, or injected `upstream_unavailable` outcomes as unexpected |

The selected logical usage includes `reserved_bytes`. Pending admission is
conservative capacity consumption, so excluding it would overstate headroom
during the contention window. The collector receives the load-test project
identifier only through an owner-only runtime input; no project identifier or
raw row survives in an artifact.

### Reconciliation artifact

| Field | Exact current source | Disposition |
|---|---|---|
| `stale_claims` | The same SQL reconciliation snapshot | Direct and shared with the quota artifact |
| `last_success_age_seconds` | Per-replica `coffer_reconciliation_last_success_timestamp_seconds` plus the phase observation time | Direct metric source. Compute the worst age across every required up reconciler; never use the freshest replica to hide a stalled peer |
| `workers_up` | Prometheus `up` for the exact direct reconciler instance allowlist already bound by the native target | Direct observed source; one replica may be down only in the declared `during` window |
| `workers_total` | Exact native target reconciler instance allowlist, cross-checked with `topology.json` | Bound expected population, not a health claim; it is accepted only alongside observed `workers_up` |
| `fresh` | Required replica `up`, bounded worst success age, and `coffer_dependency_up{component="reconcile",dependency="database"}` | Derivable only from all three direct observations. A missing, reset-only, stale, or database-down series is false, not zero/default |
| `claims_exact` | Claim primary key/unique constraints, reservation foreign key, migration `0006_claim_version_binding`, and `QuotaStore.control_evidence_snapshot()` | Implemented as a current invariant. Every active claim must map to one eligible reservation whose current version equals the version persisted when the claim was acquired |
| `fencing_violations` | `QuotaStore.control_evidence_snapshot().claim_invariant_violations` | Implemented as the number of current active claim state/version violations. Rejected `stale_claim`/`stale_version` outcomes prove the fence worked and remain separate diagnostics |

`claims_exact` is true exactly when the snapshot's claim-invariant violation
count is zero. `fencing_violations` retains that count for the current
contract. This is a point-in-time invariant, not proof that no historical
violation was later repaired. A future stronger historical claim requires an
append-only mutation audit; the Stage 6 collector must describe this limit.

## Read-Only SQL Snapshot Contract

The identity-free `QuotaControlEvidenceSnapshot` is returned by
`QuotaStore.control_evidence_snapshot()`. Its input is:

- one validated load-test project ID;
- one timezone-aware `observed_at`;
- the existing bounded reconciliation stale interval; and
- no repository, digest, token, claim token, worker identity, or credential.

One reader transaction returns only:

- `limit_bytes`, `used_bytes`, and `reserved_bytes`;
- recomputed expected used/reserved bytes;
- pending reservation count and mismatched-delta count;
- active/stale claim counts;
- eligible active-claim count and claim-invariant violation count; and
- a canonical snapshot hash calculated only after identifiers have been
  reduced to counts.

The snapshot is immutable and exposes no project, reservation, digest, claim
token, worker, or connection identity. It is bounded to 1,000 pending
reservations, 100,000 committed/pending descriptor rows, and 10,000 claims;
an exceeded bound refuses evidence rather than sampling it.

Migration `0006_claim_version_binding` persists each claim's reservation
version, backfills existing claims from their referenced reservations, adds a
positive-version constraint, requires version plus token on mutation/read
authorization, and refuses downgrade while any claim remains. This closes a
real prior gap: the claim object carried a version in memory, but the claim
row did not retain it for later invariant comparison.

The public artifact compiler converts snapshot values to percentages,
booleans, and counts. It must fail if:

- the project has no quota row;
- any stored or recomputed value is negative, exceeds signed SQL bounds, or
  makes charged usage exceed the limit;
- stored and recomputed charge differ;
- any pending reservation delta differs;
- claim rows do not map exactly to eligible reservation state/version; or
- the transaction cannot provide one consistent snapshot.

The existing `_recompute()` remains the writer repair path. The evidence
method must not call it because it updates reservation versions, timestamps,
and quota counters.

## Transaction Attempt Instrumentation

The retry decorator is the only exact place that sees a logical quota write's
observed attempt count. `QuotaStore` now accepts an optional bounded observer
and invokes it once when a decorated operation terminates, including terminal
failure. The observer receives only:

- a fixed operation class: `claim`, `commit`, `limit`, `reconcile`, `release`,
  or `reserve`;
- attempts in the closed interval 1 through 3; and
- a fixed result class: `success`, `conflict_exhausted`, `database_error`, or
  `rejected`.

Do not expose exception text, SQL state, project, repository, digest, request
ID, connection string, or method name. The
`coffer_quota_transaction_attempts` histogram has exact integer buckets 1, 2,
and 3. Edge and reconciliation stores bind it to their existing private
process-local metrics; disabled edge metrics bind no observer. Observer
failure is logged without exception text and never changes the quota
transaction result. The maximum is absent when no quota write occurred; the
collector must refuse that phase instead of substituting 1 or 3.

## Prometheus and Phase Binding

The future collector uses the private Prometheus API already present in the
native target. Its owner-only configuration binds:

- exact target bytes/hash, phase, window hash, and collector source hash;
- the SQL snapshot artifact bytes/hash;
- the exact API response bytes/hash for all query inputs;
- the required edge and reconciler instance allowlists; and
- the before/current counter baseline needed for reset-aware deltas.

It must verify process-start timestamps before accepting a decreasing counter,
apply fixed label/result allowlists, reject partial Prometheus warnings and
duplicate/missing series, and retain no raw URL or instance name. Querying a
HAProxy VIP or summing an unbounded job selector is not acceptable.

The quota and reconciliation artifacts may share one SQL snapshot and one
Prometheus capture, but they remain two separately hashed v2 artifacts with
their fixed downstream source classes.

## Rejected Shortcuts

| Shortcut | Reason rejected |
|---|---|
| Set `max_transaction_attempts` to 3 | Reports the configured ceiling, not what happened |
| Parse generic logs for all control fields | Log formatting and retention are not a consistent SQL snapshot; raw log parsing also expands the secret boundary |
| Set `claims_exact=true` because SQL has unique constraints | Does not check state/version eligibility or phase-time consistency |
| Count `stale_claim` and `stale_version` as fencing violations | Those results mean the fence rejected an unsafe write |
| Set worker totals from Kolla inventory and worker-up equal to totals | Converts desired state into observed health |
| Use only the newest reconciliation success timestamp | Hides a stalled required replica |
| Reuse workload `unexpected_errors` for quota internal errors | Conflates end-client failures with the product's bounded quota-admission result |
| Open a new public evidence endpoint | Auxiliary evidence remains on the private, phase-bound TLS server already implemented |

## Next Implementation Slice

Begin in `poc/load-soak/collector/control_artifacts.py`:

1. define the owner-only SQL and exact Prometheus source contract;
2. acquire the before/after histogram buckets, edge internal-error counters,
   per-reconciler `up`, success timestamp, and database dependency series;
3. reject missing, duplicate, partial-warning, stale, reset-without-process-
   restart, or out-of-allowlist series; and
4. compile separate identity-free quota and reconciliation v2 source
   artifacts for `phase_evidence.py`.
