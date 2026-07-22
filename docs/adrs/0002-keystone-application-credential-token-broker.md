# ADR 0002: Translate Keystone Application Credentials into Short-Lived Registry JWTs

- Status: accepted
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0001-product-discovery.md`

## Context

Standard OCI clients authenticate through a registry `401` Bearer challenge, then request a repository/action-scoped token from the advertised realm. They do not send OpenStack `X-Auth-Token` headers on each blob request. Distribution expects a signed token with its issuer, audience, time, identity, and `access` claim contract.

Keystone provides project-scoped identity and role data. Application credentials give automation a project-bound ID/secret with an optional expiration and an explicit subset of the owner's project roles. Passing a Keystone token directly as a Distribution bearer would expose a broader OpenStack credential and would not satisfy Distribution's access claim contract.

## Decision

For the MVP, use a stateless Coffer token broker with this flow:

1. A user or CI workload creates a finite, restricted Keystone application credential for one project. `unrestricted=false` remains the default.
2. Docker/Podman/ORAS uses the application-credential ID as the Basic username and the secret as the Basic password when calling Coffer's token realm. Use `--password-stdin` and an OS credential helper; never place the secret in command history or checked-in configuration.
3. The broker authenticates the application credential through Keystone `POST /v3/auth/tokens` without adding a separate scope. It reads the immutable project, user/domain identity, roles, issued Keystone-token expiry, application-credential access rules, and audit IDs. The PoC rejects access-rule-bearing credentials until exact `oci-registry` rule enforcement is designed and tested.
4. The broker validates the requested registry `service`, canonicalizes every repeated repository `scope`, resolves the explicit repository record, verifies the project-ID namespace, and computes `requested actions ∩ oslo.policy actions`.
5. The broker issues a separate asymmetric-signed Distribution JWT with exact `iss`, `aud`, time claims, unique `jti`, stable subject, and exact `access` entries. Target lifetime is approximately five minutes and never below Distribution's 60-second client-compatibility floor.
6. Distribution validates the token locally using configured public keys. It never receives Keystone credentials or calls Keystone for blob requests.

Accept Docker's `offline_token=true` request flag for protocol interoperability, but do not issue an `offline_token` or `refresh_token` in the MVP because the Distribution specification describes the refresh credential as non-expiring. Role or credential revocation blocks new exchanges immediately; an already-issued registry JWT remains valid only until its short expiry.

## Initial Role Mapping

| Keystone project role | Registry grant |
|---|---|
| `reader` | `pull` |
| `member` | `pull,push` |
| `admin` | `pull,push,delete` plus project-level registry policy |
| standalone `service` | Internal service-to-service operations only; never automatic tenant data-plane access |
| domain/system role | Operator control APIs only; no implicit repository grant |

- Scope and role are always evaluated together.
- Tenant catalog listing is provided through a project-filtered control API; tenants are not issued global registry catalog permission.
- Cross-repository blob mounts require target push rights and source pull rights. Cross-project mounts are denied in the PoC.

## Why This Choice

- It preserves the standard registry challenge and works with unmodified clients.
- It keeps Keystone off the high-volume blob data path.
- Application credentials avoid human passwords and can be role-restricted, expired, invalidated, and rotated using existing OpenStack mechanisms.
- The broker owns only translation and policy intersection, not a second permanent identity database.
- Short registry JWT expiry gives a bounded revocation delay.

## Alternatives Rejected

### Use Keystone/Fernet tokens directly as registry bearer tokens

Rejected because they lack the Distribution audience/access claim contract, expose a more broadly useful OpenStack credential, and require the data plane to understand Keystone semantics.

### Store human Keystone passwords in Docker

Rejected because it exposes high-value, long-lived credentials and conflicts with federated/MFA identity.

### Use registry-local `htpasswd`

Rejected because it creates a second identity/authorization authority with no project or role lifecycle integration.

### Issue a non-expiring Distribution refresh token

Rejected because it weakens Keystone revocation and creates another long-lived credential class.

### Mint a separate Coffer login credential before every Docker login

Deferred rather than permanently rejected. It can improve federated/MFA interactive UX, but adds credential state and revocation machinery. First prove direct finite application credentials and a credential-helper path.

## Consequences and Risks

- Standard Docker configuration may persist the application credential unless a credential helper is configured; operator/user guidance is mandatory.
- Application credentials are owned by a user, not a project. Automation credentials need dedicated service users, finite expiry, role subsets, and planned rotation before owner disablement.
- Keystone outage blocks new token exchanges but existing registry JWTs continue until expiry; the broker fails closed.
- Exact namespace canonicalization, multiple scopes, action intersection, and cross-repository mounts become security-critical code.
- Interactive federated/MFA login needs a future credential-helper or short-lived exchange design.
- Access-rule-bearing application credentials must fail closed until the token realm enforces the Coffer service, method, and path restriction itself; bypassing `keystonemiddleware` cannot bypass the credential's delegated restriction.
- Distribution's local JWKS is rotation metadata, not a remote discovery protocol. Add the new public key to every replica before switching the broker signer; retain the old public key for the maximum registry-token lifetime plus skew, and restart or recreate Distribution when its trusted key set changes.

## Local M2 Evidence

The local protocol fixture recorded in `docs/research/m2-token-contract.md` proves the exact RS256 claim contract with unmodified Docker and Distribution, explicit-repository and `oslo.policy` reduction, reader/member isolation, same-project and denied cross-project mounts, negative JWT validation, direct post-restart blob digest verification, secret-free captured logs, and acceptance of either `kid` in an overlapping two-key JWKS. Synthetic identity, MinIO, plaintext loopback HTTP, and single-process key loading do not replace the required real Keystone, TLS, Ceph RGW, client matrix, or multi-replica rotation evidence.

## Real Vertical-Slice Evidence — 2026-07-22

The `poc/integration/` harness joined real DevStack Keystone to the production Coffer application-credential authenticator, explicit repository/`oslo.policy` reducer, and RS256 issuer, then configured unmodified Distribution v3.1.1 with only the public JWKS and the existing private Ceph RGW backend. A finite project-A member credential completed standard Bearer challenge, push, and pull with unmodified Skopeo and Podman. A valid project-B member credential received an empty grant for project A; Distribution returned 401 for the read and rejected the push. The Skopeo source digest remained identical after both Distribution and Coffer broker restarts.

Two explicit token exchanges correlated distinct `X-Openstack-Request-Id` values with immutable project IDs, Keystone audit IDs, requested actions, and granted/empty access decisions. Retained broker, Distribution, denied-push, and tunnel logs contained neither application-credential secret nor registry JWT. The run deleted both finite credentials and all private runtime state and restored the storage fixture. This closes the real single-process translation and project-isolation slice; it does not prove credential-helper storage, containerd/nerdctl/ORAS clients, multi-replica key rotation, shared runtime state, or HA failover.

## Required PoC Evidence

1. Two domains with identical project/user names remain isolated by UUID.
2. Credential deletion, role removal, expiration, and owner disablement reject new exchanges.
3. Reader/member/admin and service/system/domain-role matrices match the table.
4. Altered signature, wrong issuer/audience/algorithm, expired/not-yet-valid JWT, unknown service, duplicate/multiple scopes, and path-encoding attacks fail closed.
5. Docker, Podman, containerd/nerdctl, and ORAS complete the challenge without custom protocol behavior.
6. Logs correlate broker request ID/JTI with Keystone audit IDs but contain no Basic secret, Keystone token, or full registry bearer.

## Primary Evidence

- [Keystone application credentials](https://docs.openstack.org/keystone/latest/user/application_credentials.html)
- [Keystone guidance for services, projects, roles, and scopes](https://docs.openstack.org/keystone/latest/contributor/services.html)
- [Keystone service API protection](https://docs.openstack.org/keystone/latest/admin/service-api-protection.html)
- [OpenStack Identity v3 API](https://docs.openstack.org/api-ref/identity/v3/)
- [CNCF Distribution token flow](https://distribution.github.io/distribution/spec/auth/token/)
- [CNCF Distribution JWT format](https://distribution.github.io/distribution/spec/auth/jwt/)
- [CNCF Distribution scope model](https://distribution.github.io/distribution/spec/auth/scope/)
