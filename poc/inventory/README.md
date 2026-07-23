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

The fixture is a filesystem-backed PoC for the selected read-only evidence seam.
It does not import quota state, qualify RGW credentials/configuration, authorize a
production cutover, or make the helper an upstream-supported Distribution API.
