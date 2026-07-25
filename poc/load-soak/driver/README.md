# Raw OCI load driver core

This standalone Go module is the bounded protocol core for the Stage 6 load
and soak harness. It currently implements:

- deterministic replayable content up to 256 MiB without retaining payloads;
- verified HTTPS with an explicit CA pool and TLS 1.2 or newer;
- one exact same-origin Bearer challenge and finite same-origin token
  acquisition using an injected credential provider;
- finite retries for replay-safe transport failures and Distribution
  502/503/504 responses;
- monolithic blob upload and 16 MiB-or-smaller chunked upload;
- same-origin upload and final blob `Location` validation;
- exact content digest and chunk range verification;
- context cancellation, bounded response bodies, and fixed secret-safe failure
  classes; and
- concurrency-safe, fixed-bucket aggregates written as canonical owner-only
  JSON.

The module has no CLI or external service adapter yet. Its tests use local
`httptest` TLS servers only. It must not target a registry until the Stage 6
release fence reports qualified stable Distribution and Ceph releases and the
fresh disposable pilot passes preflight.

Run the local contract with the pinned project toolchain:

```console
env -u GOROOT mise x go@1.25.3 -- go test -race ./...
env -u GOROOT mise x go@1.25.3 -- go vet ./...
```

Chunk start failures stop without creating an untracked second upload. After
an ambiguous PATCH transport or 502/503/504 result, the client queries the
same upload URL. It advances only when the exact committed range is visible,
or resends once from the exact prior range; any other offset or continuation
fails closed.

The next slice adds the owner-only CLI configuration/result boundary. Real
Docker, Podman, Skopeo, ORAS, and nerdctl adapters remain separate.
