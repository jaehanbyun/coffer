from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

from python_target import (
    PackageComponent,
    Target,
    TargetError,
    load_target,
    probe_target,
)

SCHEMA = "coffer.ui-python-overlay-runtime/v3"
PROBE_MODES = frozenset({"baseline", "candidate"})
PACKAGE_NAME = re.compile(r"[-_.]+")


class RuntimeCollectionError(RuntimeError):
    pass


def normalized_name(value: str) -> str:
    return PACKAGE_NAME.sub("-", value).lower()


def file_sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RuntimeCollectionError("target package file is invalid")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_versions(target: Target) -> dict[str, list[str]]:
    packages: dict[str, list[str]] = {}
    for distribution in metadata.distributions():
        name = normalized_name(str(distribution.metadata.get("Name", "")))
        version = str(distribution.version)
        if not name or not version:
            raise RuntimeCollectionError("Python package inventory is invalid")
        packages.setdefault(name, []).append(version)
    if any(
        component.normalized_name not in packages
        for component in target.components
    ):
        raise RuntimeCollectionError("target Python package is absent")
    return {
        name: sorted(versions)
        for name, versions in sorted(packages.items())
    }


def component_files(component: PackageComponent) -> dict[str, str]:
    distribution = metadata.distribution(component.display_name)
    files = distribution.files
    if files is None:
        raise RuntimeCollectionError("target Python package has no RECORD")
    result: dict[str, str] = {}
    for member in files:
        relative = str(member)
        if not relative.startswith(component.package_prefix):
            continue
        path = Path(distribution.locate_file(member))
        if not path.is_file() or path.is_symlink():
            raise RuntimeCollectionError("target Python package file is missing")
        result[relative] = file_sha256(path)
    if not result:
        raise RuntimeCollectionError("target Python package files are empty")
    return dict(sorted(result.items()))


def pip_check() -> dict[str, Any]:
    process = subprocess.run(
        ["/var/lib/kolla/venv/bin/python", "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    clean = (
        process.returncode == 0
        and not process.stderr
        and process.stdout.strip() == "No broken requirements found."
    )
    return {"clean": clean, "message": process.stdout.strip() if clean else ""}


def collect(target: Target, *, probe_mode: str) -> dict[str, Any]:
    if probe_mode not in PROBE_MODES:
        raise RuntimeCollectionError("target probe mode is invalid")
    target_input_paths = (
        "/tmp/target-wheels",
        "/tmp/python_target.py",
        "/tmp/python_targets.json",
    )
    probe_result = probe_target(
        target,
        enforce_security=probe_mode == "candidate",
    )
    check = pip_check()
    if check["clean"] is not True:
        raise RuntimeCollectionError("target Python compatibility check failed")
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
        "packages": package_versions(target),
        "components": [
            {
                "name": component.normalized_name,
                "version": metadata.version(component.display_name),
                "files": component_files(component),
            }
            for component in target.components
        ],
        "probe": {
            "name": target.probe,
            "mode": probe_mode,
            "result": probe_result,
        },
        "pip_check": check,
        "absent": [
            value
            for value in target_input_paths
            for path in (Path(value),)
            if not path.exists() and not path.is_symlink()
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--probe-mode",
        choices=sorted(PROBE_MODES),
        required=True,
    )
    arguments = parser.parse_args()
    try:
        target = load_target(arguments.manifest, arguments.target)
        result = collect(target, probe_mode=arguments.probe_mode)
        expected_absent = [
            "/tmp/target-wheels",
            "/tmp/python_target.py",
            "/tmp/python_targets.json",
        ]
        if result["absent"] != expected_absent:
            raise RuntimeCollectionError("target build input remains in the image")
    except RuntimeCollectionError as error:
        print(f"coffer-ui-python-overlay-runtime: {error}")
        return 2
    except metadata.PackageNotFoundError:
        print("coffer-ui-python-overlay-runtime: target package is absent")
        return 2
    except subprocess.TimeoutExpired:
        print("coffer-ui-python-overlay-runtime: compatibility check timed out")
        return 2
    except (TargetError, ImportError):
        print("coffer-ui-python-overlay-runtime: target manifest is invalid")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
