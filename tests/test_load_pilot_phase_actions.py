from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import stat
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


ACTIONS = load_module(
    "coffer_load_pilot_phase_actions_tests",
    COLLECTOR_DIRECTORY / "pilot_phase_actions.py",
)
SCHEDULE_TESTS = load_module(
    "coffer_load_pilot_phase_actions_schedule_fixtures",
    ROOT / "tests" / "test_load_pilot_schedule.py",
)
RGW_TESTS = load_module(
    "coffer_load_pilot_phase_actions_rgw_fixtures",
    ROOT / "tests" / "test_load_pilot_rgw_actions.py",
)
PHASE_TESTS = load_module(
    "coffer_load_pilot_phase_actions_phase_fixtures",
    ROOT / "tests" / "test_load_phase_preparation.py",
)


class ClientSet:
    def __call__(
        self,
        config: dict[str, Any],
    ) -> ACTIONS.pilot_rgw_actions.RgwRuntimeClients:
        before = RGW_TESTS.CLEANUP_TESTS.populated(
            config["probe_prefix"]
        )
        after = RGW_TESTS.CLEANUP_TESTS.empty_inventory()
        return ACTIONS.pilot_rgw_actions.RgwRuntimeClients(
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


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(ACTIONS._canonical(value))
    path.chmod(0o600)


def descriptor(path: Path) -> dict[str, str]:
    return {
        "file": str(path),
        "file_sha256": ACTIONS._payload_hash(path.read_bytes()),
    }


def rewrite_binding(
    path: Path,
    *,
    phase: str,
    target_path: Path,
    target_sha256: str,
    window_sha256: str,
) -> None:
    value = json.loads(path.read_bytes())
    for key, replacement in (
        ("phase", phase),
        ("target_file", str(target_path)),
        ("target_file_sha256", target_sha256),
        ("window_sha256", window_sha256),
    ):
        if key in value:
            value[key] = replacement
    if "capture_sha256" in value:
        value["capture_sha256"] = (
            ACTIONS.phase_preparation.control_artifacts._hash(
                {
                    key: item
                    for key, item in value.items()
                    if key != "capture_sha256"
                }
            )
        )
    owner_document(path, value)


def write_collector_inputs(
    *,
    adapter: ACTIONS.PilotPhaseActionAdapter,
    action: dict[str, Any],
    source_root: Path,
) -> Path:
    phase = action["phase"]
    request_path, _, request = PHASE_TESTS.fixture(
        source_root,
        phase=phase,
    )
    del request_path
    config = json.loads(Path(action["config_file"]).read_bytes())
    target_path = Path(request["target"]["file"])
    target_file_sha256 = request["target"]["file_sha256"]
    window_sha256 = config["window_sha256"]
    paths = {
        name: Path(value["file"])
        for name, value in request["collector_inputs"].items()
    }
    for name in (
        "control_baseline",
        "control_config",
        "control_current",
        "galera_config",
        "haproxy_config",
        "prometheus_config",
    ):
        rewrite_binding(
            paths[name],
            phase=phase,
            target_path=target_path,
            target_sha256=target_file_sha256,
            window_sha256=window_sha256,
        )
    collector_inputs = {
        "collector_inputs": {
            "control_baseline": descriptor(paths["control_baseline"]),
            "control_config": descriptor(paths["control_config"]),
            "control_current": descriptor(paths["control_current"]),
            "galera_config": descriptor(paths["galera_config"]),
            "haproxy_config": descriptor(paths["haproxy_config"]),
            "prometheus_config": descriptor(paths["prometheus_config"]),
        },
        "evidence_server": request["evidence_server"],
        "materializer_source_sha256": ACTIONS.adapter_source_sha256(),
        "phase": phase,
        "preparer_source_sha256": (
            ACTIONS.phase_preparation.preparer_source_sha256()
        ),
        "schedule_sha256": adapter.schedule["schedule_sha256"],
        "schema": ACTIONS.COLLECTOR_INPUT_SCHEMA,
        "target": descriptor(target_path),
        "window_sha256": window_sha256,
    }
    output = Path(action["input_file"])
    owner_document(output, collector_inputs)
    return output


def fixture(
    tmp_path: Path,
    *,
    phase: str = "before",
) -> tuple[
    ACTIONS.PilotPhaseActionAdapter,
    list[dict[str, Any]],
    Path,
]:
    request_path, schedule_output, runtime, request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    clients = ClientSet()
    clocks = {"before": 150, "during": 350, "after": 550}
    rgw = ACTIONS.pilot_rgw_actions.PilotRgwActionAdapter.load(
        schedule_output,
        Path(request["readiness"]["file"]),
        client_factory=clients,
        clock=lambda: clocks[phase],
    )
    schedule = json.loads(
        (schedule_output / "schedule.json").read_bytes()
    )
    rgw_actions = [
        action
        for action in schedule["actions"]
        if action["phase"] == phase
        and action["action"]
        in ACTIONS.pilot_rgw_actions.SUPPORTED_ACTIONS
    ]
    for action in rgw_actions:
        rgw.execute(action)
    phase_adapter = ACTIONS.PilotPhaseActionAdapter.load(
        schedule_output,
        Path(request["readiness"]["file"]),
    )
    selected = [
        action
        for action in schedule["actions"]
        if action["phase"] == phase
        and action["action"] in ACTIONS.SUPPORTED_ACTIONS
    ]
    write_collector_inputs(
        adapter=phase_adapter,
        action=selected[0],
        source_root=tmp_path / "phase-source",
    )
    return phase_adapter, selected, runtime


@pytest.mark.parametrize("phase", ACTIONS.native_target.PHASES)
def test_materializes_complete_phase_action_set(
    tmp_path: Path,
    phase: str,
) -> None:
    adapter, selected, runtime = fixture(tmp_path, phase=phase)

    results = [adapter.execute(action) for action in selected]

    assert [action["action"] for action in selected] == [
        "render-phase-preparation-request",
        "prepare-phase-atomically",
        "complete-phase",
    ]
    assert all(result["synthetic"] is False for result in results)
    assert all(result["adapter"] == "pilot-phase" for result in results)
    phase_root = runtime / phase
    evidence = phase_root / "phase-evidence"
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o700
    assert set(path.name for path in evidence.iterdir()) == set(
        ACTIONS.phase_preparation.OUTPUT_FILES
    )
    completion = json.loads(
        (phase_root / "phase-complete.json").read_bytes()
    )
    assert completion["complete"] is True
    assert completion["phase"] == phase
    assert completion["schema"] == ACTIONS.COMPLETION_SCHEMA


def test_reconcile_revalidates_without_rewriting_outputs(
    tmp_path: Path,
) -> None:
    adapter, selected, _ = fixture(tmp_path)
    first = [adapter.execute(action) for action in selected]
    outputs = [Path(action["output_file"]) for action in selected]
    identities = {str(path): path.stat().st_ino for path in outputs}

    reconciled = [adapter.reconcile(action) for action in selected]

    assert reconciled == first
    assert {str(path): path.stat().st_ino for path in outputs} == identities


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-field",
        "schedule",
        "dynamic-path",
        "input-mode",
        "target",
    ],
)
def test_collector_input_drift_is_refused_before_output(
    tmp_path: Path,
    mutation: str,
) -> None:
    adapter, selected, _ = fixture(tmp_path)
    action = selected[0]
    input_path = Path(action["input_file"])
    value = json.loads(input_path.read_bytes())
    if mutation == "unknown-field":
        value["credential"] = "forbidden"
    elif mutation == "schedule":
        value["schedule_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "dynamic-path":
        value["collector_inputs"]["control_baseline"] = value[
            "collector_inputs"
        ]["control_current"]
    elif mutation == "input-mode":
        path = Path(value["collector_inputs"]["control_current"]["file"])
        path.chmod(0o640)
    elif mutation == "target":
        value["target"] = value["collector_inputs"]["control_current"]
    owner_document(input_path, value)

    with pytest.raises(
        ACTIONS.PilotPhaseActionError,
    ):
        adapter.execute(action)

    assert not Path(action["output_file"]).exists()


def test_cleanup_or_phase_result_tamper_blocks_completion(
    tmp_path: Path,
) -> None:
    adapter, selected, runtime = fixture(tmp_path)
    adapter.execute(selected[0])
    adapter.execute(selected[1])
    cleanup_path = runtime / "before" / "rgw-cleanup-verified.json"
    cleanup = json.loads(cleanup_path.read_bytes())
    cleanup["verified"] = False
    owner_document(cleanup_path, cleanup)

    with pytest.raises(ACTIONS.PilotPhaseActionError):
        adapter.execute(selected[2])

    assert not Path(selected[2]["output_file"]).exists()


def test_existing_or_unsupported_output_is_never_overwritten(
    tmp_path: Path,
) -> None:
    adapter, selected, _ = fixture(tmp_path)
    output = Path(selected[0]["output_file"])
    owner_document(output, {"unexpected": True})

    with pytest.raises(ACTIONS.PilotPhaseActionError):
        adapter.execute(selected[0])
    assert json.loads(output.read_bytes()) == {"unexpected": True}

    unsupported = deepcopy(selected[0])
    unsupported["action"] = "collect-rgw-step"
    with pytest.raises(ACTIONS.PilotPhaseActionError):
        adapter.execute(unsupported)


def test_source_only_cli_has_no_phase_execution_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ACTIONS.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == ACTIONS.SOURCE_RESULT_SCHEMA

    assert ACTIONS.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "pilot-phase-actions-refused\n"
