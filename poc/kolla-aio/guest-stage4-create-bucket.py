#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


ENDPOINT = "https://192.168.122.200:8443"
REGION = "us-east-1"
BUCKET = "coffer-kolla-aio-stage4"
CREDENTIALS_PATH = Path("/root/coffer-kolla-aio-stage4-user.json")
CA_PATH = "/etc/ceph/coffer-rgw-root-ca.crt"


def load_key() -> tuple[str, str]:
    document = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    if document.get("user_id") != BUCKET:
        raise RuntimeError("unexpected Stage 4 RGW identity")
    keys = document.get("keys", [])
    if len(keys) != 1:
        raise RuntimeError("expected exactly one Stage 4 S3 key")
    access_key = keys[0].get("access_key")
    secret_key = keys[0].get("secret_key")
    if not isinstance(access_key, str) or not access_key:
        raise RuntimeError("missing Stage 4 access key")
    if not isinstance(secret_key, str) or not secret_key:
        raise RuntimeError("missing Stage 4 secret key")
    return access_key, secret_key


def client() -> Any:
    access_key, secret_key = load_key()
    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=ENDPOINT,
        region_name=REGION,
        verify=CA_PATH,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 4, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


def status_code(error: ClientError) -> int:
    return int(error.response["ResponseMetadata"]["HTTPStatusCode"])


def ensure_bucket(s3: Any) -> bool:
    try:
        s3.head_bucket(Bucket=BUCKET)
        return False
    except ClientError as error:
        if status_code(error) != 404:
            raise
    s3.create_bucket(Bucket=BUCKET)
    s3.head_bucket(Bucket=BUCKET)
    return True


def main() -> int:
    if not CREDENTIALS_PATH.is_file():
        raise RuntimeError("Stage 4 RGW credential state is absent")

    s3 = client()
    created = ensure_bucket(s3)
    buckets = {entry["Name"] for entry in s3.list_buckets()["Buckets"]}
    if buckets != {BUCKET}:
        raise RuntimeError("Stage 4 identity has an unexpected bucket set")

    payload = b"coffer-kolla-aio-stage4-private-sentinel\n"
    sentinel_key = "stage4/private-sentinel.txt"
    s3.put_object(Bucket=BUCKET, Key=sentinel_key, Body=payload)
    downloaded = s3.get_object(Bucket=BUCKET, Key=sentinel_key)["Body"].read()
    if downloaded != payload:
        raise RuntimeError("Stage 4 RGW sentinel changed during round trip")
    s3.delete_object(Bucket=BUCKET, Key=sentinel_key)

    evidence = {
        "bucket": BUCKET,
        "created": created,
        "sentinel_sha256": hashlib.sha256(payload).hexdigest(),
    }
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
