from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "gc-retention" / "filesystem" / "result.py"
TOPOLOGY = ROOT / "poc" / "gc-retention" / "topology.json"
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_gc_filesystem_result",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
result = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = result
SPEC.loader.exec_module(result)


def collector() -> dict[str, object]:
    return {
        "candidate_set_hash": f"sha256:{'1' * 64}",
        "candidate_total": 5,
        "distribution_revision": result.REVISION,
        "distribution_version": result.VERSION,
        "eligible_blob_count": 3,
        "eligible_link_count": 2,
        "eligible_manifest_count": 0,
        "marked_blob_count": 12,
        "normalized_output_hash": f"sha256:{'2' * 64}",
        "observed_mark_line_count": 15,
        "repository_count": 6,
        "schema": result.COLLECTOR_SCHEMA,
    }


def inputs() -> dict[str, object]:
    first = collector()
    binding = {
        "candidate_set_hash": first["candidate_set_hash"],
        "distribution_revision": result.REVISION,
        "distribution_version": result.VERSION,
        "normalized_output_hash": first["normalized_output_hash"],
    }
    authorization_id = "11111111-1111-4111-8111-111111111111"
    survivor_classes = sorted(
        json.loads(TOPOLOGY.read_text(encoding="utf-8"))["survivor_classes"]
    )
    return {
        "authorization": {
            "authorization_id": authorization_id,
            "binding": binding,
            "binding_hash": result._hash(binding),
            "consumed": True,
            "consumed_at": 11,
            "created_at": 10,
            "expires_at": 910,
            "schema": result.AUTHORIZATION_SCHEMA,
        },
        "collection": deepcopy(first),
        "consumption": {
            "authorization_id_hash": result._hash(authorization_id),
            "binding_hash": result._hash(binding),
            "consumed_at": 11,
            "schema": result.CONSUMPTION_SCHEMA,
        },
        "first": first,
        "reclaim": {
            "logical_bytes_after": 387,
            "logical_bytes_before": 1000,
            "logical_bytes_reclaimed": 613,
            "physical_backend": "filesystem",
            "schema": result.RECLAIM_SCHEMA,
            "tree_files_after": 5,
            "tree_files_before": 10,
            "tree_files_reclaimed": 5,
        },
        "restored_survivors": {
            "deleted_manifest_unreadable": True,
            "mode": "restored",
            "schema": result.SURVIVOR_SCHEMA,
            "shared_blob_repositories": 2,
            "survivor_classes": survivor_classes,
        },
        "second": deepcopy(first),
        "survivors": {
            "deleted_manifest_unreadable": True,
            "mode": "collected",
            "schema": result.SURVIVOR_SCHEMA,
            "shared_blob_repositories": 2,
            "survivor_classes": survivor_classes,
        },
        "topology": json.loads(TOPOLOGY.read_text(encoding="utf-8")),
    }


def test_compiles_and_finalizes_exact_specialist_evidence() -> None:
    candidate = result.compile_candidate(**inputs())
    final = result.finalize_candidate(candidate)

    assert candidate["schema"] == result.CANDIDATE_SCHEMA
    assert candidate["cleanup_verified"] is False
    assert final["schema"] == result.SCHEMA
    assert final["cleanup_verified"] is True
    assert final["residue"] == {
        "containers": 0,
        "networks": 0,
        "runtime_paths": 0,
        "total": 0,
    }
    assert result.validate_final_result(final) == final


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (("second", "candidate_total"), 4, "accepted"),
        (("collection", "eligible_manifest_count"), 1, "accepted"),
        (("authorization", "consumed"), False, "authorization"),
        (("survivors", "shared_blob_repositories"), 1, "incomplete"),
        (("reclaim", "logical_bytes_reclaimed"), 612, "reclaim"),
    ],
)
def test_rejects_incomplete_specialist_evidence(
    path: tuple[str, str],
    replacement: object,
    message: str,
) -> None:
    value = inputs()
    value[path[0]][path[1]] = replacement  # type: ignore[index]

    with pytest.raises(result.GCResultError, match=message):
        result.compile_candidate(**value)


def test_final_result_rejects_source_or_cleanup_self_attestation() -> None:
    final = result.finalize_candidate(result.compile_candidate(**inputs()))
    changed_source = deepcopy(final)
    changed_source["source"]["verify_harness_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(result.GCResultError, match="qualified"):
        result.validate_final_result(changed_source)

    changed_cleanup = deepcopy(final)
    changed_cleanup["residue"]["containers"] = 1
    with pytest.raises(result.GCResultError, match="qualified"):
        result.validate_final_result(changed_cleanup)


def test_private_writer_refuses_overwrite_and_unsafe_parent(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "result.json"
    value = result.finalize_candidate(result.compile_candidate(**inputs()))

    result._write_private(output.resolve(), value)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(result.GCResultError, match="already exists"):
        result._write_private(output.resolve(), value)
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    with pytest.raises(result.GCResultError, match="ownership"):
        result._write_private((unsafe / "result.json").resolve(), value)
