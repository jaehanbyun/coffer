from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

SCHEMA = "coffer.ui-python-overlay-runtime/v1"
TARGET_NAME = "mako"
TARGET_WHEEL_PATH = "/tmp/mako-1.3.12-py3-none-any.whl"
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


def package_versions() -> dict[str, list[str]]:
    packages: dict[str, list[str]] = {}
    for distribution in metadata.distributions():
        name = normalized_name(str(distribution.metadata.get("Name", "")))
        version = str(distribution.version)
        if not name or not version:
            raise RuntimeCollectionError("Python package inventory is invalid")
        packages.setdefault(name, []).append(version)
    if TARGET_NAME not in packages:
        raise RuntimeCollectionError("target Python package is absent")
    return {
        name: sorted(versions)
        for name, versions in sorted(packages.items())
    }


def target_files() -> dict[str, str]:
    distribution = metadata.distribution("Mako")
    files = distribution.files
    if files is None:
        raise RuntimeCollectionError("target Python package has no RECORD")
    result: dict[str, str] = {}
    for member in files:
        relative = str(member)
        if not relative.startswith("mako/"):
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


def collect() -> dict[str, Any]:
    from mako.template import Template

    rendered = Template("${value}").render(value="coffer")
    check = pip_check()
    if rendered != "coffer" or check["clean"] is not True:
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
        "packages": package_versions(),
        "target": {
            "name": TARGET_NAME,
            "version": metadata.version("Mako"),
            "files": target_files(),
            "rendered": rendered,
        },
        "pip_check": check,
        "absent": [
            TARGET_WHEEL_PATH
            for path in (Path(TARGET_WHEEL_PATH),)
            if not path.exists() and not path.is_symlink()
        ],
    }


def main() -> int:
    try:
        result = collect()
        if result["absent"] != [TARGET_WHEEL_PATH]:
            raise RuntimeCollectionError("target wheel remains in the image")
    except RuntimeCollectionError as error:
        print(f"coffer-ui-python-overlay-runtime: {error}")
        return 2
    except metadata.PackageNotFoundError:
        print("coffer-ui-python-overlay-runtime: target package is absent")
        return 2
    except subprocess.TimeoutExpired:
        print("coffer-ui-python-overlay-runtime: compatibility check timed out")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
