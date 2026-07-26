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

from python_target import Target, TargetError, load_target, probe_target

SCHEMA = "coffer.ui-python-overlay-runtime/v1"
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
    if target.normalized_name not in packages:
        raise RuntimeCollectionError("target Python package is absent")
    return {
        name: sorted(versions)
        for name, versions in sorted(packages.items())
    }


def target_files(target: Target) -> dict[str, str]:
    distribution = metadata.distribution(target.display_name)
    files = distribution.files
    if files is None:
        raise RuntimeCollectionError("target Python package has no RECORD")
    result: dict[str, str] = {}
    for member in files:
        relative = str(member)
        if not relative.startswith(target.package_prefix):
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


def collect(target: Target) -> dict[str, Any]:
    target_input_paths = (
        f"/tmp/{target.wheel_filename}",
        "/tmp/python_target.py",
        "/tmp/python_targets.json",
    )
    probe_result = probe_target(target)
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
        "target": {
            "name": target.normalized_name,
            "version": metadata.version(target.display_name),
            "files": target_files(target),
            "probe": target.probe,
            "probe_result": probe_result,
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
    arguments = parser.parse_args()
    try:
        target = load_target(arguments.manifest, arguments.target)
        result = collect(target)
        expected_absent = [
            f"/tmp/{target.wheel_filename}",
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
