# Production Promotion Release Readiness

This harness is the first fail-closed checkpoint for Stage 6. It combines the
official release state for CNCF Distribution, Ceph Tentacle, and the
OpenStack `stable/2026.1` `oslo.messaging` dependency. All three must reach
`candidate-qualified` before a production image, RGW/KMS, load, or fresh
multinode pilot may be treated as promotion evidence.

Run the read-only refresh from the repository root:

```text
make -C poc/production-promotion check
```

The result is written mode `0600` under ignored
`work/production-promotion/release-readiness.json`. A blocked result is a
successful observation and exits zero. A promotion pipeline must instead run:

```text
make -C poc/production-promotion require-qualified
```

The underlying Python gate exits `3` until every exact release input has
already passed its specialist qualification; `make` reports that nonzero gate
as a failed target. It does not build an image, contact the retained preview,
create a credential, start a VM, or mutate an OpenStack service.

The UI observation is deliberately allowed to be at most one day old. Refresh
the checked-in observation only from official PyPI and OpenStack
`stable/2026.1` constraints metadata. An old observation fails as invalid
evidence instead of silently reporting the last known state.

`release_inputs_qualified=true` is only permission to begin the remaining
Stage 6 sequence. The aggregate always keeps `production_candidate=false`;
the final production decision additionally requires image, RGW/KMS,
maintenance identity, data protection, observability, GC, load/soak, fresh
Kolla multinode, teardown, and operator-release evidence.

## Canonical promotion ledger

Run:

```text
make -C poc/production-promotion ledger
```

This refreshes official release readiness, validates any retained GC result
through its dedicated verifier, and writes the mode-0600 canonical ledger to
`work/production-promotion/promotion-ledger.json`. The ledger has ten fixed,
ordered gates:

1. official release inputs;
2. immutable multi-architecture artifacts;
3. RGW/Barbican SSE-KMS;
4. the expiring maintenance identity;
5. backup/import/cutover/rollback;
6. production observability;
7. coordinated GC/restore;
8. representative load/soak/faults;
9. fresh Kolla multinode plus audited teardown; and
10. operator release and supply-chain review.

The command accepts no caller-supplied gate status. A gate can become `passed`
only through a schema-specific validator over a source-bound specialist result.
Absent live evidence remains `pending`; failed release readiness remains
`blocked`. Local fixtures, preview observations, a plan checkbox, or a manually
authored `passed` value cannot promote another gate.

The immutable-artifact specialist command is:

```text
make -C poc/production-promotion artifact-result
```

It validates release readiness before opening any image evidence. The current
blocked Distribution, Ceph, or oslo.messaging result therefore exits `3`
without reading the expected artifact paths or writing an output. After
release qualification, the command requires owner-mode-0600 core and UI
qualification results for native Linux amd64 and arm64 under:

```text
work/production-promotion/artifacts/
  amd64/core/{qualification.json,images.json}
  amd64/ui-qualification.json
  arm64/core/{qualification.json,images.json}
  arm64/ui-qualification.json
```

Both architectures must independently have runtime/provenance, immutable image
IDs, SBOMs, zero secrets, zero Critical/High findings, and zero Distribution
govulncheck findings. Kolla/Horizon/Skyline revisions and UI wheel hashes must
match across architectures. Only then is the mode-0600
`artifact-result.json` created and eligible for the ledger. The older ARM-only
blocked results and partial x86 UI transaction cannot be reused as qualified
evidence.

To refresh the accepted disposable filesystem GC specialist result first:

```text
make -C poc/gc-retention/filesystem promotion-evidence
```

The final enforcement target is:

```text
make -C poc/production-promotion require-promotion
```

It exits nonzero until every fixed gate is independently validated and the
ledger itself derives `production_candidate=true`. The current stable release
inputs fail before that point by design.
