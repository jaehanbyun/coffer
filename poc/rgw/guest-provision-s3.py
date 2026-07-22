#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


ENDPOINT = "https://192.168.122.200:8443"
REGION = "us-east-1"
REGISTRY_BUCKET = "coffer-registry-poc"
DENIAL_BUCKET = "coffer-denial-poc"
EXTRA_BUCKET = "coffer-registry-extra-denied-poc"
CA_PATH = "/etc/ceph/coffer-rgw-root-ca.crt"


def load_key(path: Path) -> tuple[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    keys = document.get("keys", [])
    if len(keys) != 1:
        raise RuntimeError(f"expected exactly one S3 key for {path.name}")
    access_key = keys[0].get("access_key")
    secret_key = keys[0].get("secret_key")
    if not isinstance(access_key, str) or not access_key:
        raise RuntimeError(f"missing access key in {path.name}")
    if not isinstance(secret_key, str) or not secret_key:
        raise RuntimeError(f"missing secret key in {path.name}")
    return access_key, secret_key


def client(credentials_path: Path) -> Any:
    access_key, secret_key = load_key(credentials_path)
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


def ensure_bucket(s3: Any, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
        return
    except ClientError as error:
        if status_code(error) != 404:
            raise
    s3.create_bucket(Bucket=bucket)
    s3.head_bucket(Bucket=bucket)


def expect_bucket_denied(s3: Any, bucket: str) -> int:
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as error:
        code = status_code(error)
        if code in {403, 404}:
            return code
        raise
    raise RuntimeError(f"unexpected access to separately owned bucket {bucket}")


def expect_extra_bucket_denied(s3: Any) -> int:
    try:
        s3.create_bucket(Bucket=EXTRA_BUCKET)
    except ClientError as error:
        code = status_code(error)
        if code in {400, 403, 409}:
            return code
        raise
    try:
        s3.delete_bucket(Bucket=EXTRA_BUCKET)
    finally:
        raise RuntimeError("max-buckets=1 did not prevent an additional bucket")


def expect_anonymous_denied(bucket: str) -> int:
    context = ssl.create_default_context(cafile=CA_PATH)
    request = urllib.request.Request(f"{ENDPOINT}/{bucket}", method="GET")
    try:
        urllib.request.urlopen(request, context=context, timeout=10)
    except urllib.error.HTTPError as error:
        if error.code in {403, 404}:
            return error.code
        raise
    raise RuntimeError(f"anonymous request unexpectedly accessed {bucket}")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: guest-provision-s3.py REGISTRY_USER_JSON DENIAL_USER_JSON")
    registry = client(Path(sys.argv[1]))
    denial = client(Path(sys.argv[2]))

    ensure_bucket(registry, REGISTRY_BUCKET)
    ensure_bucket(denial, DENIAL_BUCKET)

    registry_buckets = {entry["Name"] for entry in registry.list_buckets()["Buckets"]}
    denial_buckets = {entry["Name"] for entry in denial.list_buckets()["Buckets"]}
    if registry_buckets != {REGISTRY_BUCKET}:
        raise RuntimeError("registry identity has an unexpected bucket set")
    if denial_buckets != {DENIAL_BUCKET}:
        raise RuntimeError("denial identity has an unexpected bucket set")

    payload = b"coffer-rgw-private-bucket-sentinel\n"
    sentinel_key = "poc/private-sentinel.txt"
    registry.put_object(Bucket=REGISTRY_BUCKET, Key=sentinel_key, Body=payload)
    downloaded = registry.get_object(Bucket=REGISTRY_BUCKET, Key=sentinel_key)["Body"].read()
    if downloaded != payload:
        raise RuntimeError("private bucket sentinel changed during round trip")
    registry.delete_object(Bucket=REGISTRY_BUCKET, Key=sentinel_key)

    evidence = {
        "anonymous_status": expect_anonymous_denied(REGISTRY_BUCKET),
        "cross_bucket_status": expect_bucket_denied(registry, DENIAL_BUCKET),
        "extra_bucket_status": expect_extra_bucket_denied(registry),
        "registry_bucket": REGISTRY_BUCKET,
        "denial_bucket": DENIAL_BUCKET,
        "sentinel_sha256": hashlib.sha256(payload).hexdigest(),
    }
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
