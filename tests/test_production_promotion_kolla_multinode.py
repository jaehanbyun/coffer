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
    ROOT / "poc" / "production-promotion" / "kolla_multinode.py"
)
LOAD_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_load_soak.py"
)


def _load(name: str, path: Path) -> object:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


kolla = _load("coffer_test_production_kolla_multinode", SOURCE)
load_test = _load(
    "coffer_kolla_multinode_load_test_helpers",
    LOAD_TEST_SOURCE,
)

KOLLA_DIGEST = f"sha256:{'d' * 64}"


def prerequisites() -> dict[str, str]:
    return {
        **load_test.prerequisites(),
        "load_soak_result_sha256": KOLLA_DIGEST,
    }


def load_result() -> dict[str, object]:
    return load_test.load_soak.compile_result(
        **load_test.compile_inputs()
    )


def _digest(index: int) -> str:
    return f"sha256:{index:064x}"


def evidence(
    prerequisite_values: dict[str, str] | None = None,
) -> dict[str, object]:
    artifact = load_test.artifact_result()
    return {
        "acceptance": {
            "data_path": {
                name: True for name in kolla.DATA_PATH_CHECKS
            },
            "surfaces": {
                name: {
                    "evidence_sha256": _digest(index),
                    "passed": True,
                }
                for index, name in enumerate(kolla.SURFACES, start=1)
            },
            "ui_consistency": {
                "horizon_skyline_same_quota": True,
                "horizon_skyline_same_repository": True,
                "server_side_catalog_resolution": True,
            },
        },
        "audit": {
            "forbidden_backend_exposures": 0,
            "known_secret_matches": 0,
            "log_scan_count": 2_000,
            "secret_scan_count": 100,
            "unexpected_errors": 0,
        },
        "backup_restore": {
            "authenticated_comparison": True,
            "backup_verified": True,
            "digest_readable": True,
            "evidence_sha256": _digest(40),
            "inventory_equal": True,
            "isolated_restore": True,
            "no_source_mutation": True,
            "rgw_restored": True,
            "rollback_verified": True,
            "sql_restored": True,
            "sse_kms": True,
            "writer_exclusion": True,
        },
        "deployment": {
            name: True for name in kolla.DEPLOYMENT_CHECKS
        },
        "evidence_sha256": {
            name: _digest(index)
            for index, name in enumerate(
                (
                    "acceptance_sha256",
                    "audit_sha256",
                    "backup_restore_sha256",
                    "deployment_sha256",
                    "failures_sha256",
                    "identity_sha256",
                    "teardown_sha256",
                    "topology_sha256",
                    "upgrade_rollback_sha256",
                ),
                start=50,
            )
        },
        "execution": {
            "adapter": "openstack",
            "coffer_revision": artifact["cross_architecture"][
                "core_revision"
            ],
            "disposable": True,
            "fresh": True,
            "kolla_ansible_revision": "1" * 40,
            "kolla_release": kolla.KOLLA_RELEASE,
            "non_synthetic": True,
            "phase_count": len(kolla.PHASES),
            "run_duration_seconds": 14_400,
        },
        "failures": {
            name: {
                "applied": True,
                "data_integrity": True,
                "evidence_sha256": _digest(index),
                "expected_behavior_verified": True,
                "recovered": True,
                "security_preserved": True,
            }
            for index, name in enumerate(
                kolla.FAILURE_CASES,
                start=20,
            )
        },
        "identity_catalog": {
            "checks": {
                name: True for name in kolla.IDENTITY_CHECKS
            },
            "endpoint_count": 3,
            "region": "RegionOne",
            "service_type": "oci-registry",
        },
        "prerequisites": prerequisite_values or prerequisites(),
        "schema": kolla.EVIDENCE_SCHEMA,
        "source": kolla.runtime_source_hashes(),
        "teardown": {
            "after_unrelated_sha256": _digest(60),
            "before_unrelated_sha256": _digest(60),
            "evidence_sha256": _digest(61),
            "executed": True,
            "final_audit": True,
            "preflight": True,
            "repeat_safe": True,
            "residue": {
                **{name: 0 for name in kolla.RESIDUE_KEYS},
                "total": 0,
            },
            "terminal_phase": kolla.PHASES[-1],
            "unrelated_state_unchanged": True,
        },
        "topology": {
            "backend_tls_verified": True,
            "ceph_crush_failure_domain": "host",
            "ceph_min_size": 2,
            "ceph_replication_size": 3,
            "client_network_backend_ports_closed": True,
            "controller_count": 3,
            "controller_failure_domain_count": 3,
            "controller_storage_colocated": False,
            "dependency_replicas": dict(kolla.DEPENDENCY_REPLICAS),
            "external_rgw": True,
            "internal_tls_verified": True,
            "load_balancer_ha": True,
            "service_replicas": dict(kolla.SERVICE_REPLICAS),
            "single_public_origin": True,
            "storage_count": 3,
            "storage_failure_domain_count": 3,
        },
        "upgrade_rollback": {
            "availability_maintained": True,
            "compatible_schema_verified": True,
            "configuration_rollback": True,
            "digest_persisted": True,
            "evidence_sha256": _digest(70),
            "image_rollback": True,
            "key_overlap_verified": True,
            "migration_replay_safe": True,
            "old_key_retired": True,
            "quota_state_equal": True,
            "rolling_rollback": True,
            "rolling_upgrade": True,
            "serial": 1,
        },
    }


def compile_inputs() -> dict[str, object]:
    inputs = load_test.compile_inputs()
    inputs.update(
        {
            "evidence": evidence(),
            "evidence_digest": f"sha256:{'e' * 64}",
            "load_soak_digest": KOLLA_DIGEST,
            "load_soak_result": load_result(),
        }
    )
    return inputs


def _write_private(path: Path, value: object) -> bytes:
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def test_compiles_fresh_production_shaped_multinode_transaction() -> None:
    result = kolla.compile_result(**compile_inputs())

    assert result["schema"] == kolla.SCHEMA
    assert result["production_candidate"] is True
    assert result["topology"]["controller_count"] == 3
    assert result["topology"]["storage_failure_domain_count"] == 3
    assert result["topology"]["service_replica_count"] == 12
    assert result["acceptance"]["surface_count"] == 9
    assert result["lifecycle"]["failure_case_count"] == 13
    assert kolla.validate_final_result(result) == result


def test_release_and_first_eight_specialists_fail_closed() -> None:
    blocked = compile_inputs()
    blocked["release_readiness"] = (
        load_test.observability_test.data_test.maintenance_test.release(
            False
        )
    )
    blocked["evidence"] = {}
    with pytest.raises(
        kolla.KollaMultinodeInputsBlocked,
        match="not candidate-qualified",
    ):
        kolla.compile_result(**blocked)

    changed_load = compile_inputs()
    changed_load["load_soak_result"]["execution"]["action_count"] = 52
    with pytest.raises(
        kolla.KollaMultinodeInputsBlocked,
        match="load/soak",
    ):
        kolla.compile_result(**changed_load)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("execution", "fresh", False, "fresh production pilot"),
        ("execution", "kolla_release", "2025.2", "fresh production pilot"),
        ("topology", "controller_count", 2, "production-shaped"),
        (
            "topology",
            "controller_storage_colocated",
            True,
            "production-shaped",
        ),
        ("deployment", "prechecks", False, "deployment checks"),
    ],
)
def test_execution_topology_and_deployment_fail_closed(
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    inputs = compile_inputs()
    inputs["evidence"][section][field] = value
    with pytest.raises(kolla.KollaMultinodeResultError, match=message):
        kolla.compile_result(**inputs)


def test_identity_acceptance_and_ui_consistency_fail_closed() -> None:
    identity = compile_inputs()
    identity["evidence"]["identity_catalog"]["checks"][
        "maintenance_identity_active"
    ] = False
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="identity checks",
    ):
        kolla.compile_result(**identity)

    surface = compile_inputs()
    surface["evidence"]["acceptance"]["surfaces"]["horizon"][
        "passed"
    ] = False
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="horizon",
    ):
        kolla.compile_result(**surface)

    data_path = compile_inputs()
    data_path["evidence"]["acceptance"]["data_path"][
        "edge_only_ingress"
    ] = False
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="data-path",
    ):
        kolla.compile_result(**data_path)

    ui = compile_inputs()
    ui["evidence"]["acceptance"]["ui_consistency"][
        "horizon_skyline_same_repository"
    ] = False
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="UI consistency",
    ):
        kolla.compile_result(**ui)


def test_failure_upgrade_and_backup_restore_fail_closed() -> None:
    failure = compile_inputs()
    failure["evidence"]["failures"]["storage-host"][
        "recovered"
    ] = False
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="storage-host",
    ):
        kolla.compile_result(**failure)

    upgrade = compile_inputs()
    upgrade["evidence"]["upgrade_rollback"]["serial"] = 2
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="serial",
    ):
        kolla.compile_result(**upgrade)

    restore = compile_inputs()
    restore["evidence"]["backup_restore"]["isolated_restore"] = False
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="backup and restore",
    ):
        kolla.compile_result(**restore)


def test_audit_teardown_source_and_prerequisite_binding_fail_closed() -> None:
    audit = compile_inputs()
    audit["evidence"]["audit"]["known_secret_matches"] = 1
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="unsafe evidence",
    ):
        kolla.compile_result(**audit)

    teardown = compile_inputs()
    teardown["evidence"]["teardown"]["residue"]["domains"] = 1
    teardown["evidence"]["teardown"]["residue"]["total"] = 1
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="left residue",
    ):
        kolla.compile_result(**teardown)

    unrelated = compile_inputs()
    unrelated["evidence"]["teardown"][
        "after_unrelated_sha256"
    ] = _digest(99)
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="unrelated state",
    ):
        kolla.compile_result(**unrelated)

    source = compile_inputs()
    source["evidence"]["source"]["operator_role_tree_sha256"] = _digest(
        100
    )
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="binding",
    ):
        kolla.compile_result(**source)

    prerequisite = compile_inputs()
    prerequisite["evidence"]["prerequisites"][
        "load_soak_result_sha256"
    ] = _digest(101)
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="binding",
    ):
        kolla.compile_result(**prerequisite)


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
        load_test.observability_test.data_test.maintenance_test.release(
            False
        ),
    )

    result = kolla.main(
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
            "--load-soak-result",
            str(directory / "missing-load.json"),
            "--evidence",
            str(directory / "missing-evidence.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert "not candidate-qualified" in capsys.readouterr().err


def test_final_result_rejects_source_summary_or_digest_tamper() -> None:
    result = kolla.compile_result(**compile_inputs())

    source = deepcopy(result)
    source["source"]["operator_role_tree_sha256"] = _digest(110)
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="not qualified",
    ):
        kolla.validate_final_result(source)

    summary = deepcopy(result)
    summary["topology"]["controller_count"] = 2
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="topology summary",
    ):
        kolla.validate_final_result(summary)

    digest = deepcopy(result)
    digest["evidence_sha256"]["teardown_sha256"] = "invalid"
    with pytest.raises(
        kolla.KollaMultinodeResultError,
        match="invalid",
    ):
        kolla.validate_final_result(digest)


def test_private_writer_creates_owner_only_result(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    output = directory / "result.json"
    result = kolla.compile_result(**compile_inputs())

    kolla._write_private(output.resolve(), result)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert kolla.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True
