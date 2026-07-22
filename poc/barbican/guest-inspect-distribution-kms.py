#!/usr/bin/env python3
"""Inspect newly written Distribution S3 objects for the selected KMS key."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

import boto3
from botocore.client import Config


ENDPOINT = "https://192.168.122.200:8443"
CA_PATH = "/etc/ceph/coffer-rgw-root-ca.crt"
BUCKET = "coffer-registry-poc"
REPOSITORY_ROOT = "distribution/docker/registry/v2/repositories/"
BLOB_ROOT = "distribution/docker/registry/v2/blobs/"


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def layout_blob_keys(layout_path: str, published_digest: str) -> list[str]:
    if not layout_path.startswith("/tmp/coffer-kms-oci-"):
        raise RuntimeError("OCI layout is outside the bounded scenario set")
    with open(os.path.join(layout_path, "index.json"), encoding="utf-8") as source:
        index = json.load(source)
    manifests = index.get("manifests", [])
    if len(manifests) != 1:
        raise RuntimeError("expected exactly one OCI manifest descriptor")
    manifest_digest = manifests[0]["digest"]
    algorithm, manifest_value = manifest_digest.split(":", 1)
    with open(
        os.path.join(layout_path, "blobs", algorithm, manifest_value),
        encoding="utf-8",
    ) as source:
        manifest = json.load(source)
    published = dict(manifests[0])
    published["digest"] = published_digest
    descriptors = [published, manifest["config"], *manifest["layers"]]
    if len(descriptors) != 3:
        raise RuntimeError("expected one manifest, one config, and one layer")
    keys = []
    for item in descriptors:
        algorithm, value = item["digest"].split(":", 1)
        if algorithm != "sha256" or len(value) != 64:
            raise RuntimeError("unexpected OCI descriptor digest")
        keys.append(f"{BLOB_ROOT}{algorithm}/{value[:2]}/{value}/data")
    return keys


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: guest-inspect-distribution-kms.py "
            "START_EPOCH REPOSITORY OCI_LAYOUT PUBLISHED_DIGEST"
        )
    start = datetime.fromtimestamp(float(sys.argv[1]) - 2.0, tz=timezone.utc)
    repository = sys.argv[2]
    if not repository.startswith("p/") or not repository.replace("-", "").replace(
        "/", ""
    ).isalnum():
        raise RuntimeError("invalid bounded repository path")
    prefix = f"{REPOSITORY_ROOT}{repository}/"
    blob_keys = layout_blob_keys(sys.argv[3], sys.argv[4])
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
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
    current = [
        item
        for page in pages
        for item in page.get("Contents", [])
        if item["LastModified"] >= start
    ]
    if not current:
        raise RuntimeError("no new Distribution repository objects were observed")
    encrypted = 0
    checked = [("repository", item["Key"]) for item in current]
    checked.extend(zip(("manifest", "config", "layer"), blob_keys, strict=True))
    for object_role, object_key in checked:
        try:
            head = s3.head_object(Bucket=BUCKET, Key=object_key)
        except Exception as error:
            response = getattr(error, "response", {})
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise RuntimeError(
                    f"expected novel global {object_role} blob is absent"
                ) from None
            raise
        if head["LastModified"] < start:
            raise RuntimeError("expected a novel Distribution object")
        if head.get("ServerSideEncryption") != "aws:kms":
            raise RuntimeError("a new Distribution object lacks aws:kms metadata")
        if head.get("SSEKMSKeyId") != key_id:
            raise RuntimeError("a new Distribution object does not use the selected key")
        encrypted += 1
    print(
        json.dumps(
            {
                "bucket": BUCKET,
                "encrypted_new_objects": encrypted,
                "global_payload_blobs": len(blob_keys),
                "key_id_matches": True,
                "repository_objects": len(current),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
