from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ACQUISITION_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "source_summaries.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


ACQUISITION = load_module(
    "coffer_load_source_summaries_tests",
    ACQUISITION_PATH,
)
COMPILER = ACQUISITION.phase_evidence
RENDERER = ACQUISITION.render_target
LOAD_TOPOLOGY = ACQUISITION.load_contract.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = (
    ACQUISITION.observability_contract.load_topology(
        ROOT / "poc" / "observability" / "topology.json"
    )
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
WINDOW_SHA256 = f"sha256:{'7' * 64}"
COLLECTOR_HASHES = {
    surface: f"sha256:{index + 1:064x}"
    for index, surface in enumerate(COMPILER.SURFACES)
}


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
        "load_topology_sha256": ACQUISITION.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "observability_topology_sha256": ACQUISITION.native_target._hash(
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
        "target_class": ACQUISITION.native_target.TARGET_CLASS,
    }


def aggregates() -> dict[str, dict]:
    return {
        "prometheus": {"secret_leaks": 0},
        "haproxy": {"unexpected_errors": 0},
        "galera": {
            "max_transaction_attempts": 2,
            "unexpected_errors": 0,
        },
        "rgw": {
            "kms_errors": 0,
            "multipart_uploads": 0,
            "unexpected_errors": 0,
        },
        "quota": {
            "headroom_percent": 40,
            "invariant": True,
            "limit_usage_percent": 60,
            "max_transaction_attempts": 2,
            "stale_claims": 0,
            "unexpected_errors": 0,
        },
        "reconciliation": {
            "claims_exact": True,
            "fencing_violations": 0,
            "fresh": True,
            "last_success_age_seconds": 30,
            "stale_claims": 0,
            "workers_total": 2,
            "workers_up": 2,
        },
    }


def source_artifact(
    surface: str,
    aggregate: dict,
    *,
    phase: str,
    target_sha256: str,
) -> dict:
    artifact = {
        "aggregate": aggregate,
        "collector_source_sha256": COLLECTOR_HASHES[surface],
        "observations": 10,
        "phase": phase,
        "schema": ACQUISITION.ARTIFACT_SCHEMA,
        "source_class": COMPILER.SOURCE_CLASSES[surface],
        "surface": surface,
        "target_sha256": target_sha256,
        "window_sha256": WINDOW_SHA256,
    }
    artifact["artifact_sha256"] = ACQUISITION._hash(artifact)
    return artifact


def values(
    phase: str = "before",
) -> tuple[dict, dict, bytes, dict[str, tuple[dict, bytes]]]:
    target = RENDERER.render_request(target_request())
    target_payload = canonical(target)
    payloads = aggregates()
    artifacts: dict[str, tuple[dict, bytes]] = {}
    descriptors = {}
    for surface in COMPILER.SURFACES:
        artifact = source_artifact(
            surface,
            payloads[surface],
            phase=phase,
            target_sha256=target["target_sha256"],
        )
        artifact_payload = canonical(artifact)
        artifacts[surface] = (artifact, artifact_payload)
        descriptors[surface] = {
            "collector_source_sha256": COLLECTOR_HASHES[surface],
            "file": f"/unused/{surface}.json",
            "file_sha256": payload_hash(artifact_payload),
        }
    config = {
        "acquisition_source_sha256": (
            ACQUISITION.acquisition_source_sha256()
        ),
        "artifacts": descriptors,
        "phase": phase,
        "schema": ACQUISITION.CONFIG_SCHEMA,
        "target_file": "/unused/target.json",
        "target_file_sha256": payload_hash(target_payload),
        "window_sha256": WINDOW_SHA256,
    }
    return config, target, target_payload, artifacts


@pytest.mark.parametrize("phase", ACQUISITION.native_target.PHASES)
def test_acquisition_compiles_artifacts_into_v2_summaries(
    phase: str,
) -> None:
    config, target, target_payload, artifacts = values(phase)
    request = ACQUISITION.compile_request(
        config,
        target,
        artifacts,
        target_file_sha256=payload_hash(target_payload),
    )

    assert request["schema"] == COMPILER.REQUEST_SCHEMA
    assert request["phase"] == phase
    assert request["target_sha256"] == target["target_sha256"]
    for surface, summary in request["summaries"].items():
        artifact, artifact_payload = artifacts[surface]
        assert summary["schema"] == COMPILER.SUMMARY_SCHEMA
        assert summary["schema"].endswith("/v2")
        assert summary["payload"] == artifact["aggregate"]
        assert summary["collector_source_sha256"] == COLLECTOR_HASHES[
            surface
        ]
        assert summary["source_artifact_sha256"] == payload_hash(
            artifact_payload
        )
        assert "observations" not in summary
        assert "artifact_sha256" not in summary
        unsigned = {
            key: value
            for key, value in summary.items()
            if key != "summary_sha256"
        }
        assert summary["summary_sha256"] == COMPILER._hash(unsigned)
    bundle = COMPILER.compile_bundle(
        request,
        target,
        target_file_sha256=payload_hash(target_payload),
    )
    assert bundle["phase"] == phase


def file_fixture(
    tmp_path: Path,
    *,
    phase: str = "before",
) -> tuple[Path, Path, dict, dict[str, Path]]:
    tmp_path.chmod(0o700)
    config, target, target_payload, artifacts = values(phase)
    target_path = tmp_path / "target.json"
    owner_file(target_path, target_payload)
    config["target_file"] = str(target_path)
    artifact_paths = {}
    for surface, (artifact, artifact_payload) in artifacts.items():
        path = tmp_path / f"{surface}.json"
        owner_file(path, artifact_payload)
        artifact_paths[surface] = path
        config["artifacts"][surface]["file"] = str(path)
    config_path = tmp_path / "config.json"
    owner_file(config_path, canonical(config))
    return config_path, target_path, target, artifact_paths


def test_file_compiler_is_atomic_owner_only_and_idempotent(
    tmp_path: Path,
) -> None:
    config_path, target_path, target, _ = file_fixture(tmp_path)
    output_path = tmp_path / "phase-request.json"

    first = ACQUISITION.compile_file(config_path, output_path)
    first_payload = output_path.read_bytes()
    first_mtime = output_path.stat().st_mtime_ns
    second = ACQUISITION.compile_file(config_path, output_path)

    assert first == second
    assert first_payload == canonical(first)
    assert output_path.read_bytes() == first_payload
    assert output_path.stat().st_mtime_ns == first_mtime
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    COMPILER.compile_bundle(
        first,
        target,
        target_file_sha256=payload_hash(target_path.read_bytes()),
    )


def test_acquisition_preserves_bounded_failure_aggregates() -> None:
    config, target, target_payload, artifacts = values("during")
    failure = {
        "prometheus": {"secret_leaks": 1},
        "haproxy": {"unexpected_errors": 2},
        "galera": {
            "max_transaction_attempts": 4,
            "unexpected_errors": 3,
        },
        "rgw": {
            "kms_errors": 4,
            "multipart_uploads": 5,
            "unexpected_errors": 6,
        },
        "quota": {
            "headroom_percent": 20,
            "invariant": False,
            "limit_usage_percent": 80,
            "max_transaction_attempts": 4,
            "stale_claims": 7,
            "unexpected_errors": 8,
        },
        "reconciliation": {
            "claims_exact": False,
            "fencing_violations": 9,
            "fresh": False,
            "last_success_age_seconds": 120,
            "stale_claims": 10,
            "workers_total": 2,
            "workers_up": 0,
        },
    }
    for surface, aggregate in failure.items():
        artifact = source_artifact(
            surface,
            aggregate,
            phase="during",
            target_sha256=target["target_sha256"],
        )
        artifact_payload = canonical(artifact)
        artifacts[surface] = (artifact, artifact_payload)
        config["artifacts"][surface]["file_sha256"] = payload_hash(
            artifact_payload
        )

    request = ACQUISITION.compile_request(
        config,
        target,
        artifacts,
        target_file_sha256=payload_hash(target_payload),
    )

    for surface, aggregate in failure.items():
        assert request["summaries"][surface]["payload"] == aggregate


@pytest.mark.parametrize(
    "mutation",
    (
        "config-schema",
        "config-extra",
        "acquisition-source",
        "phase",
        "window",
        "target-file-hash",
        "descriptor-missing",
        "descriptor-extra",
        "descriptor-source",
        "descriptor-file-hash",
        "artifact-schema",
        "artifact-extra",
        "artifact-phase",
        "artifact-window",
        "artifact-surface",
        "artifact-class",
        "artifact-source",
        "artifact-target",
        "artifact-hash",
        "artifact-observations-zero",
        "artifact-observations-large",
    ),
)
def test_acquisition_refuses_config_descriptor_and_artifact_drift(
    mutation: str,
) -> None:
    config, target, target_payload, artifacts = values()
    if mutation == "config-schema":
        config["schema"] = "unknown"
    elif mutation == "config-extra":
        config["raw_logs"] = []
    elif mutation == "acquisition-source":
        config["acquisition_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "phase":
        config["phase"] = "steady"
    elif mutation == "window":
        config["window_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "target-file-hash":
        config["target_file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "descriptor-missing":
        del config["artifacts"]["haproxy"]
    elif mutation == "descriptor-extra":
        config["artifacts"]["prometheus"]["raw_url"] = "https://secret"
    elif mutation == "descriptor-source":
        config["artifacts"]["prometheus"][
            "collector_source_sha256"
        ] = f"sha256:{'0' * 64}"
    elif mutation == "descriptor-file-hash":
        config["artifacts"]["prometheus"][
            "file_sha256"
        ] = f"sha256:{'0' * 64}"
    else:
        artifact = artifacts["prometheus"][0]
        if mutation == "artifact-schema":
            artifact["schema"] = "unknown"
        elif mutation == "artifact-extra":
            artifact["project_id"] = "forbidden"
        elif mutation == "artifact-phase":
            artifact["phase"] = "during"
        elif mutation == "artifact-window":
            artifact["window_sha256"] = f"sha256:{'0' * 64}"
        elif mutation == "artifact-surface":
            artifact["surface"] = "haproxy"
        elif mutation == "artifact-class":
            artifact["source_class"] = "raw-log"
        elif mutation == "artifact-source":
            artifact["collector_source_sha256"] = f"sha256:{'0' * 64}"
        elif mutation == "artifact-target":
            artifact["target_sha256"] = f"sha256:{'0' * 64}"
        elif mutation == "artifact-hash":
            artifact["artifact_sha256"] = f"sha256:{'0' * 64}"
        elif mutation == "artifact-observations-zero":
            artifact["observations"] = 0
        else:
            artifact["observations"] = 1_000_001
        if mutation != "artifact-hash":
            unsigned = {
                key: value
                for key, value in artifact.items()
                if key != "artifact_sha256"
            }
            artifact["artifact_sha256"] = ACQUISITION._hash(unsigned)
        artifact_payload = canonical(artifact)
        artifacts["prometheus"] = (artifact, artifact_payload)
        config["artifacts"]["prometheus"]["file_sha256"] = payload_hash(
            artifact_payload
        )

    with pytest.raises(ACQUISITION.SourceSummaryError):
        ACQUISITION.compile_request(
            config,
            target,
            artifacts,
            target_file_sha256=payload_hash(target_payload),
        )


@pytest.mark.parametrize(
    ("surface", "field", "value"),
    (
        ("prometheus", "secret_leaks", -1),
        ("galera", "max_transaction_attempts", 65),
        ("rgw", "kms_errors", "one"),
        ("quota", "headroom_percent", math.nan),
        ("quota", "limit_usage_percent", 80),
        ("reconciliation", "workers_total", 3),
    ),
)
def test_acquisition_reuses_strict_aggregate_validation(
    surface: str,
    field: str,
    value: object,
) -> None:
    config, target, target_payload, artifacts = values()
    artifact = artifacts[surface][0]
    artifact["aggregate"][field] = value
    unsigned = {
        key: nested
        for key, nested in artifact.items()
        if key != "artifact_sha256"
    }
    artifact["artifact_sha256"] = ACQUISITION._hash(unsigned)
    artifact_payload = canonical(artifact)
    artifacts[surface] = (artifact, artifact_payload)
    config["artifacts"][surface]["file_sha256"] = payload_hash(
        artifact_payload
    )

    with pytest.raises(
        (
            ACQUISITION.SourceSummaryError,
            COMPILER.PhaseEvidenceError,
        )
    ):
        ACQUISITION.compile_request(
            config,
            target,
            artifacts,
            target_file_sha256=payload_hash(target_payload),
        )


@pytest.mark.parametrize(
    "unsafe",
    (
        "config-mode",
        "target-mode",
        "artifact-mode",
        "artifact-symlink",
        "input-alias",
        "output-config-alias",
        "output-target-alias",
        "output-artifact-alias",
        "output-mode",
        "parent-mode",
    ),
)
def test_cli_refuses_unsafe_or_aliased_files_without_echo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    unsafe: str,
) -> None:
    config_path, target_path, _, artifact_paths = file_fixture(tmp_path)
    output_path = tmp_path / "phase-request.json"
    if unsafe == "config-mode":
        config_path.chmod(0o640)
    elif unsafe == "target-mode":
        target_path.chmod(0o640)
    elif unsafe == "artifact-mode":
        artifact_paths["prometheus"].chmod(0o640)
    elif unsafe == "artifact-symlink":
        artifact = artifact_paths["prometheus"]
        real_artifact = artifact.with_name("real-prometheus.json")
        artifact.rename(real_artifact)
        artifact.symlink_to(real_artifact)
    elif unsafe == "input-alias":
        artifact = artifact_paths["prometheus"]
        artifact.unlink()
        artifact.hardlink_to(artifact_paths["haproxy"])
    elif unsafe == "output-config-alias":
        output_path = config_path
    elif unsafe == "output-target-alias":
        output_path = target_path
    elif unsafe == "output-artifact-alias":
        output_path = artifact_paths["prometheus"]
    elif unsafe == "output-mode":
        output_path.write_bytes(b"existing")
        output_path.chmod(0o640)
    else:
        tmp_path.chmod(0o750)

    assert (
        ACQUISITION.main(
            ["compile", str(config_path), str(output_path)]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "source-summaries-refused\n"
    if (
        output_path
        not in {config_path, target_path, *artifact_paths.values()}
        and unsafe != "output-mode"
    ):
        assert not output_path.exists()


def test_cli_outputs_only_phase_and_request_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _, _, _ = file_fixture(tmp_path)
    output_path = tmp_path / "phase-request.json"

    assert (
        ACQUISITION.main(
            ["compile", str(config_path), str(output_path)]
        )
        == 0
    )
    captured = capsys.readouterr()
    request = json.loads(output_path.read_bytes())
    result = json.loads(captured.out)
    assert result == {
        "phase": "before",
        "request_sha256": ACQUISITION._hash(request),
        "schema": ACQUISITION.RESULT_SCHEMA,
    }
    assert captured.out == canonical(result).decode("utf-8")
    assert captured.err == ""
    assert "https://" not in captured.out


def test_source_hash_is_machine_readable_and_has_no_runtime_adapter(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ACQUISITION.main(["source-hash"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result == {
        "acquisition_source_sha256": (
            ACQUISITION.acquisition_source_sha256()
        ),
        "schema": ACQUISITION.SOURCE_RESULT_SCHEMA,
    }
    assert captured.out == canonical(result).decode("utf-8")
    source = ACQUISITION_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "http.client" not in source
    assert "urllib.request" not in source
    assert "\nimport socket" not in source
