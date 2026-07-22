# Quota Schema and Reconciliation Operator Boundary

- Status: verified development baseline; not a production deployment procedure
- Related ADR: `docs/adrs/0009-add-private-edge-manifest-quota-admission.md`
- Related plan: `docs/exec-plans/0004-shared-sql-quota-reconciliation.md`

## Purpose and Safety Boundary

This runbook records which component owns the quota schema, what evidence permits reconciliation to change charged usage, and how to repeat the disposable proofs. It does not authorize a production database migration, import existing registry data, handle operator credentials, or start an uncoordinated worker fleet.

Before a production rollout, operators must separately provide a tested backup and restore procedure, TLS database connectivity, owner-restricted credential delivery, maintenance/rollback policy, and an inventory of existing registry data. Never put database URLs, service tokens, private CAs, or registry credentials in this repository, shell history, plan, or handoff.

## Authority Boundaries

| Concern | Authority | Fail-safe behavior |
|---|---|---|
| Quota schema | Checked-in Alembic revisions under `migrations/` | Coffer startup rejects missing, unversioned, or unexpected schema |
| Repository identity | Coffer control database | Missing or invalid authority makes the probe indeterminate |
| Manifest presence | Exact private Distribution digest endpoint | Only one matching digest header on 200 proves presence; exact 404 proves absence |
| Reservation mutation | Shared SQL transaction and reservation version | A stale version loses compare-and-set and cannot apply its observation |
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

The reconciler reads a bounded page ordered by `(updated_at, reservation_id)`. A scheduler should pass the returned cursor until the page is exhausted, then begin a later periodic scan. The worker performs no network request while holding a SQL row lock.

For each candidate it:

1. Resolves the stored project and repository IDs through the Coffer control authority into `p/<project-id>/<repository>`.
2. Sends `HEAD /v2/<canonical-repository>/manifests/<sha256-digest>` to one credential-free configured HTTP(S) origin. Production must use a private TLS service path and an approved in-memory service-auth header or equivalent network identity.
3. Commits or refreshes state only for HTTP 200 with exactly one matching `Docker-Content-Digest` header.
4. Releases charged state only for exact HTTP 404.
5. Leaves state and timestamps unchanged for 401, 403, every 5xx or other status, missing/mismatched/duplicate digest headers, missing repository authority, timeout, or transport failure.
6. Applies an actionable observation only if the reservation version still matches the scanned candidate.

The current compare-and-set behavior prevents an old result from overwriting newer state, but it is not a distributed lease. Until a claim/lease and retry policy is implemented and tested, run at most one scheduled reconciliation worker per database. Duplicate execution is conservative and idempotent but can waste probe capacity and does not provide fair work distribution.

## Disposable Verification

With a working Podman machine, verify database behavior and the Distribution-backed state machine independently:

```bash
make -C poc/quota-sql verify
make -C poc/quota-reconciliation verify
```

The shared-SQL harness creates owner-only random passwords under ignored `work/`, applies and repeats the migration on PostgreSQL and MariaDB, checks model drift and constraints, opens independent connections, races two admissions, exercises retry/commit/release, and performs a disposable downgrade/re-upgrade. The reconciliation harness publishes and removes exact OCI digests in an ephemeral unmodified Distribution, proves stale-result rejection and last-reference refunds, and ends at zero logical usage.

Both harnesses remove their labeled containers, networks, volumes, generated passwords, and SQLite state even after failure. They use loopback or isolated fixture paths and must not be pointed at a production database or registry.

## Production Promotion Gates

- A data-preserving upgrade/import rehearsal from the actual pre-quota state, including backup restore and rollback ownership.
- Database TLS, least-privilege migration and runtime roles, connection-pool sizing, timeout, deadlock retry, and Galera behavior where applicable.
- A private authenticated TLS probe path in the integrated Distribution/RGW topology; no tenant may bypass manifest admission.
- A bounded multi-worker claim/lease, retry, shutdown, and cursor scheduling design with process-kill and replica-failure evidence.
- Operational metrics and alerts for scanned, present, absent, indeterminate, stale-version, lag, and dependency failure outcomes without project or digest labels.
- Existing registry inventory before enabling authoritative admission, plus integrated deletion/reference evidence against RGW.

Until every relevant gate passes, this implementation is a verified PoC baseline and must not be represented as a production-ready quota service.
