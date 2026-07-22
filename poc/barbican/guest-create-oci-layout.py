#!/usr/bin/env python3
"""Create one deterministic, scenario-unique OCI image layout."""

from __future__ import annotations

import hashlib
import gzip
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path


SCENARIOS = {"proof", "wrong-key", "outage", "recovery"}
MEDIA_CONFIG = "application/vnd.oci.image.config.v1+json"
MEDIA_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
MEDIA_MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def canonical_json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def descriptor(media_type: str, data: bytes) -> dict[str, object]:
    return {"mediaType": media_type, "digest": digest(data), "size": len(data)}


def layer_bytes(marker: str) -> bytes:
    content = f"coffer Barbican KMS scenario: {marker}\n".encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        item = tarfile.TarInfo("coffer-kms-marker.txt")
        item.size = len(content)
        item.mode = 0o444
        item.uid = item.gid = 0
        item.uname = item.gname = "root"
        item.mtime = 0
        archive.addfile(item, io.BytesIO(content))
    return stream.getvalue()


def write_blob(root: Path, data: bytes) -> None:
    algorithm, value = digest(data).split(":", 1)
    path = root / "blobs" / algorithm / value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: guest-create-oci-layout.py OUTPUT_DIR SCENARIO")
    root = Path(sys.argv[1])
    scenario = sys.argv[2]
    expected = Path(f"/tmp/coffer-kms-oci-{scenario}")
    if scenario not in SCENARIOS or root != expected:
        raise RuntimeError("OCI layout path is outside the bounded scenario set")

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(mode=0o700)

    uncompressed_layer = layer_bytes(scenario)
    layer = gzip.compress(uncompressed_layer, mtime=0)
    config = canonical_json(
        {
            "architecture": "amd64",
            "config": {},
            "created": "2026-07-22T00:00:00Z",
            "history": [{"created_by": f"coffer-kms-{scenario}"}],
            "os": "linux",
            "rootfs": {"diff_ids": [digest(uncompressed_layer)], "type": "layers"},
        }
    )
    manifest = canonical_json(
        {
            "config": descriptor(MEDIA_CONFIG, config),
            "layers": [descriptor(MEDIA_LAYER, layer)],
            "mediaType": MEDIA_MANIFEST,
            "schemaVersion": 2,
        }
    )
    manifest_descriptor = descriptor(MEDIA_MANIFEST, manifest)
    manifest_descriptor["annotations"] = {"org.opencontainers.image.ref.name": "image"}

    for blob in (layer, config, manifest):
        write_blob(root, blob)
    (root / "oci-layout").write_bytes(canonical_json({"imageLayoutVersion": "1.0.0"}))
    (root / "index.json").write_bytes(
        canonical_json({"schemaVersion": 2, "manifests": [manifest_descriptor]})
    )
    for path in (root / "oci-layout", root / "index.json"):
        path.chmod(0o600)
    print(f"Deterministic OCI layout prepared for scenario={scenario}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
