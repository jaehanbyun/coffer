# Disposable filesystem GC fixture

This fixture executes the exact pinned Distribution v3.1.1 garbage collector
only against a newly created temporary filesystem bind mount. It never
connects to S3, RGW, SQL, KMS, Keystone, Kolla, or a remote host.

The fixture publishes and verifies all nine retention classes from
`topology.json`: a shared blob, a private blob, a tagged manifest, an index,
its digest-only child, a digest-only manifest, a subject, a referrer, and the
OCI fallback referrers index. A separate manifest and its two unique blobs are
explicitly deleted through the Distribution API before writers stop.

The harness then:

1. stops the only registry writer;
2. snapshots the temporary storage tree;
3. runs two networkless, exact-image dry runs;
4. normalizes both outputs against the precomputed retained and candidate
   sets;
5. creates and consumes one 900-second, candidate-bound authorization;
6. runs one collection without global untagged deletion;
7. verifies all survivor classes and logical reclamation;
8. starts a separate registry over the snapshot copy and verifies restore; and
9. removes every labelled container, network, lock, and temporary file.

The collector has a read-only root filesystem, no network, no-new-privileges,
and only `DAC_OVERRIDE` after dropping all capabilities. That single
capability is required because the registry and collector alternate access to
a mode-0700 host bind mount through rootless Podman.

Run from a terminal that keeps the Podman machine alive:

```console
make -C poc/gc-retention/filesystem verify
```

To retain one canonical owner-only specialist result for the Stage 6 promotion
ledger, use:

```console
make -C poc/gc-retention/filesystem promotion-evidence
```

The result compiler consumes both normalized dry runs, the destructive
collector output, consumed single-use authorization, collected/restored
survivor checks, reclaim proof, and exact source hashes. It stages a candidate
before fixture removal and emits
`work/production-promotion/gc-filesystem-result.json` only after the harness
independently confirms zero labelled containers, networks, and runtime paths.
The output is mode 0600 and an existing result is never overwritten.

The accepted local run on 2026-07-25 reported five exact candidates, nine
survivor classes, 613 logical filesystem bytes reclaimed, successful isolated
restore, and zero fixture residue. This is a disposable filesystem result. It
does not prove RGW object-version reclamation, Ceph physical-byte reclamation,
or production safety.
