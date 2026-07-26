from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
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


RENDERER = load_module(
    "coffer_load_pilot_schedule_tests",
    COLLECTOR_DIRECTORY / "pilot_schedule.py",
)
CONTROL_TESTS = load_module(
    "coffer_load_pilot_schedule_control_fixtures",
    ROOT / "tests" / "test_load_control_artifacts.py",
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(canonical(value))
    path.chmod(0o600)


def descriptor(path: Path) -> dict[str, str]:
    return {
        "file": str(path),
        "file_sha256": payload_hash(path.read_bytes()),
    }


def qualified_readiness() -> dict:
    return {
        "ceph": {
            "baseline": "v20.2.2",
            "fix_in_latest_stable": True,
            "fix_merge_revision": (
                "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e"
            ),
            "fix_merged_to_tentacle": True,
            "fix_pull_request": 69277,
            "latest_stable": "v20.2.3",
            "reasons": [],
            "revision": "e" * 40,
            "status": "candidate-qualified",
        },
        "distribution": {
            "baseline": "v3.1.1",
            "latest_stable": "v3.1.2",
            "published_at": "2026-08-01T00:00:00Z",
            "reasons": [],
            "revision": "d" * 40,
            "status": "candidate-qualified",
            "url": (
                "https://github.com/distribution/distribution/"
                "releases/tag/v3.1.2"
            ),
            "verified_release_commit": True,
        },
        "schema": "coffer.upstream-readiness/v1",
        "status": "candidate-qualified",
    }


def plan(readiness_hash: str) -> dict:
    topology = RENDERER.plan_contract.state_machine.load_topology(
        RENDERER.TOPOLOGY_PATH
    )
    return RENDERER.plan_contract.compile_plan(
        {
            "bindings": {
                "architectures": ["aarch64", "x86_64"],
                "ceph_revision": "e" * 40,
                "ceph_version": "v20.2.3",
                "client_versions_hash": f"sha256:{'1' * 64}",
                "configuration_hash": f"sha256:{'2' * 64}",
                "distribution_revision": "d" * 40,
                "distribution_version": "v3.1.2",
                "driver_revision": "c" * 40,
                "image_set_hash": f"sha256:{'3' * 64}",
                "readiness_evidence_hash": readiness_hash,
                "readiness_status": "qualified",
            },
            "schema": RENDERER.plan_contract.REQUEST_SCHEMA,
            "topology_sha256": RENDERER.plan_contract._hash(topology),
        },
        topology=topology,
    )


def fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    runtime_parent = tmp_path / "runtime"
    inputs.mkdir(mode=0o700)
    outputs.mkdir(mode=0o700)
    runtime_parent.mkdir(mode=0o700)

    readiness_path = inputs / "readiness.json"
    readiness_path.write_text(
        json.dumps(qualified_readiness(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readiness_path.chmod(0o600)
    plan_path = inputs / "load-plan.json"
    owner_document(plan_path, plan(payload_hash(readiness_path.read_bytes())))
    _, target = CONTROL_TESTS.values()
    target_path = inputs / "native-target.json"
    owner_document(target_path, target)
    ca_path = inputs / "ca.crt"
    ca_path.write_bytes(b"bounded test CA\n")
    ca_path.chmod(0o600)

    output = outputs / "pilot-schedule"
    runtime = runtime_parent / "pilot-run"
    request = {
        "fault_evidence_sha256": {
            "kms_outage": f"sha256:{'8' * 64}",
            "wrong_key": f"sha256:{'7' * 64}",
        },
        "load_plan": descriptor(plan_path),
        "output_directory": str(output),
        "readiness": descriptor(readiness_path),
        "renderer_source_sha256": RENDERER.renderer_source_sha256(),
        "rgw": {
            "bucket": "coffer-registry-stage6",
            "bucket_scope_sha256": f"sha256:{'4' * 64}",
            "ca_file": descriptor(ca_path),
            "endpoint": "https://rgw.stage6.test:8443",
            "kms_policy_sha256": f"sha256:{'5' * 64}",
            "max_pages": 10,
            "probe_prefix_root": "coffer-evidence/pilot-001",
            "region": "us-east-1",
            "rgw_config_sha256": f"sha256:{'6' * 64}",
            "timeout_seconds": 5,
        },
        "runtime_directory": str(runtime),
        "schema": RENDERER.REQUEST_SCHEMA,
        "target": descriptor(target_path),
        "windows": {
            "before": {
                "window_completed_at_seconds": 200,
                "window_sha256": f"sha256:{'a' * 64}",
                "window_started_at_seconds": 100,
            },
            "during": {
                "window_completed_at_seconds": 400,
                "window_sha256": f"sha256:{'b' * 64}",
                "window_started_at_seconds": 300,
            },
            "after": {
                "window_completed_at_seconds": 600,
                "window_sha256": f"sha256:{'c' * 64}",
                "window_started_at_seconds": 500,
            },
        },
    }
    request_path = inputs / "request.json"
    owner_document(request_path, request)
    return request_path, output, runtime, request


def rewrite(path: Path, value: dict) -> None:
    owner_document(path, value)


def test_renders_qualified_release_bound_schedule_atomically(
    tmp_path: Path,
) -> None:
    request_path, output, runtime, _ = fixture(tmp_path)

    result = RENDERER.render_file(request_path)

    assert result["complete"] is True
    assert result["synthetic"] is False
    assert set(item.name for item in output.iterdir()) == set(
        RENDERER.OUTPUT_FILES
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert runtime.exists() is False
    for path in output.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1

    schedule = json.loads((output / "schedule.json").read_bytes())
    assert schedule["action_count"] == 53
    assert [item["order"] for item in schedule["actions"]] == list(
        range(1, 54)
    )
    assert schedule["execution_source"] == "pilot"
    assert schedule["synthetic"] is False
    assert schedule["credential_environment"] == [
        "COFFER_RGW_EVIDENCE_ACCESS_KEY",
        "COFFER_RGW_EVIDENCE_SECRET_KEY",
        "COFFER_RGW_EVIDENCE_KMS_KEY_ID",
    ]
    assert [
        action["phase"] for action in schedule["actions"]
    ].count("before") == 15
    assert [
        action["phase"] for action in schedule["actions"]
    ].count("during") == 23
    assert [
        action["phase"] for action in schedule["actions"]
    ].count("after") == 15


def test_during_schedule_orders_fault_failure_recovery_and_success(
    tmp_path: Path,
) -> None:
    request_path, output, _, _ = fixture(tmp_path)
    RENDERER.render_file(request_path)
    schedule = json.loads((output / "schedule.json").read_bytes())
    actions = [
        action
        for action in schedule["actions"]
        if action["phase"] == "during"
    ]
    names = [action["action"] for action in actions]

    first_fault = names.index("apply-wrong-key")
    assert names[first_fault : first_fault + 4] == [
        "apply-wrong-key",
        "collect-rgw-step",
        "recover-wrong-key",
        "collect-rgw-step",
    ]
    second_fault = names.index("apply-kms-outage")
    assert names[second_fault : second_fault + 4] == [
        "apply-kms-outage",
        "collect-rgw-step",
        "recover-kms-outage",
        "collect-rgw-step",
    ]
    assert actions[first_fault + 1]["step_index"] == 7
    assert actions[first_fault + 3]["step_index"] == 8
    assert actions[second_fault + 1]["step_index"] == 9
    assert actions[second_fault + 3]["step_index"] == 10

    config = json.loads(
        (output / "during-rgw-live-config.json").read_bytes()
    )
    assert [
        (step["operation"], step["result"])
        for step in config["steps"][-4:]
    ] == list(RENDERER.rgw_live_adapter.DURING_FAULT_SEQUENCE)


def test_every_phase_cleans_exact_prefix_before_atomic_preparation(
    tmp_path: Path,
) -> None:
    request_path, output, runtime, _ = fixture(tmp_path)
    RENDERER.render_file(request_path)
    schedule = json.loads((output / "schedule.json").read_bytes())

    for phase in RENDERER.native_target.PHASES:
        config = json.loads(
            (output / f"{phase}-rgw-live-config.json").read_bytes()
        )
        cleanup = schedule["cleanup_contract"][phase]
        assert cleanup == {
            "probe_prefix": f"coffer-evidence/pilot-001/{phase}",
            "require_zero_multipart_uploads": True,
            "require_zero_objects": True,
        }
        actions = [
            action
            for action in schedule["actions"]
            if action["phase"] == phase
        ]
        names = [action["action"] for action in actions]
        assert names[-7:] == [
            "compile-rgw-probe",
            "collect-rgw-multipart",
            "cleanup-rgw-prefix",
            "verify-rgw-cleanup",
            "render-phase-preparation-request",
            "prepare-phase-atomically",
            "complete-phase",
        ]
        assert config["probe_prefix"] == cleanup["probe_prefix"]
        assert actions[-2]["input_file"] == str(
            runtime / phase / "phase-preparation-request.json"
        )


def test_exact_repeat_is_idempotent(tmp_path: Path) -> None:
    request_path, output, _, _ = fixture(tmp_path)
    first = RENDERER.render_file(request_path)
    identities = {
        path.name: path.stat().st_ino for path in output.iterdir()
    }

    second = RENDERER.render_file(request_path)

    assert second == first
    assert {
        path.name: path.stat().st_ino for path in output.iterdir()
    } == identities


def test_current_blocked_releases_are_refused_before_output(
    tmp_path: Path,
) -> None:
    request_path, output, _, request = fixture(tmp_path)
    readiness_path = Path(request["readiness"]["file"])
    readiness = json.loads(readiness_path.read_bytes())
    readiness["status"] = "blocked"
    readiness["distribution"]["status"] = "blocked"
    readiness["distribution"]["reasons"] = [
        "no stable Distribution release newer than v3.1.1"
    ]
    owner_document(readiness_path, readiness)
    request["readiness"] = descriptor(readiness_path)
    rewrite(request_path, request)

    with pytest.raises(
        RENDERER.PilotScheduleError,
        match="not qualified",
    ):
        RENDERER.render_file(request_path)

    assert output.exists() is False


@pytest.mark.parametrize(
    "mutation",
    [
        "readiness-hash",
        "distribution-version",
        "ceph-revision",
        "fault-alias",
        "fault-empty",
        "window-overlap",
        "endpoint",
        "runtime-exists",
    ],
)
def test_binding_and_safety_drift_is_refused(
    tmp_path: Path,
    mutation: str,
) -> None:
    request_path, output, runtime, request = fixture(tmp_path)
    if mutation == "readiness-hash":
        request["readiness"]["file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation in {"distribution-version", "ceph-revision"}:
        plan_path = Path(request["load_plan"]["file"])
        envelope = json.loads(plan_path.read_bytes())
        key = (
            "distribution_version"
            if mutation == "distribution-version"
            else "ceph_revision"
        )
        envelope["plan"]["bindings"][key] = (
            "v3.1.3" if mutation == "distribution-version" else "f" * 40
        )
        envelope["plan"]["bindings_sha256"] = (
            RENDERER.plan_contract._hash(envelope["plan"]["bindings"])
        )
        envelope["plan_sha256"] = RENDERER.plan_contract._hash(
            envelope["plan"]
        )
        owner_document(plan_path, envelope)
        request["load_plan"] = descriptor(plan_path)
    elif mutation == "fault-alias":
        request["fault_evidence_sha256"]["kms_outage"] = (
            request["fault_evidence_sha256"]["wrong_key"]
        )
    elif mutation == "fault-empty":
        request["fault_evidence_sha256"]["wrong_key"] = (
            RENDERER.rgw_live_adapter.NO_FAULT_SHA256
        )
    elif mutation == "window-overlap":
        request["windows"]["during"]["window_started_at_seconds"] = 199
    elif mutation == "endpoint":
        request["rgw"]["endpoint"] = "http://rgw.stage6.test:8080"
    else:
        runtime.mkdir(mode=0o700)
    rewrite(request_path, request)

    with pytest.raises(RENDERER.PilotScheduleError):
        RENDERER.render_file(request_path)

    assert output.exists() is False
    assert not list(output.parent.glob(".*.pilot-schedule.*"))


def test_late_write_failure_rolls_back_without_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, output, _, _ = fixture(tmp_path)
    original = RENDERER._write
    calls = 0

    def fail(path: Path, value: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RENDERER.PilotScheduleError("injected")
        original(path, value)

    monkeypatch.setattr(RENDERER, "_write", fail)

    with pytest.raises(RENDERER.PilotScheduleError, match="injected"):
        RENDERER.render_file(request_path)

    assert output.exists() is False
    assert not list(output.parent.glob(".*.pilot-schedule.*"))


def test_cli_is_fixed_and_retains_no_secret_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path, output, _, _ = fixture(tmp_path)

    status = RENDERER.main(["render", str(request_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert json.loads(captured.out)["schema"] == RENDERER.RESULT_SCHEMA
    retained = " ".join(
        path.read_text(encoding="utf-8")
        for path in output.iterdir()
    ).lower()
    for forbidden in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "authorization:",
        "private_key",
        "secret_value",
    ):
        assert forbidden not in retained

    source_status = RENDERER.main(["source-hash"])
    source = capsys.readouterr()
    assert source_status == 0
    assert json.loads(source.out)["schema"] == RENDERER.SOURCE_RESULT_SCHEMA


def test_existing_output_tamper_is_refused(tmp_path: Path) -> None:
    request_path, output, _, _ = fixture(tmp_path)
    RENDERER.render_file(request_path)
    schedule_path = output / "schedule.json"
    schedule = json.loads(schedule_path.read_bytes())
    schedule["action_count"] = 0
    owner_document(schedule_path, schedule)

    with pytest.raises(RENDERER.PilotScheduleError):
        RENDERER.render_file(request_path)
