# Shared SQL quota verification

This disposable harness verifies the versioned quota ledger against real
PostgreSQL and MariaDB row locks. It is a development proof, not a production
database deployment or an online-upgrade procedure.

The fixture pins the multi-architecture PostgreSQL 17.10 Alpine and MariaDB
11.4.12 Noble image indexes by digest. Runtime passwords are generated under
ignored, owner-only `work/quota-sql`, mounted through Compose secrets, never
placed in Compose environment metadata, and removed with the project-scoped
containers, network, and volumes after every run.

Run with a working Podman machine:

```bash
make -C poc/quota-sql verify
```

Override `COFFER_POSTGRES_PORT` or `COFFER_MARIADB_PORT` if the loopback-only
defaults `55432` and `53306` are occupied. The verification applies both
Alembic revisions from an empty database, repeats the upgrade, checks the model
for migration drift, opens two independent SQL connections, and proves
concurrent one-winner admission, idempotent retry/commit/release behavior,
database check constraints, bounded downgrade/re-upgrade, and zero logical
usage after reconciliation.

It also races two claim workers over three reservations, verifies disjoint
fencing tokens, and launches a separate process that commits a claim and exits
with status 17. Quota remains charged until lease expiry, a replacement worker
receives a new token, and the old process's token cannot mutate state.
PostgreSQL 17.10 divided the initial contention 2+1. MariaDB 11.4.12 safely
returned 0+2 while one range was locked; one bounded retry after both short
transactions completed acquired the remaining item. A scheduler must
therefore tolerate a transient empty batch and retry later without treating it
as durable backlog exhaustion.

Cleanup proves that no labeled container, volume, network, or generated
credential remains.

The `postgresql` and `mariadb` package extras provide the pinned SQLAlchemy
drivers used by this harness. A production deployment still needs operator
database credentials, backups, an existing-data rollout plan, connection-pool
sizing, TLS, scheduler cadence/jitter and lease policy, clock/deadlock retry,
Galera behavior, and restart-correct metric aggregation.
