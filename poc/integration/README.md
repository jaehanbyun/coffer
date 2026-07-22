# Real Keystone-to-RGW Integration

This harness joins the two independently verified labs into one disposable
Coffer vertical slice:

- real Keystone in the `coffer-devstack` Lima guest;
- Coffer's production application-credential authenticator, repository
  authority, policy reducer, and RS256 token issuer on the Mac;
- the pinned, unmodified Distribution v3.1.1 data plane on `coffer-rgw-poc`;
- the existing private Ceph RGW S3 bucket over verified TLS.

Run it from the repository root:

```bash
make -C poc/integration verify
```

The harness creates one finite member application credential in each of the
two duplicate-name Keystone projects. It gives both projects an identically
named control-plane repository, pushes and pulls through project A with
unmodified Skopeo and Podman clients, proves the digest survives both a
Distribution restart and a Coffer broker restart, and proves project B cannot
push to or read project A's immutable-ID namespace. Explicit token
requests retain only redacted request IDs, project IDs, HTTP outcomes, and the
image digest so token-broker decisions can be correlated with registry
results.

The broker also exposes the production `/healthz`, SQLite-backed `/readyz`,
and bounded process-local `/metrics` resources during this isolated run. The
harness captures all three before and after its intentional broker restart,
requires issued-token and ready samples, and rejects tenant, request,
credential, repository, secret, or JWT values in the metrics text. This proves
the single-process instrumentation seam only; it does not solve production
multi-worker aggregation.

The Mac-only broker endpoint uses an ephemeral private CA and an SSH reverse
tunnel to guest loopback. That topology proves the protocol and TLS boundary;
it is not a production endpoint design. Private signing keys, TLS keys,
application-credential secrets, SQLite state, Skopeo auth files, and bearer
tokens stay in ignored owner-only or root-only temporary state. Cleanup
deletes both Keystone credentials, removes guest integration state, removes
host private runtime files, restores the unauthenticated RGW persistence
fixture, and returns a previously stopped Lima guest to its stopped state.
