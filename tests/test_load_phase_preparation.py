from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_DIRECTORY = ROOT / "poc" / "load-soak" / "collector"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


PREPARER = load_module(
    "coffer_load_phase_preparation_tests",
    COLLECTOR_DIRECTORY / "phase_preparation.py",
)
LOCAL_TESTS = load_module(
    "coffer_load_phase_preparation_local_fixtures",
    ROOT / "tests" / "test_load_local_artifacts.py",
)
CONTROL_TESTS = load_module(
    "coffer_load_phase_preparation_control_fixtures",
    ROOT / "tests" / "test_load_control_artifacts.py",
)
GALERA_TESTS = load_module(
    "coffer_load_phase_preparation_galera_fixtures",
    ROOT / "tests" / "test_load_galera_artifacts.py",
)
RGW_TESTS = load_module(
    "coffer_load_phase_preparation_rgw_fixtures",
    ROOT / "tests" / "test_load_rgw_artifacts.py",
)
SERVER_TESTS = load_module(
    "coffer_load_phase_preparation_server_fixtures",
    ROOT / "tests" / "test_load_evidence_server.py",
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def owner_document(path: Path, value: object) -> None:
    owner_bytes(path, canonical(value))


def descriptor(path: Path) -> dict[str, str]:
    return {
        "file": str(path),
        "file_sha256": payload_hash(path.read_bytes()),
    }


def fixture(
    tmp_path: Path,
    *,
    phase: str = "during",
) -> tuple[Path, Path, dict]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    inputs.mkdir(mode=0o700)
    outputs.mkdir(mode=0o700)

    _, target = CONTROL_TESTS.values()
    target_path = inputs / "target.json"
    owner_document(target_path, target)
    target_sha256 = payload_hash(target_path.read_bytes())

    ca_payload, certificate_payload, key_payload = (
        SERVER_TESTS.certificate_material(
            server_name="telemetry-adapter.stage6.test"
        )
    )
    ca_path = inputs / "ca.crt"
    certificate_path = inputs / "server.crt"
    private_key_path = inputs / "server.key"
    owner_bytes(ca_path, ca_payload)
    owner_bytes(certificate_path, certificate_payload)
    owner_bytes(private_key_path, key_payload)

    secret_scan_path = inputs / "secret-scan.log"
    profile_path = inputs / "profile.json"
    owner_bytes(secret_scan_path, b"clean bounded metrics\n")
    owner_document(profile_path, LOCAL_TESTS.profile_result())

    prometheus_config, _, _ = LOCAL_TESTS.config(
        "prometheus",
        [secret_scan_path.read_bytes()],
        phase=phase,
    )
    prometheus_config["target_file"] = str(target_path)
    prometheus_config["target_file_sha256"] = target_sha256
    prometheus_config["source"]["files"][0]["file"] = str(secret_scan_path)
    haproxy_config, _, _ = LOCAL_TESTS.config(
        "haproxy",
        [profile_path.read_bytes()],
        phase=phase,
        kinds=["profile"],
    )
    haproxy_config["target_file"] = str(target_path)
    haproxy_config["target_file_sha256"] = target_sha256
    haproxy_config["source"]["files"][0]["file"] = str(profile_path)

    control_config, _ = CONTROL_TESTS.values()
    control_config["target_file"] = str(target_path)
    control_config["target_file_sha256"] = target_sha256
    control_config["ca_file"] = str(ca_path)
    control_config["ca_file_sha256"] = payload_hash(ca_payload)
    control_config["phase"] = phase
    baseline = CONTROL_TESTS.capture(
        "baseline",
        timestamp=1000,
        attempts=None,
    )
    current = CONTROL_TESTS.capture(
        "current",
        timestamp=1100,
        attempts=2,
    )
    baseline["phase"] = phase
    baseline["capture_sha256"] = CONTROL_TESTS.COLLECTOR._hash(
        {
            key: value
            for key, value in baseline.items()
            if key != "capture_sha256"
        }
    )
    current["phase"] = phase
    current["capture_sha256"] = CONTROL_TESTS.COLLECTOR._hash(
        {
            key: value
            for key, value in current.items()
            if key != "capture_sha256"
        }
    )

    galera_config, _ = GALERA_TESTS.values(
        target_file=str(target_path),
        target_file_sha256=target_sha256,
    )
    galera_config["phase"] = phase
    rgw_config = RGW_TESTS.config(
        target,
        phase=phase,
        target_file=str(target_path),
        target_file_sha256=target_sha256,
    )
    rgw_probe = RGW_TESTS.probe(target, phase=phase)
    rgw_multipart = RGW_TESTS.multipart(target, phase=phase)

    values = {
        "prometheus_config": prometheus_config,
        "haproxy_config": haproxy_config,
        "control_config": control_config,
        "control_baseline": baseline,
        "control_current": current,
        "galera_config": galera_config,
        "rgw_config": rgw_config,
        "rgw_probe": rgw_probe,
        "rgw_multipart": rgw_multipart,
    }
    paths: dict[str, Path] = {}
    for name, value in values.items():
        path = inputs / f"{name}.json"
        owner_document(path, value)
        paths[name] = path

    output_directory = outputs / phase
    request = {
        "collector_inputs": {
            name: descriptor(path) for name, path in paths.items()
        },
        "evidence_server": {
            "bind_address": "127.0.0.1",
            "certificate": descriptor(certificate_path),
            "max_concurrency": 4,
            "port": 9443,
            "private_key": descriptor(private_key_path),
            "request_timeout_seconds": 5,
            "server_name": "telemetry-adapter.stage6.test",
            "server_source_sha256": (
                PREPARER.evidence_server.server_source_sha256()
            ),
        },
        "output_directory": str(output_directory),
        "phase": phase,
        "preparer_source_sha256": PREPARER.preparer_source_sha256(),
        "schema": PREPARER.REQUEST_SCHEMA,
        "target": descriptor(target_path),
        "window_sha256": CONTROL_TESTS.WINDOW_SHA256,
    }
    request_path = inputs / "phase-preparation.json"
    owner_document(request_path, request)
    return request_path, output_directory, request


def rewrite_request(path: Path, value: dict) -> None:
    owner_document(path, value)


def rewrite_input(
    request_path: Path,
    request: dict,
    name: str,
    value: dict,
) -> None:
    path = Path(request["collector_inputs"][name]["file"])
    owner_document(path, value)
    request["collector_inputs"][name] = descriptor(path)
    rewrite_request(request_path, request)


@pytest.mark.parametrize("phase", PREPARER.native_target.PHASES)
def test_prepares_complete_phase_transaction(
    tmp_path: Path,
    phase: str,
) -> None:
    request_path, output, _ = fixture(tmp_path, phase=phase)

    result = PREPARER.prepare_file(request_path)

    assert result["complete"] is True
    assert result["execution_source"] == "pilot"
    assert result["phase"] == phase
    assert set(item.name for item in output.iterdir()) == set(
        PREPARER.OUTPUT_FILES
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    for path in output.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1
    bundle = json.loads((output / "bundle.json").read_bytes())
    assert set(bundle["documents"]) == set(PREPARER.phase_evidence.SURFACES)
    assert bundle["bundle_sha256"] == result["bundle_sha256"]
    configuration = PREPARER.evidence_server.load_configuration(
        output / "evidence-server.json"
    )
    assert configuration.phase == phase
    assert configuration.bundle_sha256 == result["bundle_sha256"]
    retained = json.dumps(
        {
            path.name: json.loads(path.read_bytes())
            for path in output.iterdir()
        },
        sort_keys=True,
    ).lower()
    for forbidden in (
        "access_key",
        "secret_key",
        "kms_policy",
        "bucket_scope",
        "upload_id",
        "authorization",
    ):
        assert forbidden not in retained


def test_exact_repeat_is_idempotent(tmp_path: Path) -> None:
    request_path, output, _ = fixture(tmp_path)
    first = PREPARER.prepare_file(request_path)
    identities = {
        path.name: path.stat().st_ino for path in output.iterdir()
    }

    second = PREPARER.prepare_file(request_path)

    assert second == first
    assert {
        path.name: path.stat().st_ino for path in output.iterdir()
    } == identities


def test_late_collector_failure_leaves_no_output_or_staging(
    tmp_path: Path,
) -> None:
    request_path, output, request = fixture(tmp_path)
    probe_path = Path(request["collector_inputs"]["rgw_probe"]["file"])
    probe = json.loads(probe_path.read_bytes())
    probe["probe_sha256"] = f"sha256:{'0' * 64}"
    rewrite_input(request_path, request, "rgw_probe", probe)

    with pytest.raises(PREPARER.rgw_artifacts.RgwArtifactError):
        PREPARER.prepare_file(request_path)

    assert not output.exists()
    assert not list(output.parent.glob(".*.phase-preparation.*"))


def test_server_preflight_failure_leaves_no_output(
    tmp_path: Path,
) -> None:
    request_path, output, request = fixture(tmp_path)
    request["evidence_server"]["server_name"] = "wrong.stage6.test"
    rewrite_request(request_path, request)

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)

    assert not output.exists()
    assert not list(output.parent.glob(".*.phase-preparation.*"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "wrong"),
        ("phase", "unknown"),
        ("preparer_source_sha256", f"sha256:{'0' * 64}"),
        ("window_sha256", "invalid"),
    ],
)
def test_request_binding_drift_is_refused(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    request_path, output, request = fixture(tmp_path)
    request[field] = value
    rewrite_request(request_path, request)

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)

    assert not output.exists()


def test_input_hash_and_mode_drift_are_refused(tmp_path: Path) -> None:
    request_path, output, request = fixture(tmp_path)
    request["collector_inputs"]["control_current"]["file_sha256"] = (
        f"sha256:{'0' * 64}"
    )
    rewrite_request(request_path, request)

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)
    assert not output.exists()

    request_path, output, request = fixture(tmp_path / "mode")
    probe_path = Path(request["collector_inputs"]["rgw_probe"]["file"])
    probe_path.chmod(0o640)
    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)
    assert not output.exists()


def test_request_or_input_alias_is_refused(tmp_path: Path) -> None:
    request_path, output, request = fixture(tmp_path)
    alias = Path(request["collector_inputs"]["rgw_probe"]["file"])
    request_path.unlink()
    os.link(alias, request_path)

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)

    assert not output.exists()


def test_existing_output_drift_is_never_overwritten(tmp_path: Path) -> None:
    request_path, output, _ = fixture(tmp_path)
    PREPARER.prepare_file(request_path)
    unexpected = output / "unexpected.json"
    owner_document(unexpected, {"unexpected": True})

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)

    assert unexpected.exists()


def test_existing_result_tamper_is_refused(tmp_path: Path) -> None:
    request_path, output, _ = fixture(tmp_path)
    PREPARER.prepare_file(request_path)
    result_path = output / "result.json"
    result = json.loads(result_path.read_bytes())
    result["complete"] = False
    owner_document(result_path, result)

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)


def test_output_parent_must_be_owner_only(tmp_path: Path) -> None:
    request_path, output, request = fixture(tmp_path)
    output.parent.chmod(0o755)
    rewrite_request(request_path, request)

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)

    assert not output.exists()


def test_cli_has_fixed_secret_safe_results(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path, _, _ = fixture(tmp_path)
    assert PREPARER.main(["source-hash"]) == 0
    source = json.loads(capsys.readouterr().out)
    assert source == {
        "preparer_source_sha256": PREPARER.preparer_source_sha256(),
        "schema": PREPARER.SOURCE_RESULT_SCHEMA,
    }

    assert PREPARER.main(["prepare", str(request_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == PREPARER.RESULT_SCHEMA
    assert result["phase"] == "during"
    assert set(result) == {
        "bundle_sha256",
        "phase",
        "result_sha256",
        "schema",
    }

    assert PREPARER.main(["prepare", "/missing"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "phase-preparation-refused\n"


def test_unknown_fields_are_refused(tmp_path: Path) -> None:
    request_path, output, request = fixture(tmp_path)
    changed = deepcopy(request)
    changed["credential"] = "forbidden"
    rewrite_request(request_path, changed)

    with pytest.raises(PREPARER.PhasePreparationError):
        PREPARER.prepare_file(request_path)

    assert not output.exists()
