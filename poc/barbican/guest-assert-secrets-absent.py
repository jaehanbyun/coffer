#!/usr/bin/env python3
"""Scan protected logs without placing secret values in process argv."""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path


ENV_PATHS = (
    Path("/etc/coffer-rgw/barbican.env"),
    Path("/etc/coffer-rgw/distribution.env"),
)
SECRET_NAMES = {
    "COFFER_KMS_USER_PASSWORD",
    "REGISTRY_STORAGE_S3_ACCESSKEY",
    "REGISTRY_STORAGE_S3_SECRETKEY",
}
AUTHORIZATION = re.compile(
    rb"Authorization\s*:\s*(?:Basic|Bearer|AWS4-HMAC-SHA256)", re.IGNORECASE
)


def secrets() -> list[bytes]:
    found: list[bytes] = []
    for path in ENV_PATHS:
        metadata = path.stat()
        if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != 0:
            raise RuntimeError("runtime secret file has unsafe metadata")
        with path.open("rb") as source:
            for line in source:
                key, separator, value = line.rstrip(b"\n").partition(b"=")
                if separator and key.decode() in SECRET_NAMES:
                    if len(value) < 8:
                        raise RuntimeError("runtime secret value is unexpectedly short")
                    found.append(value)
    if len(found) != len(SECRET_NAMES):
        raise RuntimeError("runtime secret scan inputs are incomplete")
    return found


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in {"scan", "kms-failure"}:
        raise SystemExit(
            "usage: guest-assert-secrets-absent.py {scan|kms-failure} LOG..."
        )
    content = b"".join(Path(name).read_bytes() for name in sys.argv[2:])
    if any(value in content for value in secrets()):
        raise RuntimeError("protected log contains a runtime credential")
    if AUTHORIZATION.search(content):
        raise RuntimeError("protected log contains an authorization header")
    if sys.argv[1] == "kms-failure":
        lowered = content.lower()
        cause = any(term in lowered for term in (b"barbican", b"kms", b"encrypt"))
        failure = any(
            term in lowered
            for term in (b"error", b"fail", b"invalid", b"not found", b"unable")
        )
        if not cause or not failure:
            raise RuntimeError("negative scenario lacks bounded KMS-cause evidence")
    print("Protected runtime log scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
