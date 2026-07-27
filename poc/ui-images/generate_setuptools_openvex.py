from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from residual_finding import ResidualError, load_contract

OPENVEX_CONTEXT = "https://openvex.dev/ns/v0.2.0"
INDEX_SCHEMA = "coffer.ui-setuptools-openvex-index/v1"
SOURCE_SCHEMA = "coffer.ui-vendor-source-evidence/v1"
RUNTIME_SCHEMA = "coffer.ui-setuptools-backport-evidence/v1"
IMAGES_SCHEMA = "coffer.ui-python-overlay-images/v1"
SURFACES = ("horizon", "skyline")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP = re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


class VexError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise VexError(f"OpenVEX input is missing or linked: {path.name}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise VexError(f"OpenVEX input is unreadable: {path.name}") from error
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    sha256_file(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VexError(f"{label} is unreadable") from error
    if not isinstance(document, dict):
        raise VexError(f"{label} is not an object")
    return document


def validate_source(
    document: dict[str, Any],
    *,
    manifest_sha256: str,
    expected_patches: list[dict[str, str]],
) -> None:
    if (
        document.get("schema") != SOURCE_SCHEMA
        or document.get("manifest_sha256") != manifest_sha256
        or document.get("source")
        != {
            "package": "setuptools",
            "version": "68.1.2-2ubuntu1.2",
        }
        or document.get("patches") != expected_patches
    ):
        raise VexError("vendor source evidence is not exact")
    decision = document.get("decision")
    if (
        not isinstance(decision, dict)
        or decision.get("source_backports_verified") is not True
        or decision.get("vex_generation_allowed") is not False
    ):
        raise VexError("vendor source decision is invalid")


def image_projection(
    images: dict[str, Any],
    runtime_images: dict[str, Any],
    runtime_documents: dict[str, Any],
    surface: str,
) -> dict[str, str]:
    raw_image = images.get(f"{surface}-after")
    runtime_image = runtime_images.get(surface)
    runtime_document = runtime_documents.get(surface)
    if (
        not isinstance(raw_image, dict)
        or not isinstance(runtime_image, dict)
        or not isinstance(runtime_document, dict)
    ):
        raise VexError("OpenVEX surface evidence is incomplete")
    image_id = raw_image.get("id")
    image_name = runtime_image.get("name")
    expected_name = (
        f"localhost/coffer-ui-python-trial-{surface}-after:2026.1-python-overlay"
    )
    if (
        not isinstance(image_id, str)
        or not image_id.startswith("sha256:")
        or not DIGEST.fullmatch(image_id.removeprefix("sha256:"))
        or runtime_image
        != {
            "id": image_id,
            "name": expected_name,
        }
        or image_name != expected_name
    ):
        raise VexError("OpenVEX image identity is invalid")
    labels = raw_image.get("labels")
    if not isinstance(labels, dict):
        raise VexError("OpenVEX image labels are invalid")
    timestamp = labels.get("org.opencontainers.image.created")
    if (
        not isinstance(timestamp, str)
        or not TIMESTAMP.fullmatch(timestamp)
        or runtime_document.get("decision")
        != {
            "backported_behaviors_verified": True,
            "findings": {
                "CVE-2024-6345": "not_affected",
                "CVE-2025-47273": "not_affected",
            },
            "vex_generation_allowed": True,
        }
    ):
        raise VexError("OpenVEX runtime decision is invalid")
    repository = expected_name.removesuffix(":2026.1-python-overlay")
    return {
        "image_id": image_id,
        "product": f"pkg:docker/{repository}@{image_id}",
        "timestamp": timestamp,
    }


def vex_document(
    *,
    surface: str,
    product: str,
    timestamp: str,
    subcomponent: str,
    findings: tuple[str, ...],
) -> dict[str, Any]:
    document_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"coffer-openvex:{surface}:{product}:{','.join(findings)}",
    )
    products = [
        {
            "@id": product,
            "subcomponents": [{"@id": subcomponent}],
        }
    ]
    return {
        "@context": OPENVEX_CONTEXT,
        "@id": f"urn:uuid:{document_id}",
        "author": "Coffer Security Working Group",
        "statements": [
            {
                "impact_statement": (
                    "Ubuntu Noble python3-setuptools contains Canonical's "
                    "backported fix and the installed behavior probe passed."
                ),
                "justification": "vulnerable_code_not_present",
                "products": products,
                "status": "not_affected",
                "timestamp": timestamp,
                "vulnerability": {"name": finding},
            }
            for finding in findings
        ],
        "timestamp": timestamp,
        "version": 1,
    }


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise VexError(f"refusing existing OpenVEX output: {path.name}")
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
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        temporary.chmod(0o640)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def generate(
    *,
    manifest_path: Path,
    source_path: Path,
    baseline_result_path: Path,
    images_path: Path,
    runtimes_path: Path,
    output: Path,
) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise VexError("refusing existing OpenVEX directory")
    try:
        contract = load_contract(manifest_path)
    except ResidualError as error:
        raise VexError("residual contract is invalid") from error
    if sha256_file(baseline_result_path) != contract.result_sha256:
        raise VexError("Plan 0025 result identity is invalid")
    package = contract.package("ubuntu-setuptools")
    if (
        package.disposition != "vendor-backport-to-prove"
        or package.purl != "pkg:pypi/setuptools@68.1.2"
        or package.finding_ids != ("CVE-2024-6345", "CVE-2025-47273")
    ):
        raise VexError("setuptools residual contract is invalid")
    source = load_json(source_path, "vendor source evidence")
    validate_source(
        source,
        manifest_sha256=sha256_file(manifest_path),
        expected_patches=[
            {
                "filename": patch.filename,
                "finding_id": patch.finding_id,
                "sha256": patch.sha256,
            }
            for patch in contract.vendor_source.patches
        ],
    )
    images_document = load_json(images_path, "matrix image evidence")
    runtime_document = load_json(runtimes_path, "setuptools runtime evidence")
    if (
        images_document.get("schema") != IMAGES_SCHEMA
        or runtime_document.get("schema") != RUNTIME_SCHEMA
        or runtime_document.get("architecture") != "arm64"
    ):
        raise VexError("OpenVEX evidence schema is invalid")
    images = images_document.get("images")
    runtime_surfaces = runtime_document.get("runtimes")
    runtime_images = runtime_document.get("images")
    if (
        not isinstance(images, dict)
        or not isinstance(runtime_surfaces, dict)
        or not isinstance(runtime_images, dict)
        or set(runtime_surfaces) != set(SURFACES)
        or set(runtime_images) != set(SURFACES)
    ):
        raise VexError("OpenVEX evidence surface set is invalid")
    projections = {
        surface: image_projection(
            images,
            runtime_images,
            runtime_surfaces,
            surface,
        )
        for surface in SURFACES
    }
    output.mkdir(mode=0o700)
    files: dict[str, dict[str, str]] = {}
    for surface in SURFACES:
        projection = projections[surface]
        filename = f"{surface}.vex.json"
        path = output / filename
        atomic_json(
            path,
            vex_document(
                surface=surface,
                product=projection["product"],
                timestamp=projection["timestamp"],
                subcomponent=package.purl,
                findings=package.finding_ids,
            ),
        )
        files[surface] = {
            "filename": filename,
            "image_id": projection["image_id"],
            "product": projection["product"],
            "sha256": sha256_file(path),
        }
    index = {
        "inputs": {
            "baseline_result_sha256": contract.result_sha256,
            "images_sha256": sha256_file(images_path),
            "residual_manifest_sha256": sha256_file(manifest_path),
            "runtime_evidence_sha256": sha256_file(runtimes_path),
            "source_evidence_sha256": sha256_file(source_path),
        },
        "openvex": files,
        "schema": INDEX_SCHEMA,
    }
    atomic_json(output / "index.json", index)
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument("--baseline-result", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--runtimes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        generate(
            manifest_path=arguments.manifest,
            source_path=arguments.source_evidence,
            baseline_result_path=arguments.baseline_result,
            images_path=arguments.images,
            runtimes_path=arguments.runtimes,
            output=arguments.output,
        )
    except VexError as error:
        print(f"coffer-ui-setuptools-openvex: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
