from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "data-protection" / "state_machine.py"
TOPOLOGY_PATH = ROOT / "poc" / "data-protection" / "topology.json"
SPEC = importlib.util.spec_from_file_location(
    "coffer_data_protection_state_machine",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODEL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODEL
SPEC.loader.exec_module(MODEL)

INVOCATION_ID = "01k0a1b2c3d4e5f6g7h8j9k0mn"
TARGET_SIGNATURE = "a" * 64
UNRELATED_SIGNATURE = f"sha256:{'b' * 64}"
SOURCE_SIGNATURE = f"sha256:{'c' * 64}"
INVENTORY_DIGEST = f"sha256:{'d' * 64}"
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def topology():
    return MODEL.load_topology(TOPOLOGY_PATH)


def preflight():
    return MODEL.create_preflight_state(
        topology(),
        INVOCATION_ID,
        TARGET_SIGNATURE,
        UNRELATED_SIGNATURE,
        now=NOW,
    )


def resources():
    specs = MODEL.expected_resource_specs(topology(), INVOCATION_ID)
    return {
        key: {
            "id": f"immutable-{index:03d}-{key}",
            **spec,
        }
        for index, (key, spec) in enumerate(specs.items(), start=1)
    }


def source_created():
    return MODEL.register_source_resources(
        topology(),
        preflight(),
        resources(),
        now=NOW,
    )


def fixture_evidence():
    return {
        "content_sha256": f"sha256:{'1' * 64}",
        "source_signature": SOURCE_SIGNATURE,
        "manifest_count": 4,
        "blob_count": 5,
        "index_count": 1,
        "artifact_count": 1,
        "zero_byte_blob_count": 1,
        "multipart_upload_count": 0,
    }


def writer_fence():
    return {
        "ingress_config_sha256": f"sha256:{'2' * 64}",
        "replica_set_sha256": f"sha256:{'3' * 64}",
        "disabled_workers_sha256": f"sha256:{'4' * 64}",
        "database_fence_sha256": f"sha256:{'5' * 64}",
        "source_signature": SOURCE_SIGNATURE,
        "active_uploads": 0,
        "unknown_listeners": 0,
        "canary_write_status": 405,
        "digest_read_status": 200,
    }


def sql_backup():
    return {
        "artifact_sha256": f"sha256:{'5' * 64}",
        "backup_sha256": f"sha256:{'6' * 64}",
        "restore_sha256": f"sha256:{'6' * 64}",
        "schema_sha256": f"sha256:{'7' * 64}",
        "recovery_coordinate_sha256": f"sha256:{'8' * 64}",
        "provenance_sha256": f"sha256:{'9' * 64}",
        "bytes": 8192,
        "row_count": 42,
        "restored": True,
    }


def rgw_backup():
    return {
        "manifest_sha256": f"sha256:{'9' * 64}",
        "source_inventory_sha256": f"sha256:{'a' * 64}",
        "restore_inventory_sha256": f"sha256:{'a' * 64}",
        "metadata_sha256": f"sha256:{'b' * 64}",
        "source_signature": SOURCE_SIGNATURE,
        "provenance_sha256": f"sha256:{'9' * 64}",
        "bytes": 16384,
        "object_count": 12,
        "version_count": 12,
        "multipart_upload_count": 0,
        "restored": True,
    }


def inventory_evidence():
    return {
        "scan_one_sha256": f"sha256:{'c' * 64}",
        "scan_two_sha256": f"sha256:{'c' * 64}",
        "inventory_sha256": INVENTORY_DIGEST,
        "provenance_sha256": f"sha256:{'e' * 64}",
        "source_signature": SOURCE_SIGNATURE,
        "repository_count": 1,
        "manifest_count": 4,
        "descriptor_count": 10,
        "scans_equal": True,
    }


def baseline_import():
    return {
        "inventory_sha256": INVENTORY_DIGEST,
        "database_sha256": f"sha256:{'f' * 64}",
        "status": "imported",
        "idempotent_replay": True,
        "conflicting_replay_refused": True,
        "partial_rows": 0,
    }


def live_comparison():
    return {
        "inventory_sha256": INVENTORY_DIGEST,
        "session_sha256": f"sha256:{'1' * 64}",
        "workload_sha256": f"sha256:{'2' * 64}",
        "expected_manifest_count": 4,
        "verified_manifest_count": 4,
        "failure_count": 0,
        "private_tls_verified": True,
        "pull_only": True,
        "session_closed": True,
    }


def admission_cutover():
    state = through_live_comparison()
    routing_sha256 = f"sha256:{'4' * 64}"
    database_sha256 = f"sha256:{'5' * 64}"
    return {
        "marker_sha256": MODEL.cutover_marker_digest(
            topology(),
            state,
            routing_sha256,
            database_sha256,
        ),
        "routing_sha256": routing_sha256,
        "database_sha256": database_sha256,
        "quota_edge_forced": True,
        "direct_registry_closed": True,
        "writer_fence_released": True,
    }


def cutover_verification():
    return {
        "existing_pull": True,
        "new_push_accounted": True,
        "project_isolation": True,
        "over_quota_429": True,
        "dependency_503": True,
        "restart_persistence": True,
        "reconciliation": True,
    }


def rollback_evidence():
    return {
        "original_source_sha256": SOURCE_SIGNATURE,
        "restored_source_sha256": SOURCE_SIGNATURE,
        "routing_sha256": f"sha256:{'6' * 64}",
        "rollback_manifest_sha256": f"sha256:{'7' * 64}",
        "writer_fence_reapplied": True,
        "active_uploads": 0,
        "ambiguous_differences": 0,
        "original_digest_readable": True,
        "post_cutover_write_count": 1,
        "removed_post_cutover_write_count": 1,
    }


def restore_evidence():
    return {
        "sql_backup_sha256": sql_backup()["backup_sha256"],
        "sql_restore_sha256": sql_backup()["restore_sha256"],
        "rgw_manifest_sha256": rgw_backup()["manifest_sha256"],
        "inventory_sha256": INVENTORY_DIGEST,
        "authenticated_comparison": True,
        "pull_digest_match": True,
        "admission_checks": True,
    }


def failure_outcomes():
    return {case: "passed" for case in topology().failure_cases}


def zero_residue():
    return {key: 0 for key in topology().residue_keys}


def through_fixture():
    return MODEL.mark_fixture_populated(
        topology(),
        source_created(),
        fixture_evidence(),
        now=NOW,
    )


def through_fence():
    return MODEL.mark_writers_excluded(
        topology(),
        through_fixture(),
        writer_fence(),
        now=NOW,
    )


def through_backups():
    return MODEL.mark_backups_verified(
        topology(),
        through_fence(),
        sql_backup(),
        rgw_backup(),
        now=NOW,
    )


def through_inventory():
    return MODEL.mark_inventory_verified(
        topology(),
        through_backups(),
        inventory_evidence(),
        now=NOW,
    )


def through_import():
    return MODEL.mark_baseline_imported(
        topology(),
        through_inventory(),
        baseline_import(),
        now=NOW,
    )


def through_live_comparison():
    return MODEL.mark_live_comparison_verified(
        topology(),
        through_import(),
        live_comparison(),
        now=NOW,
    )


def through_admission():
    return MODEL.mark_admission_cutover(
        topology(),
        through_live_comparison(),
        admission_cutover(),
        now=NOW,
    )


def through_cutover():
    return MODEL.mark_cutover_verified(
        topology(),
        through_admission(),
        cutover_verification(),
        now=NOW,
    )


def through_rollback():
    return MODEL.mark_rollback_verified(
        topology(),
        through_cutover(),
        rollback_evidence(),
        now=NOW,
    )


def through_restore():
    return MODEL.mark_restore_verified(
        topology(),
        through_rollback(),
        restore_evidence(),
        now=NOW,
    )


def complete_state():
    return MODEL.mark_failures_verified(
        topology(),
        through_restore(),
        failure_outcomes(),
        now=NOW,
    )


def test_checked_in_topology_is_exact() -> None:
    loaded = topology()

    assert loaded.invocation_prefix == "coffer-cutover"
    assert loaded.phases == MODEL.EXPECTED_PHASES
    assert loaded.resource_keys == MODEL.EXPECTED_RESOURCE_KEYS
    assert loaded.cleanup_order == MODEL.EXPECTED_CLEANUP_ORDER
    assert loaded.residue_keys == MODEL.EXPECTED_RESIDUE_KEYS
    assert loaded.failure_cases == MODEL.EXPECTED_FAILURE_CASES
    assert loaded.digest.startswith("sha256:")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("phases", ["preflighted", "torn-down"], "phases"),
        ("resource_keys", ["project"], "resources"),
        ("cleanup_order", ["project"], "cleanup"),
        ("residue_keys", ["containers"], "residue"),
        ("failure_cases", ["unknown"], "failure"),
        ("work_root", "../outside", "work root"),
    ],
)
def test_topology_expansion_or_reordering_is_refused(
    field: str,
    value: object,
    message: str,
) -> None:
    raw = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    raw[field] = value

    with pytest.raises(MODEL.DataProtectionError, match=message):
        MODEL.validate_topology(raw)


def test_preflight_requires_exact_identifiers() -> None:
    with pytest.raises(MODEL.DataProtectionError, match="ULID"):
        MODEL.create_preflight_state(
            topology(),
            "invalid",
            TARGET_SIGNATURE,
            UNRELATED_SIGNATURE,
        )
    with pytest.raises(MODEL.DataProtectionError, match="target signature"):
        MODEL.create_preflight_state(
            topology(),
            INVOCATION_ID,
            "invalid",
            UNRELATED_SIGNATURE,
        )
    with pytest.raises(MODEL.DataProtectionError, match="unrelated signature"):
        MODEL.create_preflight_state(
            topology(),
            INVOCATION_ID,
            TARGET_SIGNATURE,
            "invalid",
        )


def test_source_requires_complete_exact_unique_resources() -> None:
    missing = resources()
    missing.pop("bucket-source")
    with pytest.raises(MODEL.DataProtectionError, match="incomplete"):
        MODEL.register_source_resources(topology(), preflight(), missing)

    renamed = resources()
    renamed["bucket-source"]["name"] = "some-other-bucket"
    with pytest.raises(MODEL.DataProtectionError, match="exact allowlist"):
        MODEL.register_source_resources(topology(), preflight(), renamed)

    duplicate = resources()
    duplicate["bucket-source"]["id"] = duplicate["bucket-backup"]["id"]
    with pytest.raises(MODEL.DataProtectionError, match="repeated"):
        MODEL.register_source_resources(topology(), preflight(), duplicate)


def test_happy_path_reaches_complete_failure_matrix() -> None:
    state = complete_state()

    assert state["phase"] == "failures-verified"
    assert len(state["resources"]) == len(topology().resource_keys)
    assert set(state["evidence"]["failure_outcomes"]) == set(
        topology().failure_cases
    )
    assert len(state["history"]) == len(topology().phases) - 1


def test_out_of_order_transition_is_refused_without_key_error() -> None:
    with pytest.raises(MODEL.DataProtectionError, match="requires phase"):
        MODEL.mark_writers_excluded(
            topology(),
            source_created(),
            writer_fence(),
        )
    with pytest.raises(MODEL.DataProtectionError, match="requires phase"):
        MODEL.mark_restore_verified(
            topology(),
            through_inventory(),
            restore_evidence(),
        )


def test_writer_fence_requires_zero_writers_and_stable_source() -> None:
    for field, value in (
        ("active_uploads", 1),
        ("unknown_listeners", 1),
        ("canary_write_status", 200),
        ("digest_read_status", 503),
        ("source_signature", f"sha256:{'f' * 64}"),
    ):
        evidence = writer_fence()
        evidence[field] = value
        with pytest.raises(MODEL.DataProtectionError, match="writer fence|signature"):
            MODEL.mark_writers_excluded(
                topology(),
                through_fixture(),
                evidence,
            )


def test_backup_requires_restore_digest_and_no_multipart_residue() -> None:
    sql = sql_backup()
    sql["restore_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(MODEL.DataProtectionError, match="SQL restore digest"):
        MODEL.mark_backups_verified(
            topology(),
            through_fence(),
            sql,
            rgw_backup(),
        )

    rgw = rgw_backup()
    rgw["multipart_upload_count"] = 1
    with pytest.raises(MODEL.DataProtectionError, match="multipart"):
        MODEL.mark_backups_verified(
            topology(),
            through_fence(),
            sql_backup(),
            rgw,
        )

    rgw = rgw_backup()
    rgw["restored"] = False
    with pytest.raises(MODEL.DataProtectionError, match="not restored"):
        MODEL.mark_backups_verified(
            topology(),
            through_fence(),
            sql_backup(),
            rgw,
        )


def test_inventory_requires_equal_scans_positive_counts_and_stable_source() -> None:
    for field, value in (
        ("scans_equal", False),
        ("scan_two_sha256", f"sha256:{'f' * 64}"),
        ("manifest_count", 0),
        ("source_signature", f"sha256:{'f' * 64}"),
    ):
        evidence = inventory_evidence()
        evidence[field] = value
        with pytest.raises(MODEL.DataProtectionError, match="inventory|source signature"):
            MODEL.mark_inventory_verified(
                topology(),
                through_backups(),
                evidence,
            )


def test_import_and_live_comparison_require_exact_inventory() -> None:
    imported = baseline_import()
    imported["inventory_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(MODEL.DataProtectionError, match="import evidence"):
        MODEL.mark_baseline_imported(
            topology(),
            through_inventory(),
            imported,
        )

    comparison = live_comparison()
    comparison["private_tls_verified"] = False
    with pytest.raises(MODEL.DataProtectionError, match="comparison evidence"):
        MODEL.mark_live_comparison_verified(
            topology(),
            through_import(),
            comparison,
        )


def test_cutover_requires_edge_only_routing_and_complete_matrix() -> None:
    cutover = admission_cutover()
    cutover["direct_registry_closed"] = False
    with pytest.raises(MODEL.DataProtectionError, match="routing"):
        MODEL.mark_admission_cutover(
            topology(),
            through_live_comparison(),
            cutover,
        )

    cutover = admission_cutover()
    cutover["marker_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(MODEL.DataProtectionError, match="provenance-bound"):
        MODEL.mark_admission_cutover(
            topology(),
            through_live_comparison(),
            cutover,
        )

    verification = cutover_verification()
    verification["over_quota_429"] = False
    with pytest.raises(MODEL.DataProtectionError, match="matrix"):
        MODEL.mark_cutover_verified(
            topology(),
            through_admission(),
            verification,
        )


def test_rollback_restore_and_failure_matrix_are_exact() -> None:
    rollback = rollback_evidence()
    rollback["ambiguous_differences"] = 1
    with pytest.raises(MODEL.DataProtectionError, match="rollback evidence"):
        MODEL.mark_rollback_verified(
            topology(),
            through_cutover(),
            rollback,
        )

    rollback = rollback_evidence()
    rollback["removed_post_cutover_write_count"] = 0
    with pytest.raises(MODEL.DataProtectionError, match="rollback evidence"):
        MODEL.mark_rollback_verified(
            topology(),
            through_cutover(),
            rollback,
        )

    restore = restore_evidence()
    restore["rgw_manifest_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(MODEL.DataProtectionError, match="restore evidence"):
        MODEL.mark_restore_verified(
            topology(),
            through_rollback(),
            restore,
        )

    outcomes = failure_outcomes()
    outcomes.pop("replica-loss")
    with pytest.raises(MODEL.DataProtectionError, match="failure matrix"):
        MODEL.mark_failures_verified(
            topology(),
            through_restore(),
            outcomes,
        )


def test_cleanup_plan_uses_dependency_order_and_exact_targets() -> None:
    state = complete_state()
    plan = MODEL.cleanup_plan(topology(), state)
    ranks = [
        topology().cleanup_order.index(item["kind"])
        for item in plan
    ]

    assert ranks == sorted(ranks)
    assert plan[0]["kind"] == "maintenance_session"
    assert plan[-1]["kind"] == "network"
    MODEL.assert_exact_cleanup_target(topology(), state, plan[0])

    with pytest.raises(MODEL.DataProtectionError, match="fields"):
        MODEL.assert_exact_cleanup_target(
            topology(),
            state,
            {"kind": plan[0]["kind"], "name": plan[0]["name"]},
        )
    wrong = deepcopy(plan[0])
    wrong["id"] = "immutable-wrong-target"
    with pytest.raises(MODEL.DataProtectionError, match="exact owned"):
        MODEL.assert_exact_cleanup_target(topology(), state, wrong)


def test_teardown_requires_exact_order_zero_residue_and_unchanged_unrelated() -> None:
    state = complete_state()
    plan = MODEL.cleanup_plan(topology(), state)

    with pytest.raises(MODEL.DataProtectionError, match="cleanup plan"):
        MODEL.finalize_teardown(
            topology(),
            state,
            list(reversed(plan)),
            zero_residue(),
            UNRELATED_SIGNATURE,
        )
    with pytest.raises(MODEL.DataProtectionError, match="zeroes"):
        MODEL.finalize_teardown(
            topology(),
            state,
            plan,
            {"resources": 1},
            UNRELATED_SIGNATURE,
        )
    with pytest.raises(MODEL.DataProtectionError, match="unrelated"):
        MODEL.finalize_teardown(
            topology(),
            state,
            plan,
            zero_residue(),
            f"sha256:{'f' * 64}",
        )

    terminal = MODEL.finalize_teardown(
        topology(),
        state,
        plan,
        zero_residue(),
        UNRELATED_SIGNATURE,
        now=NOW,
    )
    assert terminal["phase"] == "torn-down"
    assert terminal["resources"] == []
    assert MODEL.finalize_teardown(
        topology(),
        terminal,
        [],
        terminal["residue_counts"],
        UNRELATED_SIGNATURE,
    ) == terminal


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "do-not-retain"},
        {"nested": {"private_key": "do-not-retain"}},
        {"message": "Authorization: Basic do-not-retain"},
        {"message": "Bearer abcdefghijklmnopqrstuvwxyz"},
        {"message": "-----BEGIN PRIVATE KEY-----"},
        {"message": "eyJabcdefghijk.abcdefghijklmnop.signature"},
    ],
)
def test_retained_payload_rejects_secret_fields_and_patterns(payload) -> None:
    with pytest.raises(MODEL.DataProtectionError, match="forbidden|secret pattern"):
        MODEL.validate_retained_payload(payload)


def test_redacted_evidence_hashes_ids_and_known_secrets() -> None:
    state = complete_state()
    evidence = MODEL.redacted_evidence(
        topology(),
        state,
        known_secrets=["never-retain-this-secret"],
    )
    serialized = json.dumps(evidence, sort_keys=True)

    assert evidence["schema"] == MODEL.EVIDENCE_SCHEMA
    assert evidence["phase"] == "failures-verified"
    assert evidence["resource_id_hashes"]
    assert "immutable-" not in serialized
    assert "never-retain-this-secret" not in serialized

    with pytest.raises(MODEL.DataProtectionError, match="known secret"):
        MODEL.validate_retained_payload(
            {"message": "prefix never-retain-this-secret suffix"},
            known_secrets=["never-retain-this-secret"],
        )


def test_state_tampering_is_refused() -> None:
    state = complete_state()
    tampered = deepcopy(state)
    tampered["topology_digest"] = f"sha256:{'f' * 64}"
    with pytest.raises(MODEL.DataProtectionError, match="does not match"):
        MODEL.validate_state(topology(), tampered)

    tampered = deepcopy(state)
    tampered["resources"][0]["name"] = "other-resource"
    with pytest.raises(MODEL.DataProtectionError, match="allowlist"):
        MODEL.validate_state(topology(), tampered)

    tampered = deepcopy(state)
    tampered["evidence"].pop("writer_fence")
    with pytest.raises(MODEL.DataProtectionError, match="evidence"):
        MODEL.validate_state(topology(), tampered)

    tampered = deepcopy(state)
    tampered["history"][-1]["action"] = "skip-failure-matrix"
    with pytest.raises(MODEL.DataProtectionError, match="history"):
        MODEL.validate_state(topology(), tampered)
