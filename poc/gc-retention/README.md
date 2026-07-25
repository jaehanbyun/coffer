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

Run the focused proof with:

```bash
uv run pytest -q tests/test_gc_retention_state_machine.py
```

The next layer is a fixture-only lifecycle CLI and fake adapter. A later
filesystem fixture may invoke the exact upstream collector against a temporary
directory only after the pure gates pass. Disposable RGW/KMS and Kolla HA
execution remain later Stage 6 gates.
