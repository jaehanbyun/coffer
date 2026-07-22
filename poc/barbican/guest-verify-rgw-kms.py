#!/usr/bin/env python3
"""Verify a direct RGW SSE-KMS write without exposing credentials or key IDs."""

from __future__ import annotations

import hashlib
import json
import os
import uuid

import boto3
from botocore.client import Config


ENDPOINT = "https://192.168.122.200:8443"
CA_PATH = "/etc/ceph/coffer-rgw-root-ca.crt"
BUCKET = "coffer-registry-poc"
OBJECT_KEY = "poc/kms/direct-object.txt"
PAYLOAD = b"coffer-barbican-sse-kms-direct-proof\n"


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def main() -> int:
    key_id = required("COFFER_KMS_KEY_ID")
    uuid.UUID(key_id)
    s3 = boto3.client(
        "s3",
        aws_access_key_id=required("REGISTRY_STORAGE_S3_ACCESSKEY"),
        aws_secret_access_key=required("REGISTRY_STORAGE_S3_SECRETKEY"),
        endpoint_url=ENDPOINT,
        region_name="us-east-1",
        verify=CA_PATH,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 1, "mode": "standard"},
            connect_timeout=5,
            read_timeout=15,
            s3={"addressing_style": "path"},
        ),
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=OBJECT_KEY,
        Body=PAYLOAD,
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=key_id,
    )
    head = s3.head_object(Bucket=BUCKET, Key=OBJECT_KEY)
    if head.get("ServerSideEncryption") != "aws:kms":
        raise RuntimeError("RGW did not report aws:kms for the direct proof object")
    if head.get("SSEKMSKeyId") != key_id:
        raise RuntimeError("RGW did not report the selected Barbican key")
    body = s3.get_object(Bucket=BUCKET, Key=OBJECT_KEY)["Body"].read()
    if body != PAYLOAD:
        raise RuntimeError("decrypted direct proof object did not match its payload")
    print(
        json.dumps(
            {
                "bucket": BUCKET,
                "key": OBJECT_KEY,
                "key_id_matches": True,
                "payload_bytes": len(PAYLOAD),
                "payload_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
                "server_side_encryption": "aws:kms",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
