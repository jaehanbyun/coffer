#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config


ENDPOINT = "https://192.168.253.30:8443"
REGION = "us-east-1"
REGISTRY_BUCKET = "coffer-stage5-registry"
CA_PATH = "/etc/ceph/coffer-stage5-ingress/ca.crt"
SENTINEL_KEY = "stage5/ha-sentinel.bin"
SENTINEL_BYTES = 4 * 1024 * 1024
SENTINEL_SHA256 = (
    "543e845c8c7185da3bc04a566b068274"
    "825c837a740d029726b169481b919e50"
)


def load_client(path: Path) -> Any:
    document = json.loads(path.read_text(encoding="utf-8"))
    keys = document.get("keys", [])
    if len(keys) != 1:
        raise RuntimeError("expected exactly one registry S3 key")
    access_key = keys[0].get("access_key")
    secret_key = keys[0].get("secret_key")
    if not isinstance(access_key, str) or not access_key:
        raise RuntimeError("registry access key is missing")
    if not isinstance(secret_key, str) or not secret_key:
        raise RuntimeError("registry secret key is missing")
    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=ENDPOINT,
        region_name=REGION,
        verify=CA_PATH,
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=15,
            retries={"max_attempts": 3, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: guest-stage5-s3-read.py REGISTRY_USER_JSON")
    client = load_client(Path(sys.argv[1]))
    buckets = {entry["Name"] for entry in client.list_buckets()["Buckets"]}
    if buckets != {REGISTRY_BUCKET}:
        raise RuntimeError("registry identity has an unexpected bucket set")

    metadata = client.head_object(
        Bucket=REGISTRY_BUCKET,
        Key=SENTINEL_KEY,
    )
    if int(metadata["ContentLength"]) != SENTINEL_BYTES:
        raise RuntimeError("sentinel size changed")
    if metadata.get("Metadata", {}).get("sha256") != SENTINEL_SHA256:
        raise RuntimeError("sentinel metadata digest changed")

    body = client.get_object(
        Bucket=REGISTRY_BUCKET,
        Key=SENTINEL_KEY,
    )["Body"].read()
    digest = hashlib.sha256(body).hexdigest()
    if len(body) != SENTINEL_BYTES or digest != SENTINEL_SHA256:
        raise RuntimeError("sentinel content changed")

    print(
        json.dumps(
            {
                "bucket": REGISTRY_BUCKET,
                "sentinel_bytes": len(body),
                "sentinel_sha256": digest,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
