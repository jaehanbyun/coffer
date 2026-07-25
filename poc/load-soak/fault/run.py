from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Mapping, Protocol, Sequence


DIRECTORY = Path(__file__).resolve().parent
LOAD_DIRECTORY = DIRECTORY.parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


orchestrator = _module(
    "coffer_load_fault_orchestrator",
    LOAD_DIRECTORY / "orchestrator.py",
)
profile = _module(
    "coffer_load_fault_profile",
    LOAD_DIRECTORY / "profile" / "run.py",
)

INVOCATION_SCHEMA = "coffer.load-fault-invocation/v1"
STATE_SCHEMA = "coffer.load-fault-state/v1"
RESULT_SCHEMA = "coffer.load-fault-result/v1"
TARGET_SCHEMA = "coffer.load-fault-target/v1"
ACTION_SCHEMA = "coffer.load-fault-action/v1"
ACTION_RESULT_SCHEMA = "coffer.load-fault-action-result/v1"
TARGET_CLASS = "disposable-stage6-pilot"
SHA256 = orchestrator.plan_contract.SHA256
ACTIONS = ("preflight", "inject", "observe", "recover", "verify")
FAILURE_PHASES = {
    "inject",
    "interrupted",
    "observe",
    "recover",
    "verify",
}
FAULT_ADAPTERS = {
    "api-replica": "kolla-container",
    "edge-replica": "kolla-container",
    "registry-mid-upload": "kolla-container",
    "haproxy-vip-owner": "kolla-keepalived",
    "galera-writer": "kolla-mariadb",
    "rgw-daemon": "ceph-orchestrator",
    "rgw-ingress": "ceph-orchestrator",
    "barbican-kms": "kolla-barbican",
    "reconciler-claim": "kolla-container",
    "rolling-registry-edge": "kolla-serial",
}
CommandError = orchestrator.CommandError


class FaultError(RuntimeError):
    pass


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class ActionTask:
    binary: Path
    expected_stdout: bytes
    invocation_file: Path
    output_file: Path


class ActionRunner(Protocol):
    def run(
        self,
        task: ActionTask,
        *,
        timeout_seconds: int,
        work_root: Path,
    ) -> None: ...


class SubprocessActionRunner:
    def __init__(self) -> None:
        self._runner = profile.SubprocessBatchRunner()

    def run(
        self,
        task: ActionTask,
        *,
        timeout_seconds: int,
        work_root: Path,
    ) -> None:
        self._runner.run(
            [task],
            timeout_seconds=timeout_seconds,
            work_root=work_root,
        )


def _exact(value: object, keys: set[str], category: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise FaultError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)[:-1]).hexdigest()


def _file_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _target(
    payload: bytes,
    *,
    expected_sha256: str,
    fault: str,
    topology_sha256: str,
) -> dict[str, Any]:
    if _file_hash(payload) != expected_sha256:
        raise FaultError("fault target evidence changed")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FaultError("fault target evidence is invalid") from error
    target = _exact(
        value,
        {
            "adapter",
            "fault",
            "ownership_sha256",
            "schema",
            "selectors",
            "target_sha256",
            "topology_sha256",
        },
        "fault target",
    )
    if (
        target["schema"] != TARGET_SCHEMA
        or target["fault"] != fault
        or target["adapter"] != FAULT_ADAPTERS[fault]
        or target["topology_sha256"] != topology_sha256
        or not isinstance(target["selectors"], list)
        or not 1 <= len(target["selectors"]) <= 16
        or any(
            not isinstance(selector, str)
            or not selector
            or len(selector) > 256
            or any(ord(character) < 0x21 for character in selector)
            or "://" in selector
            for selector in target["selectors"]
        )
        or target["target_sha256"]
        != _hash(
            {
                "adapter": target["adapter"],
                "selectors": target["selectors"],
            }
        )
    ):
        raise FaultError("fault target binding changed")
    for key in ("ownership_sha256", "target_sha256", "topology_sha256"):
        if (
            not isinstance(target[key], str)
            or SHA256.fullmatch(target[key]) is None
        ):
            raise FaultError("fault target hash is invalid")
    return dict(target)


def _new_state(
    *,
    binding_sha256: str,
    execution_source: str,
    fault: str,
    plan_sha256: str,
    target_evidence_sha256: str,
) -> dict[str, Any]:
    return {
        "complete": False,
        "execution_source": execution_source,
        "failure_phase": None,
        "fault": fault,
        "history": [],
        "last_entry_sha256": binding_sha256,
        "phase": "new",
        "plan_sha256": plan_sha256,
        "fault_binding_sha256": binding_sha256,
        "schema": STATE_SCHEMA,
        "synthetic": execution_source == "fixture",
        "target_evidence_sha256": target_evidence_sha256,
    }


def _allowed_history(actions: list[str]) -> bool:
    if not actions:
        return True
    if actions[0] != "preflight" or len(actions) != len(set(actions)):
        return False
    positions = {action: index for index, action in enumerate(ACTIONS)}
    if any(action not in positions for action in actions):
        return False
    if any(
        positions[left] >= positions[right]
        for left, right in zip(actions, actions[1:])
    ):
        return False
    if "observe" in actions and "inject" not in actions:
        return False
    if "verify" in actions and "recover" not in actions:
        return False
    return True


def _validate_state(
    value: object,
    *,
    binding_sha256: str,
    execution_source: str,
    fault: str,
    plan_sha256: str,
    recovery_seconds: int,
    target_evidence_sha256: str,
    window_seconds: int,
) -> dict[str, Any]:
    state = dict(
        _exact(
            value,
            {
                "complete",
                "execution_source",
                "failure_phase",
                "fault",
                "history",
                "last_entry_sha256",
                "phase",
                "plan_sha256",
                "fault_binding_sha256",
                "schema",
                "synthetic",
                "target_evidence_sha256",
            },
            "fault state",
        )
    )
    if not isinstance(state["history"], list):
        raise FaultError("fault history is invalid")
    actions: list[str] = []
    previous_sha256 = binding_sha256
    recovery_milliseconds = 0
    observed_seconds = 0
    for sequence, entry_value in enumerate(state["history"], 1):
        entry = _exact(
            entry_value,
            {
                "action",
                "duration_milliseconds",
                "entry_sha256",
                "observed_seconds",
                "previous_sha256",
                "result_sha256",
                "sequence",
            },
            "fault history entry",
        )
        unsigned = {
            key: entry[key] for key in entry if key != "entry_sha256"
        }
        if (
            entry["sequence"] != sequence
            or entry["previous_sha256"] != previous_sha256
            or entry["entry_sha256"] != _hash(unsigned)
            or entry["action"] not in ACTIONS
            or not isinstance(entry["duration_milliseconds"], int)
            or isinstance(entry["duration_milliseconds"], bool)
            or entry["duration_milliseconds"] < 0
            or not isinstance(entry["observed_seconds"], int)
            or isinstance(entry["observed_seconds"], bool)
            or entry["observed_seconds"] < 0
            or not isinstance(entry["result_sha256"], str)
            or SHA256.fullmatch(entry["result_sha256"]) is None
        ):
            raise FaultError("fault history entry is invalid")
        if entry["action"] == "observe":
            observed_seconds += entry["observed_seconds"]
        elif entry["observed_seconds"] != 0:
            raise FaultError("fault action retained unexpected duration")
        if entry["action"] in ("recover", "verify"):
            recovery_milliseconds += entry["duration_milliseconds"]
        actions.append(entry["action"])
        previous_sha256 = entry["entry_sha256"]
    failure_phase = state["failure_phase"]
    if failure_phase is not None and failure_phase not in FAILURE_PHASES:
        raise FaultError("fault failure phase is invalid")
    if not _allowed_history(actions):
        raise FaultError("fault action history is invalid")
    expected_phase = actions[-1] + "ed" if actions else "new"
    if expected_phase == "recovered":
        pass
    elif expected_phase == "verifyed":
        expected_phase = "verified"
    elif expected_phase == "observeed":
        expected_phase = "observed"
    elif expected_phase == "injected":
        pass
    elif expected_phase == "preflighted":
        pass
    if state["phase"] in (
        "complete",
        "failed-recovered",
        "recovery-deadline-failed",
    ):
        phase_matches = actions and actions[-1] == "verify"
    elif (
        state["phase"] == "injected"
        and failure_phase == "inject"
        and "inject" not in actions
    ):
        phase_matches = bool(actions and actions[-1] == "preflight")
    else:
        phase_matches = state["phase"] == expected_phase
    if (
        state["schema"] != STATE_SCHEMA
        or state["fault_binding_sha256"] != binding_sha256
        or state["plan_sha256"] != plan_sha256
        or state["execution_source"] != execution_source
        or state["synthetic"] != (execution_source == "fixture")
        or state["fault"] != fault
        or state["target_evidence_sha256"] != target_evidence_sha256
        or state["last_entry_sha256"] != previous_sha256
        or not phase_matches
        or not isinstance(state["complete"], bool)
        or state["complete"] != (state["phase"] == "complete")
        or (state["complete"] and failure_phase is not None)
        or (
            state["phase"] == "failed-recovered"
            and failure_phase is None
        )
        or (
            state["phase"] == "recovery-deadline-failed"
            and failure_phase is None
        )
        or (state["phase"] == "complete" and actions != list(ACTIONS))
        or (
            state["phase"]
            in (
                "complete",
                "failed-recovered",
                "recovery-deadline-failed",
            )
            and observed_seconds not in (0, window_seconds)
        )
        or recovery_milliseconds > recovery_seconds * 1000
    ):
        raise FaultError("fault state is invalid")
    return state


def _append_action(
    state: dict[str, Any],
    *,
    action: str,
    result: Mapping[str, Any],
) -> None:
    unsigned = {
        "action": action,
        "duration_milliseconds": result["duration_milliseconds"],
        "observed_seconds": result["observed_seconds"],
        "previous_sha256": state["last_entry_sha256"],
        "result_sha256": _hash(result),
        "sequence": len(state["history"]) + 1,
    }
    entry = {**unsigned, "entry_sha256": _hash(unsigned)}
    state["history"].append(entry)
    state["last_entry_sha256"] = entry["entry_sha256"]
    state["phase"] = {
        "preflight": "preflighted",
        "inject": "injected",
        "observe": "observed",
        "recover": "recovered",
        "verify": "verified",
    }[action]


def _action_result(
    payload: bytes,
    *,
    action: str,
    fault: str,
    target_evidence_sha256: str,
    window_seconds: int,
) -> Mapping[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FaultError("fault action result is invalid") from error
    result = _exact(
        value,
        {
            "action",
            "duration_milliseconds",
            "fault",
            "observed_seconds",
            "schema",
            "status",
            "target_evidence_sha256",
        },
        "fault action result",
    )
    expected_observed = window_seconds if action == "observe" else 0
    if (
        result["schema"] != ACTION_RESULT_SCHEMA
        or result["action"] != action
        or result["fault"] != fault
        or result["status"] != "passed"
        or result["target_evidence_sha256"] != target_evidence_sha256
        or not isinstance(result["duration_milliseconds"], int)
        or isinstance(result["duration_milliseconds"], bool)
        or result["duration_milliseconds"] < 0
        or result["observed_seconds"] != expected_observed
    ):
        raise FaultError("fault action result changed")
    return result


def _run_action(
    *,
    action: str,
    action_binary: Path,
    adapter: str,
    execution_source: str,
    fault: str,
    recovery_seconds: int,
    runner: ActionRunner,
    target_file: Path,
    target_evidence_sha256: str,
    window_seconds: int,
    work_root: Path,
) -> Mapping[str, Any]:
    invocation_file = work_root / f".fault-{action}.invocation.json"
    output_file = work_root / f".fault-{action}.result.json"
    action_invocation = {
        "action": action,
        "adapter": adapter,
        "execution_source": execution_source,
        "fault": fault,
        "output_file": str(output_file),
        "recovery_seconds": recovery_seconds,
        "schema": ACTION_SCHEMA,
        "target_evidence_file": str(target_file),
        "target_evidence_sha256": target_evidence_sha256,
        "window_seconds": window_seconds,
    }
    try:
        orchestrator._atomic_json(invocation_file, action_invocation)
        runner.run(
            ActionTask(
                binary=action_binary,
                expected_stdout=b"fault action completed\n",
                invocation_file=invocation_file,
                output_file=output_file,
            ),
            timeout_seconds=(
                recovery_seconds
                if action in ("recover", "verify")
                else min(window_seconds + 60, 10 * 60)
            ),
            work_root=work_root,
        )
        payload = orchestrator._read_owner_file(output_file)
        if payload is None:
            raise FaultError("fault action result disappeared")
        return _action_result(
            payload,
            action=action,
            fault=fault,
            target_evidence_sha256=target_evidence_sha256,
            window_seconds=window_seconds,
        )
    except (
        OSError,
        orchestrator.CommandError,
        profile.ProfileError,
        KeyboardInterrupt,
        FaultError,
    ) as error:
        raise FaultError("fault action failed") from error
    finally:
        try:
            invocation_file.unlink(missing_ok=True)
            output_file.unlink(missing_ok=True)
        except OSError as error:
            raise FaultError("fault action cleanup failed") from error
        if any(path.name.startswith(".fault-") for path in work_root.iterdir()):
            raise FaultError("fault action residue remains")


def _binding(
    *,
    action_binary_sha256: str,
    adapter_contract_sha256: str,
    execution_source: str,
    fault: str,
    order: int,
    plan_sha256: str,
    target_evidence_sha256: str,
) -> str:
    return _hash(
        {
            "action_binary_sha256": action_binary_sha256,
            "adapter_contract_sha256": adapter_contract_sha256,
            "execution_source": execution_source,
            "fault": fault,
            "order": order,
            "plan_sha256": plan_sha256,
            "target_evidence_sha256": target_evidence_sha256,
        }
    )


def _public_result(
    state: Mapping[str, Any],
    *,
    recovery_seconds: int,
    window_seconds: int,
) -> dict[str, Any]:
    if state["phase"] != "complete" or state["complete"] is not True:
        raise FaultError("fault state is incomplete")
    result = {
        "actions_completed": len(state["history"]),
        "execution_source": state["execution_source"],
        "fault": state["fault"],
        "history_sha256": _hash(state["history"]),
        "plan_sha256": state["plan_sha256"],
        "fault_binding_sha256": state["fault_binding_sha256"],
        "recovery_seconds": recovery_seconds,
        "schema": RESULT_SCHEMA,
        "synthetic": state["synthetic"],
        "target_evidence_sha256": state["target_evidence_sha256"],
        "unexpected_errors": 0,
        "window_seconds": window_seconds,
    }
    orchestrator.plan_contract.state_machine.validate_retained_evidence(result)
    return result


def _save(
    state_path: Path,
    state: Mapping[str, Any],
) -> None:
    orchestrator._atomic_json(state_path, state)


def _finalize(
    state: dict[str, Any],
    *,
    binding_sha256: str,
    execution_source: str,
    fault: str,
    output_path: Path,
    plan_sha256: str,
    recovery_seconds: int,
    state_path: Path,
    target_evidence_sha256: str,
    window_seconds: int,
) -> None:
    if state["phase"] not in ("verified", "complete"):
        raise FaultError("fault cannot be finalized")
    state["phase"] = "complete"
    state["complete"] = True
    state = _validate_state(
        state,
        binding_sha256=binding_sha256,
        execution_source=execution_source,
        fault=fault,
        plan_sha256=plan_sha256,
        recovery_seconds=recovery_seconds,
        target_evidence_sha256=target_evidence_sha256,
        window_seconds=window_seconds,
    )
    _save(state_path, state)
    orchestrator._atomic_json(
        output_path,
        _public_result(
            state,
            recovery_seconds=recovery_seconds,
            window_seconds=window_seconds,
        ),
        output=True,
    )


def _recover_and_verify(
    state: dict[str, Any],
    *,
    action_binary: Path,
    adapter: str,
    binding_sha256: str,
    execution_source: str,
    fault: str,
    plan_sha256: str,
    recovery_seconds: int,
    runner: ActionRunner,
    state_path: Path,
    target_file: Path,
    target_evidence_sha256: str,
    window_seconds: int,
    work_root: Path,
) -> None:
    recovery_started = time.monotonic()
    if state["phase"] in ("injected", "observed"):
        result = _run_action(
            action="recover",
            action_binary=action_binary,
            adapter=adapter,
            execution_source=execution_source,
            fault=fault,
            recovery_seconds=recovery_seconds,
            runner=runner,
            target_file=target_file,
            target_evidence_sha256=target_evidence_sha256,
            window_seconds=window_seconds,
            work_root=work_root,
        )
        _append_action(state, action="recover", result=result)
        _save(state_path, state)
    if state["phase"] == "recovered":
        result = _run_action(
            action="verify",
            action_binary=action_binary,
            adapter=adapter,
            execution_source=execution_source,
            fault=fault,
            recovery_seconds=recovery_seconds,
            runner=runner,
            target_file=target_file,
            target_evidence_sha256=target_evidence_sha256,
            window_seconds=window_seconds,
            work_root=work_root,
        )
        _append_action(state, action="verify", result=result)
        _save(state_path, state)
    if state["phase"] != "verified":
        raise FaultError("fault recovery deadline failed")
    if time.monotonic() - recovery_started > recovery_seconds:
        state["phase"] = "recovery-deadline-failed"
        state["complete"] = False
        _save(state_path, state)
        raise FaultError("fault recovery deadline failed")
    state["phase"] = "failed-recovered"
    state["complete"] = False
    _validate_state(
        state,
        binding_sha256=binding_sha256,
        execution_source=execution_source,
        fault=fault,
        plan_sha256=plan_sha256,
        recovery_seconds=recovery_seconds,
        target_evidence_sha256=target_evidence_sha256,
        window_seconds=window_seconds,
    )
    _save(state_path, state)


def execute_invocation(
    invocation_path: Path,
    *,
    clock: Clock | None = None,
    runner: ActionRunner | None = None,
) -> bool:
    try:
        invocation_payload = orchestrator._read_owner_file(invocation_path)
        if invocation_payload is None:
            raise FaultError("fault invocation disappeared")
        invocation = _exact(
            orchestrator._canonical_document(
                invocation_payload,
                "fault invocation",
            ),
            {
                "action_binary",
                "action_binary_sha256",
                "adapter_contract_sha256",
                "execution_source",
                "lock_file",
                "output_file",
                "plan_file",
                "plan_file_sha256",
                "schema",
                "state_file",
                "step",
                "target_class",
                "target_evidence_file",
                "target_evidence_sha256",
                "work_root",
            },
            "fault invocation",
        )
        if (
            invocation["schema"] != INVOCATION_SCHEMA
            or invocation["target_class"] != TARGET_CLASS
            or invocation["execution_source"] not in ("fixture", "pilot")
        ):
            raise FaultError("fault invocation is invalid")
        for key in (
            "action_binary_sha256",
            "adapter_contract_sha256",
            "plan_file_sha256",
            "target_evidence_sha256",
        ):
            if (
                not isinstance(invocation[key], str)
                or SHA256.fullmatch(invocation[key]) is None
            ):
                raise FaultError("fault invocation hash is invalid")
        step = _exact(
            invocation["step"],
            {"fault", "kind", "order"},
            "fault step",
        )
        if (
            step["kind"] != "fault"
            or step["fault"] not in FAULT_ADAPTERS
            or not isinstance(step["order"], int)
            or isinstance(step["order"], bool)
        ):
            raise FaultError("fault step is invalid")
        for key in (
            "action_binary",
            "lock_file",
            "output_file",
            "plan_file",
            "state_file",
            "target_evidence_file",
            "work_root",
        ):
            if (
                not isinstance(invocation[key], str)
                or not Path(invocation[key]).is_absolute()
            ):
                raise FaultError("fault path is invalid")
        work_root = Path(invocation["work_root"])
        profile._owner_directory(work_root)
        action_binary = Path(invocation["action_binary"])
        if (
            profile._binary_hash(action_binary)
            != invocation["action_binary_sha256"]
        ):
            raise FaultError("fault action binary changed")
        plan_payload = orchestrator._read_owner_file(
            Path(invocation["plan_file"])
        )
        if (
            plan_payload is None
            or _file_hash(plan_payload) != invocation["plan_file_sha256"]
        ):
            raise FaultError("fault plan changed")
        envelope = orchestrator._canonical_document(
            plan_payload,
            "fault plan",
        )
        topology = orchestrator.plan_contract.state_machine.load_topology(
            LOAD_DIRECTORY / "topology.json"
        )
        plan = orchestrator._validate_envelope(envelope, topology)
        schedule = orchestrator.build_schedule(plan)
        matches = [
            candidate
            for candidate in schedule
            if candidate.kind == "fault"
            and candidate.name == step["fault"]
            and candidate.order == step["order"]
        ]
        if len(matches) != 1:
            raise FaultError("fault step does not match plan")
        fault_entries = [
            entry
            for entry in plan["faults"]
            if entry["fault"] == step["fault"]
        ]
        if len(fault_entries) != 1 or fault_entries[0]["serial"] is not True:
            raise FaultError("fault plan entry changed")
        limits = fault_entries[0]
        target_file = Path(invocation["target_evidence_file"])
        target_payload = orchestrator._read_owner_file(target_file)
        if target_payload is None:
            raise FaultError("fault target disappeared")
        target = _target(
            target_payload,
            expected_sha256=invocation["target_evidence_sha256"],
            fault=step["fault"],
            topology_sha256=plan["topology_sha256"],
        )
        binding = _binding(
            action_binary_sha256=invocation["action_binary_sha256"],
            adapter_contract_sha256=invocation[
                "adapter_contract_sha256"
            ],
            execution_source=invocation["execution_source"],
            fault=step["fault"],
            order=step["order"],
            plan_sha256=envelope["plan_sha256"],
            target_evidence_sha256=invocation["target_evidence_sha256"],
        )
        paths = [
            invocation_path.resolve(strict=False),
            work_root.resolve(strict=False),
            *[
                Path(invocation[key]).resolve(strict=False)
                for key in (
                    "action_binary",
                    "lock_file",
                    "output_file",
                    "plan_file",
                    "state_file",
                    "target_evidence_file",
                )
            ],
        ]
        if len(paths) != len(set(paths)):
            raise FaultError("fault paths overlap")
    except (
        CommandError,
        FaultError,
        orchestrator.OrchestratorError,
        orchestrator.plan_contract.PlanError,
        orchestrator.plan_contract.state_machine.LoadSoakError,
    ) as error:
        raise CommandError("contract-refused") from error

    state_path = Path(invocation["state_file"])
    output_path = Path(invocation["output_file"])
    lock_path = Path(invocation["lock_file"])
    orchestrator._validate_owner_path(state_path)
    orchestrator._validate_owner_path(output_path, output=True)
    chosen_clock = clock or RealClock()
    chosen_runner = runner or SubprocessActionRunner()
    fault = step["fault"]
    window_seconds = limits["window_seconds"]
    recovery_seconds = limits["recovery_seconds"]
    adapter = target["adapter"]

    with orchestrator._lock(lock_path):
        state_payload = orchestrator._read_owner_file(
            state_path,
            required=False,
        )
        try:
            state = (
                _new_state(
                    binding_sha256=binding,
                    execution_source=invocation["execution_source"],
                    fault=fault,
                    plan_sha256=envelope["plan_sha256"],
                    target_evidence_sha256=invocation[
                        "target_evidence_sha256"
                    ],
                )
                if state_payload is None
                else _validate_state(
                    orchestrator._canonical_document(
                        state_payload,
                        "fault state",
                    ),
                    binding_sha256=binding,
                    execution_source=invocation["execution_source"],
                    fault=fault,
                    plan_sha256=envelope["plan_sha256"],
                    recovery_seconds=recovery_seconds,
                    target_evidence_sha256=invocation[
                        "target_evidence_sha256"
                    ],
                    window_seconds=window_seconds,
                )
            )
        except FaultError as error:
            raise CommandError("contract-refused") from error

        output_payload = orchestrator._read_owner_file(
            output_path,
            required=False,
        )
        if output_payload is not None:
            if (
                not state["complete"]
                or orchestrator._canonical_document(
                    output_payload,
                    "fault output",
                )
                != _public_result(
                    state,
                    recovery_seconds=recovery_seconds,
                    window_seconds=window_seconds,
                )
            ):
                raise CommandError("contract-refused")
            return True
        if state["phase"] in (
            "failed-recovered",
            "recovery-deadline-failed",
        ):
            raise CommandError("execution-unavailable")
        if state["phase"] in ("verified", "complete"):
            try:
                _finalize(
                    state,
                    binding_sha256=binding,
                    execution_source=invocation["execution_source"],
                    fault=fault,
                    output_path=output_path,
                    plan_sha256=envelope["plan_sha256"],
                    recovery_seconds=recovery_seconds,
                    state_path=state_path,
                    target_evidence_sha256=invocation[
                        "target_evidence_sha256"
                    ],
                    window_seconds=window_seconds,
                )
            except (FaultError, CommandError) as error:
                raise CommandError("execution-unavailable") from error
            return True
        if state["failure_phase"] is not None or state["phase"] in (
            "injected",
            "observed",
            "recovered",
        ):
            if state["failure_phase"] is None:
                state["failure_phase"] = "interrupted"
                _save(state_path, state)
            try:
                _recover_and_verify(
                    state,
                    action_binary=action_binary,
                    adapter=adapter,
                    binding_sha256=binding,
                    execution_source=invocation["execution_source"],
                    fault=fault,
                    plan_sha256=envelope["plan_sha256"],
                    recovery_seconds=recovery_seconds,
                    runner=chosen_runner,
                    state_path=state_path,
                    target_file=target_file,
                    target_evidence_sha256=invocation[
                        "target_evidence_sha256"
                    ],
                    window_seconds=window_seconds,
                    work_root=work_root,
                )
            except FaultError as error:
                raise CommandError("execution-unavailable") from error
            raise CommandError("execution-unavailable")

        def action(name: str) -> Mapping[str, Any]:
            return _run_action(
                action=name,
                action_binary=action_binary,
                adapter=adapter,
                execution_source=invocation["execution_source"],
                fault=fault,
                recovery_seconds=recovery_seconds,
                runner=chosen_runner,
                target_file=target_file,
                target_evidence_sha256=invocation[
                    "target_evidence_sha256"
                ],
                window_seconds=window_seconds,
                work_root=work_root,
            )

        try:
            if state["phase"] == "new":
                _append_action(
                    state,
                    action="preflight",
                    result=action("preflight"),
                )
                _save(state_path, state)
            try:
                inject_result = action("inject")
            except FaultError:
                state["phase"] = "injected"
                state["failure_phase"] = "inject"
                _save(state_path, state)
                raise
            _append_action(state, action="inject", result=inject_result)
            _save(state_path, state)
            try:
                started = chosen_clock.monotonic()
                chosen_clock.sleep(window_seconds)
                if chosen_clock.monotonic() - started < window_seconds:
                    raise FaultError("fault window was shortened")
                _append_action(
                    state,
                    action="observe",
                    result=action("observe"),
                )
                _save(state_path, state)
            except KeyboardInterrupt as error:
                state["failure_phase"] = "interrupted"
                _save(state_path, state)
                raise FaultError("fault window interrupted") from error
            except FaultError:
                state["failure_phase"] = "observe"
                _save(state_path, state)
                raise
            recovery_started = chosen_clock.monotonic()
            try:
                _append_action(
                    state,
                    action="recover",
                    result=action("recover"),
                )
                _save(state_path, state)
            except FaultError:
                state["failure_phase"] = "recover"
                _save(state_path, state)
                raise
            try:
                _append_action(
                    state,
                    action="verify",
                    result=action("verify"),
                )
                _save(state_path, state)
            except FaultError:
                state["failure_phase"] = "verify"
                _save(state_path, state)
                raise
            if chosen_clock.monotonic() - recovery_started > recovery_seconds:
                state["failure_phase"] = "verify"
                state["phase"] = "recovery-deadline-failed"
                _save(state_path, state)
                raise FaultError("fault recovery exceeded deadline")
        except FaultError as primary:
            try:
                _recover_and_verify(
                    state,
                    action_binary=action_binary,
                    adapter=adapter,
                    binding_sha256=binding,
                    execution_source=invocation["execution_source"],
                    fault=fault,
                    plan_sha256=envelope["plan_sha256"],
                    recovery_seconds=recovery_seconds,
                    runner=chosen_runner,
                    state_path=state_path,
                    target_file=target_file,
                    target_evidence_sha256=invocation[
                        "target_evidence_sha256"
                    ],
                    window_seconds=window_seconds,
                    work_root=work_root,
                )
            except FaultError as cleanup_error:
                raise CommandError("execution-unavailable") from cleanup_error
            raise CommandError("execution-unavailable") from primary

        _finalize(
            state,
            binding_sha256=binding,
            execution_source=invocation["execution_source"],
            fault=fault,
            output_path=output_path,
            plan_sha256=envelope["plan_sha256"],
            recovery_seconds=recovery_seconds,
            state_path=state_path,
            target_evidence_sha256=invocation[
                "target_evidence_sha256"
            ],
            window_seconds=window_seconds,
        )
        return True


def run(
    arguments: Sequence[str],
    *,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    if (
        len(arguments) != 2
        or arguments[0] != "--invocation"
        or not arguments[1]
    ):
        print("load fault failed: invalid-arguments", file=stderr)
        return 2
    try:
        complete = execute_invocation(Path(arguments[1]))
    except CommandError as error:
        print(f"load fault failed: {error.category}", file=stderr)
        return 1
    except FaultError:
        print("load fault failed: execution-unavailable", file=stderr)
        return 1
    if not complete:
        print("load fault failed: execution-unavailable", file=stderr)
        return 1
    try:
        invocation_payload = orchestrator._read_owner_file(Path(arguments[1]))
        if invocation_payload is None:
            raise FaultError("fault invocation disappeared")
        invocation = orchestrator._canonical_document(
            invocation_payload,
            "fault invocation",
        )
        output_value = invocation.get("output_file")
        if not isinstance(output_value, str):
            raise FaultError("fault output path changed")
        output_payload = orchestrator._read_owner_file(Path(output_value))
        if output_payload is None:
            raise FaultError("fault output disappeared")
        result = orchestrator._canonical_document(
            output_payload,
            "fault output",
        )
        if not isinstance(result.get("synthetic"), bool):
            raise FaultError("fault output source changed")
    except (CommandError, FaultError, orchestrator.OrchestratorError):
        print("load fault failed: execution-unavailable", file=stderr)
        return 1
    if result["synthetic"] is True:
        print("load fault fixture completed", file=stdout)
        return 3
    print("load fault completed", file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
