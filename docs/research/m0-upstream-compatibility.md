# M0 Upstream Compatibility Baseline

- Date: 2026-07-21
- Scope: unmodified Distribution data plane only
- Environment: Docker Desktop on ARM64 macOS; registry and MinIO published only on IPv4 loopback
- Outcome: functional compatibility passed; production promotion blocked

## Executive Result

Distribution v3.1.1 can serve Coffer's thin data-plane prototype without a fork. Docker image push/pull, digest persistence across restart, S3-backed object persistence, OCI artifact attachment, and client-side referrer fallback all worked.

It is not an acceptable production pin. The exact image has unresolved Critical/High findings with reachable Go call paths, the supported-capability conformance profile has one core failure, and native OCI 1.1 Referrers is not implemented. M1 control-plane work may proceed against this isolated fixture, but production image selection remains gated by proposed ADR 0006.

## Pinned Inputs

| Input | Exact pin |
|---|---|
| Distribution release | [`v3.1.1`](https://github.com/distribution/distribution/releases/tag/v3.1.1), source commit `9a8d98b679740cd514aa7e7d84d23d442a5ef54c` |
| Registry multi-platform image | `sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33` |
| Registry Linux ARM64 manifest | `sha256:bc68ba48dae0e0423bb885c8d07d20c3210febbe996d38d54d32c574fda690ae` |
| OCI Distribution Spec | [`v1.1.1`](https://github.com/opencontainers/distribution-spec/releases/tag/v1.1.1), commit `a139cc423184af6078077b9b7ee336eddbd03f8f` |
| Official conformance image | `sha256:609201aab0905b1e90ded490e5f0dbaadc9a4bef98aca4cd38ff308f588ed27a` |
| ORAS | `v1.3.3`, multi-platform digest `sha256:a4c54befd87d0366e0ba3ac3a9536a5288c8a3735acd3b635cdace59a2c559c8` |
| MinIO local S3 substitute | `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` |
| Test image | `busybox:1.37.0@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028` |

The image and fixture digests are multi-platform manifest digests. The ARM64 child digest is recorded separately so the tested binary is unambiguous.

## License and Security Gate

Distribution v3.1.1 is licensed under [Apache License 2.0](https://github.com/distribution/distribution/blob/v3.1.1/LICENSE). Its release fixes CVE-2026-41888; v3.1.0 fixed CVE-2026-35172 and CVE-2026-33540. The corresponding upstream advisories are [GHSA-6pjf-3r9x-m592](https://github.com/distribution/distribution/security/advisories/GHSA-6pjf-3r9x-m592), [GHSA-f2g3-hh2r-cwgc](https://github.com/distribution/distribution/security/advisories/GHSA-f2g3-hh2r-cwgc), and [GHSA-3p65-76g6-3w7r](https://github.com/distribution/distribution/security/advisories/GHSA-3p65-76g6-3w7r).

Those project-specific fixes do not make the shipped binary clear under the prospective Coffer policy:

- Docker Scout 1.21.0 inspected the attached SBOM for the exact Linux ARM64 manifest and reported 8 Critical and 9 High findings across `golang.org/x/crypto` 0.49.0, `golang.org/x/net` 0.52.0, and Go standard library 1.25.9.
- `govulncheck` v1.6.0 analyzed the exact v3.1.1 source using a pinned Go 1.25.9 toolchain. It found eight vulnerabilities with symbol-level call paths: GO-2026-5856, GO-2026-5039, GO-2026-5037, GO-2026-5026, GO-2026-4982, GO-2026-4980, GO-2026-4971, and GO-2026-4918.
- Some traces depend on optional features or platforms, but not all are dismissible: TLS, token certificate verification, HTTP transport, and the S3 driver appear in reachable traces. No complete VEX disposition exists.

Decision: use the image only in the loopback M0/M1 fixture. Do not publish, deploy, or describe it as a production baseline. Re-run both scans on every candidate release.

## Functional Verification

`make verify` passed with these observations:

| Check | Result |
|---|---|
| `/v2/` on unmodified Distribution | 200 |
| Docker push and pull | passed |
| Subject manifest digest | `sha256:8050eefb54ecfbc909bb9937862ed100e9d361e3181a46b4d79a124f8d279d34` |
| Pull by digest after registry restart | passed with the same digest |
| ORAS artifact attach and discover | passed |
| Native `/referrers/<digest>` | 404 |
| ORAS referrers fallback tag | passed |
| S3-compatible bucket content | 23 objects at the recorded passing run |

The initial host probe used `localhost:5000` and reached macOS AirPlay on IPv6 `::1`, returning 403. The Compose port was correctly bound to `127.0.0.1`; all host-side M0 URLs now use that explicit address.

## OCI Conformance

Both profiles use the official OCI Distribution Spec v1.1.1 conformance image. Reports are generated under ignored `work/` paths and the harness preserves the non-zero test exit.

| Profile | Enabled capability assertions | Passed | Failed | Skipped |
|---|---|---:|---:|---:|
| Full | pull, push, content discovery, content management, automatic cross-mount | 68 | 7 | 4 |
| Supported | pull, push, content management; native Referrers and automatic cross-mount disabled | 59 | 1 | 19 |

Failure classification:

| Failure group | Count | Classification | Consequence |
|---|---:|---|---|
| Malformed manifest reference returns 500 instead of 400/404 | 1 | Core conformance failure | Production release blocker; upstream issue candidate |
| Automatic cross-mount without `from` returns 202 instead of 201 | 1 | Optional feature not implemented | Do not advertise automatic discovery; explicit cross-repository mount passed |
| Missing `OCI-Subject` response and native Referrers endpoint responses | 5 | Native OCI 1.1 Referrers capability absent | Client fallback works, but concurrent fallback tag updates can race |

The malformed reference request is `GET .../manifests/sha256:totallywrong`. Registry logs show an invalid storage path containing that value, and the response becomes `UNKNOWN`/500. The source treats any failed `digest.Parse` as a tag, then the common storage path validator rejects the colon. This is an inference from the [v3.1.1 manifest dispatcher](https://github.com/distribution/distribution/blob/9a8d98b679740cd514aa7e7d84d23d442a5ef54c/registry/handlers/manifests.go#L47-L58), [storage path validation](https://github.com/distribution/distribution/blob/9a8d98b679740cd514aa7e7d84d23d442a5ef54c/registry/storage/driver/storagedriver.go#L134-L139), runtime logs, and the [conformance assertion](https://github.com/opencontainers/distribution-spec/blob/a139cc423184af6078077b9b7ee336eddbd03f8f/conformance/01_pull_test.go#L237-L249). It is not specific to MinIO or RGW.

Automatic cross-mount is optional: the spec says a registry *may* treat `from` as optional and should return 202 when it cannot mount. Coffer should not enable the corresponding capability assertion for this release.

Native Referrers support is being developed upstream in [distribution/distribution#4828](https://github.com/distribution/distribution/pull/4828), which remained open during this verification. OCI 1.1 requires clients to use the [referrers tag fallback](https://github.com/opencontainers/distribution-spec/blob/v1.1.1/spec.md#unavailable-referrers-api) when the endpoint returns 404. ORAS did so successfully, but the specification notes that concurrent fallback updates can lose data. Native support therefore remains a release-selection criterion, not something Coffer should recreate in its control plane.

## Distribution Token Contract for M2

The exact v3.1.1 contract is documented by the upstream [Bearer token implementation](https://github.com/distribution/distribution/blob/v3.1.1/docs/content/spec/auth/jwt.md) and [token endpoint specification](https://github.com/distribution/distribution/blob/v3.1.1/docs/content/spec/auth/token.md):

- The registry emits a 401 Bearer challenge containing `realm`, `service`, and one or more repository `scope` values.
- The token service authenticates the client and places the intersection of requested and granted actions in the token; a reduced action set is not itself a token-endpoint error.
- The JOSE header requires `alg` and `typ=JWT`, with a key identifier mechanism such as `kid`.
- Registered claims are `iss`, `sub`, `aud`, `exp`, `nbf`, `iat`, and `jti`.
- The private `access` claim is an array of `{type, name, actions}` entries; Coffer uses `type=repository` and immutable `p/<project-id>/<repository>` names.
- The response returns `token` or `access_token`, with `expires_in` and `issued_at`. Coffer will not issue the optional non-expiring refresh token.
- Distribution validates the configured issuer and service/audience, time claims, access set, signing algorithm, and a locally configured root certificate bundle or JWKS file. Remote JWKS retrieval is not part of v3.1.1.

M2 must black-box the exact challenge, scope intersection, signature/key ID, audience, issuer, clock skew, expiry, and malformed/repeated scope behavior. M0 intentionally does not generate signing material.

## S3/RGW Configuration Baseline

The local fixture proved the following upstream S3 driver shape:

- explicit endpoint and region;
- SigV4 authentication;
- path-style requests;
- one private service bucket and a fixed root directory;
- redirect disabled so clients do not reach object storage directly;
- delete enabled for the conformance management workflow.

M0 uses plaintext MinIO and public fixture credentials only on a private Compose network. It does not establish Ceph RGW compatibility, TLS verification, least-privilege policy, SSE-KMS behavior, Keystone EC2 credentials, outage behavior, or production performance. Those remain M3 gates.

## Garbage Collection Constraint

The v3.1.1 [garbage-collection documentation](https://github.com/distribution/distribution/blob/v3.1.1/docs/content/about/garbage-collection.md) specifies stop-the-world mark and sweep. Uploading while collection runs can delete layers that are not yet marked and corrupt an image.

Coffer must coordinate read-only mode across every Distribution replica, drain writers, run a dry run, inspect evidence, run collection, and restore writes. Online or per-replica uncoordinated GC is outside the accepted baseline. Real RGW consistency and shared-layer survival still require M3 tests.

## ADR Implications and Next Gate

- Proposed ADR 0006 records that v3.1.1 is a PoC-only pin and defines the production release gates.
- No Coffer data-plane fork is justified by M0. The functional vertical slice works, and the identified gaps are better handled through release selection, upstream fixes, capability negotiation, and client fallback.
- The next implementation milestone is M1's Keystone-aware control API and token broker, but real acceptance requires a disposable Keystone environment. Ceph RGW is not needed until M3.
