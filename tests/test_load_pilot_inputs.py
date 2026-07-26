from __future__ import annotations

from copy import deepcopy
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


INPUTS = load_module(
    "coffer_load_pilot_inputs_tests",
    COLLECTOR_DIRECTORY / "pilot_inputs.py",
)
SCHEDULE_TESTS = load_module(
    "coffer_load_pilot_inputs_schedule_fixtures",
    ROOT / "tests" / "test_load_pilot_schedule.py",
)
PHASE_TESTS = load_module(
    "coffer_load_pilot_inputs_phase_fixtures",
    ROOT / "tests" / "test_load_phase_preparation.py",
)
PHASE_ACTION_TESTS = load_module(
    "coffer_load_pilot_inputs_phase_action_fixtures",
    ROOT / "tests" / "test_load_pilot_phase_actions.py",
)


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(INPUTS._canonical(value))
    path.chmod(0o600)


def descriptor(path: Path) -> dict[str, str]:
    return {
        "file": str(path),
        "file_sha256": INPUTS._payload_hash(path.read_bytes()),
    }


def fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict]:
    request_path, schedule_output, runtime, schedule_request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    phases: dict[str, dict] = {}
    for phase in INPUTS.native_target.PHASES:
        _, _, source = PHASE_TESTS.fixture(
            tmp_path / f"{phase}-source",
            phase=phase,
        )
        live_config = json.loads(
            (
                schedule_output
                / INPUTS.pilot_schedule.PHASE_CONFIG_FILES[phase]
            ).read_bytes()
        )
        target_path = Path(source["target"]["file"])
        target_hash = source["target"]["file_sha256"]
        static = {
            name: source["collector_inputs"][name]
            for name in INPUTS.pilot_phase_actions.COLLECTOR_INPUT_NAMES
        }
        for value in static.values():
            PHASE_ACTION_TESTS.rewrite_binding(
                Path(value["file"]),
                phase=phase,
                target_path=target_path,
                target_sha256=target_hash,
                window_sha256=live_config["window_sha256"],
            )
        phases[phase] = {
            "collector_inputs": {
                name: descriptor(Path(value["file"]))
                for name, value in static.items()
            },
            "evidence_server": source["evidence_server"],
            "target": source["target"],
        }
    request = {
        "phases": phases,
        "readiness": schedule_request["readiness"],
        "renderer_source_sha256": INPUTS.renderer_source_sha256(),
        "schedule_directory": str(schedule_output),
        "schema": INPUTS.REQUEST_SCHEMA,
    }
    deployment_request = tmp_path / "inputs" / "deployment-inputs.json"
    owner_document(deployment_request, request)
    return deployment_request, schedule_output, runtime, request


def test_renders_all_three_phase_inputs_atomically(
    tmp_path: Path,
) -> None:
    request_path, _, runtime, _ = fixture(tmp_path)

    result = INPUTS.render_file(request_path)

    assert result["complete"] is True
    assert result["synthetic"] is False
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert set(path.name for path in runtime.iterdir()) == {
        *INPUTS.native_target.PHASES,
        INPUTS.pilot_executor.DEPLOYMENT_INPUT_RESULT_FILE,
    }
    for phase in INPUTS.native_target.PHASES:
        directory = runtime / phase
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert set(path.name for path in directory.iterdir()) == {
            "collector-inputs.json"
        }
        document = json.loads(
            (directory / "collector-inputs.json").read_bytes()
        )
        assert set(document["collector_inputs"]) == set(
            INPUTS.pilot_phase_actions.COLLECTOR_INPUT_NAMES
        )
        assert document["phase"] == phase
        assert document["schedule_sha256"] == result["schedule_sha256"]
        assert stat.S_IMODE(
            (directory / "collector-inputs.json").stat().st_mode
        ) == 0o600


def test_exact_repeat_preserves_inputs_and_later_scheduled_files(
    tmp_path: Path,
) -> None:
    request_path, _, runtime, _ = fixture(tmp_path)
    first = INPUTS.render_file(request_path)
    paths = [
        runtime / INPUTS.pilot_executor.DEPLOYMENT_INPUT_RESULT_FILE,
        *(
            runtime / phase / "collector-inputs.json"
            for phase in INPUTS.native_target.PHASES
        ),
    ]
    identities = {str(path): path.stat().st_ino for path in paths}
    scheduled = runtime / "before" / "rgw-step-0.json"
    owner_document(scheduled, {"scheduled": True})

    second = INPUTS.render_file(request_path)

    assert second == first
    assert {str(path): path.stat().st_ino for path in paths} == identities
    assert json.loads(scheduled.read_bytes()) == {"scheduled": True}


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "source",
        "readiness-hash",
        "phase-missing",
        "static-hash",
        "static-mode",
        "static-alias",
        "static-window",
        "target",
    ],
)
def test_request_and_static_binding_drift_leave_no_runtime(
    tmp_path: Path,
    mutation: str,
) -> None:
    request_path, _, runtime, request = fixture(tmp_path)
    changed = deepcopy(request)
    if mutation == "schema":
        changed["schema"] = "wrong"
    elif mutation == "source":
        changed["renderer_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "readiness-hash":
        changed["readiness"]["file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "phase-missing":
        del changed["phases"]["after"]
    elif mutation == "static-hash":
        changed["phases"]["before"]["collector_inputs"][
            "control_current"
        ]["file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "static-mode":
        Path(
            changed["phases"]["before"]["collector_inputs"][
                "control_current"
            ]["file"]
        ).chmod(0o640)
    elif mutation == "static-alias":
        values = changed["phases"]["before"]["collector_inputs"]
        values["control_baseline"] = values["control_current"]
    elif mutation == "static-window":
        descriptor_value = changed["phases"]["before"][
            "collector_inputs"
        ]["control_current"]
        path = Path(descriptor_value["file"])
        value = json.loads(path.read_bytes())
        value["window_sha256"] = f"sha256:{'0' * 64}"
        value["capture_sha256"] = (
            INPUTS.control_artifacts._hash(
                {
                    key: item
                    for key, item in value.items()
                    if key != "capture_sha256"
                }
            )
        )
        owner_document(path, value)
        descriptor_value["file_sha256"] = INPUTS._payload_hash(
            path.read_bytes()
        )
    elif mutation == "target":
        changed["phases"]["before"]["target"] = changed["phases"][
            "before"
        ]["collector_inputs"]["control_current"]
    owner_document(request_path, changed)

    with pytest.raises(INPUTS.PilotInputError):
        INPUTS.render_file(request_path)

    assert not runtime.exists()
    assert not list(runtime.parent.glob(".*.pilot-inputs.*"))


def test_existing_tamper_and_unsafe_runtime_are_never_replaced(
    tmp_path: Path,
) -> None:
    request_path, _, runtime, _ = fixture(tmp_path)
    INPUTS.render_file(request_path)
    path = runtime / "during" / "collector-inputs.json"
    value = json.loads(path.read_bytes())
    value["phase"] = "before"
    owner_document(path, value)

    with pytest.raises(INPUTS.PilotInputError):
        INPUTS.render_file(request_path)
    assert json.loads(path.read_bytes())["phase"] == "before"

    request_path, _, runtime, _ = fixture(tmp_path / "unsafe")
    runtime.mkdir(mode=0o700)
    (runtime / "unexpected").mkdir(mode=0o700)
    with pytest.raises(INPUTS.PilotInputError):
        INPUTS.render_file(request_path)
    assert (runtime / "unexpected").exists()


def test_request_alias_is_refused_by_owner_only_input_set(
    tmp_path: Path,
) -> None:
    request_path, _, runtime, request = fixture(tmp_path)
    source = Path(
        request["phases"]["before"]["collector_inputs"][
            "control_current"
        ]["file"]
    )
    request_path.unlink()
    os.link(source, request_path)

    with pytest.raises(INPUTS.PilotInputError):
        INPUTS.render_file(request_path)

    assert not runtime.exists()


def test_cli_returns_fixed_secret_safe_results(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path, _, _, _ = fixture(tmp_path)
    assert INPUTS.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == INPUTS.SOURCE_RESULT_SCHEMA

    assert INPUTS.main(["render", str(request_path)]) == 0
    result = capsys.readouterr()
    assert result.err == ""
    assert set(json.loads(result.out)) == {"result_sha256", "schema"}

    assert INPUTS.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "pilot-inputs-refused\n"
