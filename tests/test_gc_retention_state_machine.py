from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "poc" / "gc-retention" / "state_machine.py"
)
TOPOLOGY_PATH = ROOT / "poc" / "gc-retention" / "topology.json"
INVOCATION_ID = "01j00000000000000000000000"
TIMES = tuple(
    f"2026-07-25T00:{minute:02d}:00Z"
    for minute in range(17)
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MODEL = _load_module("coffer_gc_retention_state_tests", MODULE_PATH)


def digest(label: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def topology() -> dict:
    return MODEL.load_topology(TOPOLOGY_PATH)


def resources() -> dict[str, str]:
    return {
        key: f"coffer-gc-{INVOCATION_ID}-{key}"
        for key in MODEL.EXPECTED_RESOURCE_KEYS
    }


def initial_state() -> dict:
    return MODEL.create_state(
        topology(),
        invocation_id=INVOCATION_ID,
        resources=resources(),
        unrelated_signature=digest("unrelated"),
        created_at=TIMES[0],
    )


def evidence_for(action: str, state: dict) -> dict:
    if action == "preflight":
        return {
            "target_class": "disposable-fixture",
            "distribution_version": "v3.1.1",
            "distribution_revision": (
                "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
            ),
            "image_digest": digest("image"),
            "config_hash": digest("config"),
            "backend_hash": digest("backend"),
            "delete_untagged": False,
            "candidate_limit": 1000,
        }
    if action == "create-source":
        return {
            "owned_signature": digest("owned"),
            "unrelated_signature": digest("unrelated"),
        }
    if action == "populate-fixture":
        return {
            "fixture_hash": digest("fixture"),
            "retained_set_hash": digest("retained"),
            "deleted_set_hash": digest("deleted"),
            "counts": {
                "manifest": 6,
                "shared_blob": 1,
                "index": 1,
                "digest_only": 1,
                "referrer": 1,
            },
        }
    if action == "apply-logical-delete":
        return {
            "policy_hash": digest("policy"),
            "deleted_set_hash": digest("deleted"),
            "deleted_manifest_count": 1,
        }
    if action == "exclude-writers":
        return {
            "fence_hash": digest("fence"),
            "fence_epoch": "writer-fence-epoch-0001",
            "replica_count": 2,
            "write_probe_count": 8,
            "active_upload_count": 0,
            "multipart_upload_count": 0,
            "background_mutator_count": 0,
            "all_read_only": True,
        }
    if action == "verify-backups":
        return {
            "fence_hash": digest("fence"),
            "sql_backup_hash": digest("sql-backup"),
            "rgw_backup_hash": digest("rgw-backup"),
            "isolated_restore_hash": digest("isolated-restore"),
            "object_version_count": 60,
            "delete_marker_count": 2,
            "multipart_upload_count": 0,
            "kms_verified": True,
        }
    if action == "verify-baseline":
        return {
            "fence_hash": digest("fence"),
            "inventory_hash": digest("inventory"),
            "sql_hash": digest("sql-state"),
            "retained_set_hash": digest("retained"),
            "expected_candidate_set_hash": digest("deleted"),
            "current_object_count": 50,
            "object_version_count": 60,
            "delete_marker_count": 2,
        }
    if action in {"verify-dry-run-one", "verify-dry-run-two"}:
        return {
            "fence_hash": digest("fence"),
            "image_digest": digest("image"),
            "distribution_revision": (
                "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
            ),
            "config_hash": digest("config"),
            "backend_hash": digest("backend"),
            "baseline_hash": digest("inventory"),
            "candidate_set_hash": digest("deleted"),
            "summary_hash": digest("dry-run-summary"),
            "eligible_blob_count": 4,
            "eligible_manifest_count": 0,
            "eligible_link_count": 2,
            "candidate_total": 6,
        }
    if action == "authorize-collection":
        return {
            "authorization_id": "coffer-gc-authority-0001",
            "issued_at": TIMES[10],
            "expires_at": TIMES[15],
            "binding_hash": MODEL.collection_binding(state),
            "command_hash": digest("registry-gc-command"),
            "candidate_set_hash": digest("deleted"),
            "delete_untagged": False,
        }
    if action == "execute-collection":
        authority = state["collection_authority"]
        return {
            "authorization_id": authority["authorization_id"],
            "binding_hash": authority["binding_hash"],
            "candidate_set_hash": authority["candidate_set_hash"],
            "fence_hash": digest("fence"),
            "exit_code": 0,
            "collector_result_hash": digest("collector-result"),
        }
    if action == "verify-survivors":
        return {
            "fence_hash": digest("fence"),
            "retained_set_hash": digest("retained"),
            "sql_hash": digest("sql-state"),
            "missing_survivor_count": 0,
            "deleted_readable_count": 0,
            "survivor_classes": {
                name: True for name in MODEL.EXPECTED_SURVIVOR_CLASSES
            },
        }
    if action == "verify-reclaim":
        return {
            "current_object_count_before": 50,
            "current_object_count_after": 45,
            "current_bytes_before": 1000,
            "current_bytes_after": 700,
            "object_version_count_before": 60,
            "object_version_count_after": 63,
            "delete_marker_count_before": 2,
            "delete_marker_count_after": 5,
            "logical_reclaimed_bytes": 300,
            "physical_reclaimed_bytes_observed": 0,
            "rgw_lifecycle_ran": False,
            "orphan_delete_ran": False,
        }
    if action == "verify-restore":
        return {
            "isolated": True,
            "kms_verified": True,
            "restore_inventory_hash": digest("inventory"),
            "restored_digest_count": 9,
            "mismatch_count": 0,
        }
    if action == "verify-failures":
        return {
            "outcomes": {
                name: "refused"
                for name in MODEL.EXPECTED_FAILURE_CASES
            }
        }
    if action == "teardown":
        return {
            "residue": {
                name: 0 for name in MODEL.EXPECTED_RESIDUE_KEYS
            },
            "unrelated_signature": digest("unrelated"),
        }
    raise AssertionError(f"unknown action {action}")


def advance_to(target_action: str) -> dict:
    state = initial_state()
    for index, action in enumerate(MODEL.EXPECTED_ACTIONS, start=1):
        state = MODEL.advance(
            topology(),
            state,
            action=action,
            evidence=evidence_for(action, state),
            at=TIMES[index],
        )
        if action == target_action:
            return state
    raise AssertionError(f"unknown target action {target_action}")


def test_checked_in_topology_fixes_the_complete_contract() -> None:
    loaded = topology()

    assert loaded["schema"] == MODEL.TOPOLOGY_SCHEMA
    assert tuple(loaded["phases"]) == MODEL.EXPECTED_PHASES
    assert tuple(loaded["resource_keys"]) == MODEL.EXPECTED_RESOURCE_KEYS
    assert tuple(loaded["cleanup_order"]) == MODEL.EXPECTED_CLEANUP_ORDER
    assert tuple(loaded["residue_keys"]) == MODEL.EXPECTED_RESIDUE_KEYS
    assert tuple(loaded["survivor_classes"]) == (
        MODEL.EXPECTED_SURVIVOR_CLASSES
    )
    assert tuple(loaded["failure_cases"]) == MODEL.EXPECTED_FAILURE_CASES
    assert loaded["collector"] == {
        "distribution_version": "v3.1.1",
        "distribution_revision": (
            "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
        ),
        "allow_delete_untagged": False,
        "candidate_limit": 1000,
        "authorization_ttl_seconds": 900,
        "dry_run_count": 2,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_class", "production"),
        ("phases", ["preflighted", "torn-down"]),
        ("resource_keys", ["bucket-source"]),
        ("cleanup_order", ["bucket"]),
        ("survivor_classes", ["tagged-manifest"]),
        ("failure_cases", ["collector-interrupted"]),
        (
            "collector",
            {
                "distribution_version": "v3.1.1",
                "distribution_revision": (
                    "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
                ),
                "allow_delete_untagged": True,
                "candidate_limit": 1000,
                "authorization_ttl_seconds": 900,
                "dry_run_count": 2,
            },
        ),
    ],
)
def test_topology_expansion_or_weakening_is_refused(field, value) -> None:
    raw = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    raw[field] = value

    with pytest.raises(MODEL.GCRetentionError, match="fixed|disposable"):
        MODEL.validate_topology(raw)


def test_complete_pure_lifecycle_reaches_zero_residue() -> None:
    state = advance_to("teardown")
    public = MODEL.public_evidence(topology(), state)

    assert state["phase"] == "torn-down"
    assert state["collection_authority"]["consumed"] is True
    assert [item["phase"] for item in state["history"]] == [
        "initialized",
        *MODEL.EXPECTED_PHASES,
    ]
    assert public["schema"] == MODEL.EVIDENCE_SCHEMA
    assert public["phase"] == "torn-down"
    assert public["authority"]["consumed"] is True
    serialized = json.dumps(public, sort_keys=True)
    assert INVOCATION_ID not in serialized
    assert not any(value in serialized for value in resources().values())


def test_phase_skip_or_replay_is_refused_without_mutation() -> None:
    state = initial_state()
    before = deepcopy(state)

    with pytest.raises(MODEL.GCRetentionError, match="expected action"):
        MODEL.advance(
            topology(),
            state,
            action="create-source",
            evidence=evidence_for("create-source", state),
            at=TIMES[1],
        )

    assert state == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values.pop("bucket-source"),
        lambda values: values.update(
            {"bucket-source": values["bucket-backup"]}
        ),
        lambda values: values.update(
            {"bucket-source": "production-bucket"}
        ),
    ],
)
def test_incomplete_ambiguous_or_non_owned_resources_are_refused(
    mutation,
) -> None:
    owned = resources()
    mutation(owned)

    with pytest.raises(MODEL.GCRetentionError, match="resource|ownership"):
        MODEL.create_state(
            topology(),
            invocation_id=INVOCATION_ID,
            resources=owned,
            unrelated_signature=digest("unrelated"),
            created_at=TIMES[0],
        )


def test_delete_untagged_is_refused_at_preflight_and_authorization() -> None:
    state = initial_state()
    preflight = evidence_for("preflight", state)
    preflight["delete_untagged"] = True

    with pytest.raises(MODEL.GCRetentionError, match="delete-untagged"):
        MODEL.advance(
            topology(),
            state,
            action="preflight",
            evidence=preflight,
            at=TIMES[1],
        )

    state = advance_to("verify-dry-run-two")
    authority = evidence_for("authorize-collection", state)
    authority["delete_untagged"] = True
    with pytest.raises(MODEL.GCRetentionError, match="delete-untagged"):
        MODEL.advance(
            topology(),
            state,
            action="authorize-collection",
            evidence=authority,
            at=TIMES[10],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("replica_count", 1, "replica"),
        ("write_probe_count", 5, "writer path"),
        ("active_upload_count", 1, "active_upload"),
        ("multipart_upload_count", 1, "multipart"),
        ("background_mutator_count", 1, "background"),
        ("all_read_only", False, "read-only"),
    ],
)
def test_compound_writer_fence_fails_closed(field, value, message) -> None:
    state = advance_to("apply-logical-delete")
    fence = evidence_for("exclude-writers", state)
    fence[field] = value

    with pytest.raises(MODEL.GCRetentionError, match=message):
        MODEL.advance(
            topology(),
            state,
            action="exclude-writers",
            evidence=fence,
            at=TIMES[5],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fence_hash", digest("wrong"), "fence"),
        ("object_version_count", 0, "object version"),
        ("multipart_upload_count", 1, "multipart"),
        ("kms_verified", False, "KMS"),
    ],
)
def test_incomplete_or_drifted_backup_is_refused(
    field,
    value,
    message,
) -> None:
    state = advance_to("exclude-writers")
    backups = evidence_for("verify-backups", state)
    backups[field] = value

    with pytest.raises(MODEL.GCRetentionError, match=message):
        MODEL.advance(
            topology(),
            state,
            action="verify-backups",
            evidence=backups,
            at=TIMES[6],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_set_hash", digest("drift")),
        ("summary_hash", digest("different-output")),
        ("candidate_total", 7),
        ("eligible_blob_count", 1001),
    ],
)
def test_dry_run_drift_or_unbounded_candidates_are_refused(
    field,
    value,
) -> None:
    state = advance_to("verify-dry-run-one")
    second = evidence_for("verify-dry-run-two", state)
    second[field] = value

    with pytest.raises(
        MODEL.GCRetentionError,
        match="differ|binding|total|limit",
    ):
        MODEL.advance(
            topology(),
            state,
            action="verify-dry-run-two",
            evidence=second,
            at=TIMES[9],
        )


def test_authorization_is_finite_bound_single_use_and_expiry_checked() -> None:
    authorized = advance_to("authorize-collection")
    execution = evidence_for("execute-collection", authorized)

    expired = deepcopy(authorized)
    with pytest.raises(MODEL.GCRetentionError, match="expired"):
        MODEL.advance(
            topology(),
            expired,
            action="execute-collection",
            evidence=execution,
            at="2026-07-25T00:16:00Z",
        )

    consumed = deepcopy(authorized)
    consumed["collection_authority"]["consumed"] = True
    with pytest.raises(MODEL.GCRetentionError, match="consumed"):
        MODEL.advance(
            topology(),
            consumed,
            action="execute-collection",
            evidence=execution,
            at=TIMES[11],
        )

    drifted = deepcopy(execution)
    drifted["fence_hash"] = digest("new-fence")
    with pytest.raises(MODEL.GCRetentionError, match="fence"):
        MODEL.advance(
            topology(),
            authorized,
            action="execute-collection",
            evidence=drifted,
            at=TIMES[11],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("missing_survivor_count", 1, "survivor"),
        ("deleted_readable_count", 1, "readable"),
        ("sql_hash", digest("changed-sql"), "SQL"),
    ],
)
def test_survivor_and_sql_gates_fail_closed(field, value, message) -> None:
    state = advance_to("execute-collection")
    survivor = evidence_for("verify-survivors", state)
    survivor[field] = value

    with pytest.raises(MODEL.GCRetentionError, match=message):
        MODEL.advance(
            topology(),
            state,
            action="verify-survivors",
            evidence=survivor,
            at=TIMES[12],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("current_object_count_after", 50, "logical"),
        ("logical_reclaimed_bytes", 301, "logical"),
        ("rgw_lifecycle_ran", True, "lifecycle"),
        ("orphan_delete_ran", True, "orphan"),
    ],
)
def test_reclaim_keeps_rgws_lower_level_cleanup_separate(
    field,
    value,
    message,
) -> None:
    state = advance_to("verify-survivors")
    reclaim = evidence_for("verify-reclaim", state)
    reclaim[field] = value

    with pytest.raises(MODEL.GCRetentionError, match=message):
        MODEL.advance(
            topology(),
            state,
            action="verify-reclaim",
            evidence=reclaim,
            at=TIMES[13],
        )


def test_restore_must_be_isolated_kms_verified_and_exact() -> None:
    state = advance_to("verify-reclaim")

    for field, value in (
        ("isolated", False),
        ("kms_verified", False),
        ("restore_inventory_hash", digest("wrong")),
        ("mismatch_count", 1),
    ):
        restore = evidence_for("verify-restore", state)
        restore[field] = value
        with pytest.raises(MODEL.GCRetentionError, match="restore|KMS|differs"):
            MODEL.advance(
                topology(),
                state,
                action="verify-restore",
                evidence=restore,
                at=TIMES[14],
            )


def test_all_fixed_failures_and_zero_residue_are_required() -> None:
    state = advance_to("verify-restore")
    failures = evidence_for("verify-failures", state)
    failures["outcomes"].pop("collector-interrupted")
    with pytest.raises(MODEL.GCRetentionError, match="exact fixed"):
        MODEL.advance(
            topology(),
            state,
            action="verify-failures",
            evidence=failures,
            at=TIMES[15],
        )

    state = advance_to("verify-failures")
    teardown = evidence_for("teardown", state)
    teardown["residue"]["locks"] = 1
    with pytest.raises(MODEL.GCRetentionError, match="residue"):
        MODEL.advance(
            topology(),
            state,
            action="teardown",
            evidence=teardown,
            at=TIMES[16],
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("token", "opaque-secret"),
        ("password", "password-value"),
        ("repository_name", "private/repository"),
        ("safe", "Authorization: Bearer opaque-secret-value"),
        ("safe", "-----BEGIN PRIVATE KEY-----"),
        ("safe", "eyJabcdefgh.abcdefgh.signature"),
    ],
)
def test_secret_or_tenant_evidence_is_refused(key, value) -> None:
    state = initial_state()
    preflight = evidence_for("preflight", state)
    preflight[key] = value

    with pytest.raises(MODEL.GCRetentionError, match="forbidden|secret"):
        MODEL.advance(
            topology(),
            state,
            action="preflight",
            evidence=preflight,
            at=TIMES[1],
        )


def test_state_history_or_evidence_tampering_is_refused() -> None:
    state = advance_to("verify-dry-run-two")
    state["evidence"]["dry-run-two-verified"]["summary_hash"] = digest("tamper")

    with pytest.raises(MODEL.GCRetentionError, match="history"):
        MODEL.public_evidence(topology(), state)


def test_model_imports_no_network_sql_s3_or_subprocess_runtime() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    for forbidden in (
        "import boto",
        "import requests",
        "import socket",
        "import sqlalchemy",
        "import subprocess",
        "urllib",
    ):
        assert forbidden not in source
