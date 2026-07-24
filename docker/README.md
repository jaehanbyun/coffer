# Kolla image contract

This directory contains the Stage 2 image boundary, not a Kolla-Ansible role.
Use it with OpenStack Kolla `stable/2026.1`.

- `coffer/Dockerfile.j2` installs the reviewed Coffer source archive and all
  database drivers into one image. Kolla selects exactly one of `coffer-api`,
  `coffer-edge`, `coffer-reconcile`, or `coffer-bootstrap` through
  `config.json`.
- `coffer-registry/Dockerfile.j2` keeps Distribution code unmodified. It
  downloads the official v3.1.1 release binary for `x86_64` or `aarch64` and
  verifies the architecture-specific SHA-256 before installation.
- `config/*.json.j2` defines the read-only Kolla copy, owner, mode, CA, data,
  and command contract for each process.
- `kolla-build.conf.sample` reserves non-conflicting external user IDs. Replace
  the source reference with an immutable reviewed commit before building.

The Coffer image ends as UID/GID 53002 and the registry image as UID/GID
53003. `kolla_start` elevates only the standard configuration, CA-copy, and
development-project helpers; the selected service command runs as the final
image user. No password, private key, access key, database URL, or token is
baked into either image.

The Distribution official runtime image remains blocked by its recorded scan.
The release-binary wrapper changes the surrounding OS/package set but does not,
by itself, close the Distribution code, conformance, Ceph SSE-KMS, or
production promotion gates.
