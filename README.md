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

M0 proves the unmodified OCI Distribution data path against local S3-compatible storage. M1 contains the first Coffer-owned seam: a Keystone-middleware-wrapped repository API with project UUID ownership, reader/member policy, and SQLite-backed test persistence. Local M2 adds a separately composed application-credential token realm, explicit repository and `oslo.policy` authorization, short-lived RS256 Distribution JWTs, and overlapping-JWKS verification. M3 adds a private manifest-admission seam with Alembic-versioned shared-SQL logical quota accounting and bounded exact-digest reconciliation, and validates the real Keystone, Ceph RGW, and Barbican SSE-KMS path in disposable labs.

The API currently supports:

- `POST /v1/repositories`
- `GET /v1/repositories`
- `GET /v1/repositories/{repository_id}`

This is testable scaffolding, not a production endpoint. The committed default uses in-memory SQLite, the Keystone tests use `AuthTokenFixture`, and the Distribution v3.1.1 fixture is blocked from production promotion by ADR 0006.

Run the isolated authenticated registry contract with:

```bash
make -C poc/m2 verify
```

The fixture uses synthetic identity, plaintext loopback HTTP, and MinIO. It cannot satisfy the real Keystone, TLS, Ceph RGW, or production release gates.

Run the disposable quota database and exact-digest reconciliation proofs with a working Podman machine:

```bash
make -C poc/quota-sql verify
make -C poc/quota-reconciliation verify
```

These fixtures validate PostgreSQL/MariaDB migration and row-lock semantics plus reconciliation against isolated unmodified Distribution. They do not provide production database credentials, existing-data rollout, authenticated TLS scheduling, or multi-worker leases.

The WSGI factory also exposes process liveness at `/healthz` and database readiness at `/readyz`. Prometheus-compatible `/metrics` is disabled by default and can be enabled with `[observability] metrics_enabled=true`; it is process-local PoC evidence and requires an operator-protected endpoint plus a multi-worker aggregation design before production use.

## Development

Install the locked test environment and run the focused suite:

```bash
uv sync --group test
uv run --group test pytest -q
```

The selected runtime matrix is Python 3.11–3.13. A real process uses the WSGI factory `coffer.wsgi:create_application()` with `COFFER_CONFIG_FILE` pointing to an operator-supplied configuration. Multi-worker execution requires a shared SQL database and token cache; the in-memory defaults are intentionally limited to tests and smoke work.

The reference process shape can be validated or started with:

```bash
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
- [Real Keystone and Ceph RGW PoC runbook](docs/runbooks/real-keystone-rgw-poc.md)
- [Quota schema and reconciliation operator boundary](docs/runbooks/quota-schema-reconciliation.md)
- [Disposable Mac DevStack identity lab](poc/devstack/README.md)
- [Completed discovery plan](docs/exec-plans/0001-product-discovery.md)
- [Superseded thin vertical PoC](docs/exec-plans/0002-thin-vertical-poc.md)
- [Completed Barbican KMS and quota PoC](docs/exec-plans/0003-barbican-kms-quota-poc.md)
- [Completed shared-SQL quota and reconciliation plan](docs/exec-plans/0004-shared-sql-quota-reconciliation.md)
