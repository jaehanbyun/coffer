# UI image production qualification

This harness closes the gap between Coffer's tested Horizon/Skyline packages
and actual immutable container images. It is deliberately separate from the
Kolla role fixture and from the Stage 6 live pilot.

The accepted transaction builds stock `horizon` and `skyline-console` parents
from Kolla `stable/2026.1` at the pinned commit and Ubuntu Noble platform
digest. It never treats `quay.io/openstack.kolla` test images as production
parents. The exact Coffer wheels are then installed with the Containerfiles in
`ui/images/`.

Four images are inspected and scanned in one bounded transaction:

```text
horizon-parent  ── exact layer prefix ──> horizon-custom
skyline-parent  ── exact layer prefix ──> skyline-custom
```

`qualification.py` validates:

- exact Kolla, Horizon, and Skyline source revisions;
- actual Horizon/Skyline wheel names, versions, and SHA-256 values;
- Linux native architecture and immutable image configuration digests;
- preserved Kolla user, entrypoint, command, and parent layer prefix;
- required Coffer OCI labels;
- installed package versions and runtime files matching wheel members;
- absence of wheel/installer build inputs from the final filesystem;
- non-empty SPDX inventories;
- Trivy vulnerability and secret results;
- Docker Scout SARIF vulnerability results;
- identical inherited finding sets plus an explicit custom-image delta.

The result is `qualified` only when both parent and custom images have zero
Critical/High findings under both scanners, no secrets, no introduced finding,
and every provenance/runtime contract passes. A custom image introducing
nothing does not hide an unresolved parent finding: the whole surface remains
blocked.

The verifier is fixture-testable without a container engine:

```console
uv run pytest -q tests/test_ui_image_qualification.py
```

The engine transaction is added only after the pure evidence contract passes.
It may retain non-secret ignored evidence under `work/ui-image-qualification/`
but must remove exact containers, images, and temporary mounts on every exit.
It does not sign, publish, push, deploy, or create a credential.
