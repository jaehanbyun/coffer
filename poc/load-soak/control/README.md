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

Current tests use `httptest` TLS servers. They prove trusted/untrusted TLS,
credential and token transport, redirect refusal, exact quota outcomes,
cleanup after mismatch, cleanup failure separation, cancellation, bounded
configuration, and secret-safe aggregates. An owner-only executable
invocation and real Coffer/Keystone target remain next; this core is
`contract-only`, not runtime-qualified.
