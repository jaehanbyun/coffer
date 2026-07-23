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
defaults `55432` and `53306` are occupied. The verification applies the full
Alembic chain from an empty database, repeats the upgrade, checks the model
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

After the clean downgrade/re-upgrade cycle, the harness creates synthetic exact
repository/quota authority and exercises revision `0004_inventory_import`. A
temporary database constraint forces the second manifest row to fail; marker
and every ledger table remain empty. Two simultaneous exact imports then
converge to one writer and one no-op, a different baseline is rejected, the
2-manifest/5-edge/2-manifest-row/4-descriptor shape matches, and honest usage
220 remains recorded against limit 10. The first MariaDB run exposed marker
deadlock 1213; the importer now uses a three-attempt whole-transaction retry
limited to known MySQL/PostgreSQL deadlock, lock-timeout, and serialization
codes.

The harness next runs `coffer-verify-inventory-import` semantics in one read-only
repeatable snapshot. Both engines accept the exact marker, authority, counters,
timestamps, reservations, edges, manifests, descriptors, and zero-claim state;
reject a released-manifest mutation with the fixed mismatch class; and accept the
restored ledger. The result is bounded SQL equality evidence, not writer
exclusion, authenticated live Distribution comparison, or cutover approval.

Cleanup proves that no labeled container, volume, network, or generated
credential remains.

The `postgresql` and `mariadb` package extras provide the pinned SQLAlchemy
drivers used by this harness. A production deployment still needs operator
database credentials, backups, production-scale inventory/import/comparison and
rollback ownership, connection-pool sizing, TLS, scheduler cadence/jitter and
lease policy, broader clock/deadlock policy, Galera behavior, and
restart-correct metric aggregation.
