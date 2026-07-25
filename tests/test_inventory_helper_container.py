from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTAINERFILE = ROOT / "poc" / "inventory" / "Containerfile"


def test_inventory_helper_image_is_pinned_static_and_nonroot() -> None:
    content = CONTAINERFILE.read_text(encoding="utf-8")

    assert (
        "docker.io/library/golang:1.25.3@sha256:"
        "6d4e5e74f47db00f7f24da5f53c1b4198ae46862a47395e30477365458347bf2"
        in content
    )
    assert "CGO_ENABLED=0" in content
    assert "-buildvcs=false" in content
    assert "-trimpath" in content
    assert "FROM scratch" in content
    assert "ca-certificates.crt" in content
    assert "USER 65532:65532" in content
    assert (
        'ENTRYPOINT ["/usr/local/bin/coffer-inventory-helper"]'
        in content
    )


def test_inventory_helper_image_has_no_registry_server_or_shell_entrypoint() -> None:
    content = CONTAINERFILE.read_text(encoding="utf-8")
    final_stage = content.split("FROM scratch", maxsplit=1)[1]

    assert "COPY --from=build" in final_stage
    assert "/usr/local/bin/registry" not in final_stage
    assert 'ENTRYPOINT ["/bin/sh"' not in final_stage
    assert "CMD " not in final_stage
    assert "EXPOSE " not in final_stage
