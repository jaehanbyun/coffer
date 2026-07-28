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
