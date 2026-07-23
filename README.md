# Coffer

Coffer is the project codename for an OpenStack-native OCI Registry service. It composes an upstream OCI Distribution data plane with Keystone-aware project isolation, authorization, policy, audit, and OpenStack-oriented operations.

The project is in proof-of-concept implementation. It is not yet a released service.

## Naming Contract

| Concern | Value |
|---|---|
| Project codename | `coffer` |
| Descriptive service name | `OCI Registry service` |
| Proposed Keystone service type | `oci-registry` |
| OpenStack CLI noun | `registry` |
| Component prefix | `coffer-` |
| Environment prefix | `COFFER_` |

The service type is a project proposal and is not currently registered in the OpenStack service-types authority. See [ADR 0005](docs/adrs/0005-name-coffer-and-oci-registry-service.md) for the accepted naming decision and constraints.

## Current Baseline

- Unmodified CNCF Distribution v3 data plane
- Short-lived registry JWTs issued by a Keystone application-credential broker
- Immutable Keystone project-ID namespaces
- Single-region Ceph RGW storage through the upstream S3 driver
- Private project-scoped repositories with bounded soft quotas
- Falcon WSGI control API served by a standard external WSGI process

## Current Implementation

M0 proves the unmodified OCI Distribution data path against local S3-compatible storage. M1 contains the first Coffer-owned seam: a Keystone-middleware-wrapped repository API with project UUID ownership, reader/member policy, and explicit fixture persistence. Local M2 adds a separately composed application-credential token realm, explicit repository and `oslo.policy` authorization, short-lived RS256 Distribution JWTs, and overlapping-JWKS verification. M3 adds an Alembic-owned shared-SQL control schema, a private manifest-admission seam with logical quota accounting, bounded exact-digest reconciliation, expiring multi-worker claims and fencing tokens, a deterministic read-only inventory verifier for pre-ledger content, a one-time transactional empty-ledger importer, a read-only exact post-import ledger comparator, and an injected-authentication live manifest-presence comparison core. Disposable labs validate the real Keystone, Ceph RGW, and Barbican SSE-KMS path plus tagged/digest-only Distribution storage enumeration and SQLite/PostgreSQL/MariaDB import/comparison semantics.

The API currently supports:

- `POST /v1/repositories`
- `GET /v1/repositories`
- `GET /v1/repositories/{repository_id}`

This is testable scaffolding, not a production endpoint. Unit and disposable fixtures opt into ephemeral SQLite schema bootstrap, while normal control and reconciliation processes require the exact Alembic revision. The Keystone tests use `AuthTokenFixture`, and the Distribution v3.1.1 fixture is blocked from production promotion by ADR 0006.

Run the isolated authenticated registry contract with:

```bash
make -C poc/m2 verify
```

The fixture uses synthetic identity, plaintext loopback HTTP, and MinIO. It cannot satisfy the real Keystone, TLS, Ceph RGW, or production release gates.

Run the disposable quota database, exact-digest reconciliation, and read-only
existing-content inventory proofs with a working Podman machine:

```bash
make -C poc/quota-sql verify
make -C poc/quota-reconciliation verify
make -C poc/inventory verify
```

These fixtures validate PostgreSQL/MariaDB migration, legacy repository-row adoption and retention, row locks, multi-worker claims, abandoned-process lease recovery, fencing semantics, reconciliation against isolated unmodified Distribution, a stopped-registry two-scan inventory containing tagged and digest-only revisions, one-transaction empty-ledger import/rollback/idempotency, and exact/drifted/restored post-import SQL comparison. The inventory helper is filesystem-only PoC evidence and the importer/comparator use synthetic disposable SQL; none of these fixtures provides production database/RGW credentials, rollout/backup/import authorization, authenticated live Distribution comparison, writer exclusion, admission cutover, Galera evidence, or production metric aggregation.

Before starting a normal Coffer process, an operator-owned migration job must run `uv run alembic upgrade head` with its database URL delivered through protected configuration. Revision `0003_repository_metadata` creates or strictly adopts the exact legacy repository table; revision `0004_inventory_import` adds an immutable singleton baseline marker and refuses downgrade after a committed import. Drift and unsupported offline adoption fail closed. See [ADR 0010](docs/adrs/0010-adopt-repository-metadata-into-alembic.md), proposed [ADR 0012](docs/adrs/0012-import-existing-content-into-empty-quota-ledger.md), and the [control schema runbook](docs/runbooks/quota-schema-reconciliation.md). Migration alone does not import manifests or make quota authoritative.

Run one bounded reconciliation cycle from protected operator configuration with:

```bash
coffer-reconcile --config-file /operator/secret/coffer.conf \
  --config-file /etc/coffer/coffer-reconcile.conf
```

The command also supports a serial `mode=periodic` loop with graceful signals, cursor continuation, bounded jitter, and capped dependency backoff. It rejects unsafe lease-versus-batch timing and non-loopback plaintext origins. The sample shape is [etc/coffer-reconcile.conf.sample](etc/coffer-reconcile.conf.sample); it intentionally contains no database connection or service credential.

The WSGI factory also exposes process liveness at `/healthz` and database readiness at `/readyz`. Prometheus-compatible `/metrics` is disabled by default and can be enabled with `[observability] metrics_enabled=true`; it is process-local PoC evidence and requires an operator-protected endpoint plus a multi-worker aggregation design before production use.

## Development

Install the locked test environment and run the focused suite:

```bash
uv sync --group test
uv run --group test pytest -q
```

The selected runtime matrix is Python 3.11–3.13. A real process uses the WSGI factory `coffer.wsgi:create_application()` with `COFFER_CONFIG_FILE` pointing to an operator-supplied configuration. Multi-worker execution requires a shared SQL database and token cache; the in-memory defaults are intentionally limited to tests and smoke work.

The reference process shape can be validated or started only after the configured database has reached Alembic head:

```bash
COFFER_CONFIG_FILE=/operator/path/coffer.conf \
  uv run gunicorn --check-config --config etc/gunicorn.conf.py \
  'coffer.wsgi:create_application()'

COFFER_CONFIG_FILE=/operator/path/coffer.conf \
  uv run gunicorn --config etc/gunicorn.conf.py \
  'coffer.wsgi:create_application()'
```

Do not place Keystone, database, signing, or cache secrets in the repository. The process configuration is only a concurrency baseline; dependency pools and timeouts must be tuned from real-environment evidence.

## Documents

- [Product discovery](docs/product-discovery.md)
- [MVP architecture baseline](docs/architecture/mvp-baseline.md)
- [OpenStack registry landscape](docs/research/openstack-registry-landscape.md)
- [M0 upstream compatibility](docs/research/m0-upstream-compatibility.md)
- [M1 framework selection](docs/research/m1-framework-selection.md)
- [M1 application-credential authentication](docs/research/m1-application-credential-authentication.md)
- [M2 registry token contract](docs/research/m2-token-contract.md)
- [M3 local observability baseline](docs/research/m3-local-observability.md)
- [M3 RGW/Barbican KMS capability and executed evidence](docs/research/m3-rgw-kms-capability.md)
- [M3 bounded quota design and validation](docs/research/m3-quota-enforcement-spike.md)
- [M3 existing-content inventory boundary](docs/research/m3-existing-content-inventory.md)
- [ADR 0010: Alembic repository metadata adoption](docs/adrs/0010-adopt-repository-metadata-into-alembic.md)
- [Proposed ADR 0011: pinned Distribution storage inventory](docs/adrs/0011-use-pinned-distribution-storage-enumerator-for-inventory.md)
- [Proposed ADR 0012: transactional empty-ledger inventory import](docs/adrs/0012-import-existing-content-into-empty-quota-ledger.md)
- [Proposed ADR 0013: explicit authentication for live comparison](docs/adrs/0013-require-explicit-authentication-for-live-comparison.md)
- [Real Keystone and Ceph RGW PoC runbook](docs/runbooks/real-keystone-rgw-poc.md)
- [Quota schema and reconciliation operator boundary](docs/runbooks/quota-schema-reconciliation.md)
- [Existing-content inventory operator boundary](docs/runbooks/existing-content-inventory.md)
- [Disposable Mac DevStack identity lab](poc/devstack/README.md)
- [Completed discovery plan](docs/exec-plans/0001-product-discovery.md)
- [Superseded thin vertical PoC](docs/exec-plans/0002-thin-vertical-poc.md)
- [Completed Barbican KMS and quota PoC](docs/exec-plans/0003-barbican-kms-quota-poc.md)
- [Completed shared-SQL quota and reconciliation plan](docs/exec-plans/0004-shared-sql-quota-reconciliation.md)
- [Completed multi-worker reconciliation plan](docs/exec-plans/0005-multi-worker-reconciliation.md)
- [Completed reconciliation runner plan](docs/exec-plans/0006-reconciliation-runner.md)
- [Completed unified control-schema plan](docs/exec-plans/0007-unified-control-schema.md)
- [Completed existing-content inventory plan](docs/exec-plans/0008-existing-content-inventory.md)
- [Completed transactional inventory-import plan](docs/exec-plans/0009-transactional-inventory-import.md)
- [Completed read-only post-import comparison plan](docs/exec-plans/0010-post-import-ledger-comparison.md)
- [Completed authenticated live inventory comparison plan](docs/exec-plans/0011-authenticated-live-inventory-comparison.md)
