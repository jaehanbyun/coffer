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
without retaining their identities on success or failure. Real-client
adapters remain next. Live execution is still gated on a fresh disposable
Stage 6 pilot and qualified stable dependencies.
