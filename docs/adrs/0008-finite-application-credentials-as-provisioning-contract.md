# ADR 0008: Treat Finite Application Credentials as a Provisioning Contract

- Status: accepted
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0002-thin-vertical-poc.md`
- Evidence: `docs/research/m1-application-credential-authentication.md`

## Context

Accepted ADR 0002 requires dedicated, restricted, finite Keystone application credentials for registry login. A successful application-credential authentication proves the credential is currently valid and returns a project-scoped token, but the token contains only the application-credential ID. Its expiration is the Keystone token expiration, not evidence that the underlying application-credential record has a configured `expires_at`.

Coffer cannot distinguish finite and non-expiring credentials from the standard authentication response alone.

The disposable Mac/DevStack lab created member-role credentials with explicit expirations and authenticated them through Coffer over verified TLS. Keystone rejected a credential after its configured expiration, after its delegated role was removed, after its owner was disabled, and after explicit deletion. The successful access information still exposed the Keystone token expiry rather than independently proving the credential record's configured expiration. These results validate the provisioning and acceptance boundary without requiring privileged per-login introspection.

## Proposed Decision

For the PoC, treat finite lifetime as a provisioning and acceptance contract rather than adding a second metadata lookup to every token exchange.

- The documented credential-creation workflow must set an explicit expiration and restricted role subset.
- The real-environment acceptance script records only non-secret ID, project, roles, and expiration metadata and proves authentication failure after expiration, deletion, role removal, and owner disable.
- Coffer authenticates the credential through the standard Keystone application-credential method and keeps its secret request-local.
- Coffer does not store application-credential secrets or maintain its own credential registry.
- Coffer does not use a privileged service identity to read tenant application-credential records during each exchange.

If operators require the service to reject otherwise-valid credentials solely because their record has no configured expiration, return with empirical Keystone policy/access-rule/cache evidence and supersede this decision with a bounded introspection design.

## Rejected Alternatives

- **Infer finiteness from the issued Keystone token expiration:** that timestamp describes the token and cannot prove the application-credential record expires.
- **Query the credential record with the caller's new token on every exchange:** depends on Keystone policy/scope and application-credential access rules and doubles the login path's dependency work.
- **Query with Coffer's service credential:** expands tenant-credential read privileges and compromise impact for a property already enforceable during provisioning.
- **Store credential metadata or secrets in Coffer:** creates a second credential authority and rotation/revocation consistency problem outside the MVP.
- **Accept non-expiring credentials silently:** contradicts ADR 0002's bounded credential exposure requirement.

## Consequences

- The PoC can retain a standard, stateless Keystone exchange without an added privileged API call.
- Operators and client tooling must enforce explicit application-credential expiration during creation.
- Coffer can reject expired credentials because Keystone rejects them, but cannot independently prove a future expiry exists from one authentication response.
- Real lifecycle tests and documentation become release gates, not optional guidance.
- The real Keystone lifecycle matrix is a release regression gate: explicit expiration, delegated-role removal, owner disablement, and deletion must continue to invalidate authentication.
