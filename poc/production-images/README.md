# Production image remediation harness

This harness turns the Stage 4 functional images into a fail-closed
production-candidate qualification. It renders the repository's Kolla
templates against the exact Kolla 2026.1 commit, uses the supported Ubuntu
Noble platform manifest pinned in `pins.env`, verifies the signed
Distribution v3.1.1 release tar and SLSA provenance subject, pins the
release inputs, and uses Kolla's Podman builder to assemble the shared base
and two product images without using Kolla test images.

It then reuses the full Stage 2 runtime contract against the candidate images,
generates Docker Scout, Trivy vulnerability and secret, and SPDX evidence,
validates the non-root architecture/provenance labels, and runs
`govulncheck` v1.6.0 in source and release-binary modes.
`verify_evidence.py` writes
`work/production-image-remediation/evidence/qualification.json`.

The Coffer image creates a dedicated venv directly on Kolla `base`, installs
only Coffer's locked runtime dependencies under
`requirements/production-constraints.txt`, and runs `pip check`. The harness
regenerates that constraint set from `uv.lock` and rejects drift before
building. The image does not inherit the broad `openstack-base` package and
build-tool inventory that Coffer does not use. Both final images remove the
Kolla base's runtime-unneeded system `pip`, `setuptools`, and `wheel`; Coffer
additionally removes the temporary system venv packages after its root-owned
application venv passes `pip check`.

The 2026-07-24 ARM64 result is a deterministic production block, not a clean
promotion. The Coffer image has zero Critical/High findings under both scanners
and zero Trivy secret findings. The registry wrapper has 8 Critical/10 High
under Docker Scout and 0 Critical/22 High under Trivy; `govulncheck` reports
three source-reachable vulnerabilities and 37 vulnerable symbol groups in the
signed Distribution release binary. Distribution v3.1.1 is still the latest
signed stable release, so those residual Go/module findings cannot be
remediated by changing the wrapper base. The harness succeeds only when the
qualification process itself completes and confirms that the gate is blocked;
it never converts that expected block into a production approval.

On macOS, keep the retained Podman machine attached to a persistent PTY, then
run:

```text
make -C poc/production-images qualify
```

Candidate containers, networks, volumes, and images are removed. Ignored
evidence, rendered contexts, verified upstream inputs, and scan databases
remain under `work/production-image-remediation/` for review. Set
`COFFER_PRODUCTION_KEEP_IMAGES=true` only for bounded diagnosis and remove the
exact `localhost/coffer-production-*` images afterward.

Both x86_64 and aarch64 release checksums and Ubuntu platform manifests are
pinned. The harness builds and runs only the Podman machine's native
architecture; the retained result above is ARM64 and must not be presented as
x86_64 execution evidence.

This harness does not publish images or evidence, recreate the Stage 4 AIO,
modify external infrastructure, accept an unreleased Distribution branch, or
carry a private dependency fork.
