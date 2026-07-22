#!/usr/bin/env python3
"""Bounded S3 prefix assertions and cleanup for KMS failure scenarios."""

from __future__ import annotations

import json
import os
import sys
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


ENDPOINT = "https://192.168.122.200:8443"
CA_PATH = "/etc/ceph/coffer-rgw-root-ca.crt"
BUCKET = "coffer-registry-poc"
ROOT = "distribution/docker/registry/v2/repositories/"
BLOB_ROOT = "distribution/docker/registry/v2/blobs/"
DIRECT_OBJECT = "poc/kms/direct-object.txt"
ZERO_BLOB = (
    f"{BLOB_ROOT}sha256/e3/"
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855/data"
)
ZERO_REPOSITORY = "p/00000000-0000-0000-0000-000000000003/kms-zero-byte"
TEST_REPOSITORIES = (
    "p/00000000-0000-0000-0000-000000000003/kms-proof",
    "p/00000000-0000-0000-0000-000000000003/kms-recovery",
    "p/00000000-0000-0000-0000-000000000003/kms-wrong-key",
    "p/00000000-0000-0000-0000-000000000003/kms-outage",
    ZERO_REPOSITORY,
)
SCENARIOS = ("proof", "recovery", "wrong-key", "outage")


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def client():
    return boto3.client(
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


def keys_under(s3, prefix: str) -> list[str]:
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
    return [item["Key"] for page in pages for item in page.get("Contents", [])]


def multipart_uploads(s3) -> list[dict[str, str]]:
    pages = s3.get_paginator("list_multipart_uploads").paginate(Bucket=BUCKET)
    return [
        {"Key": item["Key"], "UploadId": item["UploadId"]}
        for page in pages
        for item in page.get("Uploads", [])
    ]


def layout_blob_keys(layout_path: str) -> list[str]:
    if layout_path not in {
        f"/tmp/coffer-kms-oci-{scenario}" for scenario in SCENARIOS
    }:
        raise RuntimeError("OCI layout is outside the bounded scenario set")
    with open(os.path.join(layout_path, "index.json"), encoding="utf-8") as source:
        index = json.load(source)
    manifests = index.get("manifests", [])
    if len(manifests) != 1:
        raise RuntimeError("expected exactly one OCI manifest descriptor")
    algorithm, value = manifests[0]["digest"].split(":", 1)
    with open(
        os.path.join(layout_path, "blobs", algorithm, value), encoding="utf-8"
    ) as source:
        manifest = json.load(source)
    descriptors = [manifests[0], manifest["config"], *manifest["layers"]]
    if len(descriptors) != 3:
        raise RuntimeError("expected one manifest, one config, and one layer")
    keys = []
    for item in descriptors:
        algorithm, value = item["digest"].split(":", 1)
        if algorithm != "sha256" or len(value) != 64:
            raise RuntimeError("unexpected OCI descriptor digest")
        keys.append(f"{BLOB_ROOT}{algorithm}/{value[:2]}/{value}/data")
    return keys


def linked_manifest_blob_keys(s3, repository_keys: list[str]) -> set[str]:
    keys: set[str] = set()
    for key in repository_keys:
        if "/_manifests/revisions/" not in key or not key.endswith("/link"):
            continue
        response = s3.get_object(Bucket=BUCKET, Key=key)
        value = response["Body"].read().decode("ascii").strip()
        algorithm, separator, digest_value = value.partition(":")
        if separator != ":" or algorithm != "sha256" or len(digest_value) != 64:
            raise RuntimeError("invalid manifest revision link in bounded test scope")
        manifest_key = (
            f"{BLOB_ROOT}{algorithm}/{digest_value[:2]}/{digest_value}/data"
        )
        keys.add(manifest_key)
        manifest_response = s3.get_object(Bucket=BUCKET, Key=manifest_key)
        manifest = json.loads(manifest_response["Body"].read())
        descriptors = [manifest.get("config"), *manifest.get("layers", [])]
        if not descriptors or any(not isinstance(item, dict) for item in descriptors):
            raise RuntimeError("invalid published manifest in bounded test scope")
        for item in descriptors:
            algorithm, separator, descriptor_value = item["digest"].partition(":")
            if (
                separator != ":"
                or algorithm != "sha256"
                or len(descriptor_value) != 64
            ):
                raise RuntimeError("invalid published descriptor in bounded test scope")
            keys.add(
                f"{BLOB_ROOT}{algorithm}/{descriptor_value[:2]}/"
                f"{descriptor_value}/data"
            )
    return keys


def assert_empty(s3, repository: str, layout_path: str) -> None:
    if repository not in TEST_REPOSITORIES:
        raise RuntimeError("repository is outside the bounded KMS scenario set")
    if keys_under(s3, f"{ROOT}{repository}/"):
        raise RuntimeError("failed KMS write left repository objects behind")
    global_keys = set(layout_blob_keys(layout_path))
    for key in global_keys:
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
        except ClientError as error:
            if int(error.response["ResponseMetadata"]["HTTPStatusCode"]) != 404:
                raise
        else:
            raise RuntimeError("KMS scenario blob existed before or after failed write")
    prefix = f"{ROOT}{repository}/"
    if any(
        upload["Key"].startswith(prefix) or upload["Key"] in global_keys
        for upload in multipart_uploads(s3)
    ):
        raise RuntimeError("KMS scenario left an incomplete multipart upload")


def zero_scope_keys(s3) -> set[str]:
    return set(keys_under(s3, f"{ROOT}{ZERO_REPOSITORY}/")) | {ZERO_BLOB}


def assert_zero_empty(s3) -> None:
    prefix = f"{ROOT}{ZERO_REPOSITORY}/"
    if keys_under(s3, prefix):
        raise RuntimeError("zero-byte scenario retained repository objects")
    try:
        s3.head_object(Bucket=BUCKET, Key=ZERO_BLOB)
    except ClientError as error:
        if int(error.response["ResponseMetadata"]["HTTPStatusCode"]) != 404:
            raise
    else:
        raise RuntimeError("zero-byte scenario unexpectedly published a global blob")
    if any(
        upload["Key"].startswith(prefix) or upload["Key"] == ZERO_BLOB
        for upload in multipart_uploads(s3)
    ):
        raise RuntimeError("zero-byte scenario retained a multipart upload")


def cleanup_zero(s3) -> None:
    key_id = required("COFFER_KMS_KEY_ID")
    uuid.UUID(key_id)
    prefix = f"{ROOT}{ZERO_REPOSITORY}/"
    for upload in multipart_uploads(s3):
        if upload["Key"].startswith(prefix) or upload["Key"] == ZERO_BLOB:
            s3.abort_multipart_upload(
                Bucket=BUCKET, Key=upload["Key"], UploadId=upload["UploadId"]
            )
    existing: list[str] = []
    for key in zero_scope_keys(s3):
        try:
            head = s3.head_object(Bucket=BUCKET, Key=key)
        except ClientError as error:
            if int(error.response["ResponseMetadata"]["HTTPStatusCode"]) == 404:
                continue
            raise
        if head.get("ServerSideEncryption") != "aws:kms" or head.get(
            "SSEKMSKeyId"
        ) != key_id:
            raise RuntimeError("refusing zero-byte cleanup outside the selected key")
        existing.append(key)
    if existing:
        response = s3.delete_objects(
            Bucket=BUCKET,
            Delete={"Objects": [{"Key": key} for key in existing], "Quiet": True},
        )
        if response.get("Errors"):
            raise RuntimeError("zero-byte bounded cleanup failed")
    assert_zero_empty(s3)
    print(f"Zero-byte compatibility cleanup removed {len(existing)} objects")


def cleanup(s3) -> None:
    key_id = required("COFFER_KMS_KEY_ID")
    uuid.UUID(key_id)
    candidates: set[str] = set()
    for repository in TEST_REPOSITORIES:
        prefix = f"{ROOT}{repository}/"
        repository_keys = keys_under(s3, prefix)
        candidates.update(repository_keys)
        candidates.update(linked_manifest_blob_keys(s3, repository_keys))
    for scenario in SCENARIOS:
        layout_path = f"/tmp/coffer-kms-oci-{scenario}"
        if os.path.isdir(layout_path):
            candidates.update(layout_blob_keys(layout_path))
    candidates.add(ZERO_BLOB)
    try:
        head = s3.head_object(Bucket=BUCKET, Key=DIRECT_OBJECT)
    except ClientError as error:
        if int(error.response["ResponseMetadata"]["HTTPStatusCode"]) != 404:
            raise
    else:
        candidates.add(DIRECT_OBJECT)

    existing: set[str] = set()
    for key in candidates:
        try:
            head = s3.head_object(Bucket=BUCKET, Key=key)
        except ClientError as error:
            if int(error.response["ResponseMetadata"]["HTTPStatusCode"]) == 404:
                continue
            raise
        if head.get("ServerSideEncryption") != "aws:kms":
            raise RuntimeError("refusing to remove a non-KMS object from test scope")
        if head.get("SSEKMSKeyId") != key_id:
            raise RuntimeError("refusing to remove an object under another KMS key")
        existing.add(key)
    bounded_prefixes = tuple(f"{ROOT}{repository}/" for repository in TEST_REPOSITORIES)
    uploads = multipart_uploads(s3)
    for upload in uploads:
        if upload["Key"].startswith(bounded_prefixes) or upload["Key"] in candidates:
            s3.abort_multipart_upload(
                Bucket=BUCKET, Key=upload["Key"], UploadId=upload["UploadId"]
            )
    remaining_uploads = multipart_uploads(s3)
    if remaining_uploads:
        raise RuntimeError("bucket retains an out-of-scope incomplete multipart upload")

    for offset in range(0, len(existing), 1000):
        batch = sorted(existing)[offset : offset + 1000]
        if not batch:
            continue
        response = s3.delete_objects(
            Bucket=BUCKET,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )
        if response.get("Errors"):
            raise RuntimeError("S3 rejected bounded KMS object cleanup")

    for repository in TEST_REPOSITORIES:
        if keys_under(s3, f"{ROOT}{repository}/"):
            raise RuntimeError("bounded KMS repository cleanup was incomplete")
    selected_remaining = 0
    for key in keys_under(s3, ""):
        head = s3.head_object(Bucket=BUCKET, Key=key)
        if head.get("SSEKMSKeyId") == key_id:
            selected_remaining += 1
    if selected_remaining:
        raise RuntimeError("selected KMS key still protects retained bucket objects")
    print(
        f"Bounded KMS cleanup removed {len(existing)} isolated objects; "
        "bucket-wide selected-key residue=0; multipart uploads=0"
    )


def main() -> int:
    if len(sys.argv) not in {2, 4}:
        raise SystemExit(
            "usage: guest-kms-scenario-storage.py MODE [REPOSITORY OCI_LAYOUT]"
        )
    s3 = client()
    if sys.argv[1] == "assert-empty" and len(sys.argv) == 4:
        assert_empty(s3, sys.argv[2], sys.argv[3])
        print("KMS scenario has zero repository and novel global blob objects")
    elif sys.argv[1] == "cleanup" and len(sys.argv) == 2:
        cleanup(s3)
    elif sys.argv[1] == "assert-zero-empty" and len(sys.argv) == 2:
        assert_zero_empty(s3)
        print("Zero-byte compatibility scope is empty")
    elif sys.argv[1] == "cleanup-zero" and len(sys.argv) == 2:
        cleanup_zero(s3)
    else:
        raise SystemExit("unsupported KMS scenario storage mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
