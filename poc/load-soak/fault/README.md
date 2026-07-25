# Stage 6 serial fault executor

`run.py` owns the ten serial fault steps compiled by the Stage 6 load plan. An
owner-only invocation binds one exact schedule step, action binary and source
contract, opaque target evidence, state/lock/output/work paths, and an explicit
`fixture` or `pilot` source. The owner-only target document carries bounded
non-secret adapter selectors and binds their hash plus separate ownership and
topology hashes; only the hashes survive in state and result evidence.

Each fault follows:

```text
preflight -> inject -> full window -> observe -> recover -> verify
```

The executor holds a nonblocking invocation lock, starts only one action
process group at a time, passes only an owner-only generated invocation path,
and bounds runtime plus stdout/stderr. Each successful action advances an
atomic replay-validated hash chain. Target paths and identifiers remain in the
owner-only adapter input; retained state and output contain only fixed fault
names, counts, phases, and hashes.

An ambiguous inject, failed observation, interruption, lost process after
injection, failed recovery, or failed verification can never become completion
evidence. The same invocation first runs recover and verify. If that succeeds,
the state terminates as `failed-recovered` with no result; if it fails, the
active/recovered checkpoint remains for another recovery attempt. A normal
result requires all five actions, the full window, the recovery deadline, zero
unexpected errors, and no temporary residue.

Fixture output is explicitly synthetic and exits 3. The action and target
adapters remain local executable contracts until qualified binaries execute
every fault against the fresh disposable multinode pilot.
