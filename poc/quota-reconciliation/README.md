# Exact-digest quota reconciliation PoC

This disposable fixture verifies the bounded reconciliation component against
an unmodified, digest-pinned Distribution v3.1.1 process. Distribution uses an
ephemeral filesystem volume and is published only on IPv4 loopback; no
production registry, RGW data, token, or credential is used.

Run with a working Podman machine:

```bash
make -C poc/quota-reconciliation verify
```

The fixture publishes the same OCI manifest graph into `present` and `deleted`
repositories, leaves an `absent` reservation unpublished, deletes the first
manifest, and runs Coffer's real repository resolver, HTTP HEAD probe, and
quota state machine. It proves exact matching `Docker-Content-Digest` commit,
exact 404 release, stale-version rejection across reordered work, periodic
deletion refund, and preservation of shared descriptor bytes until their last
manifest reference disappears. The final usage is zero.

The SQLite file, Distribution container, network, volume, and retained logs
are removed even on failure. PostgreSQL and MariaDB row-lock behavior is
covered separately by `poc/quota-sql`; production authentication, TLS,
multi-worker claims/leases, scheduling, and service packaging remain outside
this fixture.
