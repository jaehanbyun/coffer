from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "rgw_kms.py"
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_rgw_kms",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
rgw_kms = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rgw_kms
SPEC.loader.exec_module(rgw_kms)


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
        "schema": rgw_kms.RELEASE_SCHEMA,
        "source": rgw_kms._release_sources(),
        "status": status,
        "ui_observed_on": "2026-07-28",
    }


def evidence() -> dict[str, object]:
    return {
        "cleanup": {
            "delete_markers_after": 0,
            "delete_markers_before": 2,
            "multipart_uploads_after": 0,
            "multipart_uploads_before": 1,
            "object_versions_after": 0,
            "object_versions_before": 6,
            "objects_after": 0,
            "objects_before": 4,
        },
        "execution": {
            "cleanup_evidence_sha256": f"sha256:{'1' * 64}",
            "least_privilege_evidence_sha256": f"sha256:{'2' * 64}",
            "non_synthetic": True,
            "phase_completion_sha256": {
                phase: f"sha256:{digit * 64}"
                for phase, digit in zip(
                    rgw_kms.PHASES,
                    ("3", "4", "5"),
                    strict=True,
                )
            },
            "phase_count": 3,
            "restart_evidence_sha256": f"sha256:{'6' * 64}",
            "rotation_evidence_sha256": f"sha256:{'7' * 64}",
        },
        "faults": {
            "kms_outage": {
                "evidence_sha256": f"sha256:{'8' * 64}",
                "failed_closed": True,
                "recovered": True,
            },
            "wrong_key": {
                "evidence_sha256": f"sha256:{'9' * 64}",
                "failed_closed": True,
                "recovered": True,
            },
        },
        "operations": {name: True for name in rgw_kms.OPERATIONS},
        "release_inputs": {
            "ceph": {
                "revision": "b" * 40,
                "version": "v20.2.3",
            },
            "distribution": {
                "revision": "a" * 40,
                "version": "v3.2.0",
            },
        },
        "release_readiness_sha256": f"sha256:{'d' * 64}",
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
        "schema": rgw_kms.EVIDENCE_SCHEMA,
        "source": rgw_kms.runtime_source_hashes(),
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


def compile_inputs() -> dict[str, object]:
    return {
        "evidence": evidence(),
        "evidence_digest": f"sha256:{'e' * 64}",
        "release_digest": f"sha256:{'d' * 64}",
        "release_readiness": release(),
    }


def _write_private(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_compiles_complete_live_rgw_kms_evidence() -> None:
    result = rgw_kms.compile_result(**compile_inputs())

    assert result["schema"] == rgw_kms.SCHEMA
    assert result["production_candidate"] is True
    assert result["operations"]["copy_zero"] is True
    assert result["faults"]["wrong_key"]["recovered"] is True
    assert result["cleanup"]["multipart_uploads_before"] == 1
    assert rgw_kms.validate_final_result(result) == result


def test_blocked_release_refuses_before_evidence_validation() -> None:
    inputs = compile_inputs()
    inputs["release_readiness"] = release(False)
    inputs["evidence"] = {}

    with pytest.raises(
        rgw_kms.RgwKmsInputsBlocked,
        match="not candidate-qualified",
    ):
        rgw_kms.compile_result(**inputs)


def test_zero_byte_copy_and_fault_recovery_fail_closed() -> None:
    missing_zero_copy = compile_inputs()
    missing_zero_copy["evidence"]["operations"]["copy_zero"] = False
    with pytest.raises(
        rgw_kms.RgwKmsResultError,
        match="operation coverage",
    ):
        rgw_kms.compile_result(**missing_zero_copy)

    missing_recovery = compile_inputs()
    missing_recovery["evidence"]["faults"]["kms_outage"]["recovered"] = False
    with pytest.raises(
        rgw_kms.RgwKmsResultError,
        match="kms_outage recovery",
    ):
        rgw_kms.compile_result(**missing_recovery)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("cleanup", "multipart_uploads_before", 0, "cleanup"),
        ("cleanup", "object_versions_after", 1, "cleanup"),
        ("residue", "selected_kms_keys", 1, "residue"),
        ("rotation", "generation_count", 1, "rotation"),
        ("restart", "rgw_restart_count", 0, "restart count"),
        ("transport", "least_privilege_verified", False, "least privilege"),
        ("unexpected_errors", "kms", 1, "unexpected errors"),
    ],
)
def test_cleanup_rotation_restart_and_residue_fail_closed(
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    inputs = compile_inputs()
    inputs["evidence"][section][field] = value
    with pytest.raises(rgw_kms.RgwKmsResultError, match=message):
        rgw_kms.compile_result(**inputs)


def test_release_identity_and_runtime_source_drift_fail_closed() -> None:
    changed_release = compile_inputs()
    changed_release["evidence"]["release_inputs"]["ceph"]["revision"] = (
        "f" * 40
    )
    with pytest.raises(rgw_kms.RgwKmsResultError, match="binding"):
        rgw_kms.compile_result(**changed_release)

    changed_source = compile_inputs()
    changed_source["evidence"]["source"]["rgw_cleanup_sha256"] = (
        f"sha256:{'f' * 64}"
    )
    with pytest.raises(rgw_kms.RgwKmsResultError, match="binding"):
        rgw_kms.compile_result(**changed_source)


def test_cli_blocks_before_missing_evidence_is_opened(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    output = directory / "result.json"
    _write_private(release_path, release(False))

    result = rgw_kms.main(
        [
            "--release-readiness",
            str(release_path),
            "--evidence",
            str(directory / "missing-evidence.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert "not candidate-qualified" in capsys.readouterr().err


def test_cli_writes_owner_only_result(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    evidence_path = directory / "evidence.json"
    output = directory / "result.json"
    release_payload = (
        json.dumps(release(), separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    release_path.write_bytes(release_payload)
    release_path.chmod(0o600)
    value = evidence()
    value["release_readiness_sha256"] = rgw_kms._sha256_bytes(
        release_payload
    )
    _write_private(evidence_path, value)

    result = rgw_kms.main(
        [
            "--release-readiness",
            str(release_path),
            "--evidence",
            str(evidence_path),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert rgw_kms.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True


def test_final_result_rejects_source_or_zero_residue_tamper() -> None:
    result = rgw_kms.compile_result(**compile_inputs())
    changed_source = deepcopy(result)
    changed_source["source"]["rgw_kms_compiler_sha256"] = f"sha256:{'0' * 64}"
    with pytest.raises(rgw_kms.RgwKmsResultError, match="not qualified"):
        rgw_kms.validate_final_result(changed_source)

    changed_residue = deepcopy(result)
    changed_residue["residue"]["log_secrets"] = 1
    changed_residue["residue"]["total"] = 1
    with pytest.raises(rgw_kms.RgwKmsResultError, match="residue"):
        rgw_kms.validate_final_result(changed_residue)
