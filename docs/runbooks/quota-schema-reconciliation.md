# Quota Schema and Reconciliation Operator Boundary

- Status: verified development baseline; not a production deployment procedure
- Related ADR: `docs/adrs/0009-add-private-edge-manifest-quota-admission.md`
- Related plans: `docs/exec-plans/0004-shared-sql-quota-reconciliation.md`, `docs/exec-plans/0005-multi-worker-reconciliation.md`

## Purpose and Safety Boundary

This runbook records which component owns the quota schema, what evidence permits reconciliation to change charged usage, and how to repeat the disposable proofs. It does not authorize a production database migration, import existing registry data, handle operator credentials, or start an uncoordinated worker fleet.

Before a production rollout, operators must separately provide a tested backup and restore procedure, TLS database connectivity, owner-restricted credential delivery, maintenance/rollback policy, and an inventory of existing registry data. Never put database URLs, service tokens, private CAs, or registry credentials in this repository, shell history, plan, or handoff.

## Authority Boundaries

| Concern | Authority | Fail-safe behavior |
|---|---|---|
| Quota schema | Checked-in Alembic revisions under `migrations/` | Coffer startup rejects missing, unversioned, or unexpected schema |
| Repository identity | Coffer control database | Missing or invalid authority makes the probe indeterminate |
| Manifest presence | Exact private Distribution digest endpoint | Only one matching digest header on 200 proves presence; exact 404 proves absence |
| Work ownership and mutation | Expiring shared-SQL claim, opaque fencing token, and reservation version | Expired/reassigned claims and stale versions cannot apply observations |
| Notification | Advisory wake-up hint | Lost, duplicate, or reordered events cannot authorize a refund |
| Physical reclamation | Coordinated Distribution GC procedure | Reconciliation changes logical accounting only and never deletes blobs |

`QuotaStore(..., bootstrap_schema=True)` exists only for explicit unit or disposable fixture setup. Normal construction validates `alembic_version` and the expected tables. Production code must never replace `alembic upgrade` with runtime `create_all()`.

## Empty-Database Migration

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

The checked-in baseline is an empty-database revision. Do not stamp or upgrade a database containing an earlier unversioned quota schema. Existing deployments require a separately reviewed inventory/import or data-preserving migration plan, a restorable backup, and an explicit maintenance window. A downgrade is exercised only in disposable verification and is not a production rollback prescription.

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

## Disposable Verification

With a working Podman machine, verify database behavior and the Distribution-backed state machine independently:

```bash
make -C poc/quota-sql verify
make -C poc/quota-reconciliation verify
```

The shared-SQL harness creates owner-only random passwords under ignored `work/`, applies and repeats the migration on PostgreSQL and MariaDB, checks model drift and constraints, opens independent connections, races two admissions, and performs a disposable downgrade/re-upgrade. It also divides three reconciliation candidates across database workers, verifies MariaDB's bounded contention retry, spawns a separate process that commits a claim and exits with status 17, proves quota remains charged, reclaims after expiry, rejects the old token, and ends at zero logical usage. The reconciliation harness publishes and removes exact OCI digests in an ephemeral unmodified Distribution, proves stale-result rejection and last-reference refunds, and ends at zero logical usage.

Both harnesses remove their labeled containers, networks, volumes, generated passwords, and SQLite state even after failure. They use loopback or isolated fixture paths and must not be pointed at a production database or registry.

## Production Promotion Gates

- A data-preserving upgrade/import rehearsal from the actual pre-quota state, including backup restore and rollback ownership.
- Database TLS, least-privilege migration and runtime roles, connection-pool sizing, timeout, deadlock retry, and Galera behavior where applicable.
- A private authenticated TLS probe path in the integrated Distribution/RGW topology; no tenant may bypass manifest admission.
- Production scheduler cadence, jitter, graceful shutdown, lease sizing, deadlock retry, database-time/clock policy, and Galera evidence; the current PostgreSQL/MariaDB process-exit proof is bounded development evidence.
- Protected, restart-correct multi-process/fleet aggregation and alerts for the implemented fixed `present`, `absent`, `indeterminate`, `stale_version`, and `stale_claim` outcomes, plus lag and dependency availability without project or digest labels.
- Existing registry inventory before enabling authoritative admission, plus integrated deletion/reference evidence against RGW.

Until every relevant gate passes, this implementation is a verified PoC baseline and must not be represented as a production-ready quota service.
