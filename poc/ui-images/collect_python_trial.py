from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from python_target import PackageComponent, TargetError, load_target

MANIFEST_SCHEMA = "coffer.ui-python-overlay-evidence/v4"
IMAGE_SCHEMA = "coffer.ui-python-overlay-images/v1"
INVENTORY_SCHEMA = "coffer.ui-python-overlay-os-inventories/v1"
RUNTIME_SCHEMA = "coffer.ui-python-overlay-runtimes/v1"
IMAGE_NAME = re.compile(
    r"^localhost/coffer-ui-python-trial-(horizon|skyline)-(before|after):"
    r"2026\.1-python-overlay$"
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
    extra_mounts: tuple[tuple[Path, str], ...] = (),
) -> dict[str, Any]:
    if not IMAGE_NAME.fullmatch(image):
        raise CollectionError("runtime image is outside the trial namespace")
    if not collector.is_file() or collector.is_symlink():
        raise CollectionError("runtime collector is missing or linked")
    mounts = [
        "--volume",
        f"{collector.resolve()}:/opt/coffer-ui-collector.py:ro",
    ]
    for source, destination in extra_mounts:
        if (
            not source.is_file()
            or source.is_symlink()
            or not re.fullmatch(r"/opt/[a-z0-9_.-]+", destination)
        ):
            raise CollectionError("runtime support mount is invalid")
        mounts.extend(("--volume", f"{source.resolve()}:{destination}:ro"))
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
            *mounts,
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


def component_projection(component: PackageComponent) -> dict[str, Any]:
    return {
        "name": component.display_name,
        "normalized_name": component.normalized_name,
        "from_version": component.from_version,
        "to_version": component.to_version,
        "filename": component.wheel_filename,
        "wheel_architecture": component.wheel_architecture,
        "sha256": component.wheel_sha256,
        "finding_ids": list(component.finding_ids),
        "finding_ids_by_scanner": component.scanner_finding_ids,
        "requires_dist": list(component.requires_dist),
    }


def collect(
    *,
    evidence: Path,
    images: dict[str, str],
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheels: tuple[Path, ...],
    target_manifest: Path,
    target_key: str,
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
        target = load_target(target_manifest, target_key)
    except TargetError as error:
        raise CollectionError("Python target is invalid") from error
    if (
        len(target_wheels) != len(target.components)
        or tuple(path.name for path in target_wheels)
        != tuple(component.wheel_filename for component in target.components)
        or len({path.name for path in target_wheels}) != len(target_wheels)
        or any(
            sha256_file(path) != component.wheel_sha256
            for path, component in zip(
                target_wheels,
                target.components,
                strict=True,
            )
        )
    ):
        raise CollectionError("Python target wheel identity is invalid")
    revisions = (kolla_revision, horizon_revision, skyline_revision)
    if not all(REVISION.fullmatch(value) for value in revisions):
        raise CollectionError("source revision is invalid")
    if not DIGEST.fullmatch(ubuntu_sha256):
        raise CollectionError("Ubuntu digest is invalid")
    if not docker_scout_version or not trivy_version:
        raise CollectionError("scanner version is empty")
    expected_keys = {
        f"{surface}-{kind}" for surface in target.surfaces for kind in KINDS
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
                "/opt/python_targets.json",
                "--target",
                target.key,
                "--probe-mode",
                "baseline" if key.endswith("-before") else "candidate",
            ],
            interpreter="/var/lib/kolla/venv/bin/python",
            extra_mounts=(
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
        for surface in target.surfaces
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
                "key": target.key,
                "manifest_sha256": sha256_file(target_manifest),
                "probe": target.probe,
                "trial_label": target.trial_label,
                "finding_ids": list(target.finding_ids),
                "finding_ids_by_scanner": target.scanner_finding_ids,
                "surfaces": list(target.surfaces),
                "components": [
                    component_projection(component)
                    for component in target.components
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
    parser.add_argument("--target", required=True)
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
            parser.add_argument(f"--{surface}-{kind}")
    arguments = parser.parse_args()
    try:
        target = load_target(arguments.target_manifest, arguments.target)
        images = {
            f"{surface}-{kind}": getattr(arguments, f"{surface}_{kind}")
            for surface in target.surfaces
            for kind in KINDS
        }
        if any(not value for value in images.values()) or any(
            getattr(arguments, f"{surface}_{kind}") is not None
            for surface in set(SURFACES) - set(target.surfaces)
            for kind in KINDS
        ):
            raise CollectionError("trial image arguments do not match target surfaces")
        collect(
            evidence=arguments.evidence,
            images=images,
            horizon_wheel=arguments.horizon_wheel,
            skyline_wheel=arguments.skyline_wheel,
            target_wheels=tuple(arguments.target_wheel),
            target_manifest=arguments.target_manifest,
            target_key=arguments.target,
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
    except TargetError:
        print("coffer-ui-python-overlay-collector: target manifest is invalid")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
