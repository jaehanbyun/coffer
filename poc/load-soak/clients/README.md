# Stage 6 real-client adapter contract

This directory fixes the bounded compatibility boundary for Docker, Podman,
Skopeo, ORAS, and nerdctl/containerd. `pins.json` records exact versions,
source revisions, release URLs, supported architectures, and upstream commit
verification as checked on 2026-07-25. Skopeo v1.23.0 is intentionally marked
unverified because its release tag and commit do not carry a GitHub-verifiable
signature; this pin is compatibility input, not production provenance.

`contract.py` validates an exact in-memory invocation, binary SHA-256,
mode-0600 CA/credential/artifact inputs, a mode-0700 work root, a canonical
Coffer repository route, a private registry hostname, and the expected
manifest digest. It then builds fixed client-specific command sequences:

- every login reads only the password from standard input;
- no password, token, insecure-registry flag, proxy, ambient home, or ambient
  authentication state enters argv or environment;
- Podman and Skopeo require explicit auth files, certificate directories, and
  TLS verification;
- ORAS requires an explicit registry config and CA file, attaches to one exact
  subject digest, and records an explicit native-API or fallback-tag
  disposition while running matching discovery;
- nerdctl uses one namespace/data root, a clean Docker config, and an
  owner-only containerd `hosts.toml` with the exact CA; and
- Docker uses an isolated CLI config and requires a separate read-only daemon
  CA file with identical bytes under a `<registry>/ca.crt` path. The
  disposable client VM must additionally bind that checked path to
  `/etc/docker/certs.d/<registry>/ca.crt` before a live run because Docker
  registry trust is daemon-owned.

Each adapter performs exact version proof, login, its required push/copy/pull
shape, and one digest verification. Output is streamed into a one-MiB
per-stream bound and timeout or overflow terminates the isolated process
group. Cleanup and logout run after success or failure. The generated session
is removed, and the retained result contains only the client/version, binary
and pins hashes, fixed counts, and result.
Repository, registry, tag, source, credential, artifact, CA, and temporary
paths are never retained.

Current tests use executable local fakes only. They prove command shape,
credential transport, clean environment, version/digest parsing, failure
cleanup, input ownership, and zero generated residue. They do not prove a real
client binary, Docker daemon CA installation, containerd service, registry, or
network. Those remain release-gated disposable-pilot work.

## Owner-only runner

`run.py` accepts only:

```text
python run.py --invocation /absolute/owner-only/invocation.json
```

The mode-0600 `coffer.load-client-run/v1` document contains the in-memory
client invocation plus absolute `pins_file`, `readiness_file`, and
`output_file` paths and the exact raw SHA-256 of both evidence files. The
invocation, pins, and readiness inputs must be owner-matched, single-link,
mode-0600 regular files. The output parent must already be an owner-matched
mode-0700 directory; an existing output must be a mode-0600 regular file.
Every input, work root, and output path is distinct.

Execution is refused unless the upstream document is exactly
`candidate-qualified` for both a Distribution release newer than v3.1.1 and a
Ceph Tentacle v20.2 release newer than v20.2.2 containing the accepted
encrypted-copy fix. On success the runner fsyncs and atomically replaces one
canonical mode-0600 `coffer.load-client-execution/v1` result. It retains only
the readiness and pins hashes plus the already bounded adapter result.
Failures print one fixed category; interruption, timeout, overflow, client
failure, and output failure retain no command output or secret.
