from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "local_artifacts.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


COLLECTOR = load_module("coffer_load_local_artifacts_tests", MODULE_PATH)
ACQUISITION = COLLECTOR.source_summaries
RENDERER = COLLECTOR.render_target
LOAD_TOPOLOGY = COLLECTOR.load_contract.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = (
    COLLECTOR.observability_contract.load_topology(
        ROOT / "poc" / "observability" / "topology.json"
    )
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
WINDOW_SHA256 = f"sha256:{'7' * 64}"
PLAN_SHA256 = f"sha256:{'8' * 64}"


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


def target() -> dict:
    return RENDERER.render_request(target_request())


def profile_result(
    *,
    errors: int = 0,
    plan_sha256: str = PLAN_SHA256,
    source: str = "pilot",
) -> dict:
    counts = {
        operation: 1 for operation in LOAD_TOPOLOGY["operations"]
    }
    attempts = len(counts)
    return {
        "attempts": attempts,
        "duration_seconds": 120,
        "execution_source": source,
        "kind": "profile",
        "last_wave_sha256": f"sha256:{'1' * 64}",
        "maximum_clients": 4,
        "name": "smoke",
        "operation_counts": counts,
        "order": 1,
        "plan_sha256": plan_sha256,
        "profile_binding_sha256": f"sha256:{'2' * 64}",
        "schema": COLLECTOR.PROFILE_SCHEMA,
        "successful_operations": attempts,
        "synthetic": source == "fixture",
        "transferred_bytes": 1024,
        "unexpected_errors": errors,
        "waves": 1,
    }


def fault_result(
    *,
    errors: int = 0,
    plan_sha256: str = PLAN_SHA256,
    source: str = "pilot",
) -> dict:
    return {
        "actions_completed": 5,
        "execution_source": source,
        "fault": "api-replica",
        "fault_binding_sha256": f"sha256:{'3' * 64}",
        "history_sha256": f"sha256:{'4' * 64}",
        "plan_sha256": plan_sha256,
        "recovery_seconds": 30,
        "schema": COLLECTOR.FAULT_SCHEMA,
        "synthetic": source == "fixture",
        "target_evidence_sha256": f"sha256:{'5' * 64}",
        "unexpected_errors": errors,
        "window_seconds": 60,
    }


def config(
    surface: str,
    payloads: list[bytes],
    *,
    phase: str = "before",
    fingerprints: list[dict] | None = None,
    kinds: list[str] | None = None,
) -> tuple[dict, dict, bytes]:
    target_value = target()
    target_payload = canonical(target_value)
    if kinds is None:
        kinds = ["profile"] * len(payloads)
    descriptors = []
    for index, payload in enumerate(payloads):
        descriptor = {
            "file": f"/unused/input-{index}.data",
            "file_sha256": payload_hash(payload),
        }
        if surface == "haproxy":
            descriptor["kind"] = kinds[index]
        descriptors.append(descriptor)
    source = {
        "files": descriptors,
        "kind": COLLECTOR.SOURCE_KINDS[surface],
    }
    if surface == "prometheus":
        source["fingerprints"] = (
            [] if fingerprints is None else fingerprints
        )
    value = {
        "collector_source_sha256": (
            COLLECTOR.collector_source_sha256()
        ),
        "phase": phase,
        "schema": COLLECTOR.CONFIG_SCHEMA,
        "source": source,
        "surface": surface,
        "target_file": "/unused/target.json",
        "target_file_sha256": payload_hash(target_payload),
        "window_sha256": WINDOW_SHA256,
    }
    return value, target_value, target_payload


@pytest.mark.parametrize("phase", COLLECTOR.native_target.PHASES)
def test_secret_scan_artifact_binds_phase_target_and_inputs(
    phase: str,
) -> None:
    supplied = b"dummy-stage6-registry-key"
    fingerprint = COLLECTOR.fingerprint(supplied)
    payloads = [
        b"normal metrics output\n",
        b"value=" + supplied + b"\n",
    ]
    request, target_value, target_payload = config(
        "prometheus",
        payloads,
        phase=phase,
        fingerprints=[fingerprint],
    )

    artifact = COLLECTOR.compile_artifact(
        request,
        target_value,
        payloads,
        target_file_sha256=payload_hash(target_payload),
    )

    assert artifact["schema"] == ACQUISITION.ARTIFACT_SCHEMA
    assert artifact["schema"].endswith("/v2")
    assert artifact["aggregate"] == {"secret_leaks": 1}
    assert artifact["surface"] == "prometheus"
    assert artifact["phase"] == phase
    assert artifact["target_sha256"] == target_value["target_sha256"]
    assert artifact["window_sha256"] == WINDOW_SHA256
    assert artifact["observations"] == 2
    assert artifact["collector_source_sha256"] == (
        COLLECTOR.collector_source_sha256()
    )
    assert artifact["input_set_sha256"].startswith("sha256:")
    assert artifact["artifact_sha256"] == COLLECTOR._hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifact_sha256"
        }
    )
    artifact_payload = canonical(artifact)
    summary = ACQUISITION._artifact(
        artifact,
        collector_source_sha256=artifact[
            "collector_source_sha256"
        ],
        phase=phase,
        source_artifact_sha256=payload_hash(artifact_payload),
        surface="prometheus",
        target_sha256=target_value["target_sha256"],
        window_sha256=WINDOW_SHA256,
        load_topology=LOAD_TOPOLOGY,
    )
    assert summary["payload"] == artifact["aggregate"]
    assert summary["source_artifact_sha256"] == payload_hash(
        artifact_payload
    )
    serialized = json.dumps(artifact, sort_keys=True)
    assert supplied.decode() not in serialized
    assert "/unused/" not in serialized


def test_secret_scan_counts_builtin_patterns_without_fingerprints() -> None:
    payloads = [
        (
            b"Authorization: redacted\n"
            b"Bearer abcdefghijklmnop\n"
            b"-----BEGIN PRIVATE KEY-----\n"
            b"eyJabcdefgh.ijklmnop.qrstuvwx\n"
        )
    ]
    request, target_value, target_payload = config(
        "prometheus",
        payloads,
    )

    artifact = COLLECTOR.compile_artifact(
        request,
        target_value,
        payloads,
        target_file_sha256=payload_hash(target_payload),
    )

    assert artifact["aggregate"] == {"secret_leaks": 4}


def test_secret_scan_counts_overlapping_supplied_fingerprint_hits() -> None:
    supplied = b"aaaaaaaa"
    payloads = [b"aaaaaaaaa"]
    request, target_value, target_payload = config(
        "prometheus",
        payloads,
        fingerprints=[COLLECTOR.fingerprint(supplied)],
    )

    artifact = COLLECTOR.compile_artifact(
        request,
        target_value,
        payloads,
        target_file_sha256=payload_hash(target_payload),
    )

    assert artifact["aggregate"] == {"secret_leaks": 2}


def test_workload_artifact_sums_exact_pilot_results() -> None:
    payloads = [
        canonical(profile_result(errors=2)),
        canonical(fault_result(errors=3)),
    ]
    request, target_value, target_payload = config(
        "haproxy",
        payloads,
        phase="during",
        kinds=["profile", "fault"],
    )

    artifact = COLLECTOR.compile_artifact(
        request,
        target_value,
        payloads,
        target_file_sha256=payload_hash(target_payload),
    )

    assert artifact["aggregate"] == {"unexpected_errors": 5}
    assert artifact["surface"] == "haproxy"
    assert artifact["source_class"] == "workload-error-aggregate"
    assert artifact["observations"] == 2
    assert artifact["input_set_sha256"].startswith("sha256:")
    assert PLAN_SHA256 not in json.dumps(artifact)


@pytest.mark.parametrize(
    "mutation",
    (
        "schema",
        "source-hash",
        "surface",
        "phase",
        "window",
        "target-file-hash",
        "source-kind",
        "descriptor-extra",
        "descriptor-hash",
        "duplicate-file",
        "payload-hash",
        "target",
    ),
)
def test_collector_refuses_configuration_and_input_drift(
    mutation: str,
) -> None:
    payloads = [b"clean\n", b"also clean\n"]
    request, target_value, target_payload = config(
        "prometheus",
        payloads,
    )
    if mutation == "schema":
        request["schema"] = "unknown"
    elif mutation == "source-hash":
        request["collector_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "surface":
        request["surface"] = "galera"
    elif mutation == "phase":
        request["phase"] = "steady"
    elif mutation == "window":
        request["window_sha256"] = "sha256:bad"
    elif mutation == "target-file-hash":
        request["target_file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "source-kind":
        request["source"]["kind"] = "prometheus-query"
    elif mutation == "descriptor-extra":
        request["source"]["files"][0]["url"] = "https://forbidden"
    elif mutation == "descriptor-hash":
        request["source"]["files"][0]["file_sha256"] = "sha256:bad"
    elif mutation == "duplicate-file":
        request["source"]["files"][1]["file_sha256"] = (
            request["source"]["files"][0]["file_sha256"]
        )
    elif mutation == "payload-hash":
        payloads[0] = b"changed\n"
    else:
        target_value["target_class"] = "production"

    with pytest.raises(COLLECTOR.LocalArtifactError):
        COLLECTOR.compile_artifact(
            request,
            target_value,
            payloads,
            target_file_sha256=payload_hash(target_payload),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "fingerprint-schema",
        "fingerprint-length",
        "fingerprint-rolling",
        "fingerprint-hash",
        "fingerprint-extra",
        "fingerprint-duplicate",
    ),
)
def test_collector_refuses_fingerprint_drift(mutation: str) -> None:
    payloads = [b"clean metrics\n"]
    value = COLLECTOR.fingerprint(b"dummy-fingerprint")
    fingerprints = [value]
    request, target_value, target_payload = config(
        "prometheus",
        payloads,
        fingerprints=fingerprints,
    )
    if mutation == "fingerprint-schema":
        value["schema"] = "unknown"
    elif mutation == "fingerprint-length":
        value["length"] = 7
    elif mutation == "fingerprint-rolling":
        value["rolling64"] = "rolling64:bad"
    elif mutation == "fingerprint-hash":
        value["sha256"] = "sha256:bad"
    elif mutation == "fingerprint-extra":
        value["value"] = "forbidden"
    else:
        fingerprints.append(dict(value))

    with pytest.raises(COLLECTOR.LocalArtifactError):
        COLLECTOR.compile_artifact(
            request,
            target_value,
            payloads,
            target_file_sha256=payload_hash(target_payload),
        )


@pytest.mark.parametrize(
    ("kind", "mutation"),
    (
        ("profile", "fixture"),
        ("profile", "synthetic"),
        ("profile", "schema"),
        ("profile", "extra"),
        ("profile", "operations"),
        ("profile", "plan"),
        ("fault", "fixture"),
        ("fault", "synthetic"),
        ("fault", "schema"),
        ("fault", "extra"),
        ("fault", "window"),
        ("fault", "plan"),
    ),
)
def test_collector_refuses_invalid_workload_results(
    kind: str,
    mutation: str,
) -> None:
    result = profile_result() if kind == "profile" else fault_result()
    if mutation == "fixture":
        result["execution_source"] = "fixture"
        result["synthetic"] = True
    elif mutation == "synthetic":
        result["synthetic"] = True
    elif mutation == "schema":
        result["schema"] = "unknown"
    elif mutation == "extra":
        result["raw_log"] = "forbidden"
    elif mutation == "operations":
        result["operation_counts"]["token"] = 0
    elif mutation == "window":
        result["window_seconds"] = 61
    else:
        result["plan_sha256"] = "sha256:bad"
    payloads = [canonical(result)]
    request, target_value, target_payload = config(
        "haproxy",
        payloads,
        kinds=[kind],
    )

    with pytest.raises(COLLECTOR.LocalArtifactError):
        COLLECTOR.compile_artifact(
            request,
            target_value,
            payloads,
            target_file_sha256=payload_hash(target_payload),
        )


def test_collector_refuses_cross_plan_workload_results() -> None:
    payloads = [
        canonical(profile_result()),
        canonical(
            fault_result(plan_sha256=f"sha256:{'9' * 64}")
        ),
    ]
    request, target_value, target_payload = config(
        "haproxy",
        payloads,
        kinds=["profile", "fault"],
    )

    with pytest.raises(
        COLLECTOR.LocalArtifactError,
        match="plan changed",
    ):
        COLLECTOR.compile_artifact(
            request,
            target_value,
            payloads,
            target_file_sha256=payload_hash(target_payload),
        )


def file_fixture(
    tmp_path: Path,
    *,
    surface: str = "prometheus",
) -> tuple[Path, Path, list[Path], Path]:
    tmp_path.chmod(0o700)
    payloads = (
        [b"clean metrics\n"]
        if surface == "prometheus"
        else [canonical(profile_result())]
    )
    kinds = ["profile"] if surface == "haproxy" else None
    request, target_value, target_payload = config(
        surface,
        payloads,
        kinds=kinds,
    )
    target_path = tmp_path / "target.json"
    owner_file(target_path, target_payload)
    request["target_file"] = str(target_path)
    input_paths = []
    for index, payload in enumerate(payloads):
        input_path = tmp_path / f"input-{index}.data"
        owner_file(input_path, payload)
        input_paths.append(input_path)
        request["source"]["files"][index]["file"] = str(input_path)
    config_path = tmp_path / "config.json"
    owner_file(config_path, canonical(request))
    return config_path, target_path, input_paths, tmp_path / "artifact.json"


@pytest.mark.parametrize("surface", COLLECTOR.SURFACES)
def test_file_collector_is_atomic_owner_only_and_idempotent(
    tmp_path: Path,
    surface: str,
) -> None:
    config_path, _, _, output_path = file_fixture(
        tmp_path,
        surface=surface,
    )

    first = COLLECTOR.compile_file(config_path, output_path)
    first_payload = output_path.read_bytes()
    first_mtime = output_path.stat().st_mtime_ns
    second = COLLECTOR.compile_file(config_path, output_path)

    assert second == first
    assert first_payload == canonical(first)
    assert output_path.read_bytes() == first_payload
    assert output_path.stat().st_mtime_ns == first_mtime
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "mutation",
    (
        "config-mode",
        "target-mode",
        "input-mode",
        "input-symlink",
        "input-alias",
        "output-mode",
        "output-alias",
        "parent-mode",
        "noncanonical-workload",
    ),
)
def test_file_collector_refuses_unsafe_files(
    tmp_path: Path,
    mutation: str,
) -> None:
    surface = (
        "haproxy"
        if mutation == "noncanonical-workload"
        else "prometheus"
    )
    config_path, target_path, input_paths, output_path = file_fixture(
        tmp_path,
        surface=surface,
    )
    if mutation == "config-mode":
        config_path.chmod(0o644)
    elif mutation == "target-mode":
        target_path.chmod(0o644)
    elif mutation == "input-mode":
        input_paths[0].chmod(0o644)
    elif mutation == "input-symlink":
        actual = tmp_path / "actual.data"
        input_paths[0].rename(actual)
        input_paths[0].symlink_to(actual)
    elif mutation == "input-alias":
        target_path.unlink()
        target_path.hardlink_to(input_paths[0])
    elif mutation == "output-mode":
        owner_file(output_path, b"existing\n")
        output_path.chmod(0o644)
    elif mutation == "output-alias":
        output_path.hardlink_to(input_paths[0])
    elif mutation == "parent-mode":
        tmp_path.chmod(0o755)
    else:
        value = json.loads(input_paths[0].read_bytes())
        input_paths[0].write_bytes(
            json.dumps(value, indent=2).encode("utf-8")
        )
        request = json.loads(config_path.read_bytes())
        request["source"]["files"][0]["file_sha256"] = payload_hash(
            input_paths[0].read_bytes()
        )
        owner_file(config_path, canonical(request))

    with pytest.raises(COLLECTOR.LocalArtifactError):
        COLLECTOR.compile_file(config_path, output_path)


def test_fingerprint_cli_emits_only_one_way_descriptor(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    supplied = b"dummy-owner-only-value"
    input_path = tmp_path / "value.bin"
    owner_file(input_path, supplied)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        COLLECTOR.main(
            ["fingerprint", str(input_path)],
        )
        == 0
    )
    result = COLLECTOR.fingerprint(supplied)
    assert supplied.decode() not in canonical(result).decode()


def test_cli_success_and_failure_are_secret_safe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _, _, output_path = file_fixture(tmp_path)

    assert (
        COLLECTOR.main(
            ["compile", str(config_path), str(output_path)]
        )
        == 0
    )
    success = capsys.readouterr()
    assert json.loads(success.out)["surface"] == "prometheus"
    assert success.err == ""

    config_path.chmod(0o644)
    assert (
        COLLECTOR.main(
            ["compile", str(config_path), str(output_path)]
        )
        == 2
    )
    failure = capsys.readouterr()
    assert failure.out == ""
    assert failure.err == "local-artifact-refused\n"
    assert str(tmp_path) not in failure.err


def test_collector_has_no_runtime_adapter() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    for forbidden in (
        "requests",
        "subprocess",
        "socket",
        "sqlalchemy",
        "boto",
        "urllib",
    ):
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source
