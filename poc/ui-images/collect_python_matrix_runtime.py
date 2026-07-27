from __future__ import annotations

import argparse
import json
import platform
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

from collect_python_runtime import (
    RuntimeCollectionError,
    component_files,
    normalized_name,
    pip_check,
)
from python_matrix import (
    MatrixError,
    MatrixSurface,
    load_matrix,
    probe_surface,
)
from python_target import TargetError

SCHEMA = "coffer.ui-python-matrix-runtime/v1"
PROBE_MODES = frozenset({"baseline", "candidate"})


def package_versions(surface: MatrixSurface) -> dict[str, list[str]]:
    packages: dict[str, list[str]] = {}
    for distribution in metadata.distributions():
        name = normalized_name(str(distribution.metadata.get("Name", "")))
        version = str(distribution.version)
        if not name or not version:
            raise RuntimeCollectionError("Python package inventory is invalid")
        packages.setdefault(name, []).append(version)
    if any(
        component.normalized_name not in packages for component in surface.components
    ):
        raise RuntimeCollectionError("matrix Python package is absent")
    return {name: sorted(versions) for name, versions in sorted(packages.items())}


def collect(
    surface: MatrixSurface,
    *,
    probe_mode: str,
) -> dict[str, Any]:
    if probe_mode not in PROBE_MODES:
        raise RuntimeCollectionError("matrix probe mode is invalid")
    input_paths = (
        "/tmp/target-wheels",
        "/tmp/python_matrix.py",
        "/tmp/python_matrices.json",
        "/tmp/python_target.py",
        "/tmp/python_targets.json",
    )
    probe_results = probe_surface(
        surface,
        enforce_security=probe_mode == "candidate",
    )
    check = pip_check()
    if check["clean"] is not True:
        raise RuntimeCollectionError("matrix Python compatibility check failed")
    architecture = platform.machine().lower()
    architecture = {
        "aarch64": "arm64",
        "x86_64": "amd64",
    }.get(architecture, architecture)
    if architecture not in {"arm64", "amd64"}:
        raise RuntimeCollectionError("runtime architecture is unsupported")
    return {
        "schema": SCHEMA,
        "architecture": architecture,
        "surface": surface.name,
        "packages": package_versions(surface),
        "components": [
            {
                "name": component.normalized_name,
                "version": metadata.version(component.display_name),
                "files": component_files(component),
            }
            for component in surface.components
        ],
        "probes": [
            {
                "target": target,
                "name": probe,
                "mode": probe_mode,
                "result": result,
            }
            for target, probe, result in probe_results
        ],
        "pip_check": check,
        "absent": [
            value
            for value in input_paths
            for path in (Path(value),)
            if not path.exists() and not path.is_symlink()
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--surface", required=True)
    parser.add_argument(
        "--probe-mode",
        choices=sorted(PROBE_MODES),
        required=True,
    )
    arguments = parser.parse_args()
    try:
        matrix = load_matrix(
            arguments.manifest,
            arguments.target_manifest,
            arguments.matrix,
        )
        surface = matrix.for_surface(arguments.surface)
        result = collect(surface, probe_mode=arguments.probe_mode)
        expected_absent = [
            "/tmp/target-wheels",
            "/tmp/python_matrix.py",
            "/tmp/python_matrices.json",
            "/tmp/python_target.py",
            "/tmp/python_targets.json",
        ]
        if result["absent"] != expected_absent:
            raise RuntimeCollectionError("matrix build input remains in the image")
    except RuntimeCollectionError as error:
        print(f"coffer-ui-python-matrix-runtime: {error}")
        return 2
    except metadata.PackageNotFoundError:
        print("coffer-ui-python-matrix-runtime: matrix package is absent")
        return 2
    except subprocess.TimeoutExpired:
        print("coffer-ui-python-matrix-runtime: compatibility check timed out")
        return 2
    except (MatrixError, TargetError, ImportError):
        print("coffer-ui-python-matrix-runtime: manifest is invalid")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
