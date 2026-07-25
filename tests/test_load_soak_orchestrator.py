from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "load-soak" / "orchestrator.py"
TOPOLOGY_PATH = ROOT / "poc" / "load-soak" / "topology.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ORCHESTRATOR = load_module(
    "coffer_load_soak_orchestrator_tests",
    MODULE_PATH,
)
TOPOLOGY = ORCHESTRATOR.plan_contract.state_machine.load_topology(
    TOPOLOGY_PATH
)


def request() -> dict:
    return {
        "bindings": {
            "architectures": ["aarch64", "x86_64"],
            "ceph_revision": "b" * 40,
            "ceph_version": "v20.2.3",
            "client_versions_hash": f"sha256:{'1' * 64}",
            "configuration_hash": f"sha256:{'2' * 64}",
            "distribution_revision": "a" * 40,
            "distribution_version": "v3.1.2",
            "driver_revision": "c" * 40,
            "image_set_hash": f"sha256:{'3' * 64}",
            "readiness_evidence_hash": f"sha256:{'4' * 64}",
            "readiness_status": "qualified",
        },
        "schema": "coffer.load-execution-plan-request/v1",
        "topology_sha256": ORCHESTRATOR.plan_contract._hash(TOPOLOGY),
    }


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    plan_path = tmp_path / "plan.json"
    envelope = ORCHESTRATOR.plan_contract.compile_plan(
        request(),
        topology=TOPOLOGY,
    )
    plan_payload = canonical(envelope)
    owner_file(plan_path, plan_payload)
    state_path = work / "state.json"
    output_path = work / "result.json"
    lock_path = work / "lock"
    invocation = {
        "adapter": "fixture",
        "lock_file": str(lock_path),
        "output_file": str(output_path),
        "plan_file": str(plan_path),
        "plan_file_sha256": (
            "sha256:" + hashlib.sha256(plan_payload).hexdigest()
        ),
        "schema": "coffer.load-orchestrator-invocation/v1",
        "state_file": str(state_path),
        "topology_file": str(TOPOLOGY_PATH),
    }
    invocation_path = tmp_path / "invocation.json"
    owner_file(invocation_path, canonical(invocation))
    return invocation, invocation_path, state_path, output_path, lock_path


def test_schedule_exactly_follows_client_lifecycle_and_fault_order() -> None:
    envelope = ORCHESTRATOR.plan_contract.compile_plan(
        request(),
        topology=TOPOLOGY,
    )
    schedule = ORCHESTRATOR.build_schedule(envelope["plan"])

    assert len(schedule) == 29
    assert [step.order for step in schedule] == list(range(1, 30))
    assert [step.name for step in schedule[:6]] == TOPOLOGY["clients"]
    assert schedule[6].name == "smoke"
    assert [step.name for step in schedule[7:14]] == [
        f"clients-{clients}" for clients in TOPOLOGY["ramp_clients"]
    ]
    assert schedule[14].name == "qualification"
    assert [step.name for step in schedule[15:25]] == list(
        TOPOLOGY["faults"]
    )
    assert schedule[25].name == "soak"
    assert [step.name for step in schedule[26:]] == [
        "before",
        "during",
        "after",
    ]


def test_checkpoint_resume_and_terminal_rerun_are_deterministic(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, lock_path = fixture(tmp_path)

    assert (
        ORCHESTRATOR.execute_invocation(invocation_path, max_steps=5) is False
    )
    state = json.loads(state_path.read_bytes())
    assert len(state["history"]) == 5
    assert state["complete"] is False
    assert not output_path.exists()
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600

    assert ORCHESTRATOR.execute_invocation(invocation_path) is True
    completed_state = json.loads(state_path.read_bytes())
    result = json.loads(output_path.read_bytes())
    first_output = output_path.read_bytes()
    assert completed_state["complete"] is True
    assert len(completed_state["history"]) == 29
    assert result["schema"] == "coffer.load-orchestrator-result/v1"
    assert result["steps_completed"] == 29
    assert result["synthetic"] is True
    assert output_path.read_bytes() == canonical(result)
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600

    assert ORCHESTRATOR.execute_invocation(invocation_path) is True
    assert output_path.read_bytes() == first_output


def test_failure_preserves_last_checkpoint_and_can_resume(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _ = fixture(tmp_path)
    executor = ORCHESTRATOR.FixtureExecutor(fail_step=4)

    with pytest.raises(
        ORCHESTRATOR.CommandError,
        match="execution-unavailable",
    ):
        ORCHESTRATOR.execute_invocation(
            invocation_path,
            executor=executor,
        )

    state = json.loads(state_path.read_bytes())
    assert len(state["history"]) == 3
    assert not output_path.exists()
    assert ORCHESTRATOR.execute_invocation(invocation_path) is True
    assert json.loads(output_path.read_bytes())["steps_completed"] == 29


def test_over_budget_and_non_fixture_executor_fail_closed(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _ = fixture(tmp_path)
    executor = ORCHESTRATOR.FixtureExecutor(over_budget_step=7)
    with pytest.raises(
        ORCHESTRATOR.CommandError,
        match="execution-unavailable",
    ):
        ORCHESTRATOR.execute_invocation(
            invocation_path,
            executor=executor,
        )
    assert len(json.loads(state_path.read_bytes())["history"]) == 6
    assert not output_path.exists()

    class Lookalike:
        def execute(self, step):
            return ORCHESTRATOR.FixtureExecutor().execute(step)

    _, second, second_state, second_output, _ = fixture(tmp_path / "second")
    with pytest.raises(
        ORCHESTRATOR.CommandError,
        match="execution-unavailable",
    ):
        ORCHESTRATOR.execute_invocation(second, executor=Lookalike())
    assert not second_state.exists()
    assert not second_output.exists()


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("invocation-mode", "local-file-unavailable"),
        ("plan-digest", "contract-refused"),
        ("plan-mode", "local-file-unavailable"),
        ("output-symlink", "output-unavailable"),
        ("path-alias", "contract-refused"),
        ("adapter", "contract-refused"),
    ],
)
def test_invocation_and_file_drift_fail_before_execution(
    tmp_path: Path,
    mutation: str,
    failure: str,
) -> None:
    invocation, invocation_path, state_path, output_path, _ = fixture(tmp_path)
    if mutation == "invocation-mode":
        invocation_path.chmod(0o640)
    elif mutation == "plan-digest":
        invocation["plan_file_sha256"] = f"sha256:{'0' * 64}"
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "plan-mode":
        Path(invocation["plan_file"]).chmod(0o640)
    elif mutation == "output-symlink":
        target = output_path.parent / "target"
        owner_file(target, b"preserved\n")
        output_path.symlink_to(target)
    elif mutation == "path-alias":
        invocation["output_file"] = invocation["state_file"]
        owner_file(invocation_path, canonical(invocation))
    else:
        invocation["adapter"] = "live"
        owner_file(invocation_path, canonical(invocation))

    with pytest.raises(ORCHESTRATOR.CommandError, match=failure):
        ORCHESTRATOR.execute_invocation(invocation_path)
    assert not state_path.exists()


def test_state_and_existing_output_tampering_are_refused(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _ = fixture(tmp_path)
    assert (
        ORCHESTRATOR.execute_invocation(invocation_path, max_steps=2) is False
    )
    state = json.loads(state_path.read_bytes())
    state["history"][0]["name"] = "changed"
    owner_file(state_path, canonical(state))
    with pytest.raises(ORCHESTRATOR.CommandError, match="contract-refused"):
        ORCHESTRATOR.execute_invocation(invocation_path)

    _, second, second_state, second_output, _ = fixture(tmp_path / "second")
    owner_file(second_output, canonical({"stale": True}))
    with pytest.raises(ORCHESTRATOR.CommandError, match="contract-refused"):
        ORCHESTRATOR.execute_invocation(second)
    assert not second_state.exists()


def test_nonblocking_lock_refuses_concurrent_runner(tmp_path: Path) -> None:
    _, invocation_path, state_path, output_path, lock_path = fixture(tmp_path)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(
            ORCHESTRATOR.CommandError,
            match="lock-unavailable",
        ):
            ORCHESTRATOR.execute_invocation(invocation_path)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert not state_path.exists()
    assert not output_path.exists()


def test_cli_success_and_fixed_argument_failure(tmp_path: Path) -> None:
    _, invocation_path, _, output_path, _ = fixture(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert (
        ORCHESTRATOR.run(
            ["--invocation", str(invocation_path)],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )
    assert stdout.getvalue() == "load orchestrator completed\n"
    assert stderr.getvalue() == ""
    assert output_path.exists()

    stderr = io.StringIO()
    assert (
        ORCHESTRATOR.run([], stdout=io.StringIO(), stderr=stderr) == 2
    )
    assert stderr.getvalue() == (
        "load orchestrator failed: invalid-arguments\n"
    )


def test_invalid_checkpoint_limit_is_refused(tmp_path: Path) -> None:
    _, invocation_path, state_path, output_path, _ = fixture(tmp_path)
    with pytest.raises(ORCHESTRATOR.CommandError, match="contract-refused"):
        ORCHESTRATOR.execute_invocation(invocation_path, max_steps=-1)
    assert not state_path.exists()
    assert not output_path.exists()


def test_orchestrator_has_no_network_or_subprocess_import() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "import http",
        "import requests",
        "import socket",
        "import subprocess",
        "import urllib",
    ):
        assert forbidden not in source
