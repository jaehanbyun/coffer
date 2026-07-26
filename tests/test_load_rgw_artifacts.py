from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "rgw_artifacts.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


COLLECTOR = load_module(
    "coffer_load_rgw_artifact_tests",
    COLLECTOR_PATH,
)
CONTROL = COLLECTOR.control_artifacts
RENDERER = CONTROL.render_target
LOAD_TOPOLOGY = CONTROL.load_contract.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = CONTROL.observability_contract.load_topology(
    ROOT / "poc" / "observability" / "topology.json"
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
WINDOW_SHA256 = f"sha256:{'7' * 64}"
PROBE_SOURCE_SHA256 = f"sha256:{'1' * 64}"
MULTIPART_SOURCE_SHA256 = f"sha256:{'2' * 64}"
RGW_CONFIG_SHA256 = f"sha256:{'3' * 64}"
BUCKET_SCOPE_SHA256 = f"sha256:{'4' * 64}"
KMS_POLICY_SHA256 = f"sha256:{'5' * 64}"


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, value: object) -> None:
    path.write_bytes(canonical(value))
    path.chmod(0o600)


def target_request() -> dict:
    all_hosts = CONTROLLERS + STORAGE
    return {
        "adapter_source_sha256": RENDERER.adapter_source_sha256(),
        "inventory": {
            "controllers": list(CONTROLLERS),
            "reconcile_hosts": CONTROLLERS[:2],
            "rgw_daemons": {
                "rgw.coffer.storage1.a": "storage1",
                "rgw.coffer.storage2.b": "storage2",
                "rgw.coffer.storage3.c": "storage3",
            },
            "rgw_ingress_hosts": STORAGE[:2],
            "storage_hosts": list(STORAGE),
        },
        "load_topology_sha256": CONTROL.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "observability_topology_sha256": CONTROL.native_target._hash(
            OBSERVABILITY_TOPOLOGY.raw
        ),
        "origins": {
            "ceph_exporter": "https://ceph-exporter.stage6.test:9926",
            "ceph_mgr": "https://ceph-mgr.stage6.test:9283",
            "evidence": "https://telemetry-adapter.stage6.test:9443",
            "galera": {
                host: f"https://{host}.stage6.test:9104"
                for host in CONTROLLERS
            },
            "haproxy": "https://haproxy.stage6.test:8405",
            "hosts": {
                host: f"https://{host}.stage6.test:9100"
                for host in all_hosts
            },
            "prometheus": "https://prometheus.stage6.test:9091",
            "rgw_ingress": "https://rgw-ingress.stage6.test:8406",
        },
        "schema": RENDERER.REQUEST_SCHEMA,
        "target_class": CONTROL.native_target.TARGET_CLASS,
    }


def target() -> dict:
    return RENDERER.render_request(target_request())


def expected_operations() -> dict[str, int]:
    return {name: 1 for name in COLLECTOR.OPERATION_CLASSES}


def expected_faults(phase: str) -> dict[str, int]:
    count = 1 if phase == "during" else 0
    return {name: count for name in COLLECTOR.FAULT_CLASSES}


def config(
    target_value: dict,
    *,
    phase: str = "before",
    target_file: str = "/owner/target.json",
    target_file_sha256: str | None = None,
) -> dict:
    if target_file_sha256 is None:
        target_file_sha256 = payload_hash(canonical(target_value))
    return {
        "bucket_scope_sha256": BUCKET_SCOPE_SHA256,
        "collector_source_sha256": COLLECTOR.collector_source_sha256(),
        "expected_fault_counts": expected_faults(phase),
        "expected_operation_counts": expected_operations(),
        "kms_policy_sha256": KMS_POLICY_SHA256,
        "multipart_source_sha256": MULTIPART_SOURCE_SHA256,
        "phase": phase,
        "probe_source_sha256": PROBE_SOURCE_SHA256,
        "rgw_config_sha256": RGW_CONFIG_SHA256,
        "schema": COLLECTOR.CONFIG_SCHEMA,
        "target_file": target_file,
        "target_file_sha256": target_file_sha256,
        "window_completed_at_seconds": 200,
        "window_sha256": WINDOW_SHA256,
        "window_started_at_seconds": 100,
    }


def probe(
    target_value: dict,
    *,
    phase: str = "before",
    unexpected_kms: int = 0,
    unexpected_storage: int = 0,
) -> dict:
    operations = expected_operations()
    faults = expected_faults(phase)
    total = sum(operations.values())
    successes = (
        total
        - sum(faults.values())
        - unexpected_kms
        - unexpected_storage
    )
    value = {
        "bucket_scope_sha256": BUCKET_SCOPE_SHA256,
        "completed_at_seconds": 160,
        "events_sha256": f"sha256:{'6' * 64}",
        "execution_source": "pilot",
        "kms_policy_sha256": KMS_POLICY_SHA256,
        "observed_operation_counts": operations,
        "phase": phase,
        "probe_source_sha256": PROBE_SOURCE_SHA256,
        "result_counts": {
            "expected_kms_outage": faults["expected_kms_outage"],
            "expected_wrong_key": faults["expected_wrong_key"],
            "success": successes,
            "unexpected_kms_error": unexpected_kms,
            "unexpected_storage_error": unexpected_storage,
        },
        "rgw_config_sha256": RGW_CONFIG_SHA256,
        "schema": COLLECTOR.PROBE_SCHEMA,
        "started_at_seconds": 120,
        "synthetic": False,
        "target_sha256": target_value["target_sha256"],
        "window_sha256": WINDOW_SHA256,
    }
    value["probe_sha256"] = COLLECTOR._hash(value)
    return value


def multipart(
    target_value: dict,
    *,
    phase: str = "before",
    uploads: int = 0,
) -> dict:
    value = {
        "bucket_scope_sha256": BUCKET_SCOPE_SHA256,
        "execution_source": "pilot",
        "listing_complete": True,
        "multipart_source_sha256": MULTIPART_SOURCE_SHA256,
        "observed_at_seconds": 170,
        "page_count": 1,
        "page_sha256": [f"sha256:{'8' * 64}"],
        "phase": phase,
        "rgw_config_sha256": RGW_CONFIG_SHA256,
        "schema": COLLECTOR.MULTIPART_SCHEMA,
        "synthetic": False,
        "target_sha256": target_value["target_sha256"],
        "upload_count": uploads,
        "window_sha256": WINDOW_SHA256,
    }
    value["capture_sha256"] = COLLECTOR._hash(value)
    return value


def resign_probe(value: dict) -> None:
    value["probe_sha256"] = COLLECTOR._hash(
        {key: nested for key, nested in value.items() if key != "probe_sha256"}
    )


def resign_multipart(value: dict) -> None:
    value["capture_sha256"] = COLLECTOR._hash(
        {
            key: nested
            for key, nested in value.items()
            if key != "capture_sha256"
        }
    )


@pytest.mark.parametrize("phase", COLLECTOR.native_target.PHASES)
def test_compiles_exact_phase_bound_artifact(phase: str) -> None:
    target_value = target()
    artifact = COLLECTOR.compile_artifact(
        config(target_value, phase=phase),
        target_value,
        probe(target_value, phase=phase),
        multipart(target_value, phase=phase),
        target_file_sha256=payload_hash(canonical(target_value)),
    )

    assert artifact["aggregate"] == {
        "kms_errors": 0,
        "multipart_uploads": 0,
        "unexpected_errors": 0,
    }
    assert artifact["phase"] == phase
    assert artifact["schema"] == COLLECTOR.source_summaries.ARTIFACT_SCHEMA
    assert artifact["source_class"] == (
        COLLECTOR.phase_evidence.SOURCE_CLASSES["rgw"]
    )
    assert artifact["surface"] == "rgw"
    assert artifact["target_sha256"] == target_value["target_sha256"]
    assert artifact["window_sha256"] == WINDOW_SHA256
    assert artifact["artifact_sha256"] == COLLECTOR._hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifact_sha256"
        }
    )


def test_expected_faults_do_not_become_kms_errors() -> None:
    target_value = target()
    probe_value = probe(target_value, phase="during")
    assert probe_value["result_counts"]["expected_kms_outage"] == 1
    assert probe_value["result_counts"]["expected_wrong_key"] == 1

    artifact = COLLECTOR.compile_artifact(
        config(target_value, phase="during"),
        target_value,
        probe_value,
        multipart(target_value, phase="during", uploads=2),
        target_file_sha256=payload_hash(canonical(target_value)),
    )

    assert artifact["aggregate"] == {
        "kms_errors": 0,
        "multipart_uploads": 2,
        "unexpected_errors": 0,
    }


def test_unexpected_probe_results_remain_nonzero() -> None:
    target_value = target()
    artifact = COLLECTOR.compile_artifact(
        config(target_value),
        target_value,
        probe(
            target_value,
            unexpected_kms=1,
            unexpected_storage=2,
        ),
        multipart(target_value, uploads=3),
        target_file_sha256=payload_hash(canonical(target_value)),
    )

    assert artifact["aggregate"] == {
        "kms_errors": 1,
        "multipart_uploads": 3,
        "unexpected_errors": 2,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "wrong"),
        ("execution_source", "fixture"),
        ("synthetic", True),
        ("phase", "after"),
        ("window_sha256", f"sha256:{'a' * 64}"),
        ("target_sha256", f"sha256:{'b' * 64}"),
        ("probe_source_sha256", f"sha256:{'c' * 64}"),
        ("rgw_config_sha256", f"sha256:{'d' * 64}"),
        ("bucket_scope_sha256", f"sha256:{'e' * 64}"),
        ("kms_policy_sha256", f"sha256:{'f' * 64}"),
    ],
)
def test_probe_binding_drift_is_refused(field: str, value: object) -> None:
    target_value = target()
    probe_value = probe(target_value)
    probe_value[field] = value
    resign_probe(probe_value)

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe_value,
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )


def test_probe_hash_and_exact_boundary_are_refused() -> None:
    target_value = target()
    probe_value = probe(target_value)
    probe_value["unknown"] = 1

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe_value,
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )

    probe_value.pop("unknown")
    probe_value["probe_sha256"] = f"sha256:{'0' * 64}"
    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe_value,
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )


def test_probe_requires_complete_operation_and_result_coverage() -> None:
    target_value = target()
    probe_value = probe(target_value)
    probe_value["observed_operation_counts"]["get"] = 0
    resign_probe(probe_value)

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe_value,
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )

    probe_value = probe(target_value)
    probe_value["result_counts"]["success"] -= 1
    resign_probe(probe_value)
    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe_value,
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )


def test_probe_requires_declared_fault_outcomes_only_during() -> None:
    target_value = target()
    probe_value = probe(target_value, phase="during")
    probe_value["result_counts"]["expected_wrong_key"] = 0
    probe_value["result_counts"]["success"] += 1
    resign_probe(probe_value)

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value, phase="during"),
            target_value,
            probe_value,
            multipart(target_value, phase="during"),
            target_file_sha256=payload_hash(canonical(target_value)),
        )

    config_value = config(target_value)
    config_value["expected_fault_counts"]["expected_kms_outage"] = 1
    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config_value,
            target_value,
            probe(target_value),
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )


@pytest.mark.parametrize(
    ("started", "completed"),
    [(99, 150), (120, 201), (170, 160)],
)
def test_probe_must_remain_inside_window(
    started: int,
    completed: int,
) -> None:
    target_value = target()
    probe_value = probe(target_value)
    probe_value["started_at_seconds"] = started
    probe_value["completed_at_seconds"] = completed
    resign_probe(probe_value)

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe_value,
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "wrong"),
        ("execution_source", "fixture"),
        ("synthetic", True),
        ("listing_complete", False),
        ("phase", "after"),
        ("window_sha256", f"sha256:{'a' * 64}"),
        ("target_sha256", f"sha256:{'b' * 64}"),
        ("multipart_source_sha256", f"sha256:{'c' * 64}"),
        ("rgw_config_sha256", f"sha256:{'d' * 64}"),
        ("bucket_scope_sha256", f"sha256:{'e' * 64}"),
    ],
)
def test_multipart_binding_drift_is_refused(
    field: str,
    value: object,
) -> None:
    target_value = target()
    multipart_value = multipart(target_value)
    multipart_value[field] = value
    resign_multipart(multipart_value)

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe(target_value),
            multipart_value,
            target_file_sha256=payload_hash(canonical(target_value)),
        )


def test_multipart_requires_complete_unique_pages_in_window() -> None:
    target_value = target()
    multipart_value = multipart(target_value)
    multipart_value["page_count"] = 2
    multipart_value["page_sha256"] = [
        f"sha256:{'8' * 64}",
        f"sha256:{'8' * 64}",
    ]
    resign_multipart(multipart_value)

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe(target_value),
            multipart_value,
            target_file_sha256=payload_hash(canonical(target_value)),
        )

    multipart_value = multipart(target_value)
    multipart_value["observed_at_seconds"] = 201
    resign_multipart(multipart_value)
    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config(target_value),
            target_value,
            probe(target_value),
            multipart_value,
            target_file_sha256=payload_hash(canonical(target_value)),
        )


def test_config_requires_exact_target_and_window() -> None:
    target_value = target()
    config_value = config(target_value)
    config_value["target_file_sha256"] = f"sha256:{'0' * 64}"

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config_value,
            target_value,
            probe(target_value),
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )

    config_value = config(target_value)
    config_value["window_started_at_seconds"] = 200
    config_value["window_completed_at_seconds"] = 100
    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_artifact(
            config_value,
            target_value,
            probe(target_value),
            multipart(target_value),
            target_file_sha256=payload_hash(canonical(target_value)),
        )


def test_compile_file_is_owner_only_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    target_value = target()
    target_path = tmp_path / "target.json"
    config_path = tmp_path / "config.json"
    probe_path = tmp_path / "probe.json"
    multipart_path = tmp_path / "multipart.json"
    output_path = tmp_path / "artifact.json"
    owner_file(target_path, target_value)
    owner_file(
        config_path,
        config(
            target_value,
            target_file=str(target_path),
            target_file_sha256=payload_hash(target_path.read_bytes()),
        ),
    )
    owner_file(probe_path, probe(target_value))
    owner_file(multipart_path, multipart(target_value))

    artifact = COLLECTOR.compile_file(
        config_path,
        probe_path,
        multipart_path,
        output_path,
    )
    first = output_path.read_bytes()
    first_inode = output_path.stat().st_ino
    repeated = COLLECTOR.compile_file(
        config_path,
        probe_path,
        multipart_path,
        output_path,
    )

    assert repeated == artifact
    assert output_path.read_bytes() == first
    assert output_path.stat().st_ino == first_inode
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert json.loads(first) == artifact
    assert b"bucket" not in first
    assert b"credential" not in first
    assert b"kms_policy" not in first


def test_compile_file_rejects_unsafe_or_aliased_inputs(
    tmp_path: Path,
) -> None:
    target_value = target()
    target_path = tmp_path / "target.json"
    config_path = tmp_path / "config.json"
    probe_path = tmp_path / "probe.json"
    multipart_path = tmp_path / "multipart.json"
    owner_file(target_path, target_value)
    owner_file(
        config_path,
        config(
            target_value,
            target_file=str(target_path),
            target_file_sha256=payload_hash(target_path.read_bytes()),
        ),
    )
    owner_file(probe_path, probe(target_value))
    owner_file(multipart_path, multipart(target_value))
    probe_path.chmod(0o644)

    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_file(
            config_path,
            probe_path,
            multipart_path,
            tmp_path / "artifact.json",
        )

    probe_path.chmod(0o600)
    alias_path = tmp_path / "probe-alias.json"
    os.link(probe_path, alias_path)
    with pytest.raises(COLLECTOR.RgwArtifactError):
        COLLECTOR.compile_file(
            config_path,
            alias_path,
            multipart_path,
            tmp_path / "artifact.json",
        )


def test_cli_has_fixed_secret_safe_results(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert COLLECTOR.main(["source-hash"]) == 0
    source_output = json.loads(capsys.readouterr().out)
    assert source_output == {
        "collector_source_sha256": COLLECTOR.collector_source_sha256(),
        "schema": COLLECTOR.RESULT_SCHEMA,
    }

    assert COLLECTOR.main(["compile", "/missing", "a", "b", "c"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "rgw-artifact-refused\n"
    assert COLLECTOR.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CONFIG PROBE MULTIPART OUTPUT" in captured.err
