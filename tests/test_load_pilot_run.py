from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

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


RUNNER = load_module(
    "coffer_load_pilot_run_tests",
    COLLECTOR_DIRECTORY / "pilot_run.py",
)
INPUT_TESTS = load_module(
    "coffer_load_pilot_run_input_fixtures",
    ROOT / "tests" / "test_load_pilot_inputs.py",
)
CONTROLLER_TESTS = load_module(
    "coffer_load_pilot_run_controller_fixtures",
    ROOT / "tests" / "test_load_pilot_fault_controller.py",
)
RGW_TESTS = load_module(
    "coffer_load_pilot_run_rgw_fixtures",
    ROOT / "tests" / "test_load_pilot_rgw_actions.py",
)


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(RUNNER._canonical(value))
    path.chmod(0o600)


def descriptor(path: Path) -> dict[str, str]:
    return {
        "file": str(path),
        "file_sha256": RUNNER._payload_hash(path.read_bytes()),
    }


class ClientSet:
    def __init__(self) -> None:
        self.values: dict[
            str,
            RUNNER.pilot_actions.pilot_rgw_actions.RgwRuntimeClients,
        ] = {}
        self.calls: list[str] = []

    def __call__(
        self,
        config: dict[str, Any],
    ) -> RUNNER.pilot_actions.pilot_rgw_actions.RgwRuntimeClients:
        self.calls.append(config["phase"])
        before = RGW_TESTS.CLEANUP_TESTS.populated(
            config["probe_prefix"]
        )
        after = RGW_TESTS.CLEANUP_TESTS.empty_inventory()
        clients = (
            RUNNER.pilot_actions.pilot_rgw_actions.RgwRuntimeClients(
                cleanup=RGW_TESTS.CLEANUP_TESTS.FakeCleanupClient(
                    [
                        RUNNER.pilot_actions.pilot_rgw_actions.rgw_cleanup.CleanupInventory(
                            **before.__dict__
                        ),
                        RUNNER.pilot_actions.pilot_rgw_actions.rgw_cleanup.CleanupInventory(
                            **after.__dict__
                        ),
                    ]
                ),
                evidence=RGW_TESTS.ADAPTER_TESTS.FakeClient(),
            )
        )
        self.values[config["phase"]] = clients
        return clients


def fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict, ClientSet]:
    deployment, schedule, runtime, deployment_request = (
        INPUT_TESTS.fixture(tmp_path / "pilot")
    )
    _, controller_path, _, _ = CONTROLLER_TESTS.fixture(
        tmp_path / "controller"
    )
    invocation = {
        "controller": descriptor(controller_path),
        "deployment_inputs": descriptor(deployment),
        "readiness": deployment_request["readiness"],
        "runner_source_sha256": RUNNER.runner_source_sha256(),
        "schedule_directory": str(schedule),
        "schema": RUNNER.REQUEST_SCHEMA,
    }
    invocation_path = tmp_path / "invocation.json"
    owner_document(invocation_path, invocation)
    return invocation_path, runtime, controller_path, invocation, ClientSet()


def clocks() -> dict[str, Any]:
    return {
        "before": lambda: 150,
        "during": lambda: 350,
        "after": lambda: 550,
    }


def test_qualified_invocation_completes_all_53_actions(
    tmp_path: Path,
) -> None:
    invocation, runtime, _, _, clients = fixture(tmp_path)

    result = RUNNER.run_file(
        invocation,
        client_factory=clients,
        clocks=clocks(),
    )

    assert result["complete"] is True
    assert result["synthetic"] is False
    assert clients.calls == ["before", "during", "after"]
    state = json.loads(
        (
            runtime / RUNNER.pilot_executor.STATE_FILE
        ).read_bytes()
    )
    assert state["complete"] is True
    assert state["adapter"] == "pilot"
    assert len(state["history"]) == 53
    assert (
        runtime / RUNNER.pilot_executor.DEPLOYMENT_INPUT_RESULT_FILE
    ).exists()


def test_exact_repeat_runs_no_storage_or_fault_action(
    tmp_path: Path,
) -> None:
    invocation, _, _, _, first_clients = fixture(tmp_path)
    first = RUNNER.run_file(
        invocation,
        client_factory=first_clients,
        clocks=clocks(),
    )
    second_clients = ClientSet()

    second = RUNNER.run_file(
        invocation,
        client_factory=second_clients,
        clocks=clocks(),
    )

    assert second == first
    assert second_clients.calls == ["before", "during", "after"]
    assert all(
        not clients.evidence.calls
        for clients in second_clients.values.values()
    )


def test_blocked_readiness_precedes_controller_and_client_access(
    tmp_path: Path,
) -> None:
    invocation_path, runtime, _, invocation, _ = fixture(tmp_path)
    readiness_path = Path(invocation["readiness"]["file"])
    readiness = json.loads(readiness_path.read_bytes())
    readiness["status"] = "blocked"
    readiness["distribution"]["status"] = "blocked"
    readiness["distribution"]["reasons"] = ["still blocked"]
    readiness_path.write_text(
        json.dumps(readiness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readiness_path.chmod(0o600)
    invocation["readiness"] = descriptor(readiness_path)
    owner_document(invocation_path, invocation)
    calls: list[str] = []

    def refused_controller(path: Path):
        calls.append(f"controller:{path}")
        raise AssertionError("controller must not load")

    def refused_client(config: dict[str, Any]):
        calls.append(f"client:{config['phase']}")
        raise AssertionError("client must not load")

    with pytest.raises(
        RUNNER.PilotRunError,
        match="not qualified",
    ):
        RUNNER.run_file(
            invocation_path,
            client_factory=refused_client,
            controller_loader=refused_controller,
        )

    assert calls == []
    assert not runtime.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "source",
        "schedule",
        "deployment-hash",
        "controller-hash",
        "invocation-mode",
        "input-alias",
        "unknown",
    ],
)
def test_invocation_drift_is_refused_without_runtime(
    tmp_path: Path,
    mutation: str,
) -> None:
    invocation_path, runtime, controller, invocation, clients = fixture(
        tmp_path
    )
    changed = deepcopy(invocation)
    if mutation == "schema":
        changed["schema"] = "wrong"
    elif mutation == "source":
        changed["runner_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "schedule":
        changed["schedule_directory"] = str(tmp_path / "missing")
    elif mutation == "deployment-hash":
        changed["deployment_inputs"]["file_sha256"] = (
            f"sha256:{'0' * 64}"
        )
    elif mutation == "controller-hash":
        changed["controller"]["file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "invocation-mode":
        invocation_path.chmod(0o640)
    elif mutation == "input-alias":
        changed["deployment_inputs"] = descriptor(controller)
    elif mutation == "unknown":
        changed["credential"] = "forbidden"
    owner_document(invocation_path, changed)
    if mutation == "invocation-mode":
        invocation_path.chmod(0o640)

    with pytest.raises(RUNNER.PilotRunError):
        RUNNER.run_file(
            invocation_path,
            client_factory=clients,
            clocks=clocks(),
        )

    assert not runtime.exists()
    assert clients.calls == []


def test_changed_invocation_cannot_resume_existing_checkpoint(
    tmp_path: Path,
) -> None:
    invocation_path, _, controller, invocation, clients = fixture(
        tmp_path
    )
    RUNNER.run_file(
        invocation_path,
        client_factory=clients,
        clocks=clocks(),
    )
    replacement = controller.parent / "replacement-controller.json"
    replacement.write_bytes(controller.read_bytes())
    replacement.chmod(0o600)
    invocation["controller"] = descriptor(replacement)
    owner_document(invocation_path, invocation)

    with pytest.raises(RUNNER.PilotRunError, match="execution failed"):
        RUNNER.run_file(
            invocation_path,
            client_factory=ClientSet(),
            clocks=clocks(),
        )


def test_invocation_hardlink_alias_is_refused(
    tmp_path: Path,
) -> None:
    invocation_path, runtime, controller, _, clients = fixture(tmp_path)
    invocation_path.unlink()
    os.link(controller, invocation_path)

    with pytest.raises(RUNNER.PilotRunError):
        RUNNER.run_file(
            invocation_path,
            client_factory=clients,
            clocks=clocks(),
        )

    assert not runtime.exists()
    assert clients.calls == []


def test_source_and_cli_failures_are_fixed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert RUNNER.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == RUNNER.SOURCE_RESULT_SCHEMA

    assert RUNNER.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "pilot-run-refused\n"
