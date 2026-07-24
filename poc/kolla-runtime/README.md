# Local Kolla runtime contract verification

This disposable ARM64/x86-64 harness verifies Stage 2 without creating a VM or
Kolla-Ansible role. It uses the existing local Podman machine and stops it only
when the harness started it. It never initializes, recreates, or resets a
machine.

The harness builds:

- a pinned Python/Debian contract base containing SHA-256-verified
  `kolla_start`, `kolla_set_configs`, CA-copy, development-project,
  `healthcheck_listen`, and sudo policy files from Kolla commit
  `686c6d13dc1c31092b22c6c481e16a7329e935ea`;
- the current Coffer source with all four installed product commands, final
  user `coffer` (UID/GID 53002);
- official unmodified Distribution v3.1.1 release binary in a final
  `registry` user image (UID/GID 53003), with an architecture-specific
  published checksum.

`make verify` then proves read-only Kolla source configuration, copied
owner/modes, CA injection, backend TLS and hostname validation, container
health, repeat bootstrap, empty reconciliation, sole ingress, non-root
processes, an authenticated OCI blob/manifest publication through quota
admission, digest persistence over all three service restarts, stdout log
hygiene, SBOM/CVE generation, and exact runtime/image cleanup.

The generated private keys, JWT, upload state, HTTP secret, SQLite database,
and OCI payloads stay under an ignored owner-only temporary directory and are
removed on every exit. Non-secret image metadata, SPDX SBOMs, and Docker Scout
SARIF/text reports are retained under `work/kolla-runtime/evidence/`.

Run from a persistent terminal:

```console
make -C poc/kolla-runtime verify
```

This contract image is intentionally distinct from a successful build on an
official Kolla 2026.1 base. The final Jinja templates are rendered separately;
official-base image build evidence remains a Stage 3/AIO concern unless a
trusted base reference is made available.
