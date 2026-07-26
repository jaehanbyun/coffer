from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = load(
    "coffer_ui_image_runtime_collector",
    ROOT / "poc" / "ui-images" / "collect_runtime.py",
)
EVIDENCE = load(
    "coffer_ui_image_evidence_collector",
    ROOT / "poc" / "ui-images" / "collect_evidence.py",
)


def write(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_horizon_runtime_maps_exact_destination_files(tmp_path: Path) -> None:
    horizon = tmp_path / "openstack_dashboard"
    config = tmp_path / "config"
    expected = {}
    for member, destination in RUNTIME.HORIZON_MEMBERS.items():
        expected[member] = write(horizon / destination, member.encode())
    expected[RUNTIME.HORIZON_POLICY_MEMBER] = write(
        config / "coffer_policy.yaml", b"policy"
    )

    result = RUNTIME.collect_horizon(
        horizon_root=horizon,
        config_root=config,
        package_version="0.1.0",
    )

    assert result == {
        "package": {"name": "coffer-horizon", "version": "0.1.0"},
        "files": expected,
        "absent": list(RUNTIME.HORIZON_ABSENT),
    }


def test_skyline_runtime_requires_one_regular_bundle(tmp_path: Path) -> None:
    package = tmp_path / "site-packages" / "skyline_console"
    bundle = package / "static" / "coffer.bundle.123.js"
    expected_hash = write(bundle, b"bundle")

    result = RUNTIME.collect_skyline(
        package_root=package,
        package_version="8.0.0+coffer.1",
    )

    assert result["files"] == {
        "skyline_console/static/coffer.bundle.123.js": expected_hash
    }
    write(package / "static" / "coffer.bundle.456.js", b"other")
    with pytest.raises(RUNTIME.RuntimeCollectionError, match="one Coffer"):
        RUNTIME.collect_skyline(
            package_root=package,
            package_version="8.0.0+coffer.1",
        )


def test_runtime_refuses_link_or_retained_build_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.write_text("content")
    linked = tmp_path / "linked"
    linked.symlink_to(target)
    with pytest.raises(RUNTIME.RuntimeCollectionError, match="invalid runtime"):
        RUNTIME.file_sha256(linked)

    retained = tmp_path / "coffer.whl"
    retained.write_text("wheel")
    monkeypatch.setattr(RUNTIME, "HORIZON_ABSENT", (str(retained),))
    with pytest.raises(RUNTIME.RuntimeCollectionError, match="build input"):
        RUNTIME.prove_absent(RUNTIME.HORIZON_ABSENT)


def test_image_projection_preserves_runtime_and_layer_contract() -> None:
    layers = ["sha256:" + "1" * 64, "sha256:" + "2" * 64]
    result = EVIDENCE.image_projection(
        {
            "Id": "sha256:" + "a" * 64,
            "Architecture": "arm64",
            "Os": "linux",
            "Config": {
                "User": "root",
                "Entrypoint": ["/usr/local/bin/kolla_start"],
                "Cmd": [],
                "Labels": {"name": "horizon"},
            },
            "RootFS": {"Layers": layers},
        }
    )

    assert result["id"] == "sha256:" + "a" * 64
    assert result["architecture"] == "arm64"
    assert result["layers"] == layers
    assert result["entrypoint"] == ["/usr/local/bin/kolla_start"]


def test_image_projection_normalizes_podman_native_image_id() -> None:
    result = EVIDENCE.image_projection(
        {
            "Id": "a" * 64,
            "Architecture": "arm64",
            "Os": "linux",
            "Config": {},
            "RootFS": {"Layers": ["sha256:" + "1" * 64]},
        }
    )

    assert result["id"] == "sha256:" + "a" * 64


@pytest.mark.parametrize(
    "document",
    [
        {"Id": "mutable", "RootFS": {"Layers": ["layer"]}},
        {"Id": "sha256:" + "a" * 64, "RootFS": {"Layers": []}},
    ],
)
def test_image_projection_rejects_weak_identity(document: dict[str, object]) -> None:
    with pytest.raises(EVIDENCE.CollectionError):
        EVIDENCE.image_projection(document)


def test_atomic_evidence_refuses_existing_output(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    EVIDENCE.atomic_json(path, {"schema": "fixture"})
    assert json.loads(path.read_text()) == {"schema": "fixture"}
    assert path.stat().st_mode & 0o777 == 0o640
    with pytest.raises(EVIDENCE.CollectionError, match="refusing existing"):
        EVIDENCE.atomic_json(path, {"schema": "fixture"})


@pytest.mark.parametrize(
    ("containerfile", "wheel_name"),
    [
        (
            "horizon.Containerfile",
            "coffer_horizon-0.1.0-py3-none-any.whl",
        ),
        (
            "skyline-console.Containerfile",
            "skyline_console-8.0.0+coffer.1-py3-none-any.whl",
        ),
    ],
)
def test_containerfiles_preserve_valid_wheel_filenames(
    containerfile: str,
    wheel_name: str,
) -> None:
    content = (ROOT / "ui" / "images" / containerfile).read_text()
    runtime_path = f"/tmp/{wheel_name}"
    assert f"COPY {wheel_name} {runtime_path}" in content
    assert runtime_path in content
    assert f"rm -f {runtime_path}" in content or (
        "rm -f \\\n" in content and runtime_path in content
    )
    assert not any(
        line.startswith("USER ") for line in content.splitlines()
    ), "custom images must inherit the exact Kolla runtime user"


def test_harness_separates_trivy_db_acquisition_from_offline_scan() -> None:
    content = (ROOT / "poc" / "ui-images" / "qualify.sh").read_text()

    assert "image --download-db-only" in content
    assert "image --download-java-db-only" in content
    assert "--tmpfs /root/.cache/trivy:rw,noexec,nosuid,nodev" in content
    assert '--volume "${TRIVY_CACHE}/db:/root/.cache/trivy/db:ro"' in content
    assert (
        '--volume "${TRIVY_CACHE}/java-db:/root/.cache/trivy/java-db:ro"' in content
    )
    assert "--skip-db-update" in content
    assert "--skip-java-db-update" in content
    assert "--offline-scan" in content
