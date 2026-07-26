from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "coffer.ui-python-overlay-evidence/v1"
IMAGE_SCHEMA = "coffer.ui-python-overlay-images/v1"
INVENTORY_SCHEMA = "coffer.ui-python-overlay-os-inventories/v1"
RUNTIME_SCHEMA = "coffer.ui-python-overlay-runtimes/v1"
IMAGE_NAME = re.compile(
    r"^localhost/coffer-ui-python-trial-(horizon|skyline)-(before|after):"
    r"2026\.1-mako-1\.3\.12$"
)
REVISION = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SURFACES = ("horizon", "skyline")
KINDS = ("before", "after")


class CollectionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise CollectionError(f"artifact is missing or linked: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise CollectionError(f"refusing existing evidence: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            temporary = Path(stream.name)
        temporary.chmod(0o640)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def image_projection(document: dict[str, Any]) -> dict[str, Any]:
    image_id = str(document.get("Id", ""))
    if DIGEST.fullmatch(image_id):
        image_id = f"sha256:{image_id}"
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise CollectionError("image ID is not immutable")
    rootfs = document.get("RootFS") or {}
    config = document.get("Config") or {}
    layers = rootfs.get("Layers")
    if not isinstance(layers, list) or not layers:
        raise CollectionError("image layers are missing")
    return {
        "id": image_id,
        "architecture": str(document.get("Architecture", "")),
        "os": str(document.get("Os") or document.get("OS") or ""),
        "user": str(config.get("User") or ""),
        "entrypoint": config.get("Entrypoint") or [],
        "cmd": config.get("Cmd") or [],
        "labels": config.get("Labels") or {},
        "layers": layers,
    }


def inspect_image(name: str) -> dict[str, Any]:
    if not IMAGE_NAME.fullmatch(name):
        raise CollectionError("image name is outside the trial namespace")
    process = subprocess.run(
        ["podman", "image", "inspect", name],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode != 0 or process.stderr:
        raise CollectionError("image inspection failed")
    try:
        documents = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise CollectionError("image inspection is invalid") from error
    if not isinstance(documents, list) or len(documents) != 1:
        raise CollectionError("image inspection count is invalid")
    return image_projection(documents[0])


def container_json(
    *,
    image: str,
    collector: Path,
    arguments: list[str],
    interpreter: str,
) -> dict[str, Any]:
    if not IMAGE_NAME.fullmatch(image):
        raise CollectionError("runtime image is outside the trial namespace")
    if not collector.is_file() or collector.is_symlink():
        raise CollectionError("runtime collector is missing or linked")
    process = subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "all",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "0",
            "--entrypoint",
            interpreter,
            "--volume",
            f"{collector.resolve()}:/opt/coffer-ui-collector.py:ro",
            image,
            "/opt/coffer-ui-collector.py",
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if process.returncode != 0 or process.stderr:
        key = image.rsplit("/", 1)[-1].split(":", 1)[0]
        detail = process.stdout.strip()
        if (
            process.returncode != 0
            and detail.startswith("coffer-ui-python-overlay-runtime: ")
            and "\n" not in detail
        ):
            raise CollectionError(f"{collector.stem} failed for {key}: {detail}")
        raise CollectionError(f"{collector.stem} failed for {key}")
    try:
        document = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise CollectionError("container evidence is invalid") from error
    if not isinstance(document, dict):
        raise CollectionError("container evidence is not an object")
    return document


def collect(
    *,
    evidence: Path,
    images: dict[str, str],
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheel: Path,
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
    revisions = (kolla_revision, horizon_revision, skyline_revision)
    if not all(REVISION.fullmatch(value) for value in revisions):
        raise CollectionError("source revision is invalid")
    if not DIGEST.fullmatch(ubuntu_sha256):
        raise CollectionError("Ubuntu digest is invalid")
    if not docker_scout_version or not trivy_version:
        raise CollectionError("scanner version is empty")
    expected_keys = {
        f"{surface}-{kind}" for surface in SURFACES for kind in KINDS
    }
    if set(images) != expected_keys:
        raise CollectionError("trial image set is invalid")
    inspections = {key: inspect_image(value) for key, value in images.items()}
    architectures = {item["architecture"] for item in inspections.values()}
    if architectures == {"arm64"}:
        architecture = "arm64"
    elif architectures == {"amd64"}:
        architecture = "amd64"
    else:
        raise CollectionError("trial image architectures are inconsistent")

    package_collector = Path(__file__).with_name("package_probe.py")
    python_collector = Path(__file__).with_name("collect_python_runtime.py")
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
            arguments=[],
            interpreter="/var/lib/kolla/venv/bin/python",
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
            "target": {
                "name": "Mako",
                "from_version": "1.3.10",
                "to_version": "1.3.12",
                "filename": target_wheel.name,
                "sha256": sha256_file(target_wheel),
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
    parser.add_argument("--target-wheel", type=Path, required=True)
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
            parser.add_argument(f"--{surface}-{kind}", required=True)
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
            target_wheel=arguments.target_wheel,
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
        print(f"coffer-ui-python-overlay-collector: {error}")
        return 2
    except subprocess.TimeoutExpired:
        print("coffer-ui-python-overlay-collector: collection timed out")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
