from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "ledger.py"
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_ledger",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
ledger = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ledger
SPEC.loader.exec_module(ledger)

OBSERVABILITY_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_observability.py"
)
OBSERVABILITY_SPEC = importlib.util.spec_from_file_location(
    "coffer_ledger_observability_test_helpers",
    OBSERVABILITY_TEST_SOURCE,
)
assert (
    OBSERVABILITY_SPEC is not None
    and OBSERVABILITY_SPEC.loader is not None
)
observability_test = importlib.util.module_from_spec(OBSERVABILITY_SPEC)
sys.modules[OBSERVABILITY_SPEC.name] = observability_test
OBSERVABILITY_SPEC.loader.exec_module(observability_test)

LOAD_SOAK_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_load_soak.py"
)
LOAD_SOAK_SPEC = importlib.util.spec_from_file_location(
    "coffer_ledger_load_soak_test_helpers",
    LOAD_SOAK_TEST_SOURCE,
)
assert LOAD_SOAK_SPEC is not None and LOAD_SOAK_SPEC.loader is not None
load_soak_test = importlib.util.module_from_spec(LOAD_SOAK_SPEC)
sys.modules[LOAD_SOAK_SPEC.name] = load_soak_test
LOAD_SOAK_SPEC.loader.exec_module(load_soak_test)


def release(status: str = "blocked") -> dict[str, object]:
    reason = [] if status == "candidate-qualified" else ["not qualified"]
    components = {
        "distribution": {
            "reasons": list(reason),
            "revision": "a" * 40,
            "status": status,
            "version": "v3.1.1",
        },
        "ceph": {
            "reasons": list(reason),
            "revision": "b" * 40,
            "status": status,
            "version": "v20.2.2",
        },
        "oslo_messaging": {
            "reasons": list(reason),
            "revision": None if status == "blocked" else "c" * 40,
            "status": status,
            "version": None if status == "blocked" else "17.3.1",
        },
    }
    blockers = [
        f"{name}: {item}"
        for name in ("distribution", "ceph", "oslo_messaging")
        for item in reason
    ]
    return {
        "blockers": blockers,
        "components": components,
        "next_action": "fixture",
        "production_candidate": False,
        "release_inputs_qualified": status == "candidate-qualified",
        "schema": ledger.RELEASE_SCHEMA,
        "source": {
            "upstream_classifier_sha256": ledger._sha256(
                ROOT
                / "poc"
                / "production-images"
                / "check_upstream_readiness.py"
            ),
            "ui_classifier_sha256": ledger._sha256(
                ROOT
                / "poc"
                / "ui-images"
                / "oslo_messaging_release_gate.py"
            ),
            "ui_contract_sha256": ledger._sha256(
                ROOT
                / "poc"
                / "ui-images"
                / "oslo_messaging_release_gate.json"
            ),
        },
        "status": status,
        "ui_observed_on": "2026-07-28",
    }


def gc_result() -> dict[str, object]:
    return {
        "authorization_consumed": True,
        "candidate_count": ledger.GC_RESULT.GC_RESULT.EXPECTED_CANDIDATES,
        "candidate_set_hash": f"sha256:{'1' * 64}",
        "cleanup_verified": True,
        "delete_untagged": False,
        "distribution": {
            "image": ledger.GC_RESULT.GC_RESULT.IMAGE,
            "revision": ledger.GC_RESULT.GC_RESULT.REVISION,
            "version": ledger.GC_RESULT.GC_RESULT.VERSION,
        },
        "dry_run_count": 2,
        "input_gc_result_sha256": f"sha256:{'2' * 64}",
        "logical_bytes_reclaimed": (
            ledger.GC_RESULT.GC_RESULT.EXPECTED_RECLAIMED_BYTES
        ),
        "physical_backend": "filesystem",
        "prerequisites": {
            "artifact_result_sha256": f"sha256:{'5' * 64}",
            "release_readiness_sha256": f"sha256:{'3' * 64}",
        },
        "production_candidate": True,
        "residue": {
            "containers": 0,
            "networks": 0,
            "runtime_paths": 0,
            "total": 0,
        },
        "restore_verified": True,
        "schema": ledger.GC_RESULT.SCHEMA,
        "source": ledger.GC_RESULT.source_hashes(),
        "survivor_class_count": (
            ledger.GC_RESULT.GC_RESULT.EXPECTED_SURVIVORS
        ),
        "survivor_classes_hash": f"sha256:{'3' * 64}",
    }


def artifact_result() -> dict[str, object]:
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
        "release_readiness_sha256": f"sha256:{'3' * 64}",
        "schema": ledger.ARTIFACT_RESULT.SCHEMA,
        "source": ledger.ARTIFACT_RESULT.source_hashes(),
    }


def rgw_kms_result() -> dict[str, object]:
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
            name: True for name in ledger.RGW_KMS_RESULT.OPERATIONS
        },
        "production_candidate": True,
        "release_inputs": {
            "ceph": {"revision": "b" * 40, "version": "v20.2.2"},
            "distribution": {
                "revision": "a" * 40,
                "version": "v3.1.1",
            },
        },
        "release_readiness_sha256": f"sha256:{'3' * 64}",
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
        "schema": ledger.RGW_KMS_RESULT.SCHEMA,
        "source": ledger.RGW_KMS_RESULT.source_hashes(),
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


def maintenance_identity_result() -> dict[str, object]:
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
                ("1", "2", "3", "4", "5", "6", "7"),
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
            name: True
            for name in ledger.MAINTENANCE_IDENTITY_RESULT.FAILURE_CASES
        },
        "input_evidence_sha256": f"sha256:{'8' * 64}",
        "lifecycle": {
            "log_scan_count": 50,
            "preexisting_role_count": 1,
            "terminal_phase": "torn_down",
        },
        "prerequisites": {
            "artifact_result_sha256": f"sha256:{'5' * 64}",
            "release_readiness_sha256": f"sha256:{'3' * 64}",
            "rgw_kms_result_sha256": f"sha256:{'e' * 64}",
        },
        "production_candidate": True,
        "residue": {
            **{
                name: 0
                for name in ledger.MAINTENANCE_IDENTITY_RESULT.RESIDUE_KEYS
            },
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
        "schema": ledger.MAINTENANCE_IDENTITY_RESULT.SCHEMA,
        "source": ledger.MAINTENANCE_IDENTITY_RESULT.source_hashes(),
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


def data_protection_result() -> dict[str, object]:
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
                ("1", "2", "3", "4", "5", "6", "7", "8", "9"),
                strict=True,
            )
        },
        "execution": {
            "adapter": "openstack",
            "disposable": True,
            "non_synthetic": True,
            "phase_count": len(
                ledger.DATA_PROTECTION_RESULT.STATE_MACHINE.EXPECTED_PHASES
            ),
        },
        "failure_matrix": {
            name: True
            for name in (
                ledger.DATA_PROTECTION_RESULT.STATE_MACHINE.EXPECTED_FAILURE_CASES
            )
        },
        "input_evidence_sha256": f"sha256:{'a' * 64}",
        "inventory_import": {
            "conflicting_replay_refused": True,
            "descriptor_count": 8,
            "idempotent_replay": True,
            "imported": True,
            "inventory_schema": "coffer.inventory/v3",
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
            "phase_evidence_sha256": f"sha256:{'b' * 64}",
            "terminal_phase": "torn-down",
        },
        "prerequisites": {
            "artifact_result_sha256": f"sha256:{'5' * 64}",
            "maintenance_identity_result_sha256": f"sha256:{'f' * 64}",
            "release_readiness_sha256": f"sha256:{'3' * 64}",
            "rgw_kms_result_sha256": f"sha256:{'e' * 64}",
        },
        "production_candidate": True,
        "residue": {
            **{
                name: 0
                for name in (
                    ledger.DATA_PROTECTION_RESULT.STATE_MACHINE.EXPECTED_RESIDUE_KEYS
                )
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
        "schema": ledger.DATA_PROTECTION_RESULT.SCHEMA,
        "source": ledger.DATA_PROTECTION_RESULT.source_hashes(),
        "unrelated_state": {
            "sha256": f"sha256:{'c' * 64}",
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


def observability_result() -> dict[str, object]:
    result = observability_test.observability.compile_result(
        **observability_test.compile_inputs()
    )
    result["prerequisites"] = {
        "artifact_result_sha256": f"sha256:{'5' * 64}",
        "data_protection_result_sha256": f"sha256:{'9' * 64}",
        "maintenance_identity_result_sha256": f"sha256:{'f' * 64}",
        "release_readiness_sha256": f"sha256:{'3' * 64}",
        "rgw_kms_result_sha256": f"sha256:{'e' * 64}",
    }
    return result


def load_soak_result() -> dict[str, object]:
    result = load_soak_test.load_soak.compile_result(
        **load_soak_test.compile_inputs()
    )
    result["prerequisites"] = {
        "artifact_result_sha256": f"sha256:{'5' * 64}",
        "data_protection_result_sha256": f"sha256:{'9' * 64}",
        "gc_retention_result_sha256": f"sha256:{'4' * 64}",
        "maintenance_identity_result_sha256": f"sha256:{'f' * 64}",
        "observability_result_sha256": f"sha256:{'8' * 64}",
        "release_readiness_sha256": f"sha256:{'3' * 64}",
        "rgw_kms_result_sha256": f"sha256:{'e' * 64}",
    }
    return result


def test_blocked_release_and_release_bound_gc_are_reported_independently() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        artifact_result=artifact_result(),
        artifact_digest=f"sha256:{'5' * 64}",
        gc_result=gc_result(),
        gc_digest=f"sha256:{'4' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["production_candidate"] is False
    assert result["blocked_gates"] == ["release_inputs"]
    assert result["passed_gate_count"] == 2
    assert gates["release_inputs"]["status"] == "blocked"
    assert gates["gc_retention"]["status"] == "passed"
    assert gates["gc_retention"]["evidence"] == {
        "schema": ledger.GC_RESULT.SCHEMA,
        "sha256": f"sha256:{'4' * 64}",
    }
    assert len(result["pending_gates"]) == 7


def test_valid_artifact_and_gc_specialists_pass_only_their_gates() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        gc_result=gc_result(),
        gc_digest=f"sha256:{'4' * 64}",
        artifact_result=artifact_result(),
        artifact_digest=f"sha256:{'5' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["passed_gate_count"] == 2
    assert gates["immutable_artifacts"]["status"] == "passed"
    assert gates["gc_retention"]["status"] == "passed"
    assert len(result["pending_gates"]) == 7


def test_valid_rgw_kms_specialist_passes_only_its_gate() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        rgw_kms_result=rgw_kms_result(),
        rgw_kms_digest=f"sha256:{'e' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["passed_gate_count"] == 1
    assert gates["rgw_kms"] == {
        "evidence": {
            "schema": ledger.RGW_KMS_RESULT.SCHEMA,
            "sha256": f"sha256:{'e' * 64}",
        },
        "id": "rgw_kms",
        "reason": None,
        "status": "passed",
    }
    assert len(result["pending_gates"]) == 8


def test_valid_maintenance_identity_requires_and_passes_prerequisites() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        artifact_result=artifact_result(),
        artifact_digest=f"sha256:{'5' * 64}",
        rgw_kms_result=rgw_kms_result(),
        rgw_kms_digest=f"sha256:{'e' * 64}",
        maintenance_identity_result=maintenance_identity_result(),
        maintenance_identity_digest=f"sha256:{'f' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["passed_gate_count"] == 3
    assert gates["immutable_artifacts"]["status"] == "passed"
    assert gates["rgw_kms"]["status"] == "passed"
    assert gates["maintenance_identity"] == {
        "evidence": {
            "schema": ledger.MAINTENANCE_IDENTITY_RESULT.SCHEMA,
            "sha256": f"sha256:{'f' * 64}",
        },
        "id": "maintenance_identity",
        "reason": None,
        "status": "passed",
    }
    assert len(result["pending_gates"]) == 6


def test_valid_data_protection_requires_and_passes_all_prerequisites() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        artifact_result=artifact_result(),
        artifact_digest=f"sha256:{'5' * 64}",
        rgw_kms_result=rgw_kms_result(),
        rgw_kms_digest=f"sha256:{'e' * 64}",
        maintenance_identity_result=maintenance_identity_result(),
        maintenance_identity_digest=f"sha256:{'f' * 64}",
        data_protection_result=data_protection_result(),
        data_protection_digest=f"sha256:{'9' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["passed_gate_count"] == 4
    assert gates["data_protection"] == {
        "evidence": {
            "schema": ledger.DATA_PROTECTION_RESULT.SCHEMA,
            "sha256": f"sha256:{'9' * 64}",
        },
        "id": "data_protection",
        "reason": None,
        "status": "passed",
    }
    assert len(result["pending_gates"]) == 5


def test_valid_observability_requires_and_passes_all_prerequisites() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        artifact_result=artifact_result(),
        artifact_digest=f"sha256:{'5' * 64}",
        rgw_kms_result=rgw_kms_result(),
        rgw_kms_digest=f"sha256:{'e' * 64}",
        maintenance_identity_result=maintenance_identity_result(),
        maintenance_identity_digest=f"sha256:{'f' * 64}",
        data_protection_result=data_protection_result(),
        data_protection_digest=f"sha256:{'9' * 64}",
        observability_result=observability_result(),
        observability_digest=f"sha256:{'8' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["passed_gate_count"] == 5
    assert gates["observability"] == {
        "evidence": {
            "schema": ledger.OBSERVABILITY_RESULT.SCHEMA,
            "sha256": f"sha256:{'8' * 64}",
        },
        "id": "observability",
        "reason": None,
        "status": "passed",
    }
    assert len(result["pending_gates"]) == 4


def test_valid_load_soak_requires_and_passes_all_prerequisites() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        artifact_result=artifact_result(),
        artifact_digest=f"sha256:{'5' * 64}",
        rgw_kms_result=rgw_kms_result(),
        rgw_kms_digest=f"sha256:{'e' * 64}",
        maintenance_identity_result=maintenance_identity_result(),
        maintenance_identity_digest=f"sha256:{'f' * 64}",
        data_protection_result=data_protection_result(),
        data_protection_digest=f"sha256:{'9' * 64}",
        observability_result=observability_result(),
        observability_digest=f"sha256:{'8' * 64}",
        gc_result=gc_result(),
        gc_digest=f"sha256:{'4' * 64}",
        load_soak_result=load_soak_result(),
        load_soak_digest=f"sha256:{'7' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["passed_gate_count"] == 7
    assert gates["load_soak"] == {
        "evidence": {
            "schema": ledger.LOAD_SOAK_RESULT.SCHEMA,
            "sha256": f"sha256:{'7' * 64}",
        },
        "id": "load_soak",
        "reason": None,
        "status": "passed",
    }
    assert result["pending_gates"] == [
        "kolla_multinode",
        "operator_release",
    ]


def test_qualified_release_still_cannot_self_promote_missing_gates() -> None:
    result = ledger.compile_ledger(
        release_readiness=release("candidate-qualified"),
        release_digest=f"sha256:{'3' * 64}",
        today=date(2026, 7, 28),
    )

    assert result["status"] == "pending"
    assert result["blocked_gates"] == []
    assert result["passed_gate_count"] == 1
    assert result["production_candidate"] is False
    assert "gc_retention" in result["pending_gates"]


def test_release_aggregate_or_source_binding_cannot_be_self_attested() -> None:
    changed_blockers = release()
    changed_blockers["blockers"] = []
    with pytest.raises(ledger.PromotionLedgerError, match="aggregate"):
        ledger.compile_ledger(
            release_readiness=changed_blockers,
            release_digest=f"sha256:{'3' * 64}",
            today=date(2026, 7, 28),
        )

    changed_source = release()
    changed_source["source"]["ui_contract_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(ledger.PromotionLedgerError, match="source"):
        ledger.compile_ledger(
            release_readiness=changed_source,
            release_digest=f"sha256:{'3' * 64}",
            today=date(2026, 7, 28),
        )


def test_stale_release_or_invalid_gc_result_fails_closed() -> None:
    with pytest.raises(ledger.PromotionLedgerError, match="stale"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            today=date(2026, 7, 30),
        )

    changed_gc = gc_result()
    changed_gc["residue"]["containers"] = 1
    with pytest.raises(ledger.PromotionLedgerError, match="GC specialist"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            artifact_result=artifact_result(),
            artifact_digest=f"sha256:{'5' * 64}",
            gc_result=changed_gc,
            gc_digest=f"sha256:{'4' * 64}",
            today=date(2026, 7, 28),
        )


def test_gc_result_and_digest_are_atomic_inputs() -> None:
    with pytest.raises(ledger.PromotionLedgerError, match="digest"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            gc_result=gc_result(),
            today=date(2026, 7, 28),
        )
    with pytest.raises(ledger.PromotionLedgerError, match="no specialist"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            gc_digest=f"sha256:{'4' * 64}",
            today=date(2026, 7, 28),
        )

    changed_binding = gc_result()
    changed_binding["prerequisites"]["release_readiness_sha256"] = (
        f"sha256:{'0' * 64}"
    )
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="prerequisite binding",
    ):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            artifact_result=artifact_result(),
            artifact_digest=f"sha256:{'5' * 64}",
            gc_result=changed_binding,
            gc_digest=f"sha256:{'4' * 64}",
            today=date(2026, 7, 28),
        )


def test_artifact_result_and_digest_are_atomic_and_validated() -> None:
    with pytest.raises(ledger.PromotionLedgerError, match="digest"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            artifact_result=artifact_result(),
            today=date(2026, 7, 28),
        )
    with pytest.raises(ledger.PromotionLedgerError, match="no specialist"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            artifact_digest=f"sha256:{'5' * 64}",
            today=date(2026, 7, 28),
        )
    changed = artifact_result()
    changed["source"]["core_verifier_sha256"] = f"sha256:{'0' * 64}"
    with pytest.raises(ledger.PromotionLedgerError, match="artifact specialist"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            artifact_result=changed,
            artifact_digest=f"sha256:{'5' * 64}",
            today=date(2026, 7, 28),
        )

    changed_binding = artifact_result()
    changed_binding["release_readiness_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(ledger.PromotionLedgerError, match="release binding"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            artifact_result=changed_binding,
            artifact_digest=f"sha256:{'5' * 64}",
            today=date(2026, 7, 28),
        )


def test_rgw_kms_result_and_digest_are_atomic_and_validated() -> None:
    with pytest.raises(ledger.PromotionLedgerError, match="digest"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            rgw_kms_result=rgw_kms_result(),
            today=date(2026, 7, 28),
        )
    with pytest.raises(ledger.PromotionLedgerError, match="no specialist"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            rgw_kms_digest=f"sha256:{'e' * 64}",
            today=date(2026, 7, 28),
        )
    changed = rgw_kms_result()
    changed["residue"]["key_material"] = 1
    changed["residue"]["total"] = 1
    with pytest.raises(ledger.PromotionLedgerError, match="RGW/KMS specialist"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            rgw_kms_result=changed,
            rgw_kms_digest=f"sha256:{'e' * 64}",
            today=date(2026, 7, 28),
        )

    changed_binding = rgw_kms_result()
    changed_binding["release_readiness_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(ledger.PromotionLedgerError, match="release binding"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            rgw_kms_result=changed_binding,
            rgw_kms_digest=f"sha256:{'e' * 64}",
            today=date(2026, 7, 28),
        )


def test_maintenance_identity_result_is_atomic_and_prerequisite_bound() -> None:
    common = {
        "artifact_digest": f"sha256:{'5' * 64}",
        "artifact_result": artifact_result(),
        "release_digest": f"sha256:{'3' * 64}",
        "release_readiness": release(),
        "rgw_kms_digest": f"sha256:{'e' * 64}",
        "rgw_kms_result": rgw_kms_result(),
        "today": date(2026, 7, 28),
    }
    with pytest.raises(ledger.PromotionLedgerError, match="digest"):
        ledger.compile_ledger(
            **common,
            maintenance_identity_result=maintenance_identity_result(),
        )
    with pytest.raises(ledger.PromotionLedgerError, match="no specialist"):
        ledger.compile_ledger(
            **common,
            maintenance_identity_digest=f"sha256:{'f' * 64}",
        )
    with pytest.raises(ledger.PromotionLedgerError, match="prerequisite"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            maintenance_identity_result=maintenance_identity_result(),
            maintenance_identity_digest=f"sha256:{'f' * 64}",
            today=date(2026, 7, 28),
        )

    changed = maintenance_identity_result()
    changed["residue"]["credentials"] = 1
    changed["residue"]["total"] = 1
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="maintenance identity specialist",
    ):
        ledger.compile_ledger(
            **common,
            maintenance_identity_result=changed,
            maintenance_identity_digest=f"sha256:{'f' * 64}",
        )

    changed_binding = maintenance_identity_result()
    changed_binding["prerequisites"]["rgw_kms_result_sha256"] = (
        f"sha256:{'0' * 64}"
    )
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="prerequisite binding",
    ):
        ledger.compile_ledger(
            **common,
            maintenance_identity_result=changed_binding,
            maintenance_identity_digest=f"sha256:{'f' * 64}",
        )


def test_data_protection_result_is_atomic_and_prerequisite_bound() -> None:
    common = {
        "artifact_digest": f"sha256:{'5' * 64}",
        "artifact_result": artifact_result(),
        "maintenance_identity_digest": f"sha256:{'f' * 64}",
        "maintenance_identity_result": maintenance_identity_result(),
        "release_digest": f"sha256:{'3' * 64}",
        "release_readiness": release(),
        "rgw_kms_digest": f"sha256:{'e' * 64}",
        "rgw_kms_result": rgw_kms_result(),
        "today": date(2026, 7, 28),
    }
    with pytest.raises(ledger.PromotionLedgerError, match="digest"):
        ledger.compile_ledger(
            **common,
            data_protection_result=data_protection_result(),
        )
    with pytest.raises(ledger.PromotionLedgerError, match="no specialist"):
        ledger.compile_ledger(
            **common,
            data_protection_digest=f"sha256:{'9' * 64}",
        )
    with pytest.raises(ledger.PromotionLedgerError, match="prerequisite"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            data_protection_result=data_protection_result(),
            data_protection_digest=f"sha256:{'9' * 64}",
            today=date(2026, 7, 28),
        )

    changed = data_protection_result()
    changed["residue"]["credentials"] = 1
    changed["residue"]["total"] = 1
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="data-protection specialist",
    ):
        ledger.compile_ledger(
            **common,
            data_protection_result=changed,
            data_protection_digest=f"sha256:{'9' * 64}",
        )

    changed_binding = data_protection_result()
    changed_binding["prerequisites"][
        "maintenance_identity_result_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="prerequisite binding",
    ):
        ledger.compile_ledger(
            **common,
            data_protection_result=changed_binding,
            data_protection_digest=f"sha256:{'9' * 64}",
        )


def test_observability_result_is_atomic_and_prerequisite_bound() -> None:
    common = {
        "artifact_digest": f"sha256:{'5' * 64}",
        "artifact_result": artifact_result(),
        "data_protection_digest": f"sha256:{'9' * 64}",
        "data_protection_result": data_protection_result(),
        "maintenance_identity_digest": f"sha256:{'f' * 64}",
        "maintenance_identity_result": maintenance_identity_result(),
        "release_digest": f"sha256:{'3' * 64}",
        "release_readiness": release(),
        "rgw_kms_digest": f"sha256:{'e' * 64}",
        "rgw_kms_result": rgw_kms_result(),
        "today": date(2026, 7, 28),
    }
    with pytest.raises(ledger.PromotionLedgerError, match="digest"):
        ledger.compile_ledger(
            **common,
            observability_result=observability_result(),
        )
    with pytest.raises(ledger.PromotionLedgerError, match="no specialist"):
        ledger.compile_ledger(
            **common,
            observability_digest=f"sha256:{'8' * 64}",
        )
    with pytest.raises(ledger.PromotionLedgerError, match="prerequisite"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            observability_result=observability_result(),
            observability_digest=f"sha256:{'8' * 64}",
            today=date(2026, 7, 28),
        )

    changed = observability_result()
    changed["residue"]["containers"] = 1
    changed["residue"]["total"] = 1
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="observability specialist",
    ):
        ledger.compile_ledger(
            **common,
            observability_result=changed,
            observability_digest=f"sha256:{'8' * 64}",
        )

    changed_binding = observability_result()
    changed_binding["prerequisites"][
        "data_protection_result_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="prerequisite binding",
    ):
        ledger.compile_ledger(
            **common,
            observability_result=changed_binding,
            observability_digest=f"sha256:{'8' * 64}",
        )


def test_load_soak_result_is_atomic_and_prerequisite_bound() -> None:
    common = {
        "artifact_digest": f"sha256:{'5' * 64}",
        "artifact_result": artifact_result(),
        "data_protection_digest": f"sha256:{'9' * 64}",
        "data_protection_result": data_protection_result(),
        "gc_digest": f"sha256:{'4' * 64}",
        "gc_result": gc_result(),
        "maintenance_identity_digest": f"sha256:{'f' * 64}",
        "maintenance_identity_result": maintenance_identity_result(),
        "observability_digest": f"sha256:{'8' * 64}",
        "observability_result": observability_result(),
        "release_digest": f"sha256:{'3' * 64}",
        "release_readiness": release(),
        "rgw_kms_digest": f"sha256:{'e' * 64}",
        "rgw_kms_result": rgw_kms_result(),
        "today": date(2026, 7, 28),
    }
    with pytest.raises(ledger.PromotionLedgerError, match="digest"):
        ledger.compile_ledger(
            **common,
            load_soak_result=load_soak_result(),
        )
    with pytest.raises(ledger.PromotionLedgerError, match="no specialist"):
        ledger.compile_ledger(
            **common,
            load_soak_digest=f"sha256:{'7' * 64}",
        )
    with pytest.raises(ledger.PromotionLedgerError, match="prerequisite"):
        ledger.compile_ledger(
            release_readiness=release(),
            release_digest=f"sha256:{'3' * 64}",
            load_soak_result=load_soak_result(),
            load_soak_digest=f"sha256:{'7' * 64}",
            today=date(2026, 7, 28),
        )

    changed = load_soak_result()
    changed["execution"]["action_count"] = 52
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="load/soak specialist",
    ):
        ledger.compile_ledger(
            **common,
            load_soak_result=changed,
            load_soak_digest=f"sha256:{'7' * 64}",
        )

    changed_binding = load_soak_result()
    changed_binding["prerequisites"][
        "observability_result_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        ledger.PromotionLedgerError,
        match="prerequisite binding",
    ):
        ledger.compile_ledger(
            **common,
            load_soak_result=changed_binding,
            load_soak_digest=f"sha256:{'7' * 64}",
        )


def test_output_is_owner_only_and_replaced_atomically(tmp_path: Path) -> None:
    output = tmp_path / "evidence" / "promotion-ledger.json"
    value = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        today=date(2026, 7, 28),
    )

    ledger._write_owner_only(output.resolve(), value)
    ledger._write_owner_only(output.resolve(), value)

    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == value


def test_unknown_gate_cannot_be_injected() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        today=date(2026, 7, 28),
    )
    changed = deepcopy(result)
    changed["gates"].append(
        {
            "evidence": None,
            "id": "manual_override",
            "reason": None,
            "status": "passed",
        }
    )

    assert changed != result
    assert [gate["id"] for gate in result["gates"]] == list(ledger.GATE_ORDER)
