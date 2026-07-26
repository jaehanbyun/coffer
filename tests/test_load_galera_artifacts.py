from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from coffer.quota import QuotaControlEvidenceSnapshot


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "galera_artifacts.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


COLLECTOR = load_module(
    "coffer_load_galera_artifact_tests",
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
TARGET_FILE_SHA256 = f"sha256:{'9' * 64}"


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
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


def values(
    *,
    target_file: str = "/owner/target.json",
    target_file_sha256: str = TARGET_FILE_SHA256,
) -> tuple[dict, dict]:
    target = RENDERER.render_request(target_request())
    config = {
        "collector_source_sha256": COLLECTOR.collector_source_sha256(),
        "control_collector_source_sha256": (
            CONTROL.collector_source_sha256()
        ),
        "phase": "during",
        "schema": COLLECTOR.CONFIG_SCHEMA,
        "target_file": target_file,
        "target_file_sha256": target_file_sha256,
        "window_sha256": WINDOW_SHA256,
    }
    return config, target


def sql_snapshot() -> dict:
    snapshot = QuotaControlEvidenceSnapshot(
        limit_bytes=1000,
        used_bytes=500,
        reserved_bytes=100,
        expected_used_bytes=500,
        expected_reserved_bytes=100,
        pending_reservations=1,
        mismatched_pending_deltas=0,
        descriptor_invariant_violations=0,
        active_claims=1,
        stale_claims=0,
        eligible_active_claims=1,
        claim_invariant_violations=0,
    )
    return CONTROL._sql_document(snapshot)


def sample(
    labels: dict[str, str],
    value: float,
    *,
    timestamp: float,
) -> dict:
    return {
        "labels": labels,
        "timestamp": timestamp,
        "value": float(value),
    }


def attempt_group(
    *,
    attempts: int,
    count: int = 1,
    instance: str = "controller1",
    job: str = "coffer-edge",
    operation: str = "reserve",
    result: str = "success",
    timestamp: float,
) -> list[dict]:
    values = {
        "1.0": count if attempts <= 1 else 0,
        "2.0": count if attempts <= 2 else 0,
        "3.0": count,
        "+Inf": count,
    }
    return [
        sample(
            {
                "instance": instance,
                "job": job,
                "le": bucket,
                "operation": operation,
                "result": result,
            },
            value,
            timestamp=timestamp,
        )
        for bucket, value in values.items()
    ]


def capture(
    kind: str,
    *,
    timestamp: float,
    attempts: list[dict],
    process_start: float = 900,
) -> dict:
    config, target = values()
    prometheus = {}
    for name in CONTROL.PROMQL:
        samples: list[dict] = []
        if name == "attempts":
            samples = attempts
        elif name == "process_start":
            samples = [
                sample(
                    {"component": component, "instance": instance},
                    process_start,
                    timestamp=timestamp,
                )
                for component, instances in (
                    ("edge", CONTROLLERS),
                    ("reconcile", CONTROLLERS[:2]),
                )
                for instance in instances
            ]
        prometheus[name] = {
            "promql_sha256": payload_hash(
                CONTROL.PROMQL[name].encode("utf-8")
            ),
            "samples": samples,
        }
    unsigned = {
        "capture_kind": kind,
        "collector_source_sha256": config[
            "control_collector_source_sha256"
        ],
        "completed_at_seconds": timestamp + 2,
        "phase": config["phase"],
        "prometheus": prometheus,
        "schema": CONTROL.CAPTURE_SCHEMA,
        "sql": sql_snapshot(),
        "sql_observed_at_seconds": timestamp + 1,
        "started_at_seconds": timestamp,
        "target_sha256": target["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "capture_sha256": CONTROL._hash(unsigned)}


def compile_pair(baseline: dict, current: dict) -> dict:
    config, target = values()
    return COLLECTOR.compile_artifact(
        config,
        target,
        baseline,
        current,
        target_file_sha256=TARGET_FILE_SHA256,
    )


@pytest.mark.parametrize("attempts", (1, 2, 3))
def test_galera_artifact_uses_observed_application_attempts(
    attempts: int,
) -> None:
    baseline = capture("baseline", timestamp=1000, attempts=[])
    current = capture(
        "current",
        timestamp=1100,
        attempts=attempt_group(attempts=attempts, timestamp=1100),
    )

    artifact = compile_pair(baseline, current)

    assert artifact["aggregate"] == {
        "max_transaction_attempts": attempts,
        "unexpected_errors": 0,
    }
    assert artifact["schema"] == COLLECTOR.source_summaries.ARTIFACT_SCHEMA
    assert artifact["source_class"] == "transaction-attempt-aggregate"
    retained = json.dumps(artifact, sort_keys=True)
    for forbidden in (
        "controller1",
        "coffer-edge",
        "reserve",
        "database_error",
        "project",
    ):
        assert forbidden not in retained


def test_galera_artifact_counts_only_terminal_database_failures() -> None:
    baseline = capture("baseline", timestamp=1000, attempts=[])
    current = capture(
        "current",
        timestamp=1100,
        attempts=[
            *attempt_group(
                attempts=2,
                count=4,
                result="success",
                timestamp=1100,
            ),
            *attempt_group(
                attempts=3,
                count=2,
                operation="commit",
                result="conflict_exhausted",
                timestamp=1100,
            ),
            *attempt_group(
                attempts=1,
                count=3,
                operation="claim",
                result="database_error",
                timestamp=1100,
            ),
            *attempt_group(
                attempts=1,
                count=5,
                operation="release",
                result="rejected",
                timestamp=1100,
            ),
        ],
    )

    artifact = compile_pair(baseline, current)

    assert artifact["aggregate"] == {
        "max_transaction_attempts": 3,
        "unexpected_errors": 5,
    }


def rehash(value: dict) -> None:
    value["capture_sha256"] = CONTROL._hash(
        {
            key: nested
            for key, nested in value.items()
            if key != "capture_sha256"
        }
    )


def test_galera_artifact_refuses_process_restart() -> None:
    baseline = capture(
        "baseline",
        timestamp=1000,
        attempts=[],
        process_start=900,
    )
    current = capture(
        "current",
        timestamp=1100,
        attempts=attempt_group(attempts=2, timestamp=1100),
        process_start=1050,
    )

    with pytest.raises(COLLECTOR.GaleraArtifactError, match="restarted"):
        compile_pair(baseline, current)


def test_galera_artifact_refuses_disappeared_attempt_series() -> None:
    baseline = capture(
        "baseline",
        timestamp=1000,
        attempts=attempt_group(
            attempts=1,
            count=2,
            timestamp=1000,
        ),
    )
    current = capture(
        "current",
        timestamp=1100,
        attempts=attempt_group(
            attempts=2,
            count=1,
            operation="commit",
            timestamp=1100,
        ),
    )

    with pytest.raises(
        COLLECTOR.GaleraArtifactError,
        match="transaction evidence",
    ):
        compile_pair(baseline, current)


def test_galera_artifact_refuses_counter_reset() -> None:
    baseline = capture(
        "baseline",
        timestamp=1000,
        attempts=attempt_group(
            attempts=2,
            count=2,
            result="database_error",
            timestamp=1000,
        ),
    )
    current = capture(
        "current",
        timestamp=1100,
        attempts=attempt_group(
            attempts=2,
            count=1,
            result="database_error",
            timestamp=1100,
        ),
    )

    with pytest.raises(
        COLLECTOR.GaleraArtifactError,
        match="transaction evidence",
    ):
        compile_pair(baseline, current)


def test_galera_artifact_refuses_missing_phase_observation() -> None:
    baseline = capture("baseline", timestamp=1000, attempts=[])
    current = capture("current", timestamp=1100, attempts=[])

    with pytest.raises(
        COLLECTOR.GaleraArtifactError,
        match="transaction evidence",
    ):
        compile_pair(baseline, current)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("phase", "before", "control capture"),
        (
            "window_sha256",
            f"sha256:{'0' * 64}",
            "control capture",
        ),
        (
            "control_collector_source_sha256",
            f"sha256:{'0' * 64}",
            "binding",
        ),
        (
            "collector_source_sha256",
            f"sha256:{'0' * 64}",
            "binding",
        ),
    ],
)
def test_galera_artifact_refuses_config_drift(
    field: str,
    value: str,
    message: str,
) -> None:
    config, target = values()
    config[field] = value
    baseline = capture("baseline", timestamp=1000, attempts=[])
    current = capture(
        "current",
        timestamp=1100,
        attempts=attempt_group(attempts=2, timestamp=1100),
    )

    with pytest.raises(COLLECTOR.GaleraArtifactError, match=message):
        COLLECTOR.compile_artifact(
            config,
            target,
            baseline,
            current,
            target_file_sha256=TARGET_FILE_SHA256,
        )


def test_galera_artifact_refuses_capture_hash_drift() -> None:
    baseline = capture("baseline", timestamp=1000, attempts=[])
    current = capture(
        "current",
        timestamp=1100,
        attempts=attempt_group(attempts=2, timestamp=1100),
    )
    current["prometheus"]["attempts"]["samples"][0]["value"] = 1

    with pytest.raises(
        COLLECTOR.GaleraArtifactError,
        match="control capture",
    ):
        compile_pair(baseline, current)


def test_galera_artifact_file_boundary_is_owner_only(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    target = RENDERER.render_request(target_request())
    target_path = tmp_path / "target.json"
    target_payload = canonical(target)
    owner_file(target_path, target_payload)
    config, _ = values(
        target_file=str(target_path),
        target_file_sha256=payload_hash(target_payload),
    )
    config_path = tmp_path / "config.json"
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    output_path = tmp_path / "galera.json"
    owner_file(config_path, canonical(config))
    owner_file(
        baseline_path,
        canonical(capture("baseline", timestamp=1000, attempts=[])),
    )
    owner_file(
        current_path,
        canonical(
            capture(
                "current",
                timestamp=1100,
                attempts=attempt_group(attempts=2, timestamp=1100),
            )
        ),
    )

    artifact = COLLECTOR.compile_file(
        config_path,
        baseline_path,
        current_path,
        output_path,
    )

    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert output_path.read_bytes() == canonical(artifact)


def test_galera_artifact_file_boundary_refuses_alias(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    target = RENDERER.render_request(target_request())
    target_path = tmp_path / "target.json"
    target_payload = canonical(target)
    owner_file(target_path, target_payload)
    config, _ = values(
        target_file=str(target_path),
        target_file_sha256=payload_hash(target_payload),
    )
    config_path = tmp_path / "config.json"
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    owner_file(config_path, canonical(config))
    owner_file(
        baseline_path,
        canonical(capture("baseline", timestamp=1000, attempts=[])),
    )
    os.link(baseline_path, current_path)

    with pytest.raises(COLLECTOR.GaleraArtifactError, match="file boundary"):
        COLLECTOR.compile_file(
            config_path,
            baseline_path,
            current_path,
            tmp_path / "galera.json",
        )


def test_galera_source_hash_covers_shared_attempt_contract() -> None:
    paths = [str(path.relative_to(ROOT)) for path in COLLECTOR.SOURCE_FILES]

    assert "src/coffer/quota.py" in paths
    assert "src/coffer/observability.py" in paths
    assert "poc/load-soak/collector/control_artifacts.py" in paths
    assert "poc/load-soak/collector/galera_artifacts.py" in paths
