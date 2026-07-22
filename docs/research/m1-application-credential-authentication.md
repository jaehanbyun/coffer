# M1 Application-Credential Authentication Seam

- Date: 2026-07-21
- Scope: registry token-realm caller authentication before JWT issuance
- Outcome: real Keystone authentication, roles, lifecycle, control middleware, bounded cache, and outage matrix verified
- Related decision: accepted ADRs 0002 and 0008

## Executive Result

Coffer now has a request-local Keystone application-credential authenticator and a bounded Basic-authorization parser. It uses `keystoneauth1.identity.v3.ApplicationCredential` over TLS verification with a finite HTTP timeout, requests no service catalog, and returns only the non-secret identity and audit fields needed for authorization.

The implementation does not store the supplied secret in the authenticator, principal, database, logs, or exception text. The Keystone plugin and session that necessarily hold the secret exist only inside one `authenticate()` call. The future token realm must likewise discard the parsed credential object after exchange.

The disposable Mac/DevStack lab now closes TLS, project scope, duplicate-domain-name isolation, finite credential creation, successful authentication, reader/member/admin role mapping, service/system/domain-role isolation, expiration, role removal, owner disable, deletion, and post-deletion rejection against a real Keystone deployment. It also proves the control API's real `keystonemiddleware` path, incoming service-role enforcement, bounded single-process cache behavior, and outage fail-closed response. Shared production SQL/memcache and multi-worker consistency remain deployment gates.

## Upstream Contract

Keystone [application credentials](https://docs.openstack.org/keystone/latest/user/application_credentials.html) bind an application to a project and either all or a subset of the owner's project roles. Authentication uses the application-credential ID and its one-time secret instead of a user password. Keystone stores the secret hashed and cannot return it later.

The [Identity v3 API](https://docs.openstack.org/api-ref/identity/v3/#application-credentials) does not accept a separate scope in an application-credential authentication request; the credential supplies its project scope. The current [`keystoneauth1` plugin](https://docs.openstack.org/keystoneauth/latest/api/keystoneauth1.identity.v3.html) implements that exchange and exposes the resulting project, user, roles, expiry, audit IDs, and application-credential ID through `AccessInfo`.

Coffer uses only ID-based credentials:

```text
Authorization: Basic base64(application-credential-id:secret)
        |
        v
strict bounded parser -> request-local ID/secret
        |
        v
keystoneauth1 ApplicationCredential -> Keystone /v3/auth/tokens
        |
        v
project-scoped non-secret principal -> role/scope intersection -> M2 JWT issuer
```

The M2 token realm follows the standard [OCI registry Bearer-token flow](https://distribution.github.io/distribution/spec/auth/token/). The control API remains behind `keystonemiddleware.auth_token`; the Basic-auth token realm uses a separate middleware path so a missing `X-Auth-Token` is not rejected before application-credential authentication.

Docker login requests `offline_token=true`. Coffer accepts the interoperability flag but deliberately omits `refresh_token` from the response; accepting the request is not permission to create the non-expiring credential class rejected by ADR 0002.

## Implemented Boundary

`ApplicationCredentialAuthenticator` stores only:

- Keystone authentication URL;
- TLS verification configuration;
- finite request timeout;
- class/factory references used to construct one local plugin and session per call.

On success it returns:

- application-credential ID;
- immutable user ID and project ID;
- case-sensitive role names;
- Keystone token expiration;
- Keystone audit ID and audit-chain ID when present.

It does not return or retain the Keystone token, service catalog, raw AccessInfo object, submitted secret, request header, or response body.

Because this realm bypasses `keystonemiddleware`, it must not silently bypass Keystone application-credential access rules. The PoC rejects any authentication response whose `application_credential.access_rules` field is present, including an empty rule list. Supporting such credentials later requires exact Coffer service/method/path validation against real Keystone. Dependency exceptions are converted inside the request-local exchange frame and discarded; the public exception and HTTP response retain neither the dependency error graph nor a secret-bearing local.

Failure mapping for the later HTTP resource is fixed as follows:

| Condition | Internal result | Token-realm response |
|---|---|---|
| Missing/malformed/oversized Basic credential | `InvalidBasicCredentials` | 401 with Basic challenge; no echo |
| Keystone rejects credential or identity is incomplete/non-project-scoped | `InvalidApplicationCredential` | 401; neutral body |
| Keystone connection, discovery, or timeout failure | `KeystoneUnavailable` | 503; no credential detail |
| Successful authentication | non-secret principal | continue to requested-versus-allowed scope intersection |

Real Keystone returns `keystoneauth1.exceptions.NotFound` for a deleted or nonexistent application credential in this flow. Coffer treats that client response as credential rejection, not service unavailability. Connection, discovery, timeout, and other unexpected client failures remain fail-closed as `KeystoneUnavailable`.

TLS verification defaults on. Operators may select a CA file. `insecure=true` exists only for deliberate disposable testing and cannot be an acceptance configuration. The initial timeout is 10 seconds; the real PoC must set it below the proxy/request budget and tune it from evidence.

## Basic-Input Hardening

The parser:

- accepts only the Basic scheme;
- validates Base64 strictly;
- splits only the first colon so the secret may contain colons;
- requires UTF-8 and non-empty ID/secret values;
- caps the authorization header at 16 KiB, the ID at 512 bytes, and the secret at 8 KiB;
- never includes the header or decoded values in an exception;
- marks the secret field `repr=False`.

Those limits are denial-of-service guardrails, not a new Keystone credential-format contract. Real generated credentials are much smaller.

## Finite-Credential Gap

ADR 0002 requires finite application credentials. Keystone enforces a configured credential expiration and will not authenticate an expired credential. Its [token provider also bounds the issued token by the application-credential expiry](https://opendev.org/openstack/keystone/commit/d01cde5a19d83736c9be235b27af8cc84ee01ed6). However, the successful authentication token exposes only the application-credential ID in its `application_credential` field; its `expires_at` is the issued Keystone token's expiry, not proof that the application-credential record itself has a non-null expiration.

Therefore a single standard authentication exchange cannot distinguish a finite credential from a non-expiring credential. A separate `GET /v3/users/{user_id}/application_credentials/{id}` returns the credential record's `expires_at`, but relying on that request has costs:

- policy and scope enforcement can vary by Keystone release/operator configuration;
- an access-rule-restricted credential may not authorize the Identity API path;
- every registry login gains another Keystone call and failure/cache mode;
- using Coffer's service identity for lookup expands its Keystone privileges and blast radius.

Accepted ADR 0008 therefore makes finiteness a provisioning and acceptance contract for the PoC: documentation creates the dedicated restricted credential with an explicit expiration, and real tests prove expiry/deletion/role-removal/owner-disable behavior. Coffer does not add a privileged per-exchange metadata lookup or its own credential registry unless empirical evidence later shows a safe requirement.

## Verification

Nine authenticator tests prove:

- the correct ID/secret, TLS verification, timeout, no-catalog option, and application metadata reach the local Keystone plugin/session;
- the returned principal contains only non-secret project/user/role/expiry/audit context;
- unscoped, incomplete, or mismatched application-credential identity is rejected;
- invalid credentials and Keystone outages fail closed without secret text in logs or public exceptions;
- an empty ID or secret is rejected before a Keystone call.
- access-rule-bearing application credentials fail closed;
- mapped dependency errors have no secret-bearing cause, context, or traceback local.

Ten parser tests prove valid secrets containing colons, redacted object representation, missing/wrong schemes, invalid Base64, missing ID/secret/separator, non-UTF-8 input, and oversize rejection.

The complete suite now contains 70 tests after adding the deleted-credential `NotFound` regression. It passes on Python 3.11.14, 3.12.2, and 3.13.14. The Mac/DevStack harness additionally proves real HTTP/TLS, project scoping, duplicate-name isolation, reader/member/admin/service effective roles, domain/system nonproject isolation, configured expiration, delegated-role removal, owner disablement, deletion, and post-deletion rejection through Coffer's production authenticator. Its control verifier proves real project-only middleware admission, correct incoming service-token role enforcement, a two-second revoke-cache bound, and 503 on a bounded unreachable Keystone endpoint.

## Next Gate

The local M2 realm now composes this seam and implements the exact Distribution JWT claim contract; see `docs/research/m2-token-contract.md`. The `poc/devstack` lab closes the planned real Keystone M1 application-credential, standard-role/scope, finite-lifecycle, control-middleware, service-token, bounded-cache, and outage matrix. Shared production SQL/memcache is deferred to the multi-worker deployment gate rather than claimed from this single-process lab.
