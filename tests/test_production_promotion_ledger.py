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
        "candidate_count": ledger.GC_RESULT.EXPECTED_CANDIDATES,
        "candidate_set_hash": f"sha256:{'1' * 64}",
        "cleanup_verified": True,
        "delete_untagged": False,
        "distribution": {
            "image": ledger.GC_RESULT.IMAGE,
            "revision": ledger.GC_RESULT.REVISION,
            "version": ledger.GC_RESULT.VERSION,
        },
        "dry_run_count": 2,
        "logical_bytes_reclaimed": (
            ledger.GC_RESULT.EXPECTED_RECLAIMED_BYTES
        ),
        "physical_backend": "filesystem",
        "residue": {
            "containers": 0,
            "networks": 0,
            "runtime_paths": 0,
            "total": 0,
        },
        "restore_verified": True,
        "schema": ledger.GC_RESULT.SCHEMA,
        "source": ledger.GC_RESULT.source_hashes(),
        "survivor_class_count": ledger.GC_RESULT.EXPECTED_SURVIVORS,
        "survivor_classes_hash": f"sha256:{'2' * 64}",
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


def test_blocked_release_and_passed_gc_are_reported_independently() -> None:
    result = ledger.compile_ledger(
        release_readiness=release(),
        release_digest=f"sha256:{'3' * 64}",
        gc_result=gc_result(),
        gc_digest=f"sha256:{'4' * 64}",
        today=date(2026, 7, 28),
    )
    gates = {gate["id"]: gate for gate in result["gates"]}

    assert result["status"] == "blocked"
    assert result["production_candidate"] is False
    assert result["blocked_gates"] == ["release_inputs"]
    assert result["passed_gate_count"] == 1
    assert gates["release_inputs"]["status"] == "blocked"
    assert gates["gc_retention"]["status"] == "passed"
    assert gates["gc_retention"]["evidence"] == {
        "schema": ledger.GC_RESULT.SCHEMA,
        "sha256": f"sha256:{'4' * 64}",
    }
    assert len(result["pending_gates"]) == 8


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
