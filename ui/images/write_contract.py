#!/usr/bin/env python3
"""Write a deterministic Coffer UI image contract from one built wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from email.parser import Parser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

IMAGE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$"
)
SURFACES = {
    "horizon": {
        "artifact_name": "coffer-horizon",
        "artifact_version": "0.1.0",
        "upstream_project": "openstack/horizon",
        "upstream_revision": "0a4439556517cf67be0aa949b6551a14e409af75",
    },
    "skyline": {
        "artifact_name": "skyline-console",
        "artifact_version": "8.0.0+coffer.1",
        "upstream_project": "openstack/skyline-console",
        "upstream_revision": "c9000cb1be332a213009793598f17a80ce59671e",
    },
}


class ContractError(RuntimeError):
    pass


def _wheel_metadata(path: Path) -> tuple[str, str]:
    if not path.is_file() or path.is_symlink():
        raise ContractError("artifact must be one regular wheel")
    try:
        with ZipFile(path) as archive:
            candidates = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(candidates) != 1:
                raise ContractError("wheel must contain one METADATA file")
            metadata = Parser().parsestr(
                archive.read(candidates[0]).decode("utf-8")
            )
    except (BadZipFile, UnicodeDecodeError) as error:
        raise ContractError("artifact is not a valid wheel") from error
    name = metadata.get("Name", "").strip().lower()
    version = metadata.get("Version", "").strip()
    if not name or not version:
        raise ContractError("wheel metadata is incomplete")
    return name, version


def build_contract(
    *,
    surface: str,
    artifact: Path,
    image: str,
    base_image: str,
) -> dict:
    expected = SURFACES[surface]
    for value in (image, base_image):
        if IMAGE_PATTERN.fullmatch(value) is None:
            raise ContractError("images must use exact sha256 OCI references")
    if image == base_image:
        raise ContractError("custom and fallback images must differ")

    name, version = _wheel_metadata(artifact)
    if (
        name != expected["artifact_name"]
        or version != expected["artifact_version"]
    ):
        raise ContractError("wheel name or version does not match the surface")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return {
        "artifact": {
            "name": name,
            "sha256": digest,
            "version": version,
        },
        "base_image": base_image,
        "container_contract": "coffer-ui-image-v1",
        "image": image,
        "schema_version": 1,
        "surface": surface,
        "upstream": {
            "project": expected["upstream_project"],
            "revision": expected["upstream_revision"],
        },
    }


def write_contract(path: Path, document: dict) -> None:
    content = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.is_file() and not path.is_symlink():
            if path.read_text(encoding="utf-8") == content:
                return
        raise ContractError("refusing to replace a different contract")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=sorted(SURFACES), required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    document = build_contract(
        surface=args.surface,
        artifact=args.artifact,
        image=args.image,
        base_image=args.base_image,
    )
    write_contract(args.output, document)
    print("Coffer UI image contract written.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as error:
        raise SystemExit(f"coffer-ui-contract: {error}") from None
