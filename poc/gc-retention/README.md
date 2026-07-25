# Coordinated GC and retention contract

This directory contains the Stage 6 dry-run-first garbage-collection contract.
It currently performs no registry, S3, SQL, KMS, container, subprocess, or
network operation.

`topology.json` fixes:

- the exact Distribution baseline revision;
- one disposable target class;
- sixteen ordered lifecycle phases;
- complete immutable resource ownership and cleanup order;
- fixed survivor and failure classes;
- two required dry runs;
- a 1,000-item candidate ceiling;
- a 15-minute collection-authority ceiling; and
- permanent refusal of `--delete-untagged` for this baseline.

`state_machine.py` accepts only evidence that proves:

- one exact invocation-owned fixture;
- the fixed shared/index/digest-only/referrer content graph;
- one explicit policy-authorized logical delete;
- two read-only replicas and every probed writer path fenced;
- no active upload, multipart upload, or background mutator;
- complete SQL and versioned RGW backup plus isolated KMS restore check;
- exact baseline inventory and unchanged SQL;
- two identical candidate sets bound to image, binary, config, backend, fence,
  backup, and inventory;
- one finite, single-use collection authorization;
- successful upstream collection;
- every retained content class surviving and deleted content remaining absent;
- logical and physical/version reclamation reported separately;
- no RGW lifecycle or orphan deletion mixed into the transaction;
- exact isolated restore and fixed failure refusals; and
- zero invocation-owned residue with unrelated state unchanged.

The model stores immutable resource IDs only in owner-local state. Its public
evidence hashes those IDs and refuses credentials, tokens, keys, endpoints,
tenant/content identifiers, secret-like values, and dependency exception text.

Run the focused pure model and fixture-only lifecycle proof with:

```bash
uv run pytest -q \
  tests/test_gc_retention_state_machine.py \
  tests/test_gc_retention_lifecycle_cli.py
```

`lifecycle.py` stores state below `work/gc-retention/<invocation>` using
mode-0700 directories and mode-0600 atomic files under a nonblocking lock.
`preflight`, `status`, and `cleanup-plan` are local contract operations.
Every later phase requires `--adapter fixture --fixture
tests/fixtures/gc_retention.json`; no other adapter exists. The checked-in
fixture produces deterministic hashed evidence and fixed failure outcomes but
does not emulate a registry implementation or claim storage behavior.

The next layer is an exact-v3.1.1 collector-output normalizer followed by a
filesystem-backed temporary Distribution fixture. Disposable RGW/KMS and
Kolla HA execution remain later Stage 6 gates.

`collector_output.py` implements the first half of that layer without starting
the collector. It recognizes only the pinned v3.1.1 repository, mark, summary,
blob-candidate, and layer-link-candidate line shapes. Manifest candidates are
refused because they imply the forbidden untagged-deletion path. The parser
requires a consistent summary, declared repositories, unique bounded
candidates, no retained intersection, and an optional exact expected set. It
returns raw candidates only to its in-process caller; public evidence contains
aggregate counts and sorted hashes, never repository names or digests.

`filesystem/` completes the disposable local layer. It runs the pinned
collector twice in dry-run mode and once in destructive mode against only a
new temporary bind mount. The verified graph covers every retained class,
one explicit deletion, candidate-bound single-use authorization, logical
reclamation, isolated snapshot restore, and exact teardown. The accepted run
reported five candidates, nine survivor classes, 613 logical bytes reclaimed,
and zero residue. S3/RGW object versions and Ceph physical bytes remain
separate later evidence.
