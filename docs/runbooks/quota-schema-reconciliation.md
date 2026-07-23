# Control Schema and Quota Reconciliation Operator Boundary

- Status: verified development baseline; not a production deployment procedure
- Related ADRs: `docs/adrs/0009-add-private-edge-manifest-quota-admission.md`, `docs/adrs/0010-adopt-repository-metadata-into-alembic.md`, proposed `docs/adrs/0011-use-pinned-distribution-storage-enumerator-for-inventory.md`, proposed `docs/adrs/0012-import-existing-content-into-empty-quota-ledger.md`
- Related plans: `docs/exec-plans/0004-shared-sql-quota-reconciliation.md`, `docs/exec-plans/0005-multi-worker-reconciliation.md`, `docs/exec-plans/0006-reconciliation-runner.md`, `docs/exec-plans/0007-unified-control-schema.md`, `docs/exec-plans/0009-transactional-inventory-import.md`

## Purpose and Safety Boundary

This runbook records which component owns the quota schema, what evidence permits reconciliation to change charged usage, and how to repeat the disposable proofs. It does not authorize a production database migration, import existing registry data, handle operator credentials, or start an uncoordinated worker fleet.

Before a production rollout, operators must separately provide a tested backup and restore procedure, TLS database connectivity, owner-restricted credential delivery, maintenance/rollback policy, and an inventory of existing registry data. Never put database URLs, service tokens, private CAs, or registry credentials in this repository, shell history, plan, or handoff.

## Authority Boundaries

| Concern | Authority | Fail-safe behavior |
|---|---|---|
| Repository and quota schema | Checked-in Alembic revisions under `migrations/` | Coffer startup rejects missing, unversioned, drifted, or unexpected schema |
| Repository identity | Coffer control database | Missing or invalid authority makes the probe indeterminate |
| Manifest presence | Exact private Distribution digest endpoint | Only one matching digest header on 200 proves presence; exact 404 proves absence |
| Work ownership and mutation | Expiring shared-SQL claim, opaque fencing token, and reservation version | Expired/reassigned claims and stale versions cannot apply observations |
| Notification | Advisory wake-up hint | Lost, duplicate, or reordered events cannot authorize a refund |
| Physical reclamation | Coordinated Distribution GC procedure | Reconciliation changes logical accounting only and never deletes blobs |

`RepositoryStore(..., bootstrap_schema=True)` and `QuotaStore(..., bootstrap_schema=True)` exist only for explicit unit or disposable fixture setup. Normal construction validates the exact shared `alembic_version` and its required tables. Production code must never replace `alembic upgrade` with runtime `create_all()`.

## Fresh and Legacy-Repository Migration

Install the driver matching the operator database in an isolated environment:

```bash
uv sync --extra mariadb
# or
uv sync --extra postgresql
```

Supply the SQLAlchemy URL through the deployment's protected secret mechanism, disable shell tracing, and run the migration as a dedicated migration job before starting Coffer:

```bash
set +x
umask 077
export COFFER_DATABASE_URL='<operator-supplied SQLAlchemy URL>'
uv run alembic upgrade head
unset COFFER_DATABASE_URL
```

The current head is `0004_inventory_import`. A fresh database receives repository and quota tables. A database containing the exact older PoC `repositories` table is migrated online: revision `0003` validates its five columns, primary key, string bounds, nullability, and named project/name uniqueness, then adopts it without rewriting rows. Revision `0004` creates the singleton baseline-import marker; it refuses downgrade when that marker contains a committed import. Structural drift aborts before the relevant revision is recorded. Do not use `alembic stamp` to bypass validation.

The conditional create-or-adopt decision cannot be made safely by offline `--sql` generation, so that path is rejected. Downgrade across revision `0003` deliberately retains repository rows; normal processes still reject the downgraded revision until re-upgrade validates and adopts them again. This is disposable recovery evidence, not a production rollback prescription.

Repository-row adoption and marker migration do not inspect Distribution/RGW or populate quota descriptors, manifests, references, or reservations. The read-only verifier in `docs/runbooks/existing-content-inventory.md` proves a deterministic tagged/digest-only filesystem inventory boundary, and proposed ADR 0012 proves a disposable one-transaction import into empty SQLite/PostgreSQL/MariaDB ledgers. Production still requires exact RGW/helper qualification, a restorable backup, approved maintenance/import/rollback owners, representative-scale transaction evidence, authenticated post-import comparison, and admission cutover before quota can become authoritative.

## Existing-Content Baseline Import Contract

`coffer-import-inventory` accepts only a canonical `coffer.inventory/v1` file and
its independently supplied SHA-256. It reads the database URL from
`COFFER_DATABASE_URL`; do not place a URL or password on the command line. The
command is admissible only while every registry/admission writer is stopped, the
quota ledger is globally empty, quota counters are zero, and exact project quota
plus repository authority already exists.

The importer recomputes the artifact before database access. In one transaction
it creates the singleton marker, deterministic committed reservations,
reservation graphs, committed manifests, project descriptor reference counts,
and used-byte values. Exact replay is a no-op; a different marker, live/partial
ledger, missing quota, or mismatched repository owner fails closed. Observed
usage above a configured limit is retained without raising the limit, so novel
logical bytes remain denied. The result contains only aggregate counts, the
artifact digest, status, and over-limit project count.

The executable shape is:

```bash
set +x
umask 077
# Deliver COFFER_DATABASE_URL through the operator secret mechanism.
# Set INVENTORY_SHA256 to the independently verified sha256:64-hex digest.
coffer-import-inventory \
  --inventory /operator/evidence/coffer.inventory.json \
  --expected-sha256 "$INVENTORY_SHA256"
unset INVENTORY_SHA256
unset COFFER_DATABASE_URL
```

This checked-in command has disposable semantics only. A production invocation
still requires the sequence and approvals in
`docs/runbooks/existing-content-inventory.md`; successful exit does not prove
writer exclusion, backup restorability, post-import comparison, or permission
to enable admission.

## Reconciliation Contract

Each process has a stable diagnostic worker ID and requests a bounded claim page ordered by `(updated_at, reservation_id)`. In one short writer transaction, the database excludes active claims, locks only selected reservation rows with skip-locked semantics where supported, removes a selected expired claim, and creates a unique opaque fencing token plus expiry. The transaction closes before repository resolution or any network request.

A scheduler may pass the returned cursor while draining one scan, but it must begin later scans from the start and tolerate a temporarily empty page under contention. MariaDB 11.4.12 can return an empty batch to one simultaneous caller while another transaction range-locks part of the candidate range; a later bounded retry after the short transaction completes recovered the remaining work in the disposable proof. An empty contended batch is not durable proof that the backlog is exhausted.

For each candidate it:

1. Claims the candidate with an expiry, worker ID, and random token; the worker ID is diagnostic only and the token is the fencing authority.
2. Resolves the stored project and repository IDs through the Coffer control authority into `p/<project-id>/<repository>`.
3. Sends `HEAD /v2/<canonical-repository>/manifests/<sha256-digest>` to one credential-free configured HTTP(S) origin. Production must use a private TLS service path and an approved in-memory service-auth header or equivalent network identity.
4. Commits or refreshes state only for HTTP 200 with exactly one matching `Docker-Content-Digest` header.
5. Releases charged state only for exact HTTP 404.
6. Leaves quota state unchanged for 401, 403, every 5xx or other status, missing/mismatched/duplicate digest headers, missing repository authority, timeout, or transport failure. The claim remains until expiry and supplies bounded retry backoff.
7. Applies an actionable observation only if both the reservation version and current unexpired claim token match. Successful mutation consumes that claim in the same transaction. A version conflict releases only the matching old claim; an expired or reassigned token cannot remove its successor.

A process crash never releases quota. The committed claim remains until its lease expires, after which another process receives a new token. The old process cannot mutate state if it resumes late. The one-hour code maximum is a safety bound, not a recommended interval; production values must exceed the measured probe timeout while keeping crash recovery within the operator's reconciliation objective.

## Runnable Process Contract

The installed `coffer-reconcile` command is a separate native synchronous process. It does not run inside Gunicorn, use Eventlet, elect a leader, or overlap local jobs. Scale-out consists of independent processes using the same migrated quota/control database; plan 0005's claim token remains the distributed ownership authority.

Supply the normal owner-restricted Coffer database configuration plus a `[reconciliation]` group. The checked-in non-secret shape is `etc/coffer-reconcile.conf.sample`. A minimal one-shot invocation is:

```bash
coffer-reconcile --config-file /operator/secret/coffer.conf \
  --config-file /etc/coffer/coffer-reconcile.conf
```

`mode=once` runs one bounded cycle and exits. It is suitable for an operator-owned timer or CronJob once that deployment path is separately reviewed. `mode=periodic` runs immediately, then waits an interruptible jittered interval after each cycle. SIGTERM and SIGINT set a stop event, finish only the active synchronous page, preserve its cursor/snapshot if work remains, and prevent another run. Runs never overlap within one process.

A cycle follows the returned deterministic cursor for at most `max_pages_per_cycle`; if that bound is reached, periodic mode retains the cursor for its next cycle. This prevents permanently indeterminate oldest rows from starving later reservations while preserving an explicit work bound. One-shot schedulers should run frequently enough to continue any bounded remainder; a later invocation can still progress because active indeterminate claims are excluded until lease expiry.

The process rejects startup unless:

- `upstream_url` is one credential-free HTTP(S) origin with no path, query, fragment, or URL credentials;
- HTTPS uses the system trust store or the configured public `cafile`;
- plaintext HTTP is explicitly enabled and targets only loopback, which is a disposable fixture boundary;
- the database has the exact expected Alembic quota revision before the repository store is constructed;
- `lease_seconds >= batch_limit * timeout_seconds + 10`, covering the sequential page probe budget plus mutation grace;
- initial dependency retry is no greater than the configured cap.

Completed present, absent, indeterminate, and stale outcomes exit 0 and log only fixed aggregate counts. Invalid configuration/schema exits 78. An unexpected one-shot dependency/runtime failure exits 75 with a neutral result class and no exception text. Periodic mode instead applies symmetric bounded jitter, capped exponential failure backoff, and reset to the healthy interval after the next success. Fencing still rejects late results if real work exceeds the validated lease.

No service-auth secret, bearer token, client private key, or database URL belongs on the command line or in the sample file. This package does not solve authenticated service-to-service probe credential delivery; production integration must choose an owner-approved private TLS/network identity or in-memory credential path separately.

## Disposable Verification

With a working Podman machine, verify database behavior and the Distribution-backed state machine independently:

```bash
make -C poc/quota-sql verify
make -C poc/quota-reconciliation verify
```

The shared-SQL harness creates owner-only random passwords under ignored `work/`, creates one exact legacy repository row, applies and repeats the migration on PostgreSQL and MariaDB, checks row preservation, model drift, and constraints, opens independent connections, races two admissions, and performs a non-destructive downgrade/re-upgrade with repository re-adoption. It also divides three reconciliation candidates across database workers, verifies MariaDB's bounded contention retry, spawns a separate process that commits a claim and exits with status 17, proves quota remains charged, reclaims after expiry, rejects the old token, and ends at zero logical usage. After re-upgrade it forces the second inventory reservation to fail and proves full rollback, then races two exact importers, rejects a different baseline, and records over-limit usage without raising the limit. The reconciliation harness publishes and removes exact OCI digests in an ephemeral unmodified Distribution, proves stale-result rejection and last-reference refunds, and ends at zero logical usage.

Both harnesses remove their labeled containers, networks, volumes, generated passwords, and SQLite state even after failure. They use loopback or isolated fixture paths and must not be pointed at a production database or registry.

## Production Promotion Gates

- A data-preserving upgrade/import rehearsal from the actual pre-quota state, including backup restore and rollback ownership.
- Database TLS, least-privilege migration and runtime roles, connection-pool sizing, timeout, deadlock retry, and Galera behavior where applicable.
- A private authenticated TLS probe path in the integrated Distribution/RGW topology; no tenant may bypass manifest admission.
- Production database-time/clock, deadlock retry, Galera, connection-pool, and real load/timeout evidence; the current cadence, lease validation, and PostgreSQL/MariaDB process-exit proofs are bounded development evidence.
- Packaging and lifecycle evidence for the chosen operator surface (systemd timer/service, Kubernetes CronJob/Deployment, Kolla, or Helm), including rollout, concurrent replica, and forced-termination behavior.
- Protected, restart-correct multi-process/fleet aggregation and alerts for the implemented fixed `present`, `absent`, `indeterminate`, `stale_version`, and `stale_claim` outcomes, plus lag and dependency availability without project or digest labels.
- Exact-release existing registry inventory against a disposable RGW copy, transactional ledger import and post-import comparison before enabling authoritative admission, plus integrated deletion/reference evidence against RGW.

Until every relevant gate passes, this implementation is a verified PoC baseline and must not be represented as a production-ready quota service.
