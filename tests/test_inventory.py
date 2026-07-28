from __future__ import annotations

import hashlib
import json
import stat
from copy import deepcopy
from pathlib import Path

import pytest

from coffer.inventory import (
    AUTHORITY_SCHEMA,
    EVIDENCE_SCHEMA,
    MULTI_MEDIA_INVENTORY_SCHEMA,
    PINNED_DISTRIBUTION_REVISION,
    PINNED_DISTRIBUTION_VERSION,
    PINNED_ENUMERATOR,
    S3_EVIDENCE_SCHEMA,
    S3_INVENTORY_SCHEMA,
    InvalidInventoryEvidence,
    build_inventory,
    inventory_bytes,
    main,
)
from coffer.quota import (
    DOCKER_IMAGE_MANIFEST,
    OCI_IMAGE_INDEX,
    OCI_IMAGE_MANIFEST,
)

PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REPOSITORY = f"p/{PROJECT_ID}/inventory"
CHILD_DIGEST = f"sha256:{'1' * 64}"
INDEX_DIGEST = f"sha256:{'2' * 64}"
CONFIG_DIGEST = f"sha256:{'3' * 64}"
LAYER_DIGEST = f"sha256:{'4' * 64}"


def reference(digest: str, size: int, media_type: str) -> dict[str, object]:
    return {"digest": digest, "media_type": media_type, "size": size}


def records() -> list[dict[str, object]]:
    return [
        {
            "content_digest": CHILD_DIGEST,
            "enumerated_digest": CHILD_DIGEST,
            "media_type": OCI_IMAGE_MANIFEST,
            "references": [
                reference(
                    CONFIG_DIGEST,
                    17,
                    "application/vnd.oci.image.config.v1+json",
                ),
                reference(
                    LAYER_DIGEST,
                    23,
                    "application/vnd.oci.image.layer.v1.tar+gzip",
                ),
            ],
            "repository": REPOSITORY,
            "size": 101,
            "tagged": True,
        },
        {
            "content_digest": INDEX_DIGEST,
            "enumerated_digest": INDEX_DIGEST,
            "media_type": OCI_IMAGE_INDEX,
            "references": [reference(CHILD_DIGEST, 101, OCI_IMAGE_MANIFEST)],
            "repository": REPOSITORY,
            "size": 79,
            "tagged": False,
        },
    ]


def record_hash(values: list[dict[str, object]]) -> str:
    checksum = hashlib.sha256()
    for value in values:
        checksum.update(
            (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()
        )
    return f"sha256:{checksum.hexdigest()}"


def repository_hash(values: list[str]) -> str:
    checksum = hashlib.sha256()
    for value in values:
        checksum.update(f"{value}\n".encode())
    return f"sha256:{checksum.hexdigest()}"


def scan(
    phase: str,
    values: list[dict[str, object]],
    *,
    repositories: list[str] | None = None,
) -> dict[str, object]:
    repository_values = [REPOSITORY] if repositories is None else repositories
    pages = []
    for sequence, offset in enumerate(range(0, len(values), 1)):
        item = values[offset : offset + 1]
        pages.append(
            {
                "after": None if sequence == 0 else _key(values[offset - 1]),
                "items": item,
                "next": _key(item[-1]) if offset + 1 < len(values) else None,
                "sequence": sequence,
            }
        )
    return {
        "pages": pages,
        "phase": phase,
        "repositories": repository_values,
        "summary": {
            "page_count": len(pages),
            "record_count": len(values),
            "repository_count": len(repository_values),
            "repository_sha256": repository_hash(repository_values),
            "sha256": record_hash(values),
        },
    }


def _key(value: dict[str, object]) -> str:
    return f"{value['repository']}@{value['enumerated_digest']}"


def evidence() -> dict[str, object]:
    values = records()
    return {
        "distribution_version": PINNED_DISTRIBUTION_VERSION,
        "enumerator": PINNED_ENUMERATOR,
        "page_size": 1,
        "scans": [scan("start", values), scan("end", deepcopy(values))],
        "schema": EVIDENCE_SCHEMA,
    }


def s3_backend() -> dict[str, object]:
    return {
        "bucket_sha256": f"sha256:{'1' * 64}",
        "config_sha256": f"sha256:{'2' * 64}",
        "distribution_revision": PINNED_DISTRIBUTION_REVISION,
        "endpoint_sha256": f"sha256:{'3' * 64}",
        "helper_sha256": f"sha256:{'4' * 64}",
        "module_graph_sha256": f"sha256:{'5' * 64}",
        "root_sha256": f"sha256:{'6' * 64}",
        "storage_type": "s3",
        "type": "s3",
    }


def s3_evidence() -> dict[str, object]:
    value = evidence()
    value["schema"] = S3_EVIDENCE_SCHEMA
    value["backend"] = s3_backend()
    return value


def authority() -> dict[str, object]:
    return {
        "repositories": [
            {"id": REPOSITORY_ID, "name": "inventory", "project_id": PROJECT_ID}
        ],
        "schema": AUTHORITY_SCHEMA,
    }


def resign_scan(value: dict[str, object], scan_index: int) -> None:
    target = value["scans"][scan_index]  # type: ignore[index]
    values = [
        item
        for page in target["pages"]  # type: ignore[index]
        for item in page["items"]
    ]
    target["summary"]["record_count"] = len(values)  # type: ignore[index]
    target["summary"]["sha256"] = record_hash(values)  # type: ignore[index]


def test_builds_deterministic_secret_free_inventory() -> None:
    first = build_inventory(evidence(), authority())
    second = build_inventory(deepcopy(evidence()), deepcopy(authority()))

    assert first == second
    assert first["summary"] == {
        "descriptor_count": 4,
        "logical_bytes": 220,
        "manifest_count": 2,
        "project_count": 1,
        "repository_count": 1,
    }
    repository = first["repositories"][0]
    assert repository["repository_id"] == REPOSITORY_ID
    assert [item["digest"] for item in repository["manifests"]] == [
        CHILD_DIGEST,
        INDEX_DIGEST,
    ]
    serialized = inventory_bytes(evidence(), authority()).decode()
    assert serialized == inventory_bytes(evidence(), authority()).decode()
    for excluded in (REPOSITORY, "inventory\"", "tagged", "payload", "token", "url"):
        assert excluded not in serialized.lower()


def test_s3_evidence_preserves_exact_hashed_provenance() -> None:
    inventory = build_inventory(s3_evidence(), authority())

    assert inventory["schema"] == S3_INVENTORY_SCHEMA
    assert inventory["source"] == {
        "backend": s3_backend(),
        "distribution_version": PINNED_DISTRIBUTION_VERSION,
        "enumerator": PINNED_ENUMERATOR,
        "snapshot_scans": 2,
    }
    serialized = inventory_bytes(s3_evidence(), authority()).decode()
    assert PINNED_DISTRIBUTION_REVISION in serialized
    for excluded in (
        REPOSITORY,
        "COFFERFIXTUREACCESS",
        "coffer-fixture-secret-material",
        "rgw.example.invalid",
    ):
        assert excluded not in serialized


def test_s3_inventory_preserves_blob_media_type_aliases() -> None:
    alias_digest = f"sha256:{'5' * 64}"
    alias = {
        "content_digest": alias_digest,
        "enumerated_digest": alias_digest,
        "media_type": DOCKER_IMAGE_MANIFEST,
        "references": [
            reference(
                CONFIG_DIGEST,
                17,
                "application/vnd.docker.container.image.v1+json",
            ),
            reference(
                LAYER_DIGEST,
                23,
                "application/vnd.docker.image.rootfs.diff.tar.gzip",
            ),
        ],
        "repository": REPOSITORY,
        "size": 83,
        "tagged": True,
    }
    values = [*records(), alias]
    value = {
        "backend": s3_backend(),
        "distribution_version": PINNED_DISTRIBUTION_VERSION,
        "enumerator": PINNED_ENUMERATOR,
        "page_size": 1,
        "scans": [scan("start", values), scan("end", deepcopy(values))],
        "schema": S3_EVIDENCE_SCHEMA,
    }

    inventory = build_inventory(value, authority())

    assert inventory["schema"] == MULTI_MEDIA_INVENTORY_SCHEMA
    descriptors = {
        item["digest"]: item
        for item in inventory["projects"][0]["descriptors"]
    }
    assert descriptors[CONFIG_DIGEST] == {
        "digest": CONFIG_DIGEST,
        "media_types": [
            "application/vnd.docker.container.image.v1+json",
            "application/vnd.oci.image.config.v1+json",
        ],
        "size": 17,
    }
    assert descriptors[LAYER_DIGEST] == {
        "digest": LAYER_DIGEST,
        "media_types": [
            "application/vnd.docker.image.rootfs.diff.tar.gzip",
            "application/vnd.oci.image.layer.v1.tar+gzip",
        ],
        "size": 23,
    }


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("type", "filesystem", "backend type"),
        ("storage_type", "filesystem", "storage type"),
        ("distribution_revision", "a" * 40, "revision is not pinned"),
        ("helper_sha256", "not-a-digest", "canonical sha256"),
    ],
)
def test_s3_evidence_rejects_unpinned_or_malformed_provenance(
    field: str,
    replacement: object,
    message: str,
) -> None:
    value = s3_evidence()
    value["backend"][field] = replacement  # type: ignore[index]

    with pytest.raises(InvalidInventoryEvidence, match=message):
        build_inventory(value, authority())


def test_s3_evidence_rejects_unknown_backend_fields() -> None:
    value = s3_evidence()
    value["backend"]["secret_uuid"] = "not-retained"  # type: ignore[index]

    with pytest.raises(InvalidInventoryEvidence, match="fields are invalid"):
        build_inventory(value, authority())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["scans"][0]["pages"][1].update(sequence=3), "sequence"),
        (lambda value: value["scans"][0]["pages"][1].update(after=None), "after"),
        (lambda value: value["scans"][0]["pages"][0].update(next=None), "next"),
        (
            lambda value: value["scans"][0]["summary"].update(record_count=9),
            "record count",
        ),
        (
            lambda value: value["scans"][0]["summary"].update(
                sha256=f"sha256:{'0' * 64}"
            ),
            "summary hash",
        ),
    ],
)
def test_rejects_page_and_summary_anomalies(mutation: object, message: str) -> None:
    value = evidence()
    mutation(value)  # type: ignore[operator]
    with pytest.raises(InvalidInventoryEvidence, match=message):
        build_inventory(value, authority())


def test_rejects_snapshot_drift_including_untagged_state() -> None:
    value = evidence()
    value["scans"][1]["pages"][1]["items"][0]["tagged"] = True  # type: ignore[index]
    resign_scan(value, 1)
    with pytest.raises(InvalidInventoryEvidence, match="start and end scans differ"):
        build_inventory(value, authority())


def test_rejects_backend_without_exact_control_authority() -> None:
    missing = authority()
    missing["repositories"] = []
    with pytest.raises(InvalidInventoryEvidence, match="no exact Coffer authority"):
        build_inventory(evidence(), missing)

    duplicate = authority()
    duplicate["repositories"].append(  # type: ignore[union-attr]
        deepcopy(duplicate["repositories"][0])  # type: ignore[index]
    )
    with pytest.raises(InvalidInventoryEvidence, match="duplicate repository"):
        build_inventory(evidence(), duplicate)


def test_rejects_empty_backend_repository_without_control_authority() -> None:
    orphan = f"p/{PROJECT_ID}/orphan"
    values = records()
    value = {
        "distribution_version": PINNED_DISTRIBUTION_VERSION,
        "enumerator": PINNED_ENUMERATOR,
        "page_size": 1,
        "scans": [
            scan("start", values, repositories=[REPOSITORY, orphan]),
            scan("end", deepcopy(values), repositories=[REPOSITORY, orphan]),
        ],
        "schema": EVIDENCE_SCHEMA,
    }
    with pytest.raises(InvalidInventoryEvidence, match="no exact Coffer authority"):
        build_inventory(value, authority())


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("content_digest", f"sha256:{'9' * 64}", "payload digest"),
        ("media_type", "application/unsupported", "not supported"),
        ("size", 0, "integer range"),
    ],
)
def test_rejects_invalid_manifest_facts(
    field: str, replacement: object, message: str
) -> None:
    value = evidence()
    for scan_value in value["scans"]:  # type: ignore[union-attr]
        scan_value["pages"][0]["items"][0][field] = replacement
        resign_scan(value, 0 if scan_value["phase"] == "start" else 1)
    with pytest.raises(InvalidInventoryEvidence, match=message):
        build_inventory(value, authority())


def test_rejects_missing_or_mismatched_index_children() -> None:
    value = evidence()
    for scan_value in value["scans"]:  # type: ignore[union-attr]
        child = scan_value["pages"][1]["items"][0]["references"][0]
        child["size"] = 102
    resign_scan(value, 0)
    resign_scan(value, 1)
    with pytest.raises(InvalidInventoryEvidence, match="facts do not match"):
        build_inventory(value, authority())


def test_rejects_cross_manifest_descriptor_conflict() -> None:
    conflicting = {
        "content_digest": f"sha256:{'5' * 64}",
        "enumerated_digest": f"sha256:{'5' * 64}",
        "media_type": OCI_IMAGE_MANIFEST,
        "references": [
            reference(
                CONFIG_DIGEST,
                18,
                "application/vnd.oci.image.config.v1+json",
            )
        ],
        "repository": REPOSITORY,
        "size": 67,
        "tagged": False,
    }
    values = [*records(), conflicting]
    value = {
        "distribution_version": PINNED_DISTRIBUTION_VERSION,
        "enumerator": PINNED_ENUMERATOR,
        "page_size": 1,
        "scans": [scan("start", values), scan("end", deepcopy(values))],
        "schema": EVIDENCE_SCHEMA,
    }
    with pytest.raises(InvalidInventoryEvidence, match="conflicting facts"):
        build_inventory(value, authority())


def test_rejects_project_logical_sum_outside_sql_bound() -> None:
    overflowing = records()[0]
    overflowing["references"][0]["size"] = 2**63 - 1  # type: ignore[index]
    values = [overflowing]
    value = {
        "distribution_version": PINNED_DISTRIBUTION_VERSION,
        "enumerator": PINNED_ENUMERATOR,
        "page_size": 1,
        "scans": [scan("start", values), scan("end", deepcopy(values))],
        "schema": EVIDENCE_SCHEMA,
    }
    with pytest.raises(InvalidInventoryEvidence, match="logical bytes exceed"):
        build_inventory(value, authority())


def test_rejects_unknown_fields_instead_of_retaining_secret_material() -> None:
    value = evidence()
    value["bearer_token"] = "not-retained"
    with pytest.raises(InvalidInventoryEvidence, match="fields are invalid"):
        build_inventory(value, authority())


def test_cli_creates_output_once_and_fails_closed(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    authority_path = tmp_path / "authority.json"
    output_path = tmp_path / "inventory.json"
    evidence_path.write_text(json.dumps(evidence()))
    authority_path.write_text(json.dumps(authority()))

    arguments = [
        "--evidence",
        str(evidence_path),
        "--authority",
        str(authority_path),
        "--output",
        str(output_path),
    ]
    assert main(arguments) == 0
    original = output_path.read_bytes()
    assert json.loads(original)["schema"] == "coffer.inventory/v1"
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert main(arguments) == 1
    assert output_path.read_bytes() == original
    assert not list(tmp_path.glob(".inventory.json.*.tmp"))
