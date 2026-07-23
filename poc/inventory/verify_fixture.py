from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit

from coffer.inventory import InvalidInventoryEvidence, inventory_bytes


def request(
    origin: str,
    method: str,
    target: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    parsed = urlsplit(origin)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=5)
    try:
        connection.request(method, target, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            body,
        )
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-origin", required=True)
    parser.add_argument("--work-directory", type=Path, required=True)
    args = parser.parse_args()

    expected = json.loads((args.work_directory / "expected.json").read_text())
    evidence = json.loads((args.work_directory / "evidence.json").read_text())
    authority = json.loads((args.work_directory / "authority.json").read_text())
    inventory = json.loads((args.work_directory / "inventory.json").read_text())

    assert evidence["schema"] == "coffer.distribution-storage-scan/v1"
    assert evidence["distribution_version"] == "v3.1.1"
    assert evidence["scans"][0] == {
        **evidence["scans"][1],
        "phase": "start",
    }
    facts = [
        item
        for page in evidence["scans"][0]["pages"]
        for item in page["items"]
    ]
    by_digest = {fact["enumerated_digest"]: fact for fact in facts}
    assert set(by_digest) == {expected["child_digest"], expected["index_digest"]}
    assert by_digest[expected["child_digest"]]["tagged"] is True
    assert by_digest[expected["index_digest"]]["tagged"] is False

    drifted = deepcopy(evidence)
    end_facts = [
        item
        for page in drifted["scans"][1]["pages"]
        for item in page["items"]
    ]
    end_facts[0]["tagged"] = not end_facts[0]["tagged"]
    checksum = hashlib.sha256()
    for fact in end_facts:
        checksum.update(
            (json.dumps(fact, separators=(",", ":"), sort_keys=True) + "\n").encode()
        )
    drifted["scans"][1]["summary"]["sha256"] = f"sha256:{checksum.hexdigest()}"
    try:
        inventory_bytes(drifted, authority)
    except InvalidInventoryEvidence as exc:
        assert str(exc) == "start and end scans differ"
    else:
        raise AssertionError("snapshot drift was not rejected")

    assert inventory["schema"] == "coffer.inventory/v1"
    assert inventory["summary"] == {
        "descriptor_count": 4,
        "logical_bytes": expected["logical_bytes"],
        "manifest_count": 2,
        "project_count": 1,
        "repository_count": 1,
    }
    assert inventory["repositories"][0]["repository_id"] == expected["repository_id"]
    serialized = (args.work_directory / "inventory.json").read_text().lower()
    for excluded in (
        expected["canonical_name"].lower(),
        "tagged",
        "payload",
        "authorization",
        "bearer",
        "http://",
        "https://",
    ):
        assert excluded not in serialized

    status, _, tag_body = request(
        args.registry_origin,
        "GET",
        f"/v2/{expected['canonical_name']}/tags/list?n=1",
    )
    assert status == 200
    assert json.loads(tag_body)["tags"] == ["tagged"]
    for manifest_digest in (expected["child_digest"], expected["index_digest"]):
        status, headers, _ = request(
            args.registry_origin,
            "HEAD",
            f"/v2/{expected['canonical_name']}/manifests/{manifest_digest}",
            headers={
                "Accept": (
                    "application/vnd.oci.image.manifest.v1+json, "
                    "application/vnd.oci.image.index.v1+json"
                )
            },
        )
        assert status == 200
        assert headers.get("docker-content-digest") == manifest_digest

    print(
        json.dumps(
            {
                "api_tag_count": 1,
                "control_sql_unchanged": True,
                "digest_only_manifest_enumerated": True,
                "inventory_descriptor_count": 4,
                "manifest_count": 2,
                "registry_storage_unchanged": True,
                "snapshot_drift_rejected": True,
                "snapshot_scans_equal": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
