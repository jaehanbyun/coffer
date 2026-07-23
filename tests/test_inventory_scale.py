from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

from coffer.quota_import import parse_inventory_artifact


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "coffer_inventory_scale_measure",
    ROOT / "poc" / "inventory_scale" / "measure.py",
)
assert SPEC is not None and SPEC.loader is not None
SCALE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCALE
SPEC.loader.exec_module(SCALE)
ScaleProfile = SCALE.ScaleProfile
build_inventory_document = SCALE.build_inventory_document
measure_profile = SCALE.measure_profile


def test_scale_document_is_deterministic_and_has_exact_linear_facts() -> None:
    profile = ScaleProfile(
        name="test",
        project_count=2,
        repositories_per_project=2,
        manifests_per_repository=3,
    )

    first = build_inventory_document(profile)
    second = build_inventory_document(profile)
    parsed = parse_inventory_artifact(
        first.value,
        artifact_digest=first.artifact_digest,
    )

    assert first == second
    assert first.payload == second.payload
    assert len(first.authorities) == 4
    assert len({authority.repository_id for authority in first.authorities}) == 4
    assert parsed.summary.project_count == 2
    assert parsed.summary.repository_count == 4
    assert parsed.summary.manifest_count == 12
    assert parsed.summary.descriptor_count == 36
    assert parsed.summary.logical_bytes == sum(
        project.logical_bytes for project in parsed.projects
    )


def test_measurement_is_aggregate_only_and_removes_disposable_state(
    tmp_path: Path,
) -> None:
    profile = ScaleProfile(
        name="test",
        project_count=1,
        repositories_per_project=2,
        manifests_per_repository=2,
    )

    result = measure_profile(profile, temporary_parent=tmp_path)

    assert result["schema"] == "coffer.inventory-scale/v1"
    assert result["profile"] == {
        "descriptor_count": 12,
        "manifest_count": 4,
        "name": "test",
        "project_count": 1,
        "repository_count": 2,
    }
    assert result["result"] == {
        "live_status": "verified",
        "probe_count": 4,
        "sql_status": "verified",
    }
    phases = result["phases"]
    assert set(phases) == {
        "authority_prepare",
        "document_build",
        "inventory_parse",
        "ledger_import",
        "live_compare",
        "schema_migration",
        "sql_compare",
    }
    for measurement in phases.values():
        assert measurement["duration_seconds"] >= 0
        assert measurement["peak_traced_bytes"] >= 0
        assert measurement["sql_statement_count"] >= 0
    assert phases["ledger_import"]["sql_statement_count"] == 26
    assert phases["sql_compare"]["sql_statement_count"] == 11
    assert phases["live_compare"]["sql_statement_count"] == 11
    assert list(tmp_path.iterdir()) == []

    serialized = json.dumps(result, sort_keys=True)
    assert "sha256:" not in serialized
    assert re.search(
        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
        serialized,
    ) is None
