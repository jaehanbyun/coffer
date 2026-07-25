# Stage 6 profile and ramp executor

`run.py` turns one exact compiled smoke, seven-level ramp, qualification, or
soak step into repeated concurrent child waves. It is the runtime owner for the
`profile-load` entries in `runtime_manifest.py`.

The owner-only invocation binds:

- the exact compiled plan and profile/ramp schedule identity;
- `disposable-stage6-pilot` and an explicit `fixture` or `pilot` source;
- the profile runner source-contract SHA-256;
- one SHA-bound executable and owner-only invocation template for every
  operation, with control/token/quota jointly owned by `control-load` and the
  remaining operations owned once by `raw-oci`;
- per-child transfer ceilings and explicit invocation-owned versus final
  repository-teardown cleanup ownership; and
- owner-only state, lock, result, and temporary-work paths.

Profile waves use the configured steady concurrency in the first and final
quarters and burst concurrency through the middle half. Ramp waves use the
exact fixed client level for 120 seconds. At most one `control-load` quota
contention child runs in a wave so its fixed temporary tags and cleanup cannot
race another invocation; remaining slots rotate deterministically through raw
operations. Every wave verifies child fixed stdout, empty stderr, exit status,
canonical result schema, successful aggregates, provenance, and transfer bound
before atomically advancing a bounded hash-chain checkpoint. A restart resumes
after the last complete wave.

Each child receives only `--invocation <owner-only-temporary-copy>`. No
credential enters arguments, environment, stdout, stderr, state, or result.
Subprocesses have a clean finite environment, independent process groups, and
bounded runtime and output. Failure or interruption terminates every group and
removes generated invocation, output, stdout, and stderr files. Successful raw
registry content remains owned by the disposable repository teardown;
`control-load` cleans its quota manifests within each invocation.

Fixture output is explicitly `synthetic=true`, prints
`load profile fixture completed`, and exits 3. It cannot qualify a runtime
binary. Pilot output exits 0 only after the full real duration, all operations,
zero unexpected errors, and the transfer ceiling pass. Real pilot execution is
still blocked by the signed stable Distribution and Ceph release gates.
