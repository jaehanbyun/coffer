from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "load_soak.py"
OBSERVABILITY_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_observability.py"
)
GC_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_gc_retention.py"
)
LOAD_EVIDENCE_TEST_SOURCE = ROOT / "tests" / "test_load_soak_evidence.py"


def _load(name: str, path: Path) -> object:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


load_soak = _load("coffer_test_production_promotion_load_soak", SOURCE)
observability_test = _load(
    "coffer_load_soak_observability_test_helpers",
    OBSERVABILITY_TEST_SOURCE,
)
gc_test = _load(
    "coffer_load_soak_gc_test_helpers",
    GC_TEST_SOURCE,
)
load_evidence_test = _load(
    "coffer_load_soak_evidence_test_helpers",
    LOAD_EVIDENCE_TEST_SOURCE,
)

RELEASE_DIGEST = f"sha256:{'1' * 64}"
ARTIFACT_DIGEST = f"sha256:{'2' * 64}"
RGW_KMS_DIGEST = f"sha256:{'3' * 64}"
MAINTENANCE_DIGEST = f"sha256:{'4' * 64}"
DATA_PROTECTION_DIGEST = f"sha256:{'5' * 64}"
OBSERVABILITY_DIGEST = f"sha256:{'6' * 64}"
GC_DIGEST = f"sha256:{'7' * 64}"


def observability_result() -> dict[str, object]:
    return observability_test.observability.compile_result(
        **observability_test.compile_inputs()
    )


def gc_result() -> dict[str, object]:
    return gc_test.production_gc.compile_result(**gc_test.compile_inputs())


def prerequisites() -> dict[str, str]:
    return {
        "artifact_result_sha256": ARTIFACT_DIGEST,
        "data_protection_result_sha256": DATA_PROTECTION_DIGEST,
        "gc_retention_result_sha256": GC_DIGEST,
        "maintenance_identity_result_sha256": MAINTENANCE_DIGEST,
        "observability_result_sha256": OBSERVABILITY_DIGEST,
        "release_readiness_sha256": RELEASE_DIGEST,
        "rgw_kms_result_sha256": RGW_KMS_DIGEST,
    }


def runtime_bindings() -> dict[str, str]:
    return {
        "client_versions_hash": f"sha256:{'8' * 64}",
        "configuration_hash": f"sha256:{'9' * 64}",
        "driver_revision": "a" * 40,
    }


def release() -> dict[str, object]:
    result = observability_test.data_test.maintenance_test.release()
    result["components"]["distribution"].update(
        {
            "revision": load_soak.GC_RESULT.GC_RESULT.REVISION,
            "version": load_soak.GC_RESULT.GC_RESULT.VERSION,
        }
    )
    return result


def rgw_kms_result() -> dict[str, object]:
    result = observability_test.data_test.maintenance_test.rgw_kms_result(
        RELEASE_DIGEST
    )
    result["release_inputs"]["distribution"].update(
        {
            "revision": load_soak.GC_RESULT.GC_RESULT.REVISION,
            "version": load_soak.GC_RESULT.GC_RESULT.VERSION,
        }
    )
    return result


def artifact_result() -> dict[str, object]:
    return observability_test.data_test.maintenance_test.artifact_result(
        RELEASE_DIGEST
    )


def evidence(
    prerequisite_values: dict[str, str] | None = None,
) -> dict[str, object]:
    topology = load_soak._topology()
    artifact = artifact_result()
    bindings = load_soak._expected_bindings(
        runtime_bindings(),
        release=load_soak._release_with_digest(
            release(),
            RELEASE_DIGEST,
        ),
        artifact=artifact,
    )
    document = load_evidence_test.document()
    document["bindings"] = bindings
    return {
        "audit": {
            "known_secret_matches": 0,
            "log_scan_count": 1_000,
            "unexpected_errors": 0,
        },
        "coverage": {
            "architecture_count": len(topology["required_architectures"]),
            "client_count": len(topology["clients"]),
            "content_class_count": len(topology["content_classes"]),
            "failure_case_count": len(topology["failure_cases"]),
            "fault_count": len(topology["faults"]),
            "operation_count": len(topology["operations"]),
            "phase_count": len(topology["phases"]),
            "profile_count": len(topology["profiles"]),
            "soak_seconds": topology["profiles"]["soak"][
                "duration_seconds"
            ],
        },
        "execution": {
            "action_count": load_soak.EXECUTOR_ACTION_COUNT,
            "adapter": "openstack",
            "checkpoint_count": load_soak.EXECUTOR_ACTION_COUNT,
            "disposable": True,
            "executor_result_sha256": f"sha256:{'b' * 64}",
            "non_synthetic": True,
            "resume_verified": True,
        },
        "load_document": document,
        "prerequisites": prerequisite_values or prerequisites(),
        "runtime_bindings": runtime_bindings(),
        "schema": load_soak.EVIDENCE_SCHEMA,
        "source": load_soak.runtime_source_hashes(),
    }


def compile_inputs() -> dict[str, object]:
    data_test = observability_test.data_test
    return {
        "artifact_digest": ARTIFACT_DIGEST,
        "artifact_result": artifact_result(),
        "data_protection_digest": DATA_PROTECTION_DIGEST,
        "data_protection_result": (
            observability_test.data_protection_result()
        ),
        "evidence": evidence(),
        "evidence_digest": f"sha256:{'c' * 64}",
        "gc_digest": GC_DIGEST,
        "gc_result": gc_result(),
        "maintenance_digest": MAINTENANCE_DIGEST,
        "maintenance_result": data_test.maintenance_result(),
        "observability_digest": OBSERVABILITY_DIGEST,
        "observability_result": observability_result(),
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


def test_compiles_complete_non_synthetic_load_soak_transaction() -> None:
    result = load_soak.compile_result(**compile_inputs())

    assert result["schema"] == load_soak.SCHEMA
    assert result["production_candidate"] is True
    assert result["execution"]["action_count"] == 53
    assert result["coverage"]["client_count"] == 6
    assert result["coverage"]["fault_count"] == 10
    assert result["verified_evidence"]["phase_count"] == 13
    assert load_soak.validate_final_result(result) == result


def test_release_and_prior_specialists_fail_closed() -> None:
    blocked = compile_inputs()
    blocked["release_readiness"] = (
        observability_test.data_test.maintenance_test.release(False)
    )
    blocked["evidence"] = {}
    with pytest.raises(
        load_soak.LoadSoakInputsBlocked,
        match="not candidate-qualified",
    ):
        load_soak.compile_result(**blocked)

    changed_observability = compile_inputs()
    changed_observability["observability_result"]["residue"][
        "containers"
    ] = 1
    changed_observability["observability_result"]["residue"]["total"] = 1
    with pytest.raises(
        load_soak.LoadSoakInputsBlocked,
        match="observability",
    ):
        load_soak.compile_result(**changed_observability)

    changed_gc = compile_inputs()
    changed_gc["gc_result"]["residue"]["containers"] = 1
    changed_gc["gc_result"]["residue"]["total"] = 1
    with pytest.raises(
        load_soak.LoadSoakInputsBlocked,
        match="GC retention",
    ):
        load_soak.compile_result(**changed_gc)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("execution", "non_synthetic", False, "complete live pilot"),
        ("execution", "action_count", 52, "complete live pilot"),
        ("coverage", "client_count", 5, "coverage"),
        ("audit", "known_secret_matches", 1, "unsafe evidence"),
    ],
)
def test_execution_coverage_and_audit_fail_closed(
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    inputs = compile_inputs()
    inputs["evidence"][section][field] = value
    with pytest.raises(load_soak.LoadSoakResultError, match=message):
        load_soak.compile_result(**inputs)


@pytest.mark.parametrize(
    ("phase_index", "field", "value"),
    [
        (3, "insecure_mode", True),
        (5, "digest_mismatches", 1),
        (8, "api-replica", {}),
        (10, "quota_invariant", False),
        (11, "secret_leaks", 1),
    ],
)
def test_client_profile_fault_data_and_metrics_matrix_fail_closed(
    phase_index: int,
    field: str,
    value: object,
) -> None:
    inputs = compile_inputs()
    phase = inputs["evidence"]["load_document"]["phase_evidence"][
        phase_index
    ]["evidence"]
    phase[field] = value
    with pytest.raises(
        load_soak.LoadSoakResultError,
        match="lifecycle evidence",
    ):
        load_soak.compile_result(**inputs)


def test_teardown_source_and_prerequisite_binding_fail_closed() -> None:
    teardown = compile_inputs()
    teardown["evidence"]["load_document"]["phase_evidence"][-1][
        "evidence"
    ]["residue"]["containers"] = 1
    with pytest.raises(
        load_soak.LoadSoakResultError,
        match="lifecycle evidence",
    ):
        load_soak.compile_result(**teardown)

    changed_source = compile_inputs()
    changed_source["evidence"]["source"]["pilot_run_sha256"] = (
        f"sha256:{'0' * 64}"
    )
    with pytest.raises(
        load_soak.LoadSoakResultError,
        match="binding",
    ):
        load_soak.compile_result(**changed_source)

    changed_prerequisite = compile_inputs()
    changed_prerequisite["evidence"]["prerequisites"][
        "observability_result_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        load_soak.LoadSoakResultError,
        match="binding",
    ):
        load_soak.compile_result(**changed_prerequisite)


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
        observability_test.data_test.maintenance_test.release(False),
    )

    result = load_soak.main(
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
            "--observability-result",
            str(directory / "missing-observability.json"),
            "--gc-retention-result",
            str(directory / "missing-gc.json"),
            "--evidence",
            str(directory / "missing-evidence.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert "not candidate-qualified" in capsys.readouterr().err


def test_final_result_rejects_source_or_verified_hash_tamper() -> None:
    result = load_soak.compile_result(**compile_inputs())
    changed_source = deepcopy(result)
    changed_source["source"]["pilot_run_sha256"] = f"sha256:{'0' * 64}"
    with pytest.raises(
        load_soak.LoadSoakResultError,
        match="not qualified",
    ):
        load_soak.validate_final_result(changed_source)

    changed_hash = deepcopy(result)
    changed_hash["verified_evidence"]["history_hash"] = "invalid"
    with pytest.raises(
        load_soak.LoadSoakResultError,
        match="invalid",
    ):
        load_soak.validate_final_result(changed_hash)


def test_private_writer_creates_owner_only_result(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    output = directory / "result.json"
    result = load_soak.compile_result(**compile_inputs())

    load_soak._write_private(output.resolve(), result)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert load_soak.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True
