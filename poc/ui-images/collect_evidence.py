from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

IMAGE_NAME = re.compile(r"^localhost/coffer-ui-[a-z0-9-]+:2026\.1-native-candidate$")
IMAGE_KEYS = (
    "horizon-parent",
    "horizon-custom",
    "skyline-parent",
    "skyline-custom",
)
SOURCE_REVISIONS = {
    "kolla": "686c6d13dc1c31092b22c6c481e16a7329e935ea",
    "horizon": "0a4439556517cf67be0aa949b6551a14e409af75",
    "skyline": "c9000cb1be332a213009793598f17a80ce59671e",
}


class CollectionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise CollectionError(f"invalid wheel: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_projection(document: dict[str, Any]) -> dict[str, Any]:
    image_id = str(document.get("Id", ""))
    if re.fullmatch(r"[0-9a-f]{64}", image_id):
        image_id = f"sha256:{image_id}"
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise CollectionError("Podman image ID is not immutable")
    rootfs = document.get("RootFS") or {}
    config = document.get("Config") or {}
    layers = rootfs.get("Layers")
    if not isinstance(layers, list) or not layers:
        raise CollectionError("Podman image layers are missing")
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
        raise CollectionError("image name is outside the bounded local namespace")
    process = subprocess.run(
        ["podman", "image", "inspect", name],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode != 0 or process.stderr:
        raise CollectionError("Podman image inspection failed")
    try:
        documents = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise CollectionError("Podman image inspection is invalid") from error
    if not isinstance(documents, list) or len(documents) != 1:
        raise CollectionError("Podman image inspection count is invalid")
    return image_projection(documents[0])


def runtime_surface(
    *,
    image: str,
    surface: str,
    collector: Path,
) -> dict[str, Any]:
    if not IMAGE_NAME.fullmatch(image) or surface not in {"horizon", "skyline"}:
        raise CollectionError("runtime target is invalid")
    if not collector.is_file() or collector.is_symlink():
        raise CollectionError("runtime collector is missing or linked")
    process = subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "--network",
            "none",
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "/var/lib/kolla/venv/bin/python",
            "--volume",
            f"{collector.resolve()}:/opt/coffer-ui-runtime.py:ro",
            image,
            "/opt/coffer-ui-runtime.py",
            surface,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if process.returncode != 0 or process.stderr:
        raise CollectionError("runtime collection failed")
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise CollectionError("runtime collection is invalid") from error
    if not isinstance(value, dict):
        raise CollectionError("runtime collection is not an object")
    return value


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--horizon-wheel", type=Path, required=True)
    parser.add_argument("--skyline-wheel", type=Path, required=True)
    parser.add_argument("--docker-scout-version", required=True)
    parser.add_argument("--trivy-version", required=True)
    for key in IMAGE_KEYS:
        parser.add_argument(f"--{key}", required=True)
    arguments = parser.parse_args()
    images_by_key = {
        key: getattr(arguments, key.replace("-", "_")) for key in IMAGE_KEYS
    }
    try:
        inspections = {key: inspect_image(name) for key, name in images_by_key.items()}
        architecture_values = {value["architecture"] for value in inspections.values()}
        if architecture_values == {"arm64"}:
            architecture = "arm64"
        elif architecture_values == {"amd64"}:
            architecture = "amd64"
        else:
            raise CollectionError("image architectures are inconsistent")
        runtime = {
            "schema": "coffer.ui-image-runtime/v1",
            "architecture": architecture,
            "surfaces": {
                surface: runtime_surface(
                    image=images_by_key[f"{surface}-custom"],
                    surface=surface,
                    collector=Path(__file__).with_name("collect_runtime.py"),
                )
                for surface in ("horizon", "skyline")
            },
        }
        manifest = {
            "schema": "coffer.ui-image-evidence/v1",
            "architecture": architecture,
            "platform": f"linux/{architecture}",
            "sources": SOURCE_REVISIONS,
            "artifacts": {
                "horizon": {
                    "name": "coffer-horizon",
                    "version": "0.1.0",
                    "sha256": sha256_file(arguments.horizon_wheel),
                },
                "skyline": {
                    "name": "skyline-console",
                    "version": "8.0.0+coffer.1",
                    "sha256": sha256_file(arguments.skyline_wheel),
                },
            },
            "images": {
                surface: {
                    kind: {
                        "name": images_by_key[f"{surface}-{kind}"],
                        "id": inspections[f"{surface}-{kind}"]["id"],
                    }
                    for kind in ("parent", "custom")
                }
                for surface in ("horizon", "skyline")
            },
            "scanners": {
                "docker_scout": arguments.docker_scout_version,
                "trivy": arguments.trivy_version,
            },
        }
        atomic_json(
            arguments.evidence / "images.json",
            {"schema": "coffer.ui-image-inspection/v1", "images": inspections},
        )
        atomic_json(arguments.evidence / "runtime.json", runtime)
        atomic_json(arguments.evidence / "manifest.json", manifest)
    except (CollectionError, subprocess.TimeoutExpired):
        print("coffer-ui-image-evidence: collection failed")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
