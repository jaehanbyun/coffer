# M2 Registry Token Contract

- Date: 2026-07-21
- Scope: Coffer application-credential exchange to Distribution-compatible JWT
- Outcome: local protocol, authorization, and offline-verification baseline passed
- Related decisions: accepted ADRs 0002 and 0008

## Executive Result

Coffer now exposes a separately composed `GET /auth/token` realm that authenticates a Keystone application credential, resolves explicit repository authority from the control database, applies `oslo.policy`, and issues an RS256 JWT accepted by an unmodified Distribution v3.1.1 data plane. The control API remains behind `keystonemiddleware.auth_token`; the Basic-auth token realm does not pass through that middleware.

The local black-box fixture passed Docker login, member push/pull, reader pull, restart persistence, nonexistent-repository and denied delete/push cases, negative JWT validation, same-project blob mounting, cross-project mount non-disclosure, and an overlapping two-key JWKS. It uses a synthetic authenticator, plaintext loopback HTTP, MinIO, and the already gated Distribution v3.1.1 image. It is protocol evidence, not real Keystone, TLS, Ceph RGW, or production-release evidence.

## Public Contract

The endpoint accepts the standard Distribution token query fields `service`, repeated or space-separated `scope`, `account`, `client_id`, and `offline_token`. Unknown fields, duplicate singleton fields, an unexpected service, malformed scopes, duplicate repository scopes, and more than eight scopes fail with 400 before credential authentication.

Docker sends `offline_token=true` during login. Coffer accepts `true` or `false` for interoperability but never returns `refresh_token`; the response contains only:

```json
{
  "token": "<short-lived JWT>",
  "expires_in": 300,
  "issued_at": "2026-07-21T12:00:00Z"
}
```

The JWT contract is:

| Field | Contract |
|---|---|
| JOSE `alg` | exactly `RS256` |
| JOSE `kid` | configured ID or RFC 7638-style thumbprint of RSA `e`, `kty`, and `n` |
| `iss` | exact configured Coffer issuer |
| `sub` | authenticated immutable Keystone user ID |
| `aud` | exact configured registry service |
| `iat`, `nbf` | UTC issuance time rounded to a second |
| `exp` | earlier of issuance plus 300 seconds and the Keystone token expiry |
| `jti` | unique UUID per issued registry token |
| `access` | canonical repository grants after database/project/policy intersection |

The issuer refuses a token lifetime outside 60–300 seconds, refuses an RSA key smaller than 2048 bits, and refuses a PEM file readable by group or world. The response and logs never contain a refresh token. Distribution validates the JWT offline from its local JWKS and does not receive the Keystone application-credential secret or Keystone token.

## Identity and Secret Boundary

The Basic username must be a compact or canonical lowercase UUID application-credential ID. This excludes control-character and log-injection aliases from the ID-only authentication path. The bounded parser removes the Authorization header from the request environment before authentication.

The Keystone dependency exchange runs inside a containment frame that converts expected and unexpected dependency exceptions into a neutral result. The public authenticator deletes its secret local before raising a mapped error, and the HTTP resource returns expected 400/401/503 responses without chaining dependency or Falcon exceptions. Tests inspect exception cause, context, traceback locals, logs, responses, and retained objects for the submitted secret.

Keystone application-credential access rules are service/method/path restrictions that are normally enforced by `keystonemiddleware`. Because the Basic token realm intentionally bypasses that middleware, the PoC rejects any authentication result whose `application_credential.access_rules` field is present, including an explicit empty rule set. This fail-closed boundary avoids expanding a credential restricted to a different API. Supporting Coffer-specific access rules later requires exact `oci-registry` method/path matching and real Keystone tests; role checks alone are insufficient.

The ordinary application-credential `unrestricted=false` setting remains mandatory provisioning guidance. Its token `restricted` flag concerns whether the credential can create or delete other application credentials; it is distinct from API access rules.

## Namespace and Authorization

Only canonical repository names of this form are accepted:

```text
p/<lowercase project UUID>/<lowercase repository path>
```

Both compact 32-hex and canonical hyphenated project UUIDs are accepted. Repository segments begin and end with lowercase alphanumeric characters and may use single `.`, `_`, or `-` separators. Traversal, empty segments, uppercase aliases, unsupported action names, repeated actions, and duplicate scopes are rejected.

The broker resolves every same-project repository name in the control database, then computes `requested actions ∩ oslo.policy actions`:

| Project role | Maximum registry actions |
|---|---|
| `reader` | `pull` |
| `member` | `pull,push` |
| `admin` | `pull,push,delete` |
| `service`, domain/system roles, case-mismatched names | none |

A nonexistent repository or a scope for another project contributes no grant. The broker returns a valid token with reduced or empty `access`, following the Distribution authorization-server model; Distribution then rejects an operation that lacks the required grant. Coffer never grants registry catalog access, and create-on-push is not enabled.

## Process and Key Boundary

`PathDispatcher` routes only exact `/auth/token` requests to the Basic-auth realm. All other paths, including `/v1`, remain behind Keystone token middleware. The token path therefore cannot be accidentally rejected for missing `X-Auth-Token`, while control requests cannot bypass Keystone middleware.

The PoC signer loads one unencrypted RSA PEM supplied by the operator and publishes only its public JWK. The black-box fixture proves that Distribution accepts valid tokens selected by either distinct `kid` in an overlapping two-key JWKS. This is the required metadata shape for rotation, but not a live-reload or no-downtime rotation proof.

Distribution v3.1.1 loads trusted keys while constructing its token access controller. The production rotation procedure must therefore:

1. publish the old and new public keys to every registry replica and restart or recreate each replica;
2. verify both `kid` values directly against every replica;
3. switch every broker signer to the new private key;
4. retain the old public key for at least the maximum token lifetime plus validator clock skew;
5. remove the old public key, restart every registry replica, and prove that a still-time-valid old-key token fails while a new-key token succeeds.

Private-key encryption or HSM/KMS integration, atomic rollout, replica skew, rollback, and disaster recovery remain deployment design work.

## Audit Contract

Every token response has an `X-Openstack-Request-Id`. Issuance logs record request ID, JTI, immutable project/user IDs, Keystone audit IDs, normalized requested repository/actions, reduced grants, and result. Invalid request, invalid credential, identity outage, and too-short identity-token lifetime use neutral reason codes and never log the Basic ID, header, secret, Keystone token, or registry JWT.

This closes broker-side decision correlation only. Distribution request IDs and push/pull outcome correlation, metrics, and denial-event export remain M3 work.

## Black-Box Evidence

`make -C poc/m2 verify` creates disposable secrets and keys under ignored `work/m2/`, then proves:

- the live `/v2/` challenge advertises the exact realm and service;
- unmodified Docker Basic login succeeds, while an explicit live `offline_token=true` request returns no refresh token;
- a `member` can push and pull but receives an empty grant for delete, and Distribution rejects the delete with 401;
- a `reader` can pull but cannot push, while a project-A member cannot push a project-B repository;
- an unregistered same-project repository receives no grant and Distribution returns 401;
- after restarting Distribution, a layer is fetched directly from the Registry API and its SHA-256 equals the digest declared by the manifest, avoiding Docker-cache ambiguity;
- a same-project cross-repository blob mount returns 201 and exposes the blob in the target;
- mounting an existing project-B blob into project A and mounting a nonexistent digest both return the same 401 and remain 404 in the target, so the cross-project path does not reveal existence;
- expired, future `nbf`/`iat`, altered-signature, HS256, wrong-audience, and wrong-issuer tokens all return 401;
- a valid token signed by the second key in a two-key JWKS returns 200;
- an invalid application-credential secret returns 401 and an unknown registry service returns 400;
- token issuance decision records are present, while captured token-service, registry, and client-denial logs contain neither fixture credential secrets nor a full JWT.

Cleanup removes both private keys, the synthetic credential environment, SQLite control database, bearer-token cases, downloaded blob, Docker credential directory, containers, network, and fixture volume. Retained evidence is limited to public JWKS, the challenge, and redacted logs.

The corresponding local suite now contains 69 tests after the M3 observability seam. It covers exact claims and headers, lifetime/key/file-mode limits, role/policy reduction, project and repository mismatch, strict/repeated/traversal scope cases, bounded query and Basic parsing, access-rule rejection, exception-graph secret disposal, authentication error mapping, no-cache/request-ID response headers, audit logging, and separation of token, operational, and control middleware paths.

## Failures Resolved

- A temporary `DOCKER_CONFIG` hid Docker Desktop's active context and made the client fall back to `/var/run/docker.sock`. The harness resolves and exports the active daemon endpoint before replacing the config directory.
- Docker Desktop's daemon cannot call a token realm advertised as host `127.0.0.1`. Distribution advertises `host.docker.internal`, while host-side checks retain IPv4 loopback.
- Docker login requested `offline_token=true`; rejecting the field broke the standard client. The broker now accepts the flag but deliberately omits a refresh token, preserving ADR 0002.
- A just-pushed image made Docker pulls ambiguous because layers could remain in the client cache. The harness now downloads a declared layer through the live Registry API after restart and verifies its digest.
- A mount denial without a positive control could be caused by a malformed request. The harness first proves a same-project 201 mount, then compares existing and nonexistent cross-project attempts.
- Persistent Compose volumes could make later runs depend on earlier data. Cleanup now removes the named M2 volume.
- The first token path granted any canonical repository under the caller's project. It now requires an explicit control-database record and `oslo.policy` decision, matching the accepted MVP resource model.
- The first authenticator discarded Keystone access rules and chained dependency errors containing request bodies. It now rejects access-rule-bearing credentials and discards dependency exceptions and secret-bearing locals before returning an HTTP decision.

## Remaining Gates

Local M2 does not close the active plan's real-environment criteria:

- shared production SQL/memcache and multi-worker consistency; the Mac/DevStack lab now covers real Keystone HTTP/TLS, finite application-credential lifecycle, role changes, owner disablement, service-token enforcement, and bounded single-process cache/outage behavior;
- two domains with colliding names and reader/member/admin/service/system/domain identity matrices;
- an OS credential-helper runbook proven on supported clients; the fixture intentionally isolates Docker credentials in a temporary directory;
- Podman, containerd/nerdctl, and ORAS interoperability;
- Coffer-specific Keystone access-rule support, if required; the PoC safely rejects access-rule-bearing credentials;
- complete old-only, overlap, new-only key-rotation phases across multiple replicas;
- Ceph RGW, production TLS, shared SQL/cache, Distribution-correlated audit/metrics, and the Distribution release security gate.

## Primary References

- [Distribution token authentication specification](https://distribution.github.io/distribution/spec/auth/token/)
- [Distribution JWT claim specification](https://distribution.github.io/distribution/spec/auth/jwt/)
- [Distribution scope specification](https://distribution.github.io/distribution/spec/auth/scope/)
- [Distribution v3.1.1 token access-controller key loading](https://github.com/distribution/distribution/blob/v3.1.1/registry/auth/token/accesscontroller.go#L285-L385)
- [Distribution v3.1.1 repository action requirements](https://github.com/distribution/distribution/blob/v3.1.1/registry/handlers/app.go#L873-L998)
- [Keystone application credentials and access rules](https://docs.openstack.org/keystone/latest/user/application_credentials.html)
- [Docker credential storage and login](https://docs.docker.com/reference/cli/docker/login/)
