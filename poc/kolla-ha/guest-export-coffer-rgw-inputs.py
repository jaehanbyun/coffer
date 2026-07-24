#!/usr/bin/env python3

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


STATE_ROOT = Path("/etc/coffer-stage5-rgw")
REGISTRY_USER = STATE_ROOT / "registry-user.json"
DISTRIBUTION_ENV = STATE_ROOT / "distribution.env"
RGW_CA = Path("/etc/ceph/coffer-stage5-ingress/ca.crt")


def parse_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        name, separator, value = raw_line.partition("=")
        if not separator or name in values:
            raise RuntimeError("invalid Distribution environment input")
        values[name] = value.strip("'\"")
    return values


def add_file(
    archive: tarfile.TarFile,
    name: str,
    content: bytes,
    mode: int,
) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    archive.addfile(info, BytesIO(content))


def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("usage: guest-export-coffer-rgw-inputs.py")
    if os.geteuid() != 0:
        raise RuntimeError("RGW input export requires root")
    if subprocess.run(
        ["hostname"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() != "coffer-rgw-ha-stage5-storage-1":
        raise RuntimeError("RGW input export ran on the wrong host")

    for path, mode in (
        (REGISTRY_USER, 0o600),
        (DISTRIBUTION_ENV, 0o600),
        (RGW_CA, 0o644),
    ):
        metadata = path.stat()
        if metadata.st_uid != 0 or metadata.st_gid != 0:
            raise RuntimeError("RGW input owner is invalid")
        if metadata.st_mode & 0o777 != mode or metadata.st_size == 0:
            raise RuntimeError("RGW input mode or size is invalid")

    document = json.loads(REGISTRY_USER.read_text(encoding="utf-8"))
    keys = document.get("keys", [])
    if document.get("user_id") != "coffer-stage5-registry" or len(keys) != 1:
        raise RuntimeError("registry RGW identity is invalid")
    access_key = keys[0].get("access_key")
    secret_key = keys[0].get("secret_key")
    if not isinstance(access_key, str) or len(access_key) < 8:
        raise RuntimeError("registry access key is invalid")
    if not isinstance(secret_key, str) or len(secret_key) < 16:
        raise RuntimeError("registry secret key is invalid")

    environment = parse_environment(DISTRIBUTION_ENV)
    expected_environment = {
        "REGISTRY_STORAGE_S3_REGION": "us-east-1",
        "REGISTRY_STORAGE_S3_REGIONENDPOINT": "https://192.168.253.30:8443",
        "REGISTRY_STORAGE_S3_BUCKET": "coffer-stage5-registry",
        "REGISTRY_STORAGE_S3_ACCESSKEY": access_key,
        "REGISTRY_STORAGE_S3_SECRETKEY": secret_key,
    }
    for name, value in expected_environment.items():
        if environment.get(name) != value:
            raise RuntimeError("RGW Distribution input mismatch")
    subprocess.run(
        ["openssl", "x509", "-in", str(RGW_CA), "-checkend", "86400", "-noout"],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
        add_file(archive, "rgw-access-key", f"{access_key}\n".encode(), 0o600)
        add_file(archive, "rgw-secret-key", f"{secret_key}\n".encode(), 0o600)
        add_file(archive, "rgw-ca.crt", RGW_CA.read_bytes(), 0o644)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
