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
defaults `55432` and `53306` are occupied. The verification applies the
Alembic head from an empty database, repeats the upgrade, checks the model for
migration drift, opens two independent SQL connections, and proves concurrent
one-winner admission, idempotent retry/commit/release behavior, database check
constraint enforcement, bounded downgrade/re-upgrade, and zero logical usage
after reconciliation. Cleanup then proves that no labeled container, volume,
network, or generated credential remains.

The `postgresql` and `mariadb` package extras provide the pinned SQLAlchemy
drivers used by this harness. A production deployment still needs operator
database credentials, backups, an existing-data rollout plan, connection-pool
sizing, TLS, and multi-worker reconciliation coordination.
