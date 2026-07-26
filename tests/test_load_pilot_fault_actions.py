from __future__ import annotations

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


ACTIONS = load_module(
    "coffer_load_pilot_fault_actions_tests",
    COLLECTOR_DIRECTORY / "pilot_fault_actions.py",
)
SCHEDULE_TESTS = load_module(
    "coffer_load_pilot_fault_actions_schedule_fixtures",
    ROOT / "tests" / "test_load_pilot_schedule.py",
)


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(ACTIONS._canonical(value))
    path.chmod(0o600)


class FakeController:
    name = "fixture-external-fault-controller"
    source_sha256 = f"sha256:{'9' * 64}"

    def __init__(self) -> None:
        self.states: dict[str, tuple[str, str]] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.override: dict[str, object] = {}

    def _result(
        self,
        fault: str,
        state: str,
        evidence_sha256: str,
    ) -> ACTIONS.FaultObservation:
        value = ACTIONS.FaultObservation(
            completed_at_seconds=(
                321 if state == "applied" else 361
            ),
            evidence_sha256=evidence_sha256,
            fault=fault,
            started_at_seconds=(
                320 if state == "applied" else 360
            ),
            state=state,
        )
        return self.override.get(state, value)

    def apply(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> ACTIONS.FaultObservation:
        self.calls.append(("apply", fault, evidence_sha256))
        self.states[fault] = ("applied", evidence_sha256)
        return self._result(fault, "applied", evidence_sha256)

    def recover(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> ACTIONS.FaultObservation:
        self.calls.append(("recover", fault, evidence_sha256))
        if self.states.get(fault) != ("applied", evidence_sha256):
            raise RuntimeError("fault is not applied")
        self.states[fault] = ("recovered", evidence_sha256)
        return self._result(fault, "recovered", evidence_sha256)

    def observe(
        self,
        fault: str,
        state: str,
        evidence_sha256: str,
    ) -> ACTIONS.FaultObservation | None:
        self.calls.append(("observe", fault, evidence_sha256))
        if self.states.get(fault) != (state, evidence_sha256):
            return None
        return self._result(fault, state, evidence_sha256)


def fixture(
    tmp_path: Path,
) -> tuple[
    ACTIONS.PilotFaultActionAdapter,
    list[dict],
    Path,
    FakeController,
]:
    request_path, schedule_output, runtime, request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    runtime.mkdir(mode=0o700)
    during = runtime / "during"
    during.mkdir(mode=0o700)
    controller = FakeController()
    adapter = ACTIONS.PilotFaultActionAdapter.load(
        schedule_output,
        Path(request["readiness"]["file"]),
        controller=controller,
    )
    schedule = json.loads(
        (schedule_output / "schedule.json").read_bytes()
    )
    actions = [
        action
        for action in schedule["actions"]
        if action["action"] in ACTIONS.SUPPORTED_ACTIONS
    ]
    return adapter, actions, during, controller


def test_applies_and_recovers_both_faults_in_exact_order(
    tmp_path: Path,
) -> None:
    adapter, actions, during, controller = fixture(tmp_path)

    results = [adapter.execute(action) for action in actions]

    assert [action["action"] for action in actions] == [
        "apply-wrong-key",
        "recover-wrong-key",
        "apply-kms-outage",
        "recover-kms-outage",
    ]
    assert all(result["synthetic"] is False for result in results)
    assert all(result["adapter"] == "pilot-fault" for result in results)
    assert [call[:2] for call in controller.calls] == [
        ("apply", "wrong-key"),
        ("recover", "wrong-key"),
        ("apply", "kms-outage"),
        ("recover", "kms-outage"),
    ]
    assert set(path.name for path in during.iterdir()) == {
        "apply-wrong-key.json",
        "recover-wrong-key.json",
        "apply-kms-outage.json",
        "recover-kms-outage.json",
    }
    for path in during.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1
        value = json.loads(path.read_bytes())
        assert value["schema"] == ACTIONS.ACTION_SCHEMA
        assert value["synthetic"] is False
        assert value["phase"] == "during"


def test_exact_outputs_reconcile_without_controller_call(
    tmp_path: Path,
) -> None:
    adapter, actions, _, controller = fixture(tmp_path)
    first = [adapter.execute(action) for action in actions]
    calls = list(controller.calls)

    reconciled = [adapter.reconcile(action) for action in actions]

    assert reconciled == first
    assert controller.calls == calls


def test_missing_apply_output_is_reconstructed_from_controller_state(
    tmp_path: Path,
) -> None:
    adapter, actions, _, controller = fixture(tmp_path)
    action = actions[0]
    evidence = action["fault_evidence_sha256"]
    controller.apply("wrong-key", evidence)
    calls = list(controller.calls)

    result = adapter.reconcile(action)

    assert result is not None
    assert controller.calls == [
        *calls,
        ("observe", "wrong-key", evidence),
    ]
    assert Path(action["output_file"]).exists()
    assert [call[0] for call in controller.calls].count("apply") == 1


def test_missing_unobserved_output_requests_safe_retry(
    tmp_path: Path,
) -> None:
    adapter, actions, _, controller = fixture(tmp_path)

    result = adapter.reconcile(actions[0])

    assert result is None
    assert controller.calls[0][:2] == ("observe", "wrong-key")
    assert Path(actions[0]["output_file"]).exists() is False


@pytest.mark.parametrize(
    "field",
    [
        "fault_action_sha256",
        "controller_source_sha256",
        "fault",
        "state",
        "target_sha256",
        "window_sha256",
    ],
)
def test_retained_fault_result_tamper_is_refused(
    tmp_path: Path,
    field: str,
) -> None:
    adapter, actions, _, _ = fixture(tmp_path)
    action = actions[0]
    adapter.execute(action)
    path = Path(action["output_file"])
    value = json.loads(path.read_bytes())
    value[field] = (
        False
        if field == "state"
        else f"sha256:{'0' * 64}"
        if field.endswith("sha256")
        else "changed"
    )
    owner_document(path, value)

    with pytest.raises(ACTIONS.PilotFaultActionError):
        adapter.reconcile(action)


@pytest.mark.parametrize(
    ("state", "override"),
    [
        (
            "applied",
            ACTIONS.FaultObservation(
                completed_at_seconds=321,
                evidence_sha256=f"sha256:{'0' * 64}",
                fault="wrong-key",
                started_at_seconds=320,
                state="applied",
            ),
        ),
        (
            "applied",
            ACTIONS.FaultObservation(
                completed_at_seconds=321,
                evidence_sha256=f"sha256:{'7' * 64}",
                fault="other",
                started_at_seconds=320,
                state="applied",
            ),
        ),
        (
            "applied",
            ACTIONS.FaultObservation(
                completed_at_seconds=401,
                evidence_sha256=f"sha256:{'7' * 64}",
                fault="wrong-key",
                started_at_seconds=400,
                state="applied",
            ),
        ),
    ],
)
def test_controller_observation_drift_is_refused(
    tmp_path: Path,
    state: str,
    override: ACTIONS.FaultObservation,
) -> None:
    adapter, actions, _, controller = fixture(tmp_path)
    controller.override[state] = override

    with pytest.raises(ACTIONS.PilotFaultActionError):
        adapter.execute(actions[0])

    assert Path(actions[0]["output_file"]).exists() is False


def test_recovery_requires_valid_applied_result(tmp_path: Path) -> None:
    adapter, actions, _, _ = fixture(tmp_path)
    recovery = actions[1]

    with pytest.raises(ACTIONS.PilotFaultActionError):
        adapter.execute(recovery)

    assert Path(recovery["output_file"]).exists() is False


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    adapter, actions, _, controller = fixture(tmp_path)
    output = Path(actions[0]["output_file"])
    owner_document(output, {"unrelated": True})
    inode = output.stat().st_ino

    with pytest.raises(
        ACTIONS.PilotFaultActionError,
        match="already exists",
    ):
        adapter.execute(actions[0])

    assert output.stat().st_ino == inode
    assert controller.calls == []


def test_missing_phase_refuses_before_controller_call(
    tmp_path: Path,
) -> None:
    adapter, actions, during, controller = fixture(tmp_path)
    during.rmdir()

    with pytest.raises(
        ACTIONS.PilotFaultActionError,
        match="phase",
    ):
        adapter.execute(actions[0])

    assert controller.calls == []


def test_nonfault_or_drifted_action_is_refused(tmp_path: Path) -> None:
    adapter, _, _, controller = fixture(tmp_path)
    action = next(
        item
        for item in adapter.schedule["actions"]
        if item["action"] == "collect-rgw-step"
    )

    with pytest.raises(
        ACTIONS.PilotFaultActionError,
        match="unsupported",
    ):
        adapter.execute(action)

    assert controller.calls == []


def test_blocked_readiness_refuses_adapter_load(tmp_path: Path) -> None:
    request_path, schedule_output, _, request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    readiness = Path(request["readiness"]["file"])
    value = json.loads(readiness.read_bytes())
    value["status"] = "blocked"
    owner_document(readiness, value)

    with pytest.raises(ACTIONS.PilotFaultActionError):
        ACTIONS.PilotFaultActionAdapter.load(
            schedule_output,
            readiness,
            controller=FakeController(),
        )


def test_retained_output_has_no_controller_detail(
    tmp_path: Path,
) -> None:
    adapter, actions, during, _ = fixture(tmp_path)
    adapter.execute(actions[0])
    retained = (during / "apply-wrong-key.json").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "endpoint",
        "credential",
        "secret",
        "kms_key",
        "command",
        "stdout",
        "stderr",
    ):
        assert forbidden not in retained


def test_source_only_cli_has_no_fault_execution_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ACTIONS.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == ACTIONS.SOURCE_RESULT_SCHEMA

    assert ACTIONS.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "pilot-fault-actions-refused\n"
