from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "load-soak" / "fault" / "run.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


FAULT = load_module("coffer_load_fault_run_tests", MODULE_PATH)
TOPOLOGY = FAULT.orchestrator.plan_contract.state_machine.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


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
        "topology_sha256": FAULT.orchestrator.plan_contract._hash(TOPOLOGY),
    }


def fake_action_binary(
    path: Path,
    *,
    fail_action: str | None = None,
) -> None:
    source = f"""#!{sys.executable}
import json
from pathlib import Path
import sys

arguments = sys.argv[1:]
if len(arguments) != 2 or arguments[0] != "--invocation":
    raise SystemExit(2)
invocation = json.loads(Path(arguments[1]).read_bytes())
action = invocation["action"]
if action == {fail_action!r}:
    print("fixed action failure", file=sys.stderr)
    raise SystemExit(1)
result = {{
    "action": action,
    "duration_milliseconds": 1,
    "fault": invocation["fault"],
    "observed_seconds": (
        invocation["window_seconds"] if action == "observe" else 0
    ),
    "schema": "coffer.load-fault-action-result/v1",
    "status": "passed",
    "target_evidence_sha256": invocation["target_evidence_sha256"],
}}
output = Path(invocation["output_file"])
output.write_bytes(
    (json.dumps(result, separators=(",", ":"), sort_keys=True) + "\\n").encode()
)
output.chmod(0o600)
print("fault action completed")
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)


class AcceleratedClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class Crash(BaseException):
    pass


class CrashingClock(AcceleratedClock):
    def sleep(self, seconds: float) -> None:
        raise Crash


class DeadlineClock(AcceleratedClock):
    def __init__(self):
        super().__init__()
        self.window_finished = False

    def monotonic(self) -> float:
        if self.window_finished:
            self.value += 40
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds
        self.window_finished = True


def fixture(
    tmp_path: Path,
    *,
    fail_action: str | None = None,
) -> tuple[dict, Path, Path, Path, Path, Path]:
    tmp_path.chmod(0o700)
    session = tmp_path / "session"
    session.mkdir(mode=0o700)
    work = session / "work"
    work.mkdir(mode=0o700)
    binary = tmp_path / "fault-action"
    fake_action_binary(binary, fail_action=fail_action)
    binary_sha256 = FAULT.profile._binary_hash(binary)

    envelope = FAULT.orchestrator.plan_contract.compile_plan(
        request(),
        topology=TOPOLOGY,
    )
    plan_payload = canonical(envelope)
    plan_path = tmp_path / "plan.json"
    owner_file(plan_path, plan_payload)

    selectors = ["container:coffer_api:controller1"]
    target = {
        "adapter": "kolla-container",
        "fault": "api-replica",
        "ownership_sha256": f"sha256:{'5' * 64}",
        "schema": "coffer.load-fault-target/v1",
        "selectors": selectors,
        "target_sha256": FAULT._hash(
            {"adapter": "kolla-container", "selectors": selectors}
        ),
        "topology_sha256": envelope["plan"]["topology_sha256"],
    }
    target_payload = canonical(target)
    target_path = tmp_path / "target.json"
    owner_file(target_path, target_payload)

    invocation = {
        "action_binary": str(binary),
        "action_binary_sha256": binary_sha256,
        "adapter_contract_sha256": f"sha256:{'7' * 64}",
        "execution_source": "fixture",
        "lock_file": str(session / "lock"),
        "output_file": str(session / "result.json"),
        "plan_file": str(plan_path),
        "plan_file_sha256": digest(plan_payload),
        "schema": "coffer.load-fault-invocation/v1",
        "state_file": str(session / "state.json"),
        "step": {"fault": "api-replica", "kind": "fault", "order": 16},
        "target_class": "disposable-stage6-pilot",
        "target_evidence_file": str(target_path),
        "target_evidence_sha256": digest(target_payload),
        "work_root": str(work),
    }
    invocation_path = tmp_path / "invocation.json"
    owner_file(invocation_path, canonical(invocation))
    return (
        invocation,
        invocation_path,
        session / "state.json",
        session / "result.json",
        session / "lock",
        work,
    )


def test_serial_fault_fixture_completes_full_window_and_is_idempotent(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, lock_path, work = fixture(
        tmp_path
    )

    assert FAULT.execute_invocation(
        invocation_path,
        clock=AcceleratedClock(),
    )
    state = json.loads(state_path.read_bytes())
    result_payload = output_path.read_bytes()
    result = json.loads(result_payload)
    assert state["phase"] == "complete"
    assert state["complete"] is True
    assert [entry["action"] for entry in state["history"]] == [
        "preflight",
        "inject",
        "observe",
        "recover",
        "verify",
    ]
    assert result_payload == canonical(result)
    assert result["schema"] == "coffer.load-fault-result/v1"
    assert result["fault"] == "api-replica"
    assert result["window_seconds"] == 60
    assert result["recovery_seconds"] == 30
    assert result["actions_completed"] == 5
    assert result["unexpected_errors"] == 0
    assert result["synthetic"] is True
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    assert not any(path.name.startswith(".fault-") for path in work.iterdir())
    serialized = json.dumps(result, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "https://" not in serialized

    assert FAULT.execute_invocation(
        invocation_path,
        clock=AcceleratedClock(),
    )
    assert output_path.read_bytes() == result_payload
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert (
        FAULT.run(
            ["--invocation", str(invocation_path)],
            stdout=stdout,
            stderr=stderr,
        )
        == 3
    )
    assert stdout.getvalue() == "load fault fixture completed\n"
    assert stderr.getvalue() == ""


def test_observation_failure_recovers_but_never_writes_success(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _, work = fixture(
        tmp_path,
        fail_action="observe",
    )

    with pytest.raises(FAULT.CommandError, match="execution-unavailable"):
        FAULT.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    state = json.loads(state_path.read_bytes())
    assert state["phase"] == "failed-recovered"
    assert state["failure_phase"] == "observe"
    assert state["complete"] is False
    assert [entry["action"] for entry in state["history"]] == [
        "preflight",
        "inject",
        "recover",
        "verify",
    ]
    assert not output_path.exists()
    assert not any(path.name.startswith(".fault-") for path in work.iterdir())

    with pytest.raises(FAULT.CommandError, match="execution-unavailable"):
        FAULT.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    assert json.loads(state_path.read_bytes()) == state


def test_lost_process_after_inject_is_recovered_before_resume(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _, work = fixture(tmp_path)

    with pytest.raises(Crash):
        FAULT.execute_invocation(
            invocation_path,
            clock=CrashingClock(),
        )
    injected = json.loads(state_path.read_bytes())
    assert injected["phase"] == "injected"
    assert injected["failure_phase"] is None
    assert not output_path.exists()
    assert not any(path.name.startswith(".fault-") for path in work.iterdir())

    with pytest.raises(FAULT.CommandError, match="execution-unavailable"):
        FAULT.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    recovered = json.loads(state_path.read_bytes())
    assert recovered["phase"] == "failed-recovered"
    assert recovered["failure_phase"] == "interrupted"
    assert [entry["action"] for entry in recovered["history"]] == [
        "preflight",
        "inject",
        "recover",
        "verify",
    ]
    assert not output_path.exists()


def test_inject_ambiguity_runs_recovery_and_never_completes(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _, work = fixture(
        tmp_path,
        fail_action="inject",
    )

    with pytest.raises(FAULT.CommandError, match="execution-unavailable"):
        FAULT.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    state = json.loads(state_path.read_bytes())
    assert state["phase"] == "failed-recovered"
    assert state["failure_phase"] == "inject"
    assert [entry["action"] for entry in state["history"]] == [
        "preflight",
        "recover",
        "verify",
    ]
    assert not output_path.exists()
    assert not any(path.name.startswith(".fault-") for path in work.iterdir())


def test_recovery_deadline_failure_is_terminal_without_success(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _, work = fixture(tmp_path)

    with pytest.raises(FAULT.CommandError, match="execution-unavailable"):
        FAULT.execute_invocation(
            invocation_path,
            clock=DeadlineClock(),
        )
    state = json.loads(state_path.read_bytes())
    assert state["phase"] == "recovery-deadline-failed"
    assert state["failure_phase"] == "verify"
    assert state["complete"] is False
    assert not output_path.exists()
    assert not any(path.name.startswith(".fault-") for path in work.iterdir())


def test_fault_checkpoint_hash_chain_rejects_tampering(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _, work = fixture(
        tmp_path,
        fail_action="observe",
    )
    with pytest.raises(FAULT.CommandError):
        FAULT.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    state = json.loads(state_path.read_bytes())
    state["history"][0]["duration_milliseconds"] += 1
    owner_file(state_path, canonical(state))

    with pytest.raises(FAULT.CommandError, match="contract-refused"):
        FAULT.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    assert not output_path.exists()
    assert not any(path.name.startswith(".fault-") for path in work.iterdir())


@pytest.mark.parametrize(
    "mutation",
    [
        "mode",
        "plan-hash",
        "binary-hash",
        "target-mode",
        "target-hash",
        "adapter",
        "step",
        "source",
        "alias",
    ],
)
def test_fault_preflight_drift_fails_before_state(
    tmp_path: Path,
    mutation: str,
) -> None:
    (
        invocation,
        invocation_path,
        state_path,
        output_path,
        _,
        work,
    ) = fixture(tmp_path)
    if mutation == "mode":
        invocation_path.chmod(0o640)
    elif mutation == "plan-hash":
        invocation["plan_file_sha256"] = f"sha256:{'0' * 64}"
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "binary-hash":
        invocation["action_binary_sha256"] = f"sha256:{'0' * 64}"
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "target-mode":
        Path(invocation["target_evidence_file"]).chmod(0o640)
    elif mutation == "target-hash":
        invocation["target_evidence_sha256"] = f"sha256:{'0' * 64}"
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "adapter":
        target_path = Path(invocation["target_evidence_file"])
        target = json.loads(target_path.read_bytes())
        target["adapter"] = "shell"
        payload = canonical(target)
        owner_file(target_path, payload)
        invocation["target_evidence_sha256"] = digest(payload)
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "step":
        invocation["step"]["order"] = 17
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "source":
        invocation["execution_source"] = "live"
        owner_file(invocation_path, canonical(invocation))
    else:
        invocation["output_file"] = invocation["state_file"]
        owner_file(invocation_path, canonical(invocation))

    with pytest.raises(FAULT.CommandError, match="contract-refused"):
        FAULT.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    assert not state_path.exists()
    assert not output_path.exists()
    assert not any(path.name.startswith(".fault-") for path in work.iterdir())


def test_fault_cli_argument_failure_is_fixed() -> None:
    for arguments in ([], ["--unknown"], ["--invocation", "a", "extra"]):
        stdout = io.StringIO()
        stderr = io.StringIO()
        assert FAULT.run(arguments, stdout=stdout, stderr=stderr) == 2
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == "load fault failed: invalid-arguments\n"
