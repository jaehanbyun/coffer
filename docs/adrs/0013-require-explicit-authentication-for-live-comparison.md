# ADR 0013: Require Explicit Authentication for Live Baseline Comparison

- Status: proposed
- Date: 2026-07-23
- Decision owners: Coffer maintainers and deployment operators
- Related plan: `docs/exec-plans/0011-authenticated-live-inventory-comparison.md`
- Related ADRs: `docs/adrs/0002-keystone-application-credential-token-broker.md`, `docs/adrs/0008-finite-application-credentials-as-provisioning-contract.md`, `docs/adrs/0011-use-pinned-distribution-storage-enumerator-for-inventory.md`, `docs/adrs/0012-import-existing-content-into-empty-quota-ledger.md`

## Context

Proposed ADR 0012 now has bounded evidence for importing a verified baseline and
comparing the complete SQL ledger. Production promotion still needs a separate
authenticated observation that every inventory manifest root is readable from
the live Distribution path before admission becomes authoritative.

That comparison crosses two different authorities. Coffer SQL maps immutable
repository UUIDs to current canonical paths; Distribution authorizes a Bearer
subject for repository-specific actions. The inventory artifact deliberately
omits mutable repository names and every credential. Adding either to the
artifact would weaken its durable evidence boundary.

An ordinary Keystone application credential does not solve a multi-project
baseline implicitly. Keystone creates it for the project to which its owner is
currently scoped and delegates the same or a reduced role set on that project.
The Distribution token contract likewise intersects an authenticated subject's
authorization with requested repository actions. Multiple repository scopes can
appear in one token request, but that does not grant the subject authorization it
does not already possess.

Primary contracts:

- [Keystone application credentials](https://docs.openstack.org/keystone/latest/user/application_credentials.html)
  define project binding, delegated role subsets, one-time secret disclosure,
  hashing, expiration, invalidation, and rotation.
- [Distribution token authentication](https://distribution.github.io/distribution/spec/auth/token/)
  defines the Bearer challenge/exchange and requested-versus-granted
  intersection.
- [Distribution token scope](https://distribution.github.io/distribution/spec/auth/scope/)
  defines repository resources, `pull` actions, subject/audience binding, and
  multiple requested resource scopes.

## Proposed Decision

1. The live-comparison core first verifies the exact imported ledger and resolves
   repository UUID/project/name routes in one read-only repeatable SQL snapshot.
   It closes that snapshot before any network operation.
2. The core accepts only an injected `AuthenticatedManifestProbe`. Before any
   digest HEAD, the probe must prepare authentication for every resolved
   repository target or fail with one fixed authentication-required class.
   Anonymous fallback is forbidden.
3. Each manifest is requested only by canonical repository name and immutable
   digest. One 200 with exactly one matching `Docker-Content-Digest` is present;
   exact 404 is absent; 401, 403, every other status, missing/incorrect/duplicate
   digest header, timeout, TLS, transport, or probe failure is indeterminate.
4. The core continues across all manifest roots and returns only aggregate
   present/absent/indeterminate counts plus the inventory-artifact digest. Any
   non-present result raises one fixed mismatch class without tenant, repository,
   manifest, origin, credential, header, URL, or SQL detail.
5. This proposal does not select the production probe provider. Until a follow-up
   acceptance decision and operator evidence exist, there is no installed live
   comparison CLI and no Coffer-created maintenance identity or secret-delivery
   format.
6. Successful output is named `verified`, never `ready` or `cutover-approved`.
   SQL equality plus live presence still cannot prove writer exclusion over the
   observation interval, all-replica consistency, backup restorability, rollback
   readiness, operator authorization, or admission safety.

## Production Provider Candidates Still Requiring a Decision

| Candidate | Benefit | Unresolved cost/risk |
|---|---|---|
| Per-project finite application credential and token exchange | Preserves existing project ownership and least-privilege pull reduction | Potentially large credential fan-out, lifecycle coordination, evidence retention, and multi-project failure recovery |
| Dedicated maintenance principal issuing exact repository-read claims | One bounded operation can cover the signed route set | Introduces a privileged cross-project boundary, new policy/actions, audit requirements, rotation, and blast-radius review |
| Operator-owned mTLS read-only comparison proxy | Separates machine identity from tenant credentials and can enforce HEAD-only paths | Adds a new proxy/trust/HA component and must prove exact repository authorization rather than network location alone |

The least-privilege default for further evaluation is per-project exchange. It is
not accepted here because representative credential count, provisioning,
revocation, failure recovery, and owner-only delivery evidence do not yet exist.
A maintenance principal or proxy must not be implemented merely to simplify the
PoC.

## Consequences

- The comparison algorithm is testable without embedding a privileged identity
  decision in artifact, SQL, command-line, or configuration contracts.
- Repository routing remains current control-plane authority and is observed in
  the same snapshot as ledger equality. A rename after that snapshot is an
  external-writer violation, not something the comparator can serialize across
  HTTP.
- Authentication preparation occurs before the first probe, but the provider is
  responsible for proving that its prepared state is truly authenticated,
  repository-bounded, expiring, revocable, and secret-safe.
- All HTTP failures remain conservative evidence failures. The comparator never
  reconciles, releases quota, repairs rows, retries with anonymous access, or
  changes Distribution state.
- A large baseline currently means a serial bounded-time comparison. Production
  promotion needs measured concurrency/rate/timeout behavior without changing
  aggregate-only output or holding SQL through network I/O.

## Alternatives Rejected for This PoC

- **Anonymous HEAD with private-network trust:** network location is not project
  authorization and can hide a missing registry auth configuration.
- **One tenant application credential for every project:** contradicts
  Keystone's project-bound delegation model unless a new privileged policy is
  explicitly designed and accepted.
- **Bearer token or application secret on the command line/environment:** risks
  process, shell-history, diagnostic, and handoff exposure and prematurely fixes
  a delivery format.
- **Repository names or tokens in `coffer.inventory/v1`:** mixes mutable routing
  and secrets into long-lived signed content evidence.
- **Reuse the reconciliation worker end to end:** that path claims and may mutate
  ledger state; live baseline comparison must remain read-only.
- **Hold the SQL snapshot during HTTP:** creates unbounded database resource and
  timeout coupling without proving external writer exclusion.

## Evidence and Acceptance Gates

Focused tests prove same-snapshot route resolution, a concurrent route change
remaining outside that snapshot, noncanonical-route refusal, zero DML, mandatory
probe preparation before network, exact all-manifest aggregation, fixed handling
of absence/indeterminate/probe exceptions, secret-safe output, authenticated
Bearer HEAD success, and wrong-token 401 refusal. Existing tests independently
cover every exact Distribution HEAD status/header/transport outcome.

A fresh unmodified Distribution fixture is deliberately deferred: without an
accepted provider it would prove only another static synthetic Bearer mechanism.
The existing M2 fixture already proves unmodified Distribution validates Coffer
JWT repository claims, while the reconciliation fixture proves exact digest HEAD
against unmodified Distribution. The missing evidence is the production
maintenance subject and delivery path, not Distribution's token validation.

Before accepting this ADR for a production candidate, maintainers still need:

- select one provider through security/operator review and record its exact
  Keystone, Coffer policy, token, expiry, revocation, rotation, and audit contract;
- prove owner-only credential delivery without command-line, environment,
  repository, evidence, log, exception, or handoff exposure;
- test a representative multi-project baseline, partial provider failure,
  credential expiry/revocation, wrong scope/audience/signature, and dependency
  outage against private TLS endpoints;
- prove all-replica/load-balancer behavior, writer exclusion for the full
  inventory/import/SQL/live interval, backup restore, rollback, and controlled
  service restoration; and
- obtain explicit authorization for production credentials, data, maintenance,
  comparison, and any later admission enablement.
