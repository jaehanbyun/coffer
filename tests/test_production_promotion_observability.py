from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "observability.py"
DATA_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_data_protection.py"
)


def _load(name: str, path: Path) -> object:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


observability = _load(
    "coffer_test_production_promotion_observability",
    SOURCE,
)
data_test = _load(
    "coffer_observability_data_test_helpers",
    DATA_TEST_SOURCE,
)

RELEASE_DIGEST = f"sha256:{'1' * 64}"
ARTIFACT_DIGEST = f"sha256:{'2' * 64}"
RGW_KMS_DIGEST = f"sha256:{'3' * 64}"
MAINTENANCE_DIGEST = f"sha256:{'4' * 64}"
DATA_PROTECTION_DIGEST = f"sha256:{'5' * 64}"


def data_protection_result() -> dict[str, object]:
    return data_test.data.compile_result(**data_test.compile_inputs())


def prerequisites() -> dict[str, str]:
    return {
        "artifact_result_sha256": ARTIFACT_DIGEST,
        "data_protection_result_sha256": DATA_PROTECTION_DIGEST,
        "maintenance_identity_result_sha256": MAINTENANCE_DIGEST,
        "release_readiness_sha256": RELEASE_DIGEST,
        "rgw_kms_result_sha256": RGW_KMS_DIGEST,
    }


def evidence(
    prerequisite_values: dict[str, str] | None = None,
) -> dict[str, object]:
    topology = observability._topology()
    component_counts = {"api": 2, "edge": 2, "reconcile": 1, "registry": 2}
    return {
        "alerts": {
            name: {
                "evidence_sha256": f"sha256:{index:x}" + "0" * 63,
                "fired": True,
                "recovered": True,
            }
            for index, name in enumerate(topology.raw["alerts"], start=1)
        },
        "audit": {
            "alert_evaluation_count": 200,
            "forbidden_label_matches": 0,
            "known_secret_matches": 0,
            "log_scan_count": 100,
            "sample_count": 1_000,
            "unexpected_errors": 0,
        },
        "dependencies": {
            name: True
            for name in topology.raw["application_labels"]["dependency"]
        },
        "evidence_sha256": {
            name: f"sha256:{digit * 64}"
            for name, digit in zip(
                (
                    "alerts_sha256",
                    "audit_sha256",
                    "dependencies_sha256",
                    "failure_budget_sha256",
                    "metric_schema_sha256",
                    "restarts_sha256",
                    "targets_sha256",
                    "teardown_sha256",
                    "transport_sha256",
                ),
                ("6", "7", "8", "9", "a", "b", "c", "d", "e"),
                strict=True,
            )
        },
        "execution": {
            "adapter": "openstack",
            "disposable": True,
            "non_synthetic": True,
            "pilot_window_seconds": 1_800,
        },
        "failure_budget": {
            "client_failures_excluded": True,
            "dependency_failures_counted": True,
            "fast_burn_verified": True,
            "maintenance_fences_excluded": True,
            "objective_basis_points": dict(observability.OBJECTIVES),
            "policy_days": 30,
            "recovery_cleared": True,
            "slow_burn_verified": True,
            "work_freeze_verified": True,
        },
        "metric_schema": {
            "alert_count": len(topology.raw["alerts"]),
            "bounded_labels": True,
            "counter_reset_requires_new_start": True,
            "dashboard_row_count": len(topology.raw["dashboard_rows"]),
            "duplicate_healthy_series": 0,
            "forbidden_label_count": 0,
            "process_start_present": True,
            "recording_rule_count": len(topology.raw["recording_rules"]),
            "required_series_present": True,
            "schema_consistent": True,
            "scrape_interval_seconds": topology.raw[
                "scrape_interval_seconds"
            ],
            "stale_after_seconds": topology.raw["stale_after_seconds"],
            "stale_series_removed": True,
            "worker_count_per_container": 1,
        },
        "prerequisites": prerequisite_values or prerequisites(),
        "residue": {
            **{name: 0 for name in observability.RESIDUE_KEYS},
            "known_secret_matches": 0,
            "total": 0,
        },
        "restarts": {
            "availability_maintained": True,
            "component_restart_counts": dict(component_counts),
            "counter_resets_valid": True,
            "no_duplicate_healthy_series": True,
            "recording_rules_continuous": True,
            "rolling_restart": True,
            "rolling_rollback": True,
            "rolling_upgrade": True,
            "stale_series_removed": True,
        },
        "schema": observability.EVIDENCE_SCHEMA,
        "source": observability.runtime_source_hashes(),
        "targets": {
            "component_counts": component_counts,
            "direct_target_count": 7,
            "expected_target_count": 7,
            "scrapes_successful": True,
            "target_set_sha256": f"sha256:{'f' * 64}",
            "unique_target_count": 7,
        },
        "transport": {
            "direct_per_replica": True,
            "monitoring_network_only": True,
            "no_forwarded_client_headers": True,
            "profiling_denied": True,
            "public_operational_paths_denied": True,
            "public_target_refused": True,
            "registry_allowlist_proxy": True,
            "registry_loopback_debug": True,
            "verified_backend_tls": True,
            "vip_target_refused": True,
        },
    }


def compile_inputs() -> dict[str, object]:
    return {
        "artifact_digest": ARTIFACT_DIGEST,
        "artifact_result": data_test.maintenance_test.artifact_result(
            RELEASE_DIGEST
        ),
        "data_protection_digest": DATA_PROTECTION_DIGEST,
        "data_protection_result": data_protection_result(),
        "evidence": evidence(),
        "evidence_digest": f"sha256:{'0' * 64}",
        "maintenance_digest": MAINTENANCE_DIGEST,
        "maintenance_result": data_test.maintenance_result(),
        "release_digest": RELEASE_DIGEST,
        "release_readiness": data_test.maintenance_test.release(),
        "rgw_kms_digest": RGW_KMS_DIGEST,
        "rgw_kms_result": data_test.maintenance_test.rgw_kms_result(
            RELEASE_DIGEST
        ),
    }


def _write_private(path: Path, value: object) -> bytes:
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def test_compiles_complete_live_observability_transaction() -> None:
    result = observability.compile_result(**compile_inputs())

    assert result["schema"] == observability.SCHEMA
    assert result["production_candidate"] is True
    assert result["targets"]["direct_target_count"] == 7
    assert result["metric_schema"]["worker_count_per_container"] == 1
    assert all(item["recovered"] for item in result["alerts"].values())
    assert observability.validate_final_result(result) == result


def test_release_and_data_protection_prerequisites_fail_closed() -> None:
    blocked = compile_inputs()
    blocked["release_readiness"] = data_test.maintenance_test.release(False)
    blocked["evidence"] = {}
    with pytest.raises(
        observability.ObservabilityInputsBlocked,
        match="not candidate-qualified",
    ):
        observability.compile_result(**blocked)

    changed_data = compile_inputs()
    changed_data["data_protection_result"]["residue"]["credentials"] = 1
    changed_data["data_protection_result"]["residue"]["total"] = 1
    with pytest.raises(
        observability.ObservabilityInputsBlocked,
        match="data protection",
    ):
        observability.compile_result(**changed_data)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("execution", "non_synthetic", False, "complete live pilot"),
        ("targets", "direct_target_count", 6, "target coverage"),
        ("transport", "vip_target_refused", False, "transport"),
        (
            "metric_schema",
            "worker_count_per_container",
            2,
            "metric schema",
        ),
        ("restarts", "rolling_rollback", False, "restart lifecycle"),
        (
            "failure_budget",
            "dependency_failures_counted",
            False,
            "failure-budget",
        ),
        ("dependencies", "kms", False, "dependency correlation"),
        ("audit", "known_secret_matches", 1, "unsafe evidence"),
        ("residue", "containers", 1, "residue remains"),
    ],
)
def test_observability_surfaces_fail_closed(
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
        observability.ObservabilityResultError,
        match=message,
    ):
        observability.compile_result(**inputs)


def test_alert_lifecycle_and_source_binding_fail_closed() -> None:
    changed_alert = compile_inputs()
    changed_alert["evidence"]["alerts"]["CofferTargetDown"][
        "recovered"
    ] = False
    with pytest.raises(
        observability.ObservabilityResultError,
        match="alert lifecycle",
    ):
        observability.compile_result(**changed_alert)

    changed_source = compile_inputs()
    changed_source["evidence"]["source"]["observability_runtime_sha256"] = (
        f"sha256:{'9' * 64}"
    )
    with pytest.raises(
        observability.ObservabilityResultError,
        match="binding",
    ):
        observability.compile_result(**changed_source)


def test_cli_blocks_before_missing_downstream_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    output = directory / "result.json"
    _write_private(
        release_path,
        data_test.maintenance_test.release(False),
    )

    result = observability.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(directory / "missing-artifact.json"),
            "--rgw-kms-result",
            str(directory / "missing-rgw.json"),
            "--maintenance-identity-result",
            str(directory / "missing-maintenance.json"),
            "--data-protection-result",
            str(directory / "missing-data.json"),
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
    data_path = directory / "data.json"
    evidence_path = directory / "evidence.json"
    output = directory / "result.json"

    release_payload = _write_private(
        release_path,
        data_test.maintenance_test.release(),
    )
    release_digest = observability._sha256_bytes(release_payload)
    artifact_payload = _write_private(
        artifact_path,
        data_test.maintenance_test.artifact_result(release_digest),
    )
    artifact_digest = observability._sha256_bytes(artifact_payload)
    rgw_payload = _write_private(
        rgw_path,
        data_test.maintenance_test.rgw_kms_result(release_digest),
    )
    rgw_digest = observability._sha256_bytes(rgw_payload)
    maintenance_value = data_test.maintenance_result(
        release_digest=release_digest,
        artifact_digest=artifact_digest,
        rgw_digest=rgw_digest,
    )
    maintenance_payload = _write_private(
        maintenance_path,
        maintenance_value,
    )
    maintenance_digest = observability._sha256_bytes(maintenance_payload)
    data_inputs = data_test.compile_inputs()
    data_inputs.update(
        {
            "artifact_digest": artifact_digest,
            "artifact_result": data_test.maintenance_test.artifact_result(
                release_digest
            ),
            "maintenance_digest": maintenance_digest,
            "maintenance_result": maintenance_value,
            "release_digest": release_digest,
            "release_readiness": data_test.maintenance_test.release(),
            "rgw_kms_digest": rgw_digest,
            "rgw_kms_result": (
                data_test.maintenance_test.rgw_kms_result(release_digest)
            ),
        }
    )
    data_inputs["evidence"] = data_test.evidence(
        prerequisite_values=data_test.prerequisites(
            release_digest=release_digest,
            artifact_digest=artifact_digest,
            rgw_digest=rgw_digest,
            maintenance_digest=maintenance_digest,
        )
    )
    data_value = data_test.data.compile_result(**data_inputs)
    data_payload = _write_private(data_path, data_value)
    data_digest = observability._sha256_bytes(data_payload)
    _write_private(
        evidence_path,
        evidence(
            {
                "artifact_result_sha256": artifact_digest,
                "data_protection_result_sha256": data_digest,
                "maintenance_identity_result_sha256": maintenance_digest,
                "release_readiness_sha256": release_digest,
                "rgw_kms_result_sha256": rgw_digest,
            }
        ),
    )

    result = observability.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(artifact_path),
            "--rgw-kms-result",
            str(rgw_path),
            "--maintenance-identity-result",
            str(maintenance_path),
            "--data-protection-result",
            str(data_path),
            "--evidence",
            str(evidence_path),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert observability.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True


def test_final_result_rejects_source_or_zero_residue_tamper() -> None:
    result = observability.compile_result(**compile_inputs())
    changed_source = deepcopy(result)
    changed_source["source"]["observability_runtime_sha256"] = (
        f"sha256:{'9' * 64}"
    )
    with pytest.raises(
        observability.ObservabilityResultError,
        match="not qualified",
    ):
        observability.validate_final_result(changed_source)

    changed_residue = deepcopy(result)
    changed_residue["residue"]["containers"] = 1
    changed_residue["residue"]["total"] = 1
    with pytest.raises(
        observability.ObservabilityResultError,
        match="residue",
    ):
        observability.validate_final_result(changed_residue)
