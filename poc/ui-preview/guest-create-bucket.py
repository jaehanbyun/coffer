#!/usr/bin/env python3

from __future__ import annotations

import hashlib
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


ENDPOINT = "https://coffer-rgw-poc:8443"
REGION = "us-east-1"
BUCKET = "coffer-ui-preview-1"
SECRET_ROOT = Path("/etc/kolla/config/coffer/secrets")
CA_PATH = "/etc/kolla/config/coffer/public/rgw-ca.crt"


def read_secret(name: str) -> str:
    path = SECRET_ROOT / name
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError(f"invalid owner-only secret file: {name}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"empty owner-only secret file: {name}")
    return value


def main() -> int:
    s3 = boto3.client(
        "s3",
        aws_access_key_id=read_secret("rgw-access-key"),
        aws_secret_access_key=read_secret("rgw-secret-key"),
        endpoint_url=ENDPOINT,
        region_name=REGION,
        verify=CA_PATH,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 4, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )
    created = False
    try:
        s3.head_bucket(Bucket=BUCKET)
    except ClientError as error:
        status = int(error.response["ResponseMetadata"]["HTTPStatusCode"])
        if status != 404:
            raise
        s3.create_bucket(Bucket=BUCKET)
        created = True
    s3.head_bucket(Bucket=BUCKET)
    buckets = {entry["Name"] for entry in s3.list_buckets()["Buckets"]}
    if buckets != {BUCKET}:
        raise RuntimeError("UI preview RGW identity has unexpected buckets")

    payload = b"coffer-ui-preview-private-sentinel\n"
    key = "preview/private-sentinel.txt"
    s3.put_object(Bucket=BUCKET, Key=key, Body=payload)
    downloaded = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    if downloaded != payload:
        raise RuntimeError("UI preview RGW sentinel changed")
    s3.delete_object(Bucket=BUCKET, Key=key)
    print(
        "preview_rgw "
        f"bucket={BUCKET} created={str(created).lower()} "
        f"sentinel_sha256={hashlib.sha256(payload).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
