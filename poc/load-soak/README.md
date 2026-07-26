# Stage 6 load and soak contract

This directory contains the fail-closed load, soak, saturation, and fault
contract described in `docs/research/stage6-load-soak.md`.

`topology.json` fixes:

- smoke, qualification, and two-hour soak profiles with transfer ceilings;
- the seven-level virtual-client ramp;
- Docker, Podman, Skopeo, ORAS, nerdctl, and raw OCI client classes;
- twelve bounded operation and nine content classes;
- p95/p99 latency and availability thresholds;
- resource headroom, limit usage, retry, and replica boundaries;
- ten serial fault windows and recovery limits;
- direct metric targets, recording rules, and alert allowlists; and
- exact invocation-owned resource and residue categories.

`state_machine.py` is pure local validation. It requires qualified released
dependencies on both architectures before runtime topology or load evidence
can advance. A complete state then proves exact clients, deterministic seed,
smoke, a measured saturation point, qualification, every fault, soak, final
data/Galera/quota invariants, restart-correct metrics, secret-safe canonical
history, unchanged unrelated state, and zero residue.

The model does not start a client, registry, database, RGW, KMS, Kolla,
container, VM, subprocess, socket, or network request. It is not load evidence.
`lifecycle.py` adds the fixture-only lifecycle. It atomically checkpoints all
thirteen phases below one exact invocation, uses an owner-only nonblocking
lock, rejects every adapter except the explicit versioned fixture, identifies
its dependency evidence as synthetic, detects state/history tampering, resumes
or returns an exact terminal result idempotently, and removes its local state
without residue.

`evidence.py` implements the canonical production-mode verifier. It accepts
only one sorted `coffer.load-soak-evidence/v1` document, exact caller-supplied
qualified release/image/configuration/client/driver bindings, and the complete
ordered phase evidence. It replays the pure state machine and returns only
binding, artifact, facts, history, and topology hashes. Synthetic evidence,
unknown fields, noncanonical files, release drift, missing phases, raw
identities, and weakened phase results fail closed.

`driver/` contains the standalone Go raw-OCI protocol core. It generates
bounded deterministic streams, follows the exact same-origin Bearer flow over
verified TLS, performs monolithic and chunked blob uploads, validates digest,
range, and `Location` continuity, records fixed secret-safe result/latency
buckets, and emits canonical owner-only JSON. After an ambiguous chunk PATCH,
it queries the same upload URL and only advances or resends from an exact
committed or prior offset; partial or drifted state fails closed.

The owner-only executable now requires exact mode-0600 invocation, CA,
credential, and SHA-bound `candidate-qualified` readiness files, and verifies
its output destination before any request. All upload, blob-read,
manifest-read/publish, and same-project cross-mount operations are now exposed
through the invocation. Cross-mount fallback is cleaned and classified.
Subject-bearing artifacts now distinguish exact native OCI 1.1 Referrers from
the standard fallback-tag path, and exactly two partial uploads are cancelled
without retaining their identities on success or failure.

`clients/` now pins Docker, Podman, Skopeo, ORAS, nerdctl, and containerd
versions/source revisions and implements their bounded command, CA,
stdin-password, isolated-state, digest-verification, and cleanup contracts.
Its owner-only runner additionally binds exact pins and qualified upstream
readiness, emits only canonical mode-0600 results, and cleans child state on
failure or interruption. Executable fakes prove the local boundary; real
pinned binaries on both architectures remain release-gated.

`telemetry.py` validates one canonical before/during/after snapshot bundle
against both the load and observability topologies. It requires every direct
API/edge/reconciler/registry target, recording rule and alert; restart and
stale-series transitions; bounded Galera, RGW, quota, reconciliation, HAProxy,
and six-host resource facts; and zero schema/leak/invariant errors. Its
owner-only CLI emits only hashes, counts, and the exact `metrics-verified`
phase payload. Until a typed live collector exists it accepts only explicit
`source=fixture`, `synthetic=true` evidence, so this local proof cannot be
mistaken for production telemetry.

`plan.py` compiles one exact, synthetic execution envelope from the checked-in
topology and qualified release/image/configuration/client/driver hashes. The
plan fixes all six client capability requirements, twelve operations, nine
content classes, three profiles, seven ramp levels, ten serial faults,
transfer ceilings, and three telemetry windows. Its matrix marks every
executor and verified-TLS behavior as required rather than claiming those
runtime adapters have executed. The owner-only CLI emits a deterministic,
canonical mode-0600 envelope and cannot start a subprocess or network client.

`orchestrator.py` replays that compiled scope through one exact 29-step order:
six client qualifications, smoke, seven ramp levels, qualification, ten
serial faults, soak, and three telemetry windows. The fixture executor
checkpoints canonical owner-only state after every step under a nonblocking
lock, enforces per-step and cumulative budgets, resumes from the last complete
entry, and produces only a synthetic terminal hash summary. Failed steps do
not advance state, stale outputs and tampered history fail closed, and
lookalike or live executors are rejected by exact type.

`profile/run.py` is the owner-only runtime contract for smoke, ramp,
qualification, and soak steps. It binds the exact compiled step plus one
source- and binary-hashed child template for every operation, executes
steady/burst or fixed-ramp waves for the full duration, and advances an
atomically replayable hash-chain checkpoint only after every child result and
transfer bound pass. Child process groups, stdout/stderr, temporary invocation
copies, interruption, and resume are bounded. Control quota contention is
limited to one child per wave to avoid fixed-tag races. Local executable
fixtures remain explicitly synthetic; both-architecture pilot execution is
still required.

`fault/run.py` is the serial owner-only runtime contract for all ten fault
windows. It binds a compiled fault step, hashed action binary/source, bounded
non-secret adapter selectors, and owner-only target/state/lock/output paths.
Each fault executes preflight, inject, the full observation window, recover,
and verify under one lock. An ambiguous inject, interruption, lost process,
action failure, or recovery deadline can only end in retryable recovery state
or `failed-recovered`; it can never produce success evidence. Local action
fixtures remain explicitly synthetic.

`collector/run.py` is the owner-only three-window telemetry executor. It binds
the compiled before/during/after steps to checked source, CA, target and shared
state, fetches seven explicit verified-TLS normalized surfaces for Prometheus
and the native-exporter domains, caps transport and JSON shape, and checkpoints
semantic snapshots in a replay-validated hash chain. Every step emits a
redacted collection result; the final step also emits the canonical telemetry
bundle for independent verification. Local TLS fakes qualify only this
transport and state boundary, not a pilot adapter or native exporter
deployment.

`collector/native_surfaces.py` adds the bounded raw-source parser seam for the
Prometheus v1 API, HAProxy, mysqld-exporter/Galera, Ceph mgr/ceph-exporter/RGW
ingress, and node-exporter. It produces the existing seven internal payload
shapes while keeping quota/reconciliation/KMS/multipart/workload error fields
as explicit auxiliary evidence instead of inventing native metrics. The v1
collector remains byte-compatible. A separately versioned native target binds
the exact source URLs, PromQL, and allowlists, and `collector/run.py` selects
the normalized or native path only by exact schema without fallback. Local
three-window TLS evidence qualifies dispatch and state handling, not the
uncreated pilot endpoints or their runtime data.

`collector/render_target.py` converts one canonical owner-only disposable
pilot inventory and its explicit credential-free HTTPS origins into that
native target without contacting a service. It binds the checked renderer,
parser, and target sources together with the fixed load and observability
topologies, fixes every query and evidence route, validates the resulting
target through the runtime parser, and atomically emits mode-0600 JSON.
This qualifies deterministic target construction only; it does not assert
that any declared source exists or is healthy.

`collector/phase_evidence.py` compiles the six auxiliary sources that have no
equivalent native metric. Each phase binds fixed summary classes, an exact
window hash, the native target file/hash, the current compiler sources, and
only bounded numeric or boolean payload fields. It emits one canonical
owner-only bundle containing the exact native evidence documents and their
independent hashes. It deliberately preserves bounded failure evidence for the
independent verifier; compilation is not a pass decision.

`collector/evidence_server.py` is the private TLS serving boundary for one
compiled phase bundle. It binds the exact target and bundle bytes, source
contract, private IPv4 listener, TLS name/certificate/key, bounded concurrency
and request timeout, and only the six target-declared evidence routes. It
serves no discovery, index, redirect, health, raw input, or cross-phase path.

`collector/source_summaries.py` removes hand-authored summary requests. It
validates six dedicated collector artifacts, binds each canonical artifact
file and collector source hash into the v2 summary, and atomically emits the
exact request consumed by `phase_evidence.py`. Observation counts and artifact
metadata remain in their owner-only source files; only bounded aggregates and
their provenance hashes advance.

`collector/local_artifacts.py` implements the first two dedicated source
collectors without network access. It scans only explicit owner-only files
against fixed credential patterns and supplied one-way fingerprints, and
sums only the explicit error field from canonical nonsynthetic pilot
profile/fault results sharing one plan. The v2 artifact binds the exact input
file set while retaining no raw value or path. This does not produce or imply
Galera, RGW, quota, or reconciliation evidence.

`collector/control_artifacts.py` implements the quota/reconciliation source
boundary. It takes owner-only baseline/current captures around one phase,
reads the identity-free SQL invariant snapshot through the product store,
queries six fixed verified-TLS Prometheus expressions derived from the bound
native target, and emits the exact two v2 artifacts accepted by
`source_summaries.py`. Final artifacts contain only bounded aggregates and
hashes. Local fake-adapter tests do not qualify a pilot SQL or Prometheus
runtime.

`runtime_manifest.py` maps every schedule entry and operation to the current
runtime capability baseline. It binds a canonical owner-only compiled plan,
qualified readiness file, exact client pins, checked-in runner source hashes,
target class, per-step input/output schemas, timeout, cleanup owner, verified
TLS, and owner-only requirements. Current client/raw paths are only
`contract-only`; profile, fault, telemetry, standalone control, token, and
quota-contention operations are also `contract-only`. No executable has
qualified binary evidence, so every executable SHA remains null and the
manifest always reports `ready=false` with explicit gaps.

`control/` adds the verified-TLS protocol core for finite Keystone
application-credential token acquisition, Coffer repository control probing,
standalone registry-token acquisition, and concurrent 201/429 quota admission
with independent cleanup of every owner-created manifest digest. It retains
only fixed aggregates. Its owner-only executable now binds the running binary,
checked-source provenance, qualified release evidence, explicit CA and
credential, distinct SHA-bound manifests, exact quota outcomes, target class,
timeouts, concurrency, and canonical output before any request. Local TLS
proves the boundary; real execution on both architectures remains
`contract-only` until the disposable pilot qualifies it.

Live execution remains gated on a fresh disposable Stage 6 pilot and qualified
stable dependencies.
