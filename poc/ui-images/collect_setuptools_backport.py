from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from collect_python_trial import (
    DIGEST,
    CollectionError,
    atomic_json,
    container_json,
    inspect_image,
)

SCHEMA = "coffer.ui-setuptools-backport-evidence/v1"
RUNTIME_SCHEMA = "coffer.ui-setuptools-backport-runtime/v1"
SURFACES = ("horizon", "skyline")


def validate_runtime(document: dict[str, Any], architecture: str) -> None:
    if (
        document.get("schema") != RUNTIME_SCHEMA
        or document.get("architecture") != architecture
        or document.get("decision")
        != {
            "backported_behaviors_verified": True,
            "findings": {
                "CVE-2024-6345": "not_affected",
                "CVE-2025-47273": "not_affected",
            },
            "vex_generation_allowed": True,
        }
    ):
        raise CollectionError("setuptools backport runtime decision is invalid")
    package = document.get("package")
    if not isinstance(package, dict) or package != {
        "dpkg_name": "python3-setuptools",
        "dpkg_version": "68.1.2-2ubuntu1.2",
        "metadata_name": "setuptools",
        "metadata_version": "68.1.2",
        "module_path": ("/usr/lib/python3/dist-packages/setuptools/package_index.py"),
        "python": "/usr/bin/python3",
    }:
        raise CollectionError("setuptools backport package identity is invalid")
    if document.get("path_containment") != {
        "benign_relative_path": "setuptools-78.1.0.tar.gz",
        "encoded_absolute_path_rejected": True,
    }:
        raise CollectionError("setuptools path containment proof is invalid")
    vcs = document.get("vcs")
    if (
        not isinstance(vcs, dict)
        or vcs.get("source")
        != {
            "check_call_sites": 2,
            "os_system_sites": 0,
            "shell_true_sites": 0,
        }
        or vcs.get("runtime")
        != {
            "argv_is_list": True,
            "calls": [
                [
                    "git",
                    "clone",
                    "--quiet",
                    "<url-with-metacharacters>",
                    "<destination>",
                ],
                [
                    "git",
                    "-C",
                    "<destination>",
                    "checkout",
                    "--quiet",
                    "<revision-with-metacharacters>",
                ],
            ],
            "subprocess_count": 2,
        }
    ):
        raise CollectionError("setuptools VCS proof is invalid")


def collect(
    *,
    output: Path,
    images: dict[str, str],
) -> dict[str, Any]:
    if set(images) != set(SURFACES):
        raise CollectionError("setuptools backport surface set is invalid")
    inspections: dict[str, dict[str, Any]] = {}
    for surface in SURFACES:
        expected = (
            f"localhost/coffer-ui-python-trial-{surface}-after:2026.1-python-overlay"
        )
        if images[surface] != expected:
            raise CollectionError("setuptools backport image name is invalid")
        inspections[surface] = inspect_image(images[surface])
    architectures = {item["architecture"] for item in inspections.values()}
    if architectures == {"arm64"}:
        architecture = "arm64"
    elif architectures == {"amd64"}:
        architecture = "amd64"
    else:
        raise CollectionError("setuptools backport architectures are inconsistent")
    probe = Path(__file__).with_name("probe_setuptools_backport.py")
    runtimes = {
        surface: container_json(
            image=images[surface],
            collector=probe,
            arguments=[],
            interpreter="/usr/bin/python3",
        )
        for surface in SURFACES
    }
    for runtime in runtimes.values():
        validate_runtime(runtime, architecture)
    document = {
        "architecture": architecture,
        "images": {
            surface: {
                "id": inspections[surface]["id"],
                "name": images[surface],
            }
            for surface in SURFACES
        },
        "runtimes": runtimes,
        "schema": SCHEMA,
    }
    if any(
        not DIGEST.fullmatch(item["id"].removeprefix("sha256:"))
        for item in document["images"].values()
    ):
        raise CollectionError("setuptools backport image identity is invalid")
    atomic_json(output, document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizon-after", required=True)
    parser.add_argument("--skyline-after", required=True)
    arguments = parser.parse_args()
    try:
        collect(
            output=arguments.output,
            images={
                "horizon": arguments.horizon_after,
                "skyline": arguments.skyline_after,
            },
        )
    except CollectionError as error:
        print(f"coffer-ui-setuptools-backport-collector: {error}")
        return 2
    except subprocess.TimeoutExpired:
        print("coffer-ui-setuptools-backport-collector: collection timed out")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
