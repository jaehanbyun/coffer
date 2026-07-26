from __future__ import annotations

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
    "coffer_load_pilot_rgw_actions_tests",
    COLLECTOR_DIRECTORY / "pilot_rgw_actions.py",
)
SCHEDULE_TESTS = load_module(
    "coffer_load_pilot_rgw_actions_schedule_fixtures",
    ROOT / "tests" / "test_load_pilot_schedule.py",
)
ADAPTER_TESTS = load_module(
    "coffer_load_pilot_rgw_actions_adapter_fixtures",
    ROOT / "tests" / "test_load_rgw_live_adapter.py",
)
CLEANUP_TESTS = load_module(
    "coffer_load_pilot_rgw_actions_cleanup_fixtures",
    ROOT / "tests" / "test_load_rgw_cleanup.py",
)


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(ACTIONS._canonical(value))
    path.chmod(0o600)


class ClientSet:
    def __init__(self) -> None:
        self.values: dict[str, ACTIONS.RgwRuntimeClients] = {}

    def __call__(
        self,
        config: dict[str, Any],
    ) -> ACTIONS.RgwRuntimeClients:
        before = CLEANUP_TESTS.populated(config["probe_prefix"])
        after = CLEANUP_TESTS.empty_inventory()
        clients = ACTIONS.RgwRuntimeClients(
            cleanup=CLEANUP_TESTS.FakeCleanupClient(
                [
                    ACTIONS.rgw_cleanup.CleanupInventory(
                        **before.__dict__
                    ),
                    ACTIONS.rgw_cleanup.CleanupInventory(
                        **after.__dict__
                    ),
                ]
            ),
            evidence=ADAPTER_TESTS.FakeClient(),
        )
        self.values[config["phase"]] = clients
        return clients


def fixture(
    tmp_path: Path,
) -> tuple[
    ACTIONS.PilotRgwActionAdapter,
    list[dict[str, Any]],
    Path,
    ClientSet,
]:
    request_path, schedule_output, runtime, request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    clients = ClientSet()
    adapter = ACTIONS.PilotRgwActionAdapter.load(
        schedule_output,
        Path(request["readiness"]["file"]),
        client_factory=clients,
        clock=lambda: 150,
    )
    schedule = json.loads(
        (schedule_output / "schedule.json").read_bytes()
    )
    return adapter, schedule["actions"], runtime, clients


def before_supported(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        action
        for action in actions
        if action["phase"] == "before"
        and action["action"] in ACTIONS.SUPPORTED_ACTIONS
    ]


def test_materializes_complete_before_rgw_action_set(
    tmp_path: Path,
) -> None:
    adapter, actions, runtime, clients = fixture(tmp_path)
    selected = before_supported(actions)

    results = [adapter.execute(action) for action in selected]

    assert [action["action"] for action in selected] == [
        "open-phase",
        *(["collect-rgw-step"] * 7),
        "compile-rgw-probe",
        "collect-rgw-multipart",
        "cleanup-rgw-prefix",
        "verify-rgw-cleanup",
    ]
    assert all(result["synthetic"] is False for result in results)
    assert all(result["adapter"] == "pilot-rgw" for result in results)
    phase = runtime / "before"
    assert stat.S_IMODE(phase.stat().st_mode) == 0o700
    assert set(path.name for path in phase.iterdir()) == {
        *(f"rgw-step-{index}.json" for index in range(7)),
        "rgw-probe.json",
        "rgw-multipart.json",
        "rgw-cleanup.json",
        "rgw-cleanup-verified.json",
    }
    for path in phase.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1
    probe = json.loads((phase / "rgw-probe.json").read_bytes())
    multipart = json.loads((phase / "rgw-multipart.json").read_bytes())
    cleanup = json.loads((phase / "rgw-cleanup.json").read_bytes())
    verified = json.loads(
        (phase / "rgw-cleanup-verified.json").read_bytes()
    )
    assert probe["schema"] == ACTIONS.rgw_live_adapter.rgw_artifacts.PROBE_SCHEMA
    assert multipart["schema"] == (
        ACTIONS.rgw_live_adapter.rgw_artifacts.MULTIPART_SCHEMA
    )
    assert cleanup["remaining"] == {
        "current_objects": 0,
        "delete_markers": 0,
        "multipart_uploads": 0,
        "versions": 0,
    }
    assert verified["verified"] is True
    evidence = clients.values["before"].evidence
    assert len(evidence.calls) == 7
    assert evidence.page_bounds == [10]


def test_reconcile_accepts_exact_outputs_without_reexecution(
    tmp_path: Path,
) -> None:
    adapter, actions, _, clients = fixture(tmp_path)
    selected = before_supported(actions)
    first = [adapter.execute(action) for action in selected]
    evidence = clients.values["before"].evidence
    calls = list(evidence.calls)
    pages = list(evidence.page_bounds)

    reconciled = [adapter.reconcile(action) for action in selected]

    assert reconciled == first
    assert evidence.calls == calls
    assert evidence.page_bounds == pages


def test_during_fault_and_recovery_steps_use_exact_indices(
    tmp_path: Path,
) -> None:
    adapter, actions, runtime, clients = fixture(tmp_path)
    adapter.clock = lambda: 350
    during = [action for action in actions if action["phase"] == "during"]
    open_action = during[0]
    adapter.execute(open_action)
    step_actions = [
        action
        for action in during
        if action["action"] == "collect-rgw-step"
    ]

    results = [adapter.execute(action) for action in step_actions]

    assert [action["step_index"] for action in step_actions] == list(
        range(11)
    )
    assert all(result["synthetic"] is False for result in results)
    expected = [
        (
            step["operation"],
            step["result"],
        )
        for step in json.loads(
            (
                adapter.schedule_directory
                / "during-rgw-live-config.json"
            ).read_bytes()
        )["steps"]
    ]
    assert clients.values["during"].evidence.calls == expected
    assert len(list((runtime / "during").glob("rgw-step-*.json"))) == 11


@pytest.mark.parametrize(
    "kind",
    ["step", "probe", "multipart", "cleanup", "verification"],
)
def test_reconcile_rejects_tampered_runtime_output(
    tmp_path: Path,
    kind: str,
) -> None:
    adapter, actions, runtime, _ = fixture(tmp_path)
    selected = before_supported(actions)
    open_action = selected[0]
    adapter.execute(open_action)
    if kind == "step":
        action = selected[1]
        adapter.execute(action)
        path = runtime / "before" / "rgw-step-0.json"
        value = json.loads(path.read_bytes())
        value["step_sha256"] = f"sha256:{'0' * 64}"
    elif kind == "probe":
        for prerequisite in selected[1:8]:
            adapter.execute(prerequisite)
        action = selected[8]
        adapter.execute(action)
        path = runtime / "before" / "rgw-probe.json"
        value = json.loads(path.read_bytes())
        value["probe_sha256"] = f"sha256:{'0' * 64}"
    elif kind == "multipart":
        action = selected[9]
        adapter.execute(action)
        path = runtime / "before" / "rgw-multipart.json"
        value = json.loads(path.read_bytes())
        value["capture_sha256"] = f"sha256:{'0' * 64}"
    elif kind == "cleanup":
        action = selected[10]
        adapter.execute(action)
        path = runtime / "before" / "rgw-cleanup.json"
        value = json.loads(path.read_bytes())
        value["remaining"]["current_objects"] = 1
    else:
        adapter.execute(selected[10])
        action = selected[11]
        adapter.execute(action)
        path = runtime / "before" / "rgw-cleanup-verified.json"
        value = json.loads(path.read_bytes())
        value["verified"] = False
    owner_document(path, value)

    with pytest.raises(ACTIONS.PilotRgwActionError):
        adapter.reconcile(action)


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    adapter, actions, runtime, _ = fixture(tmp_path)
    selected = before_supported(actions)
    adapter.execute(selected[0])
    output = runtime / "before" / "rgw-step-0.json"
    owner_document(output, {"unrelated": True})
    inode = output.stat().st_ino

    with pytest.raises(
        ACTIONS.PilotRgwActionError,
        match="already exists",
    ):
        adapter.execute(selected[1])

    assert output.stat().st_ino == inode
    assert json.loads(output.read_bytes()) == {"unrelated": True}


@pytest.mark.parametrize("name", ["apply-wrong-key", "complete-phase"])
def test_unsupported_actions_fail_without_output(
    tmp_path: Path,
    name: str,
) -> None:
    adapter, actions, _, _ = fixture(tmp_path)
    action = next(item for item in actions if item["action"] == name)
    output = Path(action["output_file"])

    with pytest.raises(
        ACTIONS.PilotRgwActionError,
        match="unsupported",
    ):
        adapter.execute(action)

    assert output.exists() is False


def test_action_binding_drift_is_refused(tmp_path: Path) -> None:
    adapter, actions, _, _ = fixture(tmp_path)
    changed = dict(before_supported(actions)[0])
    changed["output_file"] = str(
        Path(adapter.schedule["runtime_directory"]) / "other"
    )

    with pytest.raises(ACTIONS.PilotRgwActionError):
        adapter.execute(changed)


def test_blocked_readiness_is_refused_before_client_creation(
    tmp_path: Path,
) -> None:
    request_path, schedule_output, _, request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    readiness = Path(request["readiness"]["file"])
    value = json.loads(readiness.read_bytes())
    value["status"] = "blocked"
    owner_document(readiness, value)
    calls = 0

    def factory(config: dict[str, Any]) -> ACTIONS.RgwRuntimeClients:
        nonlocal calls
        calls += 1
        raise AssertionError(config)

    with pytest.raises(ACTIONS.PilotRgwActionError):
        ACTIONS.PilotRgwActionAdapter.load(
            schedule_output,
            readiness,
            client_factory=factory,
        )

    assert calls == 0


def test_runtime_outputs_retain_no_operational_identity(
    tmp_path: Path,
) -> None:
    adapter, actions, runtime, _ = fixture(tmp_path)
    for action in before_supported(actions):
        adapter.execute(action)
    retained = " ".join(
        path.read_text(encoding="utf-8")
        for path in (runtime / "before").iterdir()
    )
    for forbidden in (
        "rgw.stage6.test",
        "coffer-registry-stage6",
        "coffer-evidence",
        "version-1",
        "marker-1",
        "upload-1",
        "access_key",
        "secret_key",
        "kms_key",
    ):
        assert forbidden not in retained


def test_source_only_cli_has_no_execution_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ACTIONS.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == ACTIONS.SOURCE_RESULT_SCHEMA

    assert ACTIONS.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "pilot-rgw-actions-refused\n"
