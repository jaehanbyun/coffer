# Stage 6 control, token, and quota load core

This standalone Go 1.25 module closes the protocol-core gap for the load
topology's `control`, standalone `token`, and `quota-contention` operations.
It uses only the standard library and requires:

- three explicit HTTPS origins for Keystone, Coffer control, and registry
  token/data paths;
- an explicit CA pool, TLS 1.2 or newer, no ambient proxy, no redirect, a
  finite one-to-ten-minute timeout, and concurrency from 1 through 64;
- an injected finite application credential;
- one canonical project-scoped Coffer repository route and registry service;
- exact bounded Keystone application-credential token acquisition;
- a project-scoped `GET /v1/repositories` control probe;
- a standalone Basic application-credential registry-token request;
- concurrent owner-created manifest admission with exact 201/429 counts and
  response digests; and
- independent bounded cleanup of every successfully created manifest digest,
  even after a primary operation failure or cancellation.

Retained snapshots contain only fixed operation/result/count/duration
aggregates. Credential IDs/secrets, Keystone and registry tokens, project and
repository identities, manifest bytes/digests, URLs, and cleanup targets remain
in memory only.

`cmd/coffer-control-load` is the owner-only executable boundary. It accepts
only `--invocation <absolute-path>`. The invocation, CA, application
credential, qualified upstream-readiness document, and every quota manifest
must be mode-0600 regular single-link files owned by the process user. The
output parent must already be owner-only, the one-shot output must not already
exist, and every input/output path must be absolute and distinct.

The `coffer.control-load-invocation/v1` document binds:

- the exact `disposable-stage6-pilot` target class;
- separate HTTPS Keystone, Coffer control, and registry origins;
- one canonical project-scoped repository and registry service;
- a finite one-to-ten-minute timeout and concurrency from 2 through 64;
- exact positive expected 201 and 429 counts whose sum equals the manifest
  count;
- the running executable's SHA-256 and the load runtime manifest's
  source-contract SHA-256;
- the exact qualified readiness file and SHA-256; and
- two through 64 distinct owner-only JSON manifests with their individual
  SHA-256 values.

The executable verifies its own binary digest before any request. The supplied
source-contract digest is retained as provenance so the outer runtime manifest
and final evidence verifier can compare it with the checked-in Go source hash;
it is not a substitute for that independent comparison. Successful output is
one canonical mode-0600 `coffer.control-load-execution/v1` document containing
only provenance hashes and sorted fixed aggregates. Paths, URLs, credentials,
tokens, project/repository identities, manifests, manifest digests, and cleanup
targets are excluded. Preflight, runtime, quota, cleanup, and cancellation
failures write no success result.

Current tests use `httptest` TLS servers. They prove trusted/untrusted TLS,
credential and token transport, redirect refusal, exact quota outcomes,
cleanup after mismatch, cleanup failure separation, cancellation, bounded
configuration, executable/readiness/manifest drift refusal, unsafe-file and
path-alias refusal, fixed command failures, and secret-safe canonical output.
Real Coffer/Keystone execution on both supported architectures remains
release-gated, so this path is still `contract-only`, not runtime-qualified.

Run the local contract with the pinned project toolchain:

```console
env -u GOROOT mise x go@1.25.3 -- go test -race ./...
env -u GOROOT mise x go@1.25.3 -- go vet ./...
```
