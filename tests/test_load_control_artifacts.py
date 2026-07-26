from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

from coffer.quota import QuotaControlEvidenceSnapshot


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "control_artifacts.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


COLLECTOR = load_module(
    "coffer_load_control_artifact_tests",
    COLLECTOR_PATH,
)
RENDERER = COLLECTOR.render_target
LOAD_TOPOLOGY = COLLECTOR.load_contract.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = COLLECTOR.observability_contract.load_topology(
    ROOT / "poc" / "observability" / "topology.json"
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
WINDOW_SHA256 = f"sha256:{'7' * 64}"
TARGET_FILE = "/owner/control/native-target.json"
CA_FILE = "/owner/control/ca.pem"
CA_SHA256 = f"sha256:{'8' * 64}"
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
        "load_topology_sha256": COLLECTOR.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "observability_topology_sha256": COLLECTOR.native_target._hash(
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
        "target_class": COLLECTOR.native_target.TARGET_CLASS,
    }


def values() -> tuple[dict, dict]:
    target = RENDERER.render_request(target_request())
    config = {
        "ca_file": CA_FILE,
        "ca_file_sha256": CA_SHA256,
        "collector_source_sha256": COLLECTOR.collector_source_sha256(),
        "phase": "during",
        "reconciliation_freshness_seconds": 90,
        "schema": COLLECTOR.CONFIG_SCHEMA,
        "target_file": TARGET_FILE,
        "target_file_sha256": TARGET_FILE_SHA256,
        "timeout_seconds": 5,
        "window_sha256": WINDOW_SHA256,
    }
    return config, target


def vector(samples: list[tuple[dict[str, str], float]], timestamp: float) -> dict:
    return {
        "data": {
            "result": [
                {
                    "metric": labels,
                    "value": [timestamp, str(value)],
                }
                for labels, value in samples
            ],
            "resultType": "vector",
        },
        "status": "success",
    }


def documents(
    *,
    timestamp: float,
    attempts: int | None,
    edge_errors: int = 0,
    process_start: float = 900,
    workers_up: tuple[int, int] = (1, 1),
    database_up: tuple[int, int] = (1, 1),
    last_success: tuple[float, float] | None = None,
) -> dict[str, dict]:
    if last_success is None:
        last_success = (timestamp - 20, timestamp - 30)
    attempt_samples: list[tuple[dict[str, str], float]] = []
    if attempts is not None:
        bucket_values = {
            "1.0": int(attempts <= 1),
            "2.0": int(attempts <= 2),
            "3.0": 1,
            "+Inf": 1,
        }
        attempt_samples = [
            (
                {
                    "instance": CONTROLLERS[0],
                    "job": "coffer-edge",
                    "le": bucket,
                    "operation": "reserve",
                    "result": "success",
                },
                count,
            )
            for bucket, count in bucket_values.items()
        ]
    return {
        "attempts": vector(attempt_samples, timestamp),
        "edge_internal_errors": vector(
            [
                ({"instance": instance}, edge_errors)
                for instance in CONTROLLERS
            ],
            timestamp,
        ),
        "process_start": vector(
            [
                (
                    {"component": component, "instance": instance},
                    process_start,
                )
                for component, instances in (
                    ("edge", CONTROLLERS),
                    ("reconcile", CONTROLLERS[:2]),
                )
                for instance in instances
            ],
            timestamp,
        ),
        "reconcile_database_up": vector(
            [
                ({"instance": instance}, value)
                for instance, value in zip(CONTROLLERS[:2], database_up)
            ],
            timestamp,
        ),
        "reconcile_last_success": vector(
            [
                ({"instance": instance}, value)
                for instance, value in zip(CONTROLLERS[:2], last_success)
            ],
            timestamp,
        ),
        "reconcile_up": vector(
            [
                ({"instance": instance}, value)
                for instance, value in zip(CONTROLLERS[:2], workers_up)
            ],
            timestamp,
        ),
    }


class FakeClient:
    def __init__(
        self,
        query_documents: dict[str, dict],
        *,
        expected_ca: Path = Path(CA_FILE),
    ) -> None:
        self.documents = query_documents
        self.expected_ca = expected_ca
        self.urls: list[str] = []

    def fetch_json(
        self,
        url: str,
        *,
        ca_file: Path,
        timeout_seconds: float,
    ) -> object:
        assert ca_file == self.expected_ca
        assert timeout_seconds == 5
        self.urls.append(url)
        query = parse_qs(urlsplit(url).query)["query"]
        assert len(query) == 1
        name = next(
            name
            for name, promql in COLLECTOR.PROMQL.items()
            if promql == query[0]
        )
        return self.documents[name]


class FakeStore:
    def __init__(self, snapshot: QuotaControlEvidenceSnapshot) -> None:
        self.snapshot = snapshot
        self.projects: list[str] = []

    def control_evidence_snapshot(
        self,
        project_id: str,
        *,
        observed_at,
    ) -> QuotaControlEvidenceSnapshot:
        assert observed_at.tzinfo is not None
        self.projects.append(project_id)
        return self.snapshot


def snapshot() -> QuotaControlEvidenceSnapshot:
    return QuotaControlEvidenceSnapshot(
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


def capture(
    kind: str,
    *,
    timestamp: float,
    attempts: int | None,
    edge_errors: int = 0,
    process_start: float = 900,
    workers_up: tuple[int, int] = (1, 1),
    database_up: tuple[int, int] = (1, 1),
    last_success: tuple[float, float] | None = None,
    sql_snapshot: QuotaControlEvidenceSnapshot | None = None,
) -> dict:
    config, target = values()
    client = FakeClient(
        documents(
            timestamp=timestamp,
            attempts=attempts,
            edge_errors=edge_errors,
            process_start=process_start,
            workers_up=workers_up,
            database_up=database_up,
            last_success=last_success,
        )
    )
    store = FakeStore(sql_snapshot or snapshot())
    result = COLLECTOR.capture_snapshot(
        config,
        target,
        target_file_sha256=TARGET_FILE_SHA256,
        capture_kind=kind,
        client=client,
        store=store,
        project_id="project-owner-only",
        ca_file=Path(CA_FILE),
        clock=iter((timestamp, timestamp + 1, timestamp + 2)).__next__,
    )
    assert len(client.urls) == len(COLLECTOR.PROMQL)
    assert store.projects == ["project-owner-only"]
    assert "project-owner-only" not in json.dumps(result)
    return result


def compile_pair(
    baseline: dict,
    current: dict,
) -> dict[str, dict]:
    config, target = values()
    return COLLECTOR.compile_artifacts(
        config,
        target,
        baseline,
        current,
        target_file_sha256=TARGET_FILE_SHA256,
    )


@pytest.mark.parametrize("attempts", (1, 2, 3))
def test_control_capture_compiles_exact_v2_artifacts(attempts: int) -> None:
    baseline = capture("baseline", timestamp=1000, attempts=None)
    current = capture("current", timestamp=1100, attempts=attempts)

    artifacts = compile_pair(baseline, current)

    quota = artifacts["quota"]
    reconciliation = artifacts["reconciliation"]
    assert quota["schema"] == COLLECTOR.source_summaries.ARTIFACT_SCHEMA
    assert quota["aggregate"] == {
        "headroom_percent": 40.0,
        "invariant": True,
        "limit_usage_percent": 60.0,
        "max_transaction_attempts": attempts,
        "stale_claims": 0,
        "unexpected_errors": 0,
    }
    assert reconciliation["aggregate"] == {
        "claims_exact": True,
        "fencing_violations": 0,
        "fresh": True,
        "last_success_age_seconds": 32.0,
        "stale_claims": 0,
        "workers_total": 2,
        "workers_up": 2,
    }
    assert (
        quota["input_set_sha256"]
        == reconciliation["input_set_sha256"]
    )
    for artifact in artifacts.values():
        retained = json.dumps(artifact, sort_keys=True)
        for forbidden in (
            "controller1",
            "project-owner-only",
            "prometheus.stage6.test",
            "coffer-edge",
            "reserve",
        ):
            assert forbidden not in retained


def rehash_capture(value: dict) -> None:
    unsigned = {
        key: nested
        for key, nested in value.items()
        if key != "capture_sha256"
    }
    value["capture_sha256"] = COLLECTOR._hash(unsigned)


def test_control_artifact_reduces_errors_and_unhealthy_reconciler() -> None:
    baseline = capture(
        "baseline",
        timestamp=1000,
        attempts=None,
        edge_errors=2,
    )
    current = capture(
        "current",
        timestamp=1100,
        attempts=2,
        edge_errors=3,
        workers_up=(1, 0),
        database_up=(1, 0),
    )

    artifacts = compile_pair(baseline, current)

    assert artifacts["quota"]["aggregate"]["unexpected_errors"] == 3
    assert artifacts["reconciliation"]["aggregate"]["fresh"] is False
    assert artifacts["reconciliation"]["aggregate"]["workers_up"] == 1


def test_control_artifact_refuses_missing_attempt_observation() -> None:
    baseline = capture("baseline", timestamp=1000, attempts=None)
    current = capture("current", timestamp=1100, attempts=None)

    with pytest.raises(
        COLLECTOR.ControlArtifactError,
        match="observation is absent",
    ):
        compile_pair(baseline, current)


def test_control_artifact_refuses_process_restart() -> None:
    baseline = capture(
        "baseline",
        timestamp=1000,
        attempts=None,
        process_start=900,
    )
    current = capture(
        "current",
        timestamp=1100,
        attempts=2,
        process_start=1050,
    )

    with pytest.raises(
        COLLECTOR.ControlArtifactError,
        match="restarted",
    ):
        compile_pair(baseline, current)


def test_control_artifact_refuses_counter_reset() -> None:
    baseline = capture(
        "baseline",
        timestamp=1000,
        attempts=None,
        edge_errors=2,
    )
    current = capture(
        "current",
        timestamp=1100,
        attempts=2,
        edge_errors=1,
    )

    with pytest.raises(COLLECTOR.ControlArtifactError, match="counter reset"):
        compile_pair(baseline, current)


@pytest.mark.parametrize(
    ("query", "mutation", "message"),
    [
        (
            "reconcile_up",
            lambda samples: samples.pop(),
            "incomplete",
        ),
        (
            "reconcile_database_up",
            lambda samples: samples.append(samples[0]),
            "duplicated",
        ),
        (
            "edge_internal_errors",
            lambda samples: samples[0]["labels"].update(
                {"instance": "unknown-controller"}
            ),
            "series changed",
        ),
        (
            "attempts",
            lambda samples: samples.pop(),
            "buckets are incomplete",
        ),
    ],
)
def test_control_artifact_refuses_series_drift(
    query: str,
    mutation,
    message: str,
) -> None:
    baseline = capture("baseline", timestamp=1000, attempts=None)
    current = capture("current", timestamp=1100, attempts=2)
    mutation(current["prometheus"][query]["samples"])
    rehash_capture(current)

    with pytest.raises(COLLECTOR.ControlArtifactError, match=message):
        compile_pair(baseline, current)


def test_control_capture_refuses_partial_prometheus_warning() -> None:
    config, target = values()
    query_documents = documents(timestamp=1000, attempts=None)
    query_documents["reconcile_up"]["warnings"] = ["partial response"]

    with pytest.raises(
        COLLECTOR.ControlArtifactError,
        match="response is invalid",
    ):
        COLLECTOR.capture_snapshot(
            config,
            target,
            target_file_sha256=TARGET_FILE_SHA256,
            capture_kind="baseline",
            client=FakeClient(query_documents),
            store=FakeStore(snapshot()),
            project_id="project-owner-only",
            ca_file=Path(CA_FILE),
            clock=iter((1000, 1001, 1002)).__next__,
        )


def test_control_artifact_refuses_sql_invariant_conflict() -> None:
    baseline = capture("baseline", timestamp=1000, attempts=None)
    current = capture("current", timestamp=1100, attempts=2)
    current["sql"]["quota_invariant"] = False
    rehash_capture(current)

    with pytest.raises(COLLECTOR.ControlArtifactError, match="conflicts"):
        compile_pair(baseline, current)


def test_control_artifact_retains_failed_sql_invariant_truthfully() -> None:
    baseline = capture("baseline", timestamp=1000, attempts=None)
    current = capture(
        "current",
        timestamp=1100,
        attempts=2,
        sql_snapshot=replace(
            snapshot(),
            used_bytes=501,
        ),
    )

    artifacts = compile_pair(baseline, current)

    assert artifacts["quota"]["aggregate"]["invariant"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("phase", "before", "binding"),
        ("window_sha256", f"sha256:{'0' * 64}", "binding"),
        ("target_sha256", f"sha256:{'0' * 64}", "binding"),
        (
            "collector_source_sha256",
            f"sha256:{'0' * 64}",
            "binding",
        ),
    ],
)
def test_control_artifact_refuses_capture_binding_drift(
    field: str,
    value: object,
    message: str,
) -> None:
    baseline = capture("baseline", timestamp=1000, attempts=None)
    current = capture("current", timestamp=1100, attempts=2)
    current[field] = value
    rehash_capture(current)

    with pytest.raises(COLLECTOR.ControlArtifactError, match=message):
        compile_pair(baseline, current)


def test_control_artifact_refuses_capture_hash_drift() -> None:
    baseline = capture("baseline", timestamp=1000, attempts=None)
    current = capture("current", timestamp=1100, attempts=2)
    current["sql"]["reserved_bytes"] = 101

    with pytest.raises(COLLECTOR.ControlArtifactError, match="hash changed"):
        compile_pair(baseline, current)


def test_source_hash_covers_collector_and_runtime_contract() -> None:
    expected = {
        str(path.relative_to(ROOT)): payload_hash(path.read_bytes())
        for path in COLLECTOR.SOURCE_FILES
    }

    assert COLLECTOR.collector_source_sha256() == COLLECTOR._hash(
        {
            "files": [
                {"path": path, "sha256": digest}
                for path, digest in expected.items()
            ]
        }
    )
    assert "src/coffer/quota.py" in expected
    assert "src/coffer/observability.py" in expected
    assert "poc/load-soak/collector/control_artifacts.py" in expected


def file_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict, dict]:
    tmp_path.chmod(0o700)
    target = RENDERER.render_request(target_request())
    target_path = tmp_path / "target.json"
    target_payload = canonical(target)
    owner_file(target_path, target_payload)
    ca_path = tmp_path / "ca.pem"
    ca_payload = b"fixture-ca"
    owner_file(ca_path, ca_payload)
    config = {
        "ca_file": str(ca_path),
        "ca_file_sha256": payload_hash(ca_payload),
        "collector_source_sha256": COLLECTOR.collector_source_sha256(),
        "phase": "during",
        "reconciliation_freshness_seconds": 90,
        "schema": COLLECTOR.CONFIG_SCHEMA,
        "target_file": str(target_path),
        "target_file_sha256": payload_hash(target_payload),
        "timeout_seconds": 5,
        "window_sha256": WINDOW_SHA256,
    }
    config_path = tmp_path / "config.json"
    owner_file(config_path, canonical(config))
    return config_path, target_path, ca_path, config, target


def test_file_boundary_captures_and_compiles_owner_only_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, ca_path, _, _ = file_fixture(tmp_path)
    monkeypatch.setenv(COLLECTOR.DATABASE_URL_ENV, "sqlite:///owner-only")
    monkeypatch.setenv(COLLECTOR.PROJECT_ID_ENV, "project-owner-only")
    connections: list[str] = []

    def store_factory(connection: str) -> FakeStore:
        connections.append(connection)
        return FakeStore(snapshot())

    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    COLLECTOR.capture_file(
        config_path,
        "baseline",
        baseline_path,
        client=FakeClient(
            documents(timestamp=1000, attempts=None),
            expected_ca=ca_path,
        ),
        store_factory=store_factory,
        clock=iter((1000, 1001, 1002)).__next__,
    )
    COLLECTOR.capture_file(
        config_path,
        "current",
        current_path,
        client=FakeClient(
            documents(timestamp=1100, attempts=2),
            expected_ca=ca_path,
        ),
        store_factory=store_factory,
        clock=iter((1100, 1101, 1102)).__next__,
    )
    quota_path = tmp_path / "quota.json"
    reconciliation_path = tmp_path / "reconciliation.json"

    artifacts = COLLECTOR.compile_files(
        config_path,
        baseline_path,
        current_path,
        quota_path,
        reconciliation_path,
    )

    assert connections == ["sqlite:///owner-only", "sqlite:///owner-only"]
    for path, surface in (
        (quota_path, "quota"),
        (reconciliation_path, "reconciliation"),
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_bytes() == canonical(artifacts[surface])
        retained = path.read_text()
        assert "project-owner-only" not in retained
        assert "sqlite:///owner-only" not in retained


def test_capture_refuses_unsafe_config_before_runtime_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, ca_path, _, _ = file_fixture(tmp_path)
    config_path.chmod(0o640)
    monkeypatch.setenv(COLLECTOR.DATABASE_URL_ENV, "sqlite:///credential-secret")
    monkeypatch.setenv(COLLECTOR.PROJECT_ID_ENV, "project-owner-only")
    store_calls: list[str] = []

    with pytest.raises(COLLECTOR.ControlArtifactError, match="unsafe"):
        COLLECTOR.capture_file(
            config_path,
            "baseline",
            tmp_path / "capture.json",
            client=FakeClient(
                documents(timestamp=1000, attempts=None),
                expected_ca=ca_path,
            ),
            store_factory=lambda connection: (
                store_calls.append(connection) or FakeStore(snapshot())
            ),
            clock=iter((1000, 1001, 1002)).__next__,
        )

    assert store_calls == []


def test_compile_refuses_output_hardlink_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, ca_path, _, _ = file_fixture(tmp_path)
    monkeypatch.setenv(COLLECTOR.DATABASE_URL_ENV, "sqlite:///owner-only")
    monkeypatch.setenv(COLLECTOR.PROJECT_ID_ENV, "project-owner-only")
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    COLLECTOR.capture_file(
        config_path,
        "baseline",
        baseline_path,
        client=FakeClient(
            documents(timestamp=1000, attempts=None),
            expected_ca=ca_path,
        ),
        store_factory=lambda _connection: FakeStore(snapshot()),
        clock=iter((1000, 1001, 1002)).__next__,
    )
    COLLECTOR.capture_file(
        config_path,
        "current",
        current_path,
        client=FakeClient(
            documents(timestamp=1100, attempts=2),
            expected_ca=ca_path,
        ),
        store_factory=lambda _connection: FakeStore(snapshot()),
        clock=iter((1100, 1101, 1102)).__next__,
    )
    quota_path = tmp_path / "quota.json"
    reconciliation_path = tmp_path / "reconciliation.json"
    owner_file(quota_path, b"existing")
    os.link(quota_path, reconciliation_path)

    with pytest.raises(COLLECTOR.ControlArtifactError, match="output is unsafe"):
        COLLECTOR.compile_files(
            config_path,
            baseline_path,
            current_path,
            quota_path,
            reconciliation_path,
        )
