# ADR 0009: Add Private-Edge Manifest Admission for Bounded Project Quotas

- Status: accepted for PoC validation
- Date: 2026-07-22
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0003-barbican-kms-quota-poc.md`
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
5. Removed all disposable containers, volumes, credentials, JWTs, and private keys; retained logs contained no credential or JWT-shaped value.

Production promotion still requires PostgreSQL/MariaDB migrations and replica-level row-lock evidence, a reconciliation worker against real Distribution/RGW state, multi-replica private ingress enforcement, load/failure testing, and the remaining client matrix such as containerd/nerdctl and ORAS. The PoC's isolated SQLite transaction is concurrency evidence, not a production database recommendation.

The user accepted this seam as the quota PoC implementation target on 2026-07-22. The bounded local validation passed, but the remaining production gates above prevent treating it as a final deployable architecture claim.
