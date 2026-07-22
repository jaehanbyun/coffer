# ADR 0009: Add Private-Edge Manifest Admission for Bounded Project Quotas

- Status: accepted for PoC validation
- Date: 2026-07-22
- Decision owners: Coffer maintainers
- Related plans: `docs/exec-plans/0003-barbican-kms-quota-poc.md`, `docs/exec-plans/0004-shared-sql-quota-reconciliation.md`
- Research: `docs/research/m3-quota-enforcement-spike.md`

## Context

Accepted ADR 0003 defines project quota as logical unique descriptor bytes referenced in that project and requires a measured bounded-soft admission/reconciliation model. The selected data plane is unmodified Distribution backed by one shared RGW bucket.

The implemented token realm can decide repository actions but a standard token request has no upload size or one-use operation identity. Distribution notifications are advisory and RGW sees only one service bucket. These existing seams can observe or globally limit storage, but cannot synchronously bound project logical usage.

## Decision

Add a narrow manifest-admission hook at the private registry edge:

1. Keep blob upload/download bodies on the normal streamed edge-to-Distribution path.
2. For manifest/index PUT only, verify the Coffer-issued Bearer JWT, enforce a small body limit, parse the descriptor graph, and call a Coffer quota-admission API.
3. In shared SQL, atomically reserve the new project-unique logical bytes before forwarding the exact manifest body to unmodified Distribution.
4. Commit manifest/reference state after Distribution returns success; retain a conservative pending reservation across ambiguous failure and repair it through an idempotent reconciliation worker.
5. Return a Distribution-compatible 429 when the logical limit is exceeded and 503 when the quota authority is unavailable or indeterminate.
6. Keep a service-wide RGW quota, upload purging, request limits, and GC as physical-staging guardrails. Do not claim a per-project hard physical-byte quota.

Distribution tenant write access must be private to the edge so manifest publication cannot bypass admission. Notifications may accelerate reconciliation but are never authorization or quota authority.

### Schema and reconciliation authority

- Alembic revisions are the sole production quota-schema authority. Application startup validates the exact expected revision and fails closed when quota tables or revision metadata are missing; `MetaData.create_all()` is restricted to explicit test-fixture bootstrap.
- Reconciliation reads bounded, deterministic `(updated_at, reservation_id)` pages from the durable ledger. It includes stale `pending` and `release_pending` work and periodically revisits `committed` manifests so a lost deletion notification is eventually repaired.
- Repository paths are rebuilt from immutable project and repository records in Coffer's control authority. The worker probes only the exact canonical digest with `HEAD /v2/<repository>/manifests/<digest>` over a private Distribution service path.
- Only HTTP 200 with exactly one matching `Docker-Content-Digest` proves presence. Exact 404 proves absence. Missing, mismatched, or duplicate digest headers, 401/403, every other status, and transport failures are indeterminate and leave the charge unchanged.
- Every reservation has a monotonically increasing version. Reconciliation applies an observation only when that version still matches, preventing a delayed or reordered probe from overwriting newer state. This compare-and-set guard is not a distributed work claim or lease.

## Consequences

- This adds a synchronous control dependency to manifest publication and requires shared SQL availability.
- Coffer or its edge integration briefly handles bounded manifest payloads, changing the earlier assumption that no manifest body crosses a Coffer-owned admission seam. Canonical payload storage remains Distribution/RGW only.
- Blob throughput remains outside Coffer; logical quota is enforced at publication rather than byte upload.
- Pending reservations favor safety over availability after crashes and can temporarily underutilize quota until reconciliation.
- Existing registry data requires a write-stopped import before the quota ledger is authoritative.
- All Coffer and Distribution replicas need a non-bypassable network topology and overlapping JWT trust.
- Physical staging may exceed a project's logical limit before publication; this is explicit and bounded only by service-wide storage safeguards.

## Alternatives Rejected by the Spike

- Token-time fixed reservation: unusable or unbounded because standard tokens carry no size and are reusable.
- Notification-only enforcement: cannot deny before publication and cannot bound missing/delayed event drift.
- RGW project quota in the shared bucket: no project identity exists at the storage credential boundary.
- Custom/forked Distribution middleware: violates the upstream data-plane baseline.

Project-isolated buckets/fleets remain a valid later alternative if users require hard physical isolation. Removing the MVP quota promise is preferable to advertising token-only or notification-only enforcement as bounded.

## PoC Validation and Production Promotion Gates

Completed in the local PoC:

1. Reviewed the edge/body-handling boundary against ADRs 0001 and 0004 and kept blob bodies on the streamed Distribution path.
2. Exercised pinned Docker 29.5.3, Podman 5.6.0, and Skopeo 1.20.0 through a private edge while Distribution had no host port.
3. Proved atomic one-winner concurrent admission with 201/429, idempotent 201 retry, missing-quota 503, project-unique shared-digest accounting, and conservative pending/release recovery.
4. Proved unpublished blob staging increased S3 objects from 28 to 30 while project logical usage stayed unchanged.
5. Applied the Alembic baseline from empty PostgreSQL 17.10 and MariaDB 11.4.12 databases, repeated the upgrade, compared the schema to the model, used two independent connections, proved one-winner row-lock behavior and retry/commit/release transitions, and completed a bounded downgrade/re-upgrade.
6. Exercised bounded reconciliation against an unmodified pinned Distribution v3.1.1 process. Exact presence committed a pending reservation, exact absence released unpublished and deleted manifests, stale observations lost their version race, and shared descriptor bytes remained charged until the last manifest reference disappeared.
7. Covered exact 200/404, 401/403/500/503, malformed success headers, and transport failure in focused tests. Only verified presence or absence changed ledger state.
8. Removed all disposable containers, volumes, networks, database passwords, SQLite state, credentials, JWTs, and private keys; retained logs contained no credential or JWT-shaped value.

Production promotion still requires an operator-owned online rollout/import and backup procedure for existing data, TLS and service authentication on the private reconciliation path, multi-worker scheduling with an explicit claim/lease policy, reconciliation in the integrated Distribution/RGW deployment, multi-replica non-bypassable ingress, load/failure testing, and the remaining client matrix such as containerd/nerdctl and ORAS. The disposable PostgreSQL/MariaDB and filesystem-backed Distribution fixtures prove the database and state-machine semantics; they are not a production deployment recommendation.

The user accepted this seam as the quota PoC implementation target on 2026-07-22. The bounded local validation passed, but the remaining production gates above prevent treating it as a final deployable architecture claim.
