from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "poc"
    / "production-promotion"
    / "maintenance_identity.py"
)
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_maintenance_identity",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
maintenance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = maintenance
SPEC.loader.exec_module(maintenance)

RELEASE_DIGEST = f"sha256:{'1' * 64}"
ARTIFACT_DIGEST = f"sha256:{'2' * 64}"
RGW_KMS_DIGEST = f"sha256:{'3' * 64}"


def release(qualified: bool = True) -> dict[str, object]:
    status = "candidate-qualified" if qualified else "blocked"
    reasons = [] if qualified else ["not qualified"]
    return {
        "blockers": (
            []
            if qualified
            else [
                f"{name}: not qualified"
                for name in ("distribution", "ceph", "oslo_messaging")
            ]
        ),
        "components": {
            "distribution": {
                "reasons": list(reasons),
                "revision": "a" * 40,
                "status": status,
                "version": "v3.2.0",
            },
            "ceph": {
                "reasons": list(reasons),
                "revision": "b" * 40,
                "status": status,
                "version": "v20.2.3",
            },
            "oslo_messaging": {
                "reasons": list(reasons),
                "revision": "c" * 40,
                "status": status,
                "version": "17.3.1",
            },
        },
        "next_action": "fixture",
        "production_candidate": False,
        "release_inputs_qualified": qualified,
        "schema": maintenance.RGW_KMS_RESULT.RELEASE_SCHEMA,
        "source": maintenance.RGW_KMS_RESULT._release_sources(),
        "status": status,
        "ui_observed_on": "2026-07-28",
    }


def artifact_result(
    release_digest: str = RELEASE_DIGEST,
) -> dict[str, object]:
    architectures = []
    for architecture, digit in (("amd64", "5"), ("arm64", "6")):
        architectures.append(
            {
                "architecture": architecture,
                "core_images": {
                    "coffer": f"sha256:{digit * 64}",
                    "registry": f"sha256:{str(int(digit) + 1) * 64}",
                },
                "core_images_sha256": f"sha256:{'7' * 64}",
                "core_qualification_sha256": f"sha256:{'8' * 64}",
                "ui_images": {
                    "horizon": f"sha256:{'9' * 64}",
                    "skyline": f"sha256:{'a' * 64}",
                },
                "ui_qualification_sha256": f"sha256:{'b' * 64}",
            }
        )
    return {
        "architectures": architectures,
        "cross_architecture": {
            "core_revision": "c" * 40,
            "ui_artifacts": {
                "horizon": f"sha256:{'d' * 64}",
                "skyline": f"sha256:{'e' * 64}",
            },
            "ui_sources": {
                "horizon": "d" * 40,
                "kolla": "c" * 40,
                "skyline": "e" * 40,
            },
        },
        "production_candidate": True,
        "release_readiness_sha256": release_digest,
        "schema": maintenance.ARTIFACT_RESULT.SCHEMA,
        "source": maintenance.ARTIFACT_RESULT.source_hashes(),
    }


def rgw_kms_result(
    release_digest: str = RELEASE_DIGEST,
) -> dict[str, object]:
    return {
        "cleanup": {
            "delete_markers_after": 0,
            "delete_markers_before": 1,
            "multipart_uploads_after": 0,
            "multipart_uploads_before": 1,
            "object_versions_after": 0,
            "object_versions_before": 4,
            "objects_after": 0,
            "objects_before": 4,
        },
        "evidence_sha256": f"sha256:{'4' * 64}",
        "execution": {
            "cleanup_evidence_sha256": f"sha256:{'5' * 64}",
            "least_privilege_evidence_sha256": f"sha256:{'6' * 64}",
            "non_synthetic": True,
            "phase_completion_sha256": {
                "after": f"sha256:{'7' * 64}",
                "before": f"sha256:{'8' * 64}",
                "during": f"sha256:{'9' * 64}",
            },
            "phase_count": 3,
            "restart_evidence_sha256": f"sha256:{'a' * 64}",
            "rotation_evidence_sha256": f"sha256:{'b' * 64}",
        },
        "faults": {
            "kms_outage": {
                "evidence_sha256": f"sha256:{'c' * 64}",
                "failed_closed": True,
                "recovered": True,
            },
            "wrong_key": {
                "evidence_sha256": f"sha256:{'d' * 64}",
                "failed_closed": True,
                "recovered": True,
            },
        },
        "operations": {
            name: True for name in maintenance.RGW_KMS_RESULT.OPERATIONS
        },
        "production_candidate": True,
        "release_inputs": {
            "ceph": {"revision": "b" * 40, "version": "v20.2.3"},
            "distribution": {
                "revision": "a" * 40,
                "version": "v3.2.0",
            },
        },
        "release_readiness_sha256": release_digest,
        "residue": {
            "configuration_secrets": 0,
            "credential_values": 0,
            "delete_markers": 0,
            "host_secrets": 0,
            "key_material": 0,
            "log_secrets": 0,
            "multipart_uploads": 0,
            "object_versions": 0,
            "objects": 0,
            "runtime_files": 0,
            "selected_kms_keys": 0,
            "total": 0,
        },
        "restart": {
            "distribution_restart_count": 1,
            "positive_object_persisted": True,
            "rgw_restart_count": 1,
            "zero_object_persisted": True,
        },
        "rotation": {
            "generation_count": 2,
            "new_key_write_read": True,
            "old_key_readable_during_overlap": True,
            "old_key_revoked_after_overlap": True,
            "overlapping": True,
        },
        "schema": maintenance.RGW_KMS_RESULT.SCHEMA,
        "source": maintenance.RGW_KMS_RESULT.source_hashes(),
        "transport": {
            "barbican_sse_kms": True,
            "credential_policy_denials_verified": True,
            "least_privilege_verified": True,
            "private_tls_verified": True,
            "s3_addressing_style": "path",
            "s3_signature_version": "v4",
            "versioning_enabled": True,
        },
        "unexpected_errors": {"kms": 0, "storage": 0},
    }


def evidence(
    *,
    release_digest: str = RELEASE_DIGEST,
    artifact_digest: str = ARTIFACT_DIGEST,
    rgw_digest: str = RGW_KMS_DIGEST,
) -> dict[str, object]:
    topology = maintenance.STATE_MACHINE.load_topology(
        maintenance.TOPOLOGY_SOURCE
    )
    resource_counts = {
        name: 0 for name in maintenance.STATE_MACHINE.EXPECTED_CLEANUP_ORDER
    }
    resource_counts["role"] = 1
    return {
        "audit": {
            "audit_event_count": 100,
            "known_secret_matches": 0,
            "unexpected_errors": 0,
        },
        "authority": {
            "access_rule_exact": True,
            "application_credential_lifetime_seconds": 3600,
            "application_credential_restricted": True,
            "client_certificate_lifetime_seconds": 3600,
            "pull_only_registry_jwt": True,
            "registry_token_lifetime_seconds": 120,
            "required_roles_exact": True,
            "runtime_secret_retrieval_denied": True,
            "server_side_sql_authority": True,
            "service_project_scoped": True,
            "user_password_disabled": True,
        },
        "evidence_sha256": {
            name: f"sha256:{digit * 64}"
            for name, digit in zip(
                (
                    "audit_sha256",
                    "authority_sha256",
                    "failure_matrix_sha256",
                    "lifecycle_sha256",
                    "rotation_sha256",
                    "teardown_sha256",
                    "transport_sha256",
                ),
                ("4", "5", "6", "7", "8", "9", "a"),
                strict=True,
            )
        },
        "execution": {
            "adapter": "openstack",
            "generation_count": 2,
            "non_synthetic": True,
            "selected_workload_count": 3,
        },
        "failure_matrix": {
            name: True for name in maintenance.FAILURE_CASES
        },
        "lifecycle": {
            "fixed_failure_category": "none",
            "http_status_class": "2xx",
            "immutable_id_hashes": ["b" * 64],
            "invocation_id": "01k0a1b2c3d4e5f6g7h8j9k0mn",
            "log_scan_count": 50,
            "phase": "torn_down",
            "residue_counts": {
                "credentials": 0,
                "identities": 0,
                "mappings": 0,
                "materializations": 0,
                "secrets": 0,
                "sessions": 0,
            },
            "resource_counts": resource_counts,
            "schema": maintenance.STATE_MACHINE.EVIDENCE_SCHEMA,
            "target_signature": "c" * 64,
            "topology_digest": topology.digest,
        },
        "prerequisites": {
            "artifact_result_sha256": artifact_digest,
            "release_readiness_sha256": release_digest,
            "rgw_kms_result_sha256": rgw_digest,
        },
        "residue": {
            **{name: 0 for name in maintenance.RESIDUE_KEYS},
            "total": 0,
        },
        "rotation": {
            "generation_count": 2,
            "keystone_cache_seconds": 30,
            "old_credential_revoked": True,
            "old_mapping_removed": True,
            "old_secret_removed": True,
            "overlap_verified": True,
            "registry_token_seconds": 120,
            "rotation_elapsed_seconds": 120,
        },
        "schema": maintenance.EVIDENCE_SCHEMA,
        "source": maintenance.runtime_source_hashes(),
        "transport": {
            "correct_workload_succeeded": True,
            "private_mtls_verified": True,
            "public_internal_path_denied": True,
            "unknown_fingerprint_denied": True,
            "wrong_client_certificate_denied": True,
            "wrong_method_denied": True,
            "wrong_path_denied": True,
            "wrong_workload_denied": True,
        },
    }


def compile_inputs() -> dict[str, object]:
    return {
        "artifact_digest": ARTIFACT_DIGEST,
        "artifact_result": artifact_result(),
        "evidence": evidence(),
        "evidence_digest": f"sha256:{'f' * 64}",
        "release_digest": RELEASE_DIGEST,
        "release_readiness": release(),
        "rgw_kms_digest": RGW_KMS_DIGEST,
        "rgw_kms_result": rgw_kms_result(),
    }


def _write_private(path: Path, value: object) -> bytes:
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def test_compiles_complete_non_synthetic_identity_lifecycle() -> None:
    result = maintenance.compile_result(**compile_inputs())

    assert result["schema"] == maintenance.SCHEMA
    assert result["production_candidate"] is True
    assert result["execution"]["non_synthetic"] is True
    assert result["lifecycle"]["terminal_phase"] == "torn_down"
    assert result["rotation"]["old_credential_revoked"] is True
    assert maintenance.validate_final_result(result) == result
    retained = json.dumps(result, sort_keys=True)
    assert "01k0a1b2c3d4e5f6g7h8j9k0mn" not in retained
    assert '"target_signature"' not in retained
    assert '"immutable_id_hashes"' not in retained


def test_release_and_specialist_prerequisites_fail_closed() -> None:
    blocked = compile_inputs()
    blocked["release_readiness"] = release(False)
    blocked["evidence"] = {}
    with pytest.raises(
        maintenance.MaintenanceIdentityInputsBlocked,
        match="not candidate-qualified",
    ):
        maintenance.compile_result(**blocked)

    changed_artifact = compile_inputs()
    changed_artifact["artifact_result"]["source"][
        "core_verifier_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        maintenance.MaintenanceIdentityInputsBlocked,
        match="artifacts",
    ):
        maintenance.compile_result(**changed_artifact)

    changed_rgw = compile_inputs()
    changed_rgw["rgw_kms_result"]["residue"]["key_material"] = 1
    changed_rgw["rgw_kms_result"]["residue"]["total"] = 1
    with pytest.raises(
        maintenance.MaintenanceIdentityInputsBlocked,
        match="RGW/KMS",
    ):
        maintenance.compile_result(**changed_rgw)


def test_fixture_or_incomplete_terminal_lifecycle_is_refused() -> None:
    fixture = compile_inputs()
    fixture["evidence"]["execution"]["non_synthetic"] = False
    with pytest.raises(
        maintenance.MaintenanceIdentityResultError,
        match="non-synthetic",
    ):
        maintenance.compile_result(**fixture)

    incomplete = compile_inputs()
    incomplete["evidence"]["lifecycle"]["phase"] = "failures_verified"
    with pytest.raises(
        maintenance.MaintenanceIdentityResultError,
        match="terminal state",
    ):
        maintenance.compile_result(**incomplete)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("authority", "required_roles_exact", False, "authority"),
        (
            "authority",
            "registry_token_lifetime_seconds",
            3600,
            "lifetime",
        ),
        ("transport", "private_mtls_verified", False, "transport"),
        ("rotation", "rotation_elapsed_seconds", 119, "rotation"),
        (
            "failure_matrix",
            "keystone_unavailable",
            False,
            "failure matrix",
        ),
        ("audit", "known_secret_matches", 1, "secrets"),
        ("residue", "credentials", 1, "residue"),
    ],
)
def test_security_rotation_audit_and_residue_fail_closed(
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    inputs = compile_inputs()
    inputs["evidence"][section][field] = value
    if section == "residue":
        inputs["evidence"]["residue"]["total"] = 1
    with pytest.raises(
        maintenance.MaintenanceIdentityResultError,
        match=message,
    ):
        maintenance.compile_result(**inputs)


def test_evidence_prerequisite_or_runtime_source_drift_is_refused() -> None:
    changed_prerequisite = compile_inputs()
    changed_prerequisite["evidence"]["prerequisites"][
        "rgw_kms_result_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        maintenance.MaintenanceIdentityResultError,
        match="binding",
    ):
        maintenance.compile_result(**changed_prerequisite)

    changed_source = compile_inputs()
    changed_source["evidence"]["source"]["lifecycle_sha256"] = (
        f"sha256:{'0' * 64}"
    )
    with pytest.raises(
        maintenance.MaintenanceIdentityResultError,
        match="binding",
    ):
        maintenance.compile_result(**changed_source)


def test_cli_blocks_before_missing_specialist_or_identity_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    output = directory / "result.json"
    _write_private(release_path, release(False))

    result = maintenance.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(directory / "missing-artifact.json"),
            "--rgw-kms-result",
            str(directory / "missing-rgw.json"),
            "--evidence",
            str(directory / "missing-identity.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert "not candidate-qualified" in capsys.readouterr().err

    _write_private(release_path, release())
    result = maintenance.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(directory / "missing-artifact.json"),
            "--rgw-kms-result",
            str(directory / "missing-rgw.json"),
            "--evidence",
            str(directory / "missing-identity.json"),
            "--output",
            str(output),
        ]
    )
    assert result == 3
    assert not output.exists()
    assert "artifact specialist result is absent" in capsys.readouterr().err


def test_cli_writes_owner_only_result(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    artifact_path = directory / "artifact.json"
    rgw_path = directory / "rgw.json"
    evidence_path = directory / "evidence.json"
    output = directory / "result.json"

    release_payload = _write_private(release_path, release())
    release_digest = maintenance._sha256_bytes(release_payload)
    artifact_payload = _write_private(
        artifact_path,
        artifact_result(release_digest),
    )
    artifact_digest = maintenance._sha256_bytes(artifact_payload)
    rgw_payload = _write_private(
        rgw_path,
        rgw_kms_result(release_digest),
    )
    rgw_digest = maintenance._sha256_bytes(rgw_payload)
    _write_private(
        evidence_path,
        evidence(
            release_digest=release_digest,
            artifact_digest=artifact_digest,
            rgw_digest=rgw_digest,
        ),
    )

    result = maintenance.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(artifact_path),
            "--rgw-kms-result",
            str(rgw_path),
            "--evidence",
            str(evidence_path),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert maintenance.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True


def test_final_result_rejects_source_or_zero_residue_tamper() -> None:
    result = maintenance.compile_result(**compile_inputs())
    changed_source = deepcopy(result)
    changed_source["source"]["lifecycle_sha256"] = f"sha256:{'0' * 64}"
    with pytest.raises(
        maintenance.MaintenanceIdentityResultError,
        match="not qualified",
    ):
        maintenance.validate_final_result(changed_source)

    changed_residue = deepcopy(result)
    changed_residue["residue"]["secrets"] = 1
    changed_residue["residue"]["total"] = 1
    with pytest.raises(
        maintenance.MaintenanceIdentityResultError,
        match="residue",
    ):
        maintenance.validate_final_result(changed_residue)
