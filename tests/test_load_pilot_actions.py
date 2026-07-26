from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping

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
    "coffer_load_pilot_actions_tests",
    COLLECTOR_DIRECTORY / "pilot_actions.py",
)
SCHEDULE_TESTS = load_module(
    "coffer_load_pilot_actions_schedule_fixtures",
    ROOT / "tests" / "test_load_pilot_schedule.py",
)
RGW_TESTS = load_module(
    "coffer_load_pilot_actions_rgw_fixtures",
    ROOT / "tests" / "test_load_pilot_rgw_actions.py",
)
PHASE_TESTS = load_module(
    "coffer_load_pilot_actions_phase_fixtures",
    ROOT / "tests" / "test_load_pilot_phase_actions.py",
)


class ClientSet:
    def __init__(self) -> None:
        self.values: dict[
            str,
            ACTIONS.pilot_rgw_actions.RgwRuntimeClients,
        ] = {}

    def __call__(
        self,
        config: dict[str, Any],
    ) -> ACTIONS.pilot_rgw_actions.RgwRuntimeClients:
        before = RGW_TESTS.CLEANUP_TESTS.populated(
            config["probe_prefix"]
        )
        after = RGW_TESTS.CLEANUP_TESTS.empty_inventory()
        clients = ACTIONS.pilot_rgw_actions.RgwRuntimeClients(
            cleanup=RGW_TESTS.CLEANUP_TESTS.FakeCleanupClient(
                [
                    ACTIONS.pilot_rgw_actions.rgw_cleanup.CleanupInventory(
                        **before.__dict__
                    ),
                    ACTIONS.pilot_rgw_actions.rgw_cleanup.CleanupInventory(
                        **after.__dict__
                    ),
                ]
            ),
            evidence=RGW_TESTS.ADAPTER_TESTS.FakeClient(),
        )
        self.values[config["phase"]] = clients
        return clients


class FakeController:
    name = "fixture-external-controller"
    source_sha256 = f"sha256:{'9' * 64}"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.observations: dict[
            tuple[str, str, str],
            ACTIONS.pilot_fault_actions.FaultObservation,
        ] = {}
        self.raise_after_apply: str | None = None

    def _change(
        self,
        fault: str,
        state: str,
        evidence_sha256: str,
    ) -> ACTIONS.pilot_fault_actions.FaultObservation:
        self.calls.append((state, fault, evidence_sha256))
        offset = len(self.calls) * 2
        observation = ACTIONS.pilot_fault_actions.FaultObservation(
            completed_at_seconds=321 + offset,
            evidence_sha256=evidence_sha256,
            fault=fault,
            started_at_seconds=320 + offset,
            state=state,
        )
        self.observations[(fault, state, evidence_sha256)] = observation
        if state == "applied" and self.raise_after_apply == fault:
            self.raise_after_apply = None
            raise RuntimeError("controller response interrupted")
        return observation

    def apply(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> ACTIONS.pilot_fault_actions.FaultObservation:
        return self._change(fault, "applied", evidence_sha256)

    def recover(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> ACTIONS.pilot_fault_actions.FaultObservation:
        return self._change(fault, "recovered", evidence_sha256)

    def observe(
        self,
        fault: str,
        state: str,
        evidence_sha256: str,
    ) -> ACTIONS.pilot_fault_actions.FaultObservation | None:
        self.calls.append((f"observe-{state}", fault, evidence_sha256))
        return self.observations.get((fault, state, evidence_sha256))


@dataclass
class InterruptingPilot:
    delegate: ACTIONS.PilotActionAdapter
    fail_before_order: int | None = None
    raise_after_order: int | None = None
    contract: str = ACTIONS.pilot_executor.PILOT_ADAPTER_CONTRACT
    name: str = "pilot"
    source_sha256: str = ""
    synthetic: bool = False

    def __post_init__(self) -> None:
        self.source_sha256 = self.delegate.source_sha256

    def execute(
        self,
        action: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if self.fail_before_order == action["order"]:
            self.fail_before_order = None
            raise RuntimeError("pilot failed before action")
        result = self.delegate.execute(action)
        if self.raise_after_order == action["order"]:
            self.raise_after_order = None
            raise RuntimeError("pilot response interrupted")
        return result

    def reconcile(
        self,
        action: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        return self.delegate.reconcile(action)


def fixture(
    tmp_path: Path,
) -> tuple[
    ACTIONS.PilotActionAdapter,
    Path,
    Path,
    ClientSet,
    FakeController,
]:
    request_path, schedule_output, runtime, request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    clients = ClientSet()
    controller = FakeController()
    clocks = {
        "before": lambda: 150,
        "during": lambda: 350,
        "after": lambda: 550,
    }
    adapter = ACTIONS.PilotActionAdapter.load(
        schedule_output,
        Path(request["readiness"]["file"]),
        client_factory=clients,
        controller=controller,
        clocks=clocks,
    )
    runtime.mkdir(mode=0o700)
    schedule = json.loads(
        (schedule_output / "schedule.json").read_bytes()
    )
    for phase in ACTIONS.native_target.PHASES:
        phase_root = runtime / phase
        phase_root.mkdir(mode=0o700)
        render_action = next(
            action
            for action in schedule["actions"]
            if action["phase"] == phase
            and action["action"]
            == "render-phase-preparation-request"
        )
        PHASE_TESTS.write_collector_inputs(
            adapter=adapter.phase,
            action=render_action,
            source_root=tmp_path / f"{phase}-collector-source",
        )
    return (
        adapter,
        schedule_output,
        Path(request["readiness"]["file"]),
        clients,
        controller,
    )


def test_executes_all_53_nonsynthetic_actions_with_checkpoints(
    tmp_path: Path,
) -> None:
    adapter, schedule, readiness, clients, controller = fixture(tmp_path)

    result = ACTIONS.pilot_executor.execute(
        schedule,
        readiness,
        adapter=adapter,
    )

    assert result["complete"] is True
    assert result["synthetic"] is False
    runtime = Path(adapter.schedule["runtime_directory"])
    state = json.loads(
        (
            runtime / ACTIONS.pilot_executor.STATE_FILE
        ).read_bytes()
    )
    assert state["adapter"] == "pilot"
    assert state["adapter_contract"] == adapter.contract
    assert state["adapter_source_sha256"] == adapter.source_sha256
    assert state["complete"] is True
    assert len(state["history"]) == 53
    assert [item["order"] for item in state["history"]] == list(
        range(1, 54)
    )
    assert all(item["adapter"] == "pilot" for item in state["history"])
    assert all(item["synthetic"] is False for item in state["history"])
    assert [call[:2] for call in controller.calls] == [
        ("applied", "wrong-key"),
        ("recovered", "wrong-key"),
        ("applied", "kms-outage"),
        ("recovered", "kms-outage"),
    ]
    assert {
        phase: len(value.evidence.calls)
        for phase, value in clients.values.items()
    } == {"before": 7, "during": 11, "after": 7}
    for phase in ACTIONS.native_target.PHASES:
        root = runtime / phase
        completion = json.loads(
            (root / "phase-complete.json").read_bytes()
        )
        assert completion["complete"] is True
        assert completion["phase"] == phase
        assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_complete_repeat_executes_no_external_action(
    tmp_path: Path,
) -> None:
    adapter, schedule, readiness, clients, controller = fixture(tmp_path)
    first = ACTIONS.pilot_executor.execute(
        schedule,
        readiness,
        adapter=adapter,
    )
    calls = list(controller.calls)
    evidence_calls = {
        phase: list(value.evidence.calls)
        for phase, value in clients.values.items()
    }

    second = ACTIONS.pilot_executor.execute(
        schedule,
        readiness,
        adapter=adapter,
    )

    assert second == first
    assert controller.calls == calls
    assert {
        phase: value.evidence.calls
        for phase, value in clients.values.items()
    } == evidence_calls


def test_failure_before_action_resumes_exact_checkpoint(
    tmp_path: Path,
) -> None:
    adapter, schedule, readiness, _, _ = fixture(tmp_path)
    interrupted = InterruptingPilot(
        delegate=adapter,
        fail_before_order=20,
    )

    with pytest.raises(RuntimeError, match="before"):
        ACTIONS.pilot_executor.execute(
            schedule,
            readiness,
            adapter=interrupted,
        )

    result = ACTIONS.pilot_executor.execute(
        schedule,
        readiness,
        adapter=adapter,
    )

    assert result["complete"] is True
    runtime = Path(adapter.schedule["runtime_directory"])
    state = json.loads(
        (
            runtime / ACTIONS.pilot_executor.STATE_FILE
        ).read_bytes()
    )
    assert len(state["history"]) == 53


def test_rgW_output_interruption_reconciles_without_duplicate_call(
    tmp_path: Path,
) -> None:
    adapter, schedule, readiness, clients, _ = fixture(tmp_path)
    interrupted = InterruptingPilot(
        delegate=adapter,
        raise_after_order=2,
    )

    with pytest.raises(RuntimeError, match="response"):
        ACTIONS.pilot_executor.execute(
            schedule,
            readiness,
            adapter=interrupted,
        )
    calls = list(clients.values["before"].evidence.calls)

    result = ACTIONS.pilot_executor.execute(
        schedule,
        readiness,
        adapter=adapter,
    )

    assert result["complete"] is True
    assert clients.values["before"].evidence.calls.count(calls[0]) == 1


def test_fault_apply_interruption_recovers_from_observation(
    tmp_path: Path,
) -> None:
    adapter, schedule, readiness, _, controller = fixture(tmp_path)
    controller.raise_after_apply = "wrong-key"

    with pytest.raises(RuntimeError, match="controller"):
        ACTIONS.pilot_executor.execute(
            schedule,
            readiness,
            adapter=adapter,
        )

    result = ACTIONS.pilot_executor.execute(
        schedule,
        readiness,
        adapter=adapter,
    )

    assert result["complete"] is True
    applied = [
        call
        for call in controller.calls
        if call[:2] == ("applied", "wrong-key")
    ]
    observed = [
        call
        for call in controller.calls
        if call[:2] == ("observe-applied", "wrong-key")
    ]
    assert len(applied) == 1
    assert len(observed) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "contract",
        "name",
        "source",
        "synthetic",
        "phase-extra",
        "phase-mode",
        "collector-mode",
    ],
)
def test_executor_and_owner_only_runtime_boundary_is_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    adapter, schedule, readiness, _, _ = fixture(tmp_path)
    runtime = Path(adapter.schedule["runtime_directory"])
    wrapped = InterruptingPilot(delegate=adapter)
    if mutation == "contract":
        wrapped.contract = "wrong"
    elif mutation == "name":
        wrapped.name = "pilot-rgw"
    elif mutation == "source":
        wrapped.source_sha256 = "wrong"
    elif mutation == "synthetic":
        wrapped.synthetic = True
    elif mutation == "phase-extra":
        PHASE_TESTS.owner_document(
            runtime / "before" / "unexpected.json",
            {},
        )
    elif mutation == "phase-mode":
        (runtime / "before").chmod(0o755)
    elif mutation == "collector-mode":
        (runtime / "before" / "collector-inputs.json").chmod(0o640)

    with pytest.raises(ACTIONS.pilot_executor.PilotExecutorError):
        ACTIONS.pilot_executor.execute(
            schedule,
            readiness,
            adapter=wrapped,
        )


def test_source_only_cli_has_no_pilot_execution_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ACTIONS.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == ACTIONS.SOURCE_RESULT_SCHEMA

    assert ACTIONS.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "pilot-actions-refused\n"
