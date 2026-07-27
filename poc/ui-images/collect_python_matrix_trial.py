from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from collect_python_trial import (
    DIGEST,
    KINDS,
    REVISION,
    SURFACES,
    CollectionError,
    atomic_json,
    component_projection,
    container_json,
    inspect_image,
    sha256_file,
)
from python_matrix import Matrix, MatrixError, load_matrix
from python_target import TargetError

MANIFEST_SCHEMA = "coffer.ui-python-matrix-evidence/v1"
IMAGE_SCHEMA = "coffer.ui-python-overlay-images/v1"
INVENTORY_SCHEMA = "coffer.ui-python-overlay-os-inventories/v1"
RUNTIME_SCHEMA = "coffer.ui-python-matrix-runtimes/v1"


def wheel_map(
    paths: tuple[Path, ...],
    matrix: Matrix,
) -> dict[str, Path]:
    expected = tuple(component.wheel_filename for component in matrix.components)
    actual = tuple(path.name for path in paths)
    if (
        actual != expected
        or len(set(actual)) != len(actual)
        or len(paths) != len(matrix.components)
    ):
        raise CollectionError("Python matrix wheel set is invalid")
    result = dict(zip(expected, paths, strict=True))
    if any(
        sha256_file(result[component.wheel_filename]) != component.wheel_sha256
        for component in matrix.components
    ):
        raise CollectionError("Python matrix wheel identity is invalid")
    return result


def surface_projection(matrix: Matrix, surface: str) -> dict[str, Any]:
    selected = matrix.for_surface(surface)
    return {
        "target_keys": list(selected.target_keys),
        "probes": [
            {"target": target.key, "name": target.probe} for target in selected.targets
        ],
        "finding_ids_by_scanner": selected.scanner_finding_ids,
        "components": [
            component_projection(component) for component in selected.components
        ],
    }


def collect(
    *,
    evidence: Path,
    images: dict[str, str],
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheels: tuple[Path, ...],
    target_manifest: Path,
    matrix_manifest: Path,
    matrix_key: str,
    baseline_result: Path,
    baseline_inventories: Path,
    remediation_result: Path,
    ubuntu_sha256: str,
    kolla_revision: str,
    horizon_revision: str,
    skyline_revision: str,
    docker_scout_version: str,
    trivy_version: str,
) -> None:
    try:
        matrix = load_matrix(
            matrix_manifest,
            target_manifest,
            matrix_key,
        )
    except (MatrixError, TargetError) as error:
        raise CollectionError("Python matrix is invalid") from error
    wheel_map(target_wheels, matrix)
    revisions = (kolla_revision, horizon_revision, skyline_revision)
    if not all(REVISION.fullmatch(value) for value in revisions):
        raise CollectionError("source revision is invalid")
    if not DIGEST.fullmatch(ubuntu_sha256):
        raise CollectionError("Ubuntu digest is invalid")
    if not docker_scout_version or not trivy_version:
        raise CollectionError("scanner version is empty")
    expected_keys = {f"{surface}-{kind}" for surface in SURFACES for kind in KINDS}
    if set(images) != expected_keys:
        raise CollectionError("matrix trial image set is invalid")
    inspections = {key: inspect_image(value) for key, value in images.items()}
    architectures = {item["architecture"] for item in inspections.values()}
    if architectures == {"arm64"}:
        architecture = "arm64"
    elif architectures == {"amd64"}:
        architecture = "amd64"
    else:
        raise CollectionError("matrix trial architectures are inconsistent")

    package_collector = Path(__file__).with_name("package_probe.py")
    python_collector = Path(__file__).with_name("collect_python_matrix_runtime.py")
    common_runtime = Path(__file__).with_name("collect_python_runtime.py")
    matrix_module = Path(__file__).with_name("python_matrix.py")
    target_module = Path(__file__).with_name("python_target.py")
    ui_collector = Path(__file__).with_name("collect_runtime.py")
    inventories = {
        key: container_json(
            image=images[key],
            collector=package_collector,
            arguments=["--inventory-only"],
            interpreter="python3",
        )
        for key in sorted(images)
    }
    python_runtimes = {
        key: container_json(
            image=images[key],
            collector=python_collector,
            arguments=[
                "--manifest",
                "/opt/python_matrices.json",
                "--target-manifest",
                "/opt/python_targets.json",
                "--matrix",
                matrix.key,
                "--surface",
                key.split("-", 1)[0],
                "--probe-mode",
                "baseline" if key.endswith("-before") else "candidate",
            ],
            interpreter="/var/lib/kolla/venv/bin/python",
            extra_mounts=(
                (common_runtime, "/opt/collect_python_runtime.py"),
                (matrix_module, "/opt/python_matrix.py"),
                (matrix_manifest, "/opt/python_matrices.json"),
                (target_module, "/opt/python_target.py"),
                (target_manifest, "/opt/python_targets.json"),
            ),
        )
        for key in sorted(images)
    }
    ui_runtimes = {
        surface: container_json(
            image=images[f"{surface}-after"],
            collector=ui_collector,
            arguments=[surface],
            interpreter="/var/lib/kolla/venv/bin/python",
        )
        for surface in SURFACES
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "architecture": architecture,
        "platform": f"linux/{architecture}",
        "sources": {
            "ubuntu_sha256": ubuntu_sha256,
            "kolla": kolla_revision,
            "horizon": horizon_revision,
            "skyline": skyline_revision,
        },
        "artifacts": {
            "horizon": {
                "name": "coffer-horizon",
                "version": "0.1.0",
                "sha256": sha256_file(horizon_wheel),
            },
            "skyline": {
                "name": "skyline-console",
                "version": "8.0.0+coffer.1",
                "sha256": sha256_file(skyline_wheel),
            },
            "matrix": {
                "key": matrix.key,
                "manifest_sha256": sha256_file(matrix_manifest),
                "target_manifest_sha256": sha256_file(target_manifest),
                "trial_label": matrix.trial_label,
                "surfaces": {
                    surface: surface_projection(matrix, surface) for surface in SURFACES
                },
                "wheels": [
                    component_projection(component) for component in matrix.components
                ],
            },
        },
        "baseline": {
            "os_cleanup_result_sha256": sha256_file(baseline_result),
            "os_cleanup_inventories_sha256": sha256_file(baseline_inventories),
            "remediation_result_sha256": sha256_file(remediation_result),
        },
        "images": {
            key: {"name": images[key], "id": inspections[key]["id"]}
            for key in sorted(images)
        },
        "scanners": {
            "docker_scout": docker_scout_version,
            "trivy": trivy_version,
        },
    }
    atomic_json(evidence / "manifest.json", manifest)
    atomic_json(
        evidence / "images.json",
        {"schema": IMAGE_SCHEMA, "images": inspections},
    )
    atomic_json(
        evidence / "os-inventories.json",
        {"schema": INVENTORY_SCHEMA, "images": inventories},
    )
    atomic_json(
        evidence / "runtimes.json",
        {
            "schema": RUNTIME_SCHEMA,
            "architecture": architecture,
            "python": python_runtimes,
            "ui": ui_runtimes,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--horizon-wheel", type=Path, required=True)
    parser.add_argument("--skyline-wheel", type=Path, required=True)
    parser.add_argument(
        "--target-wheel",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--matrix-manifest", type=Path, required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--baseline-result", type=Path, required=True)
    parser.add_argument("--baseline-inventories", type=Path, required=True)
    parser.add_argument("--remediation-result", type=Path, required=True)
    parser.add_argument("--ubuntu-sha256", required=True)
    parser.add_argument("--kolla-revision", required=True)
    parser.add_argument("--horizon-revision", required=True)
    parser.add_argument("--skyline-revision", required=True)
    parser.add_argument("--docker-scout-version", required=True)
    parser.add_argument("--trivy-version", required=True)
    for surface in SURFACES:
        for kind in KINDS:
            parser.add_argument(
                f"--{surface}-{kind}",
                required=True,
            )
    arguments = parser.parse_args()
    images = {
        f"{surface}-{kind}": getattr(arguments, f"{surface}_{kind}")
        for surface in SURFACES
        for kind in KINDS
    }
    try:
        collect(
            evidence=arguments.evidence,
            images=images,
            horizon_wheel=arguments.horizon_wheel,
            skyline_wheel=arguments.skyline_wheel,
            target_wheels=tuple(arguments.target_wheel),
            target_manifest=arguments.target_manifest,
            matrix_manifest=arguments.matrix_manifest,
            matrix_key=arguments.matrix,
            baseline_result=arguments.baseline_result,
            baseline_inventories=arguments.baseline_inventories,
            remediation_result=arguments.remediation_result,
            ubuntu_sha256=arguments.ubuntu_sha256,
            kolla_revision=arguments.kolla_revision,
            horizon_revision=arguments.horizon_revision,
            skyline_revision=arguments.skyline_revision,
            docker_scout_version=arguments.docker_scout_version,
            trivy_version=arguments.trivy_version,
        )
    except CollectionError as error:
        print(f"coffer-ui-python-matrix-collector: {error}")
        return 2
    except subprocess.TimeoutExpired:
        print("coffer-ui-python-matrix-collector: collection timed out")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
