# M0 Upstream Compatibility Spike

This environment tests an unmodified Distribution v3.1.1 data plane against an S3-compatible local substitute before any Coffer code is added.

It is loopback-only and intentionally unauthenticated. The fixture credentials are public test values. This environment is not a production or final TLS/RGW acceptance path.

## Pinned Inputs

| Input | Pin |
|---|---|
| Distribution | `registry:3.1.1@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33` |
| Distribution Linux ARM64 manifest | `sha256:bc68ba48dae0e0423bb885c8d07d20c3210febbe996d38d54d32c574fda690ae` |
| MinIO S3 substitute | `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` |
| MinIO client | `sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727` |
| ORAS | `v1.3.3@sha256:a4c54befd87d0366e0ba3ac3a9536a5288c8a3735acd3b635cdace59a2c559c8` |
| OCI conformance suite | Distribution Spec v1.1.1 commit `a139cc423184af6078077b9b7ee336eddbd03f8f`; official conformance image `sha256:609201aab0905b1e90ded490e5f0dbaadc9a4bef98aca4cd38ff308f588ed27a` |
| Test image | `busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028` |

## Run

```bash
cd poc/m0
make verify
make conformance-full
make conformance-supported
make scan-security
```

Inspect logs with `make logs` and stop the services with `make down`. `make reset` additionally deletes only the named M0 test volume and its object data.

The functional script verifies image push/pull by digest, persistence across a registry restart, OCI artifact attachment/discovery, the native Referrers API response, and object presence in the S3-compatible bucket.

The host-side scripts deliberately use `127.0.0.1` instead of `localhost`. On macOS, `localhost` can resolve to IPv6 `::1`, where AirPlay Receiver may already own port 5000 even though Docker is bound only to IPv4 loopback.

The conformance runner uses the upstream v1.1.1 `linux/amd64` image through Docker emulation so its result does not depend on the host Go toolchain.

`conformance-full` enables native Referrers discovery and automatic cross-mount capability tests. `conformance-supported` disables those two optional capabilities to isolate the core Distribution behavior. A non-zero conformance exit is retained rather than masked; inspect the generated JUnit and HTML reports under the ignored `work/` directory.

## Security Gate

As checked on 2026-07-21, Docker Scout resolved the pinned Linux ARM64 image from its attached SBOM and reported 8 Critical and 9 High dependency/standard-library findings. Upstream Distribution-specific GitHub advisories show v3.1.1 fixes CVE-2026-41888 and v3.1.0 fixed CVE-2026-35172 and CVE-2026-33540.

The image is acceptable only for this isolated compatibility spike. Production promotion is blocked until upstream publishes a supported image that clears the vulnerability policy or a reachability/VEX review demonstrates that every finding is non-applicable.
