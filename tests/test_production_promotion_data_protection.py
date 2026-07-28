from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "data_protection.py"
MAINTENANCE_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_maintenance_identity.py"
)


def _load(name: str, path: Path) -> object:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


data = _load("coffer_test_production_promotion_data_protection", SOURCE)
maintenance_test = _load(
    "coffer_data_protection_maintenance_test_helpers",
    MAINTENANCE_TEST_SOURCE,
)

RELEASE_DIGEST = f"sha256:{'1' * 64}"
ARTIFACT_DIGEST = f"sha256:{'2' * 64}"
RGW_KMS_DIGEST = f"sha256:{'3' * 64}"
MAINTENANCE_DIGEST = f"sha256:{'4' * 64}"


def maintenance_result(
    *,
    release_digest: str = RELEASE_DIGEST,
    artifact_digest: str = ARTIFACT_DIGEST,
    rgw_digest: str = RGW_KMS_DIGEST,
) -> dict[str, object]:
    inputs = maintenance_test.compile_inputs()
    inputs["release_digest"] = release_digest
    inputs["release_readiness"] = maintenance_test.release()
    inputs["artifact_digest"] = artifact_digest
    inputs["artifact_result"] = maintenance_test.artifact_result(
        release_digest
    )
    inputs["rgw_kms_digest"] = rgw_digest
    inputs["rgw_kms_result"] = maintenance_test.rgw_kms_result(
        release_digest
    )
    inputs["evidence"] = maintenance_test.evidence(
        release_digest=release_digest,
        artifact_digest=artifact_digest,
        rgw_digest=rgw_digest,
    )
    return maintenance_test.maintenance.compile_result(**inputs)


def prerequisites(
    *,
    release_digest: str = RELEASE_DIGEST,
    artifact_digest: str = ARTIFACT_DIGEST,
    rgw_digest: str = RGW_KMS_DIGEST,
    maintenance_digest: str = MAINTENANCE_DIGEST,
) -> dict[str, str]:
    return {
        "artifact_result_sha256": artifact_digest,
        "maintenance_identity_result_sha256": maintenance_digest,
        "release_readiness_sha256": release_digest,
        "rgw_kms_result_sha256": rgw_digest,
    }


def evidence(
    *,
    prerequisite_values: dict[str, str] | None = None,
) -> dict[str, object]:
    topology = data.STATE_MACHINE.load_topology(data.TOPOLOGY_SOURCE)
    return {
        "backup_restore": {
            "delete_marker_count": 1,
            "isolated_restore": True,
            "multipart_upload_count": 0,
            "object_count": 4,
            "rgw_inventory_equal": True,
            "rgw_restored": True,
            "sql_restored": True,
            "sql_row_count": 12,
            "sse_kms": True,
            "version_count": 7,
        },
        "cutover": {
            "dependency_503": True,
            "direct_registry_closed": True,
            "existing_pull": True,
            "new_push_accounted": True,
            "over_quota_429": True,
            "project_isolation": True,
            "quota_edge_forced": True,
            "reconciliation": True,
            "restart_persistence": True,
        },
        "evidence_sha256": {
            name: f"sha256:{digit * 64}"
            for name, digit in zip(
                (
                    "backup_restore_sha256",
                    "cutover_sha256",
                    "failure_matrix_sha256",
                    "inventory_import_sha256",
                    "lifecycle_sha256",
                    "rollback_recovery_sha256",
                    "teardown_sha256",
                    "unrelated_state_sha256",
                    "writer_exclusion_sha256",
                ),
                ("5", "6", "7", "8", "9", "a", "b", "c", "d"),
                strict=True,
            )
        },
        "execution": {
            "adapter": "openstack",
            "disposable": True,
            "non_synthetic": True,
            "phase_count": len(data.STATE_MACHINE.EXPECTED_PHASES),
        },
        "failure_matrix": {
            name: True
            for name in data.STATE_MACHINE.EXPECTED_FAILURE_CASES
        },
        "inventory_import": {
            "conflicting_replay_refused": True,
            "descriptor_count": 8,
            "idempotent_replay": True,
            "imported": True,
            "inventory_schema": data.INVENTORY_SCHEMA,
            "live_comparison_verified": True,
            "manifest_count": 4,
            "partial_rows": 0,
            "private_tls_verified": True,
            "pull_only": True,
            "repository_count": 2,
            "scans_equal": True,
            "session_closed": True,
        },
        "lifecycle": {
            "invocation_id": "01k0a1b2c3d4e5f6g7h8j9k0mn",
            "phase": "torn-down",
            "phase_evidence_sha256": f"sha256:{'e' * 64}",
            "resource_counts": {
                name: 0
                for name in data.STATE_MACHINE.EXPECTED_CLEANUP_ORDER
            },
            "resource_id_hashes": [],
            "schema": data.STATE_MACHINE.EVIDENCE_SCHEMA,
            "target_signature": "f" * 64,
            "topology_digest": topology.digest,
            "unrelated_signature": f"sha256:{'0' * 64}",
        },
        "prerequisites": prerequisite_values or prerequisites(),
        "residue": {
            **{
                name: 0
                for name in data.STATE_MACHINE.EXPECTED_RESIDUE_KEYS
            },
            "known_secret_matches": 0,
            "total": 0,
        },
        "rollback_recovery": {
            "active_uploads": 0,
            "admission_checks": True,
            "ambiguous_differences": 0,
            "authenticated_comparison": True,
            "backup_recovery": True,
            "original_digest_readable": True,
            "post_cutover_write_count": 3,
            "pull_digest_match": True,
            "removed_post_cutover_write_count": 3,
            "writer_fence_reapplied": True,
        },
        "schema": data.EVIDENCE_SCHEMA,
        "source": data.runtime_source_hashes(),
        "unrelated_state": {
            "after_sha256": f"sha256:{'0' * 64}",
            "before_sha256": f"sha256:{'0' * 64}",
            "unchanged": True,
        },
        "writer_exclusion": {
            "active_uploads": 0,
            "canary_write_status": 405,
            "digest_read_status": 200,
            "source_stable": True,
            "unknown_listeners": 0,
            "writers_disabled": True,
        },
    }


def compile_inputs() -> dict[str, object]:
    return {
        "artifact_digest": ARTIFACT_DIGEST,
        "artifact_result": maintenance_test.artifact_result(RELEASE_DIGEST),
        "evidence": evidence(),
        "evidence_digest": f"sha256:{'a' * 64}",
        "maintenance_digest": MAINTENANCE_DIGEST,
        "maintenance_result": maintenance_result(),
        "release_digest": RELEASE_DIGEST,
        "release_readiness": maintenance_test.release(),
        "rgw_kms_digest": RGW_KMS_DIGEST,
        "rgw_kms_result": maintenance_test.rgw_kms_result(RELEASE_DIGEST),
    }


def _write_private(path: Path, value: object) -> bytes:
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def test_compiles_complete_non_synthetic_data_protection_transaction() -> None:
    result = data.compile_result(**compile_inputs())

    assert result["schema"] == data.SCHEMA
    assert result["production_candidate"] is True
    assert result["execution"]["adapter"] == "openstack"
    assert result["lifecycle"]["terminal_phase"] == "torn-down"
    assert result["inventory_import"]["inventory_schema"] == "coffer.inventory/v3"
    assert data.validate_final_result(result) == result
    retained = json.dumps(result, sort_keys=True)
    assert "01k0a1b2c3d4e5f6g7h8j9k0mn" not in retained
    assert '"target_signature"' not in retained
    assert '"resource_id_hashes"' not in retained


def test_release_and_prior_specialist_prerequisites_fail_closed() -> None:
    blocked = compile_inputs()
    blocked["release_readiness"] = maintenance_test.release(False)
    blocked["evidence"] = {}
    with pytest.raises(
        data.DataProtectionInputsBlocked,
        match="not candidate-qualified",
    ):
        data.compile_result(**blocked)

    changed_maintenance = compile_inputs()
    changed_maintenance["maintenance_result"]["residue"]["credentials"] = 1
    changed_maintenance["maintenance_result"]["residue"]["total"] = 1
    with pytest.raises(
        data.DataProtectionInputsBlocked,
        match="maintenance identity",
    ):
        data.compile_result(**changed_maintenance)

    changed_binding = compile_inputs()
    changed_binding["maintenance_result"]["prerequisites"][
        "rgw_kms_result_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        data.DataProtectionInputsBlocked,
        match="prerequisite binding",
    ):
        data.compile_result(**changed_binding)


def test_fixture_or_retained_lifecycle_is_refused() -> None:
    fixture = compile_inputs()
    fixture["evidence"]["execution"]["adapter"] = "fixture"
    fixture["evidence"]["execution"]["non_synthetic"] = False
    with pytest.raises(
        data.DataProtectionResultError,
        match="complete disposable run",
    ):
        data.compile_result(**fixture)

    retained = compile_inputs()
    retained["evidence"]["lifecycle"]["resource_counts"]["database"] = 1
    with pytest.raises(
        data.DataProtectionResultError,
        match="resources remain",
    ):
        data.compile_result(**retained)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        (
            "writer_exclusion",
            "writers_disabled",
            False,
            "writers were not exactly excluded",
        ),
        (
            "backup_restore",
            "multipart_upload_count",
            1,
            "backup and isolated restore",
        ),
        (
            "inventory_import",
            "inventory_schema",
            "coffer.inventory/v2",
            "inventory/import/live comparison",
        ),
        ("cutover", "quota_edge_forced", False, "admission cutover"),
        (
            "rollback_recovery",
            "removed_post_cutover_write_count",
            2,
            "rollback and recovery",
        ),
        (
            "failure_matrix",
            "kms-wrong-key",
            False,
            "failure matrix",
        ),
        ("residue", "credentials", 1, "residue remains"),
    ],
)
def test_transaction_sections_fail_closed(
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    inputs = compile_inputs()
    inputs["evidence"][section][field] = value
    if section == "residue":
        inputs["evidence"]["residue"]["total"] = 1
    with pytest.raises(data.DataProtectionResultError, match=message):
        data.compile_result(**inputs)


def test_unrelated_state_and_evidence_bindings_fail_closed() -> None:
    changed_unrelated = compile_inputs()
    changed_unrelated["evidence"]["unrelated_state"]["after_sha256"] = (
        f"sha256:{'9' * 64}"
    )
    with pytest.raises(
        data.DataProtectionResultError,
        match="unrelated state changed",
    ):
        data.compile_result(**changed_unrelated)

    changed_prerequisite = compile_inputs()
    changed_prerequisite["evidence"]["prerequisites"][
        "maintenance_identity_result_sha256"
    ] = f"sha256:{'9' * 64}"
    with pytest.raises(
        data.DataProtectionResultError,
        match="binding",
    ):
        data.compile_result(**changed_prerequisite)

    changed_source = compile_inputs()
    changed_source["evidence"]["source"]["inventory_sha256"] = (
        f"sha256:{'9' * 64}"
    )
    with pytest.raises(
        data.DataProtectionResultError,
        match="binding",
    ):
        data.compile_result(**changed_source)


def test_cli_blocks_before_missing_downstream_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    output = directory / "result.json"
    _write_private(release_path, maintenance_test.release(False))

    result = data.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(directory / "missing-artifact.json"),
            "--rgw-kms-result",
            str(directory / "missing-rgw.json"),
            "--maintenance-identity-result",
            str(directory / "missing-maintenance.json"),
            "--evidence",
            str(directory / "missing-evidence.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert "not candidate-qualified" in capsys.readouterr().err


def test_cli_writes_owner_only_result(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    artifact_path = directory / "artifact.json"
    rgw_path = directory / "rgw.json"
    maintenance_path = directory / "maintenance.json"
    evidence_path = directory / "evidence.json"
    output = directory / "result.json"

    release_payload = _write_private(
        release_path,
        maintenance_test.release(),
    )
    release_digest = data._sha256_bytes(release_payload)
    artifact_payload = _write_private(
        artifact_path,
        maintenance_test.artifact_result(release_digest),
    )
    artifact_digest = data._sha256_bytes(artifact_payload)
    rgw_payload = _write_private(
        rgw_path,
        maintenance_test.rgw_kms_result(release_digest),
    )
    rgw_digest = data._sha256_bytes(rgw_payload)
    compiled_maintenance = maintenance_result(
        release_digest=release_digest,
        artifact_digest=artifact_digest,
        rgw_digest=rgw_digest,
    )
    maintenance_payload = _write_private(
        maintenance_path,
        compiled_maintenance,
    )
    maintenance_digest = data._sha256_bytes(maintenance_payload)
    _write_private(
        evidence_path,
        evidence(
            prerequisite_values=prerequisites(
                release_digest=release_digest,
                artifact_digest=artifact_digest,
                rgw_digest=rgw_digest,
                maintenance_digest=maintenance_digest,
            )
        ),
    )

    result = data.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(artifact_path),
            "--rgw-kms-result",
            str(rgw_path),
            "--maintenance-identity-result",
            str(maintenance_path),
            "--evidence",
            str(evidence_path),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert data.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True


def test_final_result_rejects_source_or_zero_residue_tamper() -> None:
    result = data.compile_result(**compile_inputs())
    changed_source = deepcopy(result)
    changed_source["source"]["quota_sha256"] = f"sha256:{'9' * 64}"
    with pytest.raises(
        data.DataProtectionResultError,
        match="not qualified",
    ):
        data.validate_final_result(changed_source)

    changed_residue = deepcopy(result)
    changed_residue["residue"]["credentials"] = 1
    changed_residue["residue"]["total"] = 1
    with pytest.raises(
        data.DataProtectionResultError,
        match="residue",
    ):
        data.validate_final_result(changed_residue)
