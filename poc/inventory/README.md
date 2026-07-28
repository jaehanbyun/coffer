# Existing-content inventory fixture

This disposable fixture proves that the exact Distribution v3.1.1 storage
enumerators expose both a tagged image manifest and a digest-only untagged index
that the standard tags API does not list. The registry is stopped before two
storage scans. Its named volume is mounted read-only into the pinned Go helper,
and storage file hashes plus the Coffer control SQLite hash must remain unchanged.

The installed `coffer-inventory-verify` command validates bounded evidence pages,
two-scan equality, exact repository authority, payload/link digest agreement,
descriptor sizes and nested index children. It then creates a deterministic
artifact containing IDs and content facts but no repository name, tag, payload,
origin, credential, token, or timestamp.

Run with an already-running Podman machine:

```console
make -C poc/inventory verify
```

The helper now has two mutually exclusive storage adapters:

- `--root` retains the filesystem fixture contract; and
- `--config`, `--expected-distribution-version`, and
  `--expected-config-sha256` construct the exact release's registered
  `s3`/`s3aws` driver from one owner-only Distribution configuration.

The S3 adapter refuses a configuration that is not a regular single-link
mode-0600 file owned by the process, any `REGISTRY_*` override or ambient AWS
credential selector, a release/config digest mismatch, multiple/non-S3
drivers, storage middleware, proxy mode, missing static credentials, insecure
or unverified TLS, non-v4 auth, non-path-style RGW access, a root bucket
prefix, or request/body debug logging. Its total scan timeout is bounded from
one second through one hour and defaults to ten minutes.

Both adapters construct only a storage namespace and use the same repository
and manifest scan core. The helper does not start Distribution's HTTP
application, upload purger, events, health checks, cache, or delete/GC
behavior. S3/driver failures are reported as fixed categories without
configuration or backend detail.

The checked-in repeatable fixture still exercises only filesystem storage. S3 scans use
`coffer.distribution-storage-scan/v2` and bind the pinned Distribution source
revision, canonical runtime module graph, helper executable, exact
configuration, storage type, endpoint, bucket, and root through non-secret
SHA-256 evidence. `coffer-inventory-verify` preserves that binding in
`coffer.inventory/v2`, or v3 when compatible Docker/OCI blob media-type aliases
exist, and `coffer-import-inventory` validates it before the artifact digest can
authorize a baseline import. Filesystem v1 and single-media S3 v2 inventory
remain byte-compatible.

On 2026-07-28 the helper ran read-only against the retained preview RGW over
verified TLS. It emitted an owner-only v3 artifact, preserved two compatible
Docker/OCI blob media-type alias sets, imported once into disposable SQLite,
replayed as a no-op, passed independent ledger verification, and left zero
remote transient residue. Writers were not excluded and no backup/restore or
admission cutover occurred, so this is anticipatory evidence rather than a
production rehearsal. The immutable scratch image is not a signed production
artifact and the pinned Distribution/Ceph release pair remains blocked. The
helper therefore does not qualify RGW credentials, authorize a production
cutover, or become an upstream-supported Distribution API.
