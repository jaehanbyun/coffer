from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time

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


CONTROLLER = load_module(
    "coffer_load_pilot_fault_controller_tests",
    COLLECTOR_DIRECTORY / "pilot_fault_controller.py",
)
SCHEDULE_TESTS = load_module(
    "coffer_load_pilot_fault_controller_schedule_fixtures",
    ROOT / "tests" / "test_load_pilot_schedule.py",
)
ACTION_TESTS = load_module(
    "coffer_load_pilot_fault_controller_action_fixtures",
    ROOT / "tests" / "test_load_pilot_actions.py",
)


HELPER = """#!{python}
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def canonical(value):
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\\n").encode()


def digest(value):
    return "sha256:" + hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


state_path = Path(sys.argv[1])
behavior = sys.argv[2]
fault = os.environ["COFFER_PILOT_FAULT"]
evidence = os.environ["COFFER_PILOT_FAULT_EVIDENCE_SHA256"]
operation = os.environ["COFFER_PILOT_FAULT_OPERATION"]
state = os.environ["COFFER_PILOT_FAULT_STATE"]
allowed = {{
    "COFFER_PILOT_FAULT",
    "COFFER_PILOT_FAULT_EVIDENCE_SHA256",
    "COFFER_PILOT_FAULT_OPERATION",
    "COFFER_PILOT_FAULT_STATE",
    "LANG",
    "LC_ALL",
    "PATH",
}}
if set(os.environ) - {{"__CF_USER_TEXT_ENCODING"}} != allowed:
    raise SystemExit(90)
if behavior == "sleep":
    time.sleep(30)
if behavior == "stderr":
    print("bounded failure detail", file=sys.stderr)
if behavior == "nonzero":
    raise SystemExit(7)
if behavior == "oversize":
    sys.stdout.write("x" * 65536)
    raise SystemExit(0)
if behavior == "malformed":
    print("not-json")
    raise SystemExit(0)
records = {{}}
if state_path.exists():
    records = json.loads(state_path.read_bytes())
key = "|".join((fault, state, evidence))
if operation in {{"apply", "recover"}}:
    records[key] = True
    state_path.write_bytes(canonical(records))
    state_path.chmod(0o600)
if operation == "observe" and not records.get(key):
    unsigned = {{
        "evidence_sha256": evidence,
        "fault": fault,
        "observed": False,
        "schema": "{absent_schema}",
        "state": state,
    }}
else:
    unsigned = {{
        "completed_at_seconds": 321,
        "evidence_sha256": evidence,
        "fault": fault,
        "schema": "{observation_schema}",
        "started_at_seconds": 320,
        "state": state,
    }}
value = {{**unsigned, "observation_sha256": digest(unsigned)}}
if behavior == "tamper":
    value["observation_sha256"] = "sha256:" + "0" * 64
sys.stdout.buffer.write(canonical(value))
""".format(
    python=sys.executable,
    absent_schema=CONTROLLER.ABSENT_SCHEMA,
    observation_schema=CONTROLLER.OBSERVATION_SCHEMA,
)


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(CONTROLLER._canonical(value))
    path.chmod(0o600)


def helper(path: Path) -> Path:
    path.write_text(HELPER, encoding="utf-8")
    path.chmod(0o700)
    return path


def executable_descriptor(path: Path) -> dict[str, str]:
    return {
        "file": str(path),
        "file_sha256": CONTROLLER._payload_hash(path.read_bytes()),
    }


def fixture(
    tmp_path: Path,
    *,
    behavior: str = "normal",
    timeout: int = 5,
) -> tuple[
    CONTROLLER.CommandFaultController,
    Path,
    Path,
    dict,
]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    executable = helper(tmp_path / "fault-helper.py")
    state = tmp_path / "external-state.json"
    command = {
        "argv": [str(executable), str(state), behavior],
        "executable": executable_descriptor(executable),
    }
    config = {
        "commands": {
            name: deepcopy(command) for name in CONTROLLER.COMMANDS
        },
        "controller_source_sha256": (
            CONTROLLER.controller_source_sha256()
        ),
        "name": "coffer-stage6-fault-controller",
        "schema": CONTROLLER.CONFIG_SCHEMA,
        "timeout_seconds": timeout,
    }
    config_path = tmp_path / "fault-controller.json"
    owner_document(config_path, config)
    return (
        CONTROLLER.CommandFaultController.load(config_path),
        config_path,
        executable,
        config,
    )


def test_applies_observes_and_recovers_both_faults(
    tmp_path: Path,
) -> None:
    controller, _, _, _ = fixture(tmp_path)
    evidence = {
        "wrong-key": f"sha256:{'7' * 64}",
        "kms-outage": f"sha256:{'8' * 64}",
    }

    for fault in CONTROLLER.pilot_fault_actions.FAULTS:
        assert controller.observe(
            fault,
            "applied",
            evidence[fault],
        ) is None
        applied = controller.apply(fault, evidence[fault])
        assert applied.state == "applied"
        assert controller.observe(
            fault,
            "applied",
            evidence[fault],
        ) == applied
        recovered = controller.recover(fault, evidence[fault])
        assert recovered.state == "recovered"
        assert controller.observe(
            fault,
            "recovered",
            evidence[fault],
        ) == recovered


def test_composes_with_qualified_fault_action_adapter(
    tmp_path: Path,
) -> None:
    controller, _, _, _ = fixture(tmp_path / "controller")
    request_path, schedule_output, runtime, request = (
        SCHEDULE_TESTS.fixture(tmp_path / "schedule")
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    runtime.mkdir(mode=0o700)
    (runtime / "during").mkdir(mode=0o700)
    adapter = (
        CONTROLLER.pilot_fault_actions.PilotFaultActionAdapter.load(
            schedule_output,
            Path(request["readiness"]["file"]),
            controller=controller,
        )
    )
    schedule = json.loads(
        (schedule_output / "schedule.json").read_bytes()
    )
    actions = [
        action
        for action in schedule["actions"]
        if action["action"] in {"apply-wrong-key", "recover-wrong-key"}
    ]

    applied = adapter.execute(actions[0])
    recovered = adapter.execute(actions[1])

    assert applied["synthetic"] is False
    assert recovered["synthetic"] is False
    assert (runtime / "during" / "apply-wrong-key.json").exists()
    assert (runtime / "during" / "recover-wrong-key.json").exists()


def test_composes_through_all_53_checkpointed_actions(
    tmp_path: Path,
) -> None:
    controller, _, _, _ = fixture(tmp_path / "controller")
    deployment_request, schedule, _, request = (
        ACTION_TESTS.INPUT_TESTS.fixture(tmp_path / "pilot")
    )
    ACTION_TESTS.INPUTS.render_file(deployment_request)
    clients = ACTION_TESTS.ClientSet()
    adapter = ACTION_TESTS.ACTIONS.PilotActionAdapter.load(
        schedule,
        Path(request["readiness"]["file"]),
        client_factory=clients,
        controller=controller,
        clocks={
            "before": lambda: 150,
            "during": lambda: 350,
            "after": lambda: 550,
        },
    )

    result = ACTION_TESTS.ACTIONS.pilot_executor.execute(
        schedule,
        Path(request["readiness"]["file"]),
        adapter=adapter,
    )

    assert result["complete"] is True
    assert result["synthetic"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "source",
        "name",
        "timeout",
        "missing-command",
        "executable-hash",
        "executable-mode",
        "executable-link",
        "argv-binary",
        "argv-secret",
        "argv-shell",
    ],
)
def test_configuration_and_executable_drift_are_refused(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, config_path, executable, config = fixture(tmp_path)
    changed = deepcopy(config)
    if mutation == "schema":
        changed["schema"] = "wrong"
    elif mutation == "source":
        changed["controller_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "name":
        changed["name"] = "name with spaces"
    elif mutation == "timeout":
        changed["timeout_seconds"] = 0
    elif mutation == "missing-command":
        del changed["commands"]["apply-wrong-key"]
    elif mutation == "executable-hash":
        changed["commands"]["apply-wrong-key"]["executable"][
            "file_sha256"
        ] = f"sha256:{'0' * 64}"
    elif mutation == "executable-mode":
        executable.chmod(0o755)
    elif mutation == "executable-link":
        os.link(executable, tmp_path / "executable-link")
    elif mutation == "argv-binary":
        changed["commands"]["apply-wrong-key"]["argv"][0] = "/bin/false"
    elif mutation == "argv-secret":
        changed["commands"]["apply-wrong-key"]["argv"].append(
            "--password"
        )
    elif mutation == "argv-shell":
        changed["commands"]["apply-wrong-key"]["argv"].append(";whoami")
    owner_document(config_path, changed)

    with pytest.raises(CONTROLLER.PilotFaultControllerError):
        CONTROLLER.CommandFaultController.load(config_path)


@pytest.mark.parametrize(
    ("behavior", "message"),
    [
        ("stderr", "failed"),
        ("nonzero", "failed"),
        ("oversize", "exceeded"),
        ("malformed", "invalid"),
        ("tamper", "changed"),
    ],
)
def test_command_failure_has_fixed_secret_safe_category(
    tmp_path: Path,
    behavior: str,
    message: str,
) -> None:
    controller, _, _, _ = fixture(tmp_path, behavior=behavior)

    with pytest.raises(
        CONTROLLER.PilotFaultControllerError,
        match=message,
    ):
        controller.apply("wrong-key", f"sha256:{'7' * 64}")


def test_timeout_kills_isolated_process_group(
    tmp_path: Path,
) -> None:
    controller, _, _, _ = fixture(
        tmp_path,
        behavior="sleep",
        timeout=1,
    )
    started = time.monotonic()

    with pytest.raises(
        CONTROLLER.PilotFaultControllerError,
        match="timed out",
    ):
        controller.apply("kms-outage", f"sha256:{'8' * 64}")

    assert time.monotonic() - started < 5


def test_observation_and_request_drift_are_refused(
    tmp_path: Path,
) -> None:
    controller, _, _, _ = fixture(tmp_path)
    evidence = f"sha256:{'7' * 64}"

    with pytest.raises(CONTROLLER.PilotFaultControllerError):
        controller.apply("unknown", evidence)
    with pytest.raises(CONTROLLER.PilotFaultControllerError):
        controller.apply("wrong-key", "invalid")
    with pytest.raises(CONTROLLER.PilotFaultControllerError):
        controller.observe("wrong-key", "unknown", evidence)


def test_source_only_cli_has_no_controller_execution_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert CONTROLLER.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == (
        CONTROLLER.SOURCE_RESULT_SCHEMA
    )

    assert CONTROLLER.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "pilot-fault-controller-refused\n"
