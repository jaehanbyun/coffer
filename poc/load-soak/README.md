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
The next layer is a fixture-only lifecycle and canonical evidence verifier,
followed by the raw OCI driver and real-client adapters. Live execution remains
gated on a fresh disposable Stage 6 pilot and qualified stable dependencies.
