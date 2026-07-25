from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Iterator, Mapping, Protocol, Sequence


PLAN_PATH = Path(__file__).with_name("plan.py")
PLAN_SPEC = importlib.util.spec_from_file_location(
    "coffer_load_orchestrator_plan",
    PLAN_PATH,
)
if PLAN_SPEC is None or PLAN_SPEC.loader is None:
    raise RuntimeError("load execution plan contract is unavailable")
plan_contract = importlib.util.module_from_spec(PLAN_SPEC)
sys.modules[PLAN_SPEC.name] = plan_contract
PLAN_SPEC.loader.exec_module(plan_contract)

INVOCATION_SCHEMA = "coffer.load-orchestrator-invocation/v1"
STATE_SCHEMA = "coffer.load-orchestrator-state/v1"
RESULT_SCHEMA = "coffer.load-orchestrator-result/v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
FIXED_FAILURES = frozenset(
    {
        "contract-refused",
        "execution-unavailable",
        "invalid-arguments",
        "local-file-unavailable",
        "lock-unavailable",
        "output-unavailable",
    }
)


class OrchestratorError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURES:
            raise ValueError("orchestrator failure category is not fixed")
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class Step:
    kind: str
    name: str
    order: int
    transfer_ceiling_bytes: int


class Executor(Protocol):
    def execute(self, step: Step) -> Mapping[str, Any]: ...


class FixtureExecutor:
    def __init__(
        self,
        *,
        fail_step: int | None = None,
        over_budget_step: int | None = None,
    ):
        self.fail_step = fail_step
        self.over_budget_step = over_budget_step

    def execute(self, step: Step) -> Mapping[str, Any]:
        if self.fail_step == step.order:
            raise OrchestratorError("fixture step failed")
        transferred = 0
        if step.kind in ("profile", "ramp"):
            transferred = step.transfer_ceiling_bytes // 2
        if self.over_budget_step == step.order:
            transferred = step.transfer_ceiling_bytes + 1
        return {
            "attempts": 1,
            "executor": "fixture",
            "status": "passed",
            "transferred_bytes": transferred,
            "unexpected_errors": 0,
        }


def _exact(
    value: object,
    keys: set[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise OrchestratorError(f"{category} boundary changed")
    return value


def _hash(value: object) -> str:
    payload = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_envelope(
    value: object,
    topology: Mapping[str, Any],
) -> Mapping[str, Any]:
    envelope = _exact(
        value,
        {"plan", "plan_sha256", "schema", "synthetic"},
        "load plan envelope",
    )
    plan = envelope["plan"]
    if (
        envelope["schema"] != plan_contract.ENVELOPE_SCHEMA
        or envelope["synthetic"] is not True
        or envelope["plan_sha256"] != _hash(plan)
        or not isinstance(plan, Mapping)
    ):
        raise OrchestratorError("load plan envelope is invalid")
    checked_plan = _exact(
        plan,
        {
            "bindings",
            "bindings_sha256",
            "content",
            "faults",
            "matrix",
            "phases",
            "profiles",
            "ramp",
            "schema",
            "target_class",
            "telemetry_windows",
            "topology_sha256",
            "transfer_ceiling_bytes",
        },
        "load execution plan",
    )
    request = {
        "bindings": checked_plan["bindings"],
        "schema": plan_contract.REQUEST_SCHEMA,
        "topology_sha256": checked_plan["topology_sha256"],
    }
    expected = plan_contract.compile_plan(request, topology=topology)
    if envelope != expected:
        raise OrchestratorError("load plan does not match compiler")
    return checked_plan


def build_schedule(plan: Mapping[str, Any]) -> list[Step]:
    profiles = {
        entry["name"]: entry for entry in plan["profiles"]
    }
    order = 0
    result: list[Step] = []

    def append(kind: str, name: str, ceiling: int = 0) -> None:
        nonlocal order
        order += 1
        result.append(
            Step(
                kind=kind,
                name=name,
                order=order,
                transfer_ceiling_bytes=ceiling,
            )
        )

    for entry in plan["matrix"]:
        append("client", entry["client"])
    append(
        "profile",
        "smoke",
        profiles["smoke"]["transfer_ceiling_bytes"],
    )
    for entry in plan["ramp"]:
        append(
            "ramp",
            f"clients-{entry['clients']}",
            entry["transfer_ceiling_bytes"],
        )
    append(
        "profile",
        "qualification",
        profiles["qualification"]["transfer_ceiling_bytes"],
    )
    for entry in plan["faults"]:
        append("fault", entry["fault"])
    append(
        "profile",
        "soak",
        profiles["soak"]["transfer_ceiling_bytes"],
    )
    for window in plan["telemetry_windows"]:
        append("telemetry", window)
    expected_kinds = (
        ["client"] * 6
        + ["profile"]
        + ["ramp"] * 7
        + ["profile"]
        + ["fault"] * 10
        + ["profile"]
        + ["telemetry"] * 3
    )
    if (
        [step.kind for step in result] != expected_kinds
        or [step.order for step in result] != list(range(1, 30))
    ):
        raise OrchestratorError("load execution schedule changed")
    return result


def new_state(plan_sha256: str, schedule: Sequence[Step]) -> dict[str, Any]:
    return {
        "budgets": {
            "profiles": {
                "qualification": 0,
                "smoke": 0,
                "soak": 0,
            },
            "ramp": 0,
        },
        "complete": False,
        "history": [],
        "next_step": 1,
        "plan_sha256": plan_sha256,
        "schedule_sha256": _hash(
            [
                {
                    "kind": step.kind,
                    "name": step.name,
                    "order": step.order,
                    "transfer_ceiling_bytes": step.transfer_ceiling_bytes,
                }
                for step in schedule
            ]
        ),
        "schema": STATE_SCHEMA,
        "synthetic": True,
    }


def validate_state(
    value: object,
    *,
    plan_sha256: str,
    schedule: Sequence[Step],
) -> dict[str, Any]:
    state = dict(
        _exact(
            value,
            {
                "budgets",
                "complete",
                "history",
                "next_step",
                "plan_sha256",
                "schedule_sha256",
                "schema",
                "synthetic",
            },
            "orchestrator state",
        )
    )
    expected_schedule_hash = new_state(plan_sha256, schedule)[
        "schedule_sha256"
    ]
    if (
        state["schema"] != STATE_SCHEMA
        or state["synthetic"] is not True
        or state["plan_sha256"] != plan_sha256
        or state["schedule_sha256"] != expected_schedule_hash
        or not isinstance(state["history"], list)
        or not isinstance(state["complete"], bool)
        or state["next_step"] != len(state["history"]) + 1
        or state["complete"] != (len(state["history"]) == len(schedule))
    ):
        raise OrchestratorError("orchestrator state is invalid")
    budgets = _exact(
        state["budgets"],
        {"profiles", "ramp"},
        "orchestrator budgets",
    )
    profiles = _exact(
        budgets["profiles"],
        {"qualification", "smoke", "soak"},
        "profile budgets",
    )
    expected_budgets = {
        "profiles": {"qualification": 0, "smoke": 0, "soak": 0},
        "ramp": 0,
    }
    previous_hash = state["schedule_sha256"]
    for index, entry_value in enumerate(state["history"]):
        entry = _exact(
            entry_value,
            {
                "entry_sha256",
                "evidence_sha256",
                "kind",
                "name",
                "previous_sha256",
                "sequence",
                "transferred_bytes",
            },
            "orchestrator history",
        )
        step = schedule[index]
        unsigned = {
            key: entry[key]
            for key in entry
            if key != "entry_sha256"
        }
        transferred = entry["transferred_bytes"]
        if (
            entry["sequence"] != index + 1
            or entry["kind"] != step.kind
            or entry["name"] != step.name
            or entry["previous_sha256"] != previous_hash
            or entry["entry_sha256"] != _hash(unsigned)
            or not isinstance(transferred, int)
            or isinstance(transferred, bool)
            or transferred < 0
            or transferred > step.transfer_ceiling_bytes
        ):
            raise OrchestratorError("orchestrator history is invalid")
        if step.kind == "profile":
            expected_budgets["profiles"][step.name] += transferred
        elif step.kind == "ramp":
            expected_budgets["ramp"] += transferred
        previous_hash = entry["entry_sha256"]
    if budgets != expected_budgets or profiles != expected_budgets["profiles"]:
        raise OrchestratorError("orchestrator budget state changed")
    return state


def advance(
    state_value: object,
    *,
    plan: Mapping[str, Any],
    plan_sha256: str,
    schedule: Sequence[Step],
    executor: Executor,
) -> dict[str, Any]:
    if type(executor) is not FixtureExecutor:
        raise OrchestratorError("live executor is not available")
    state = validate_state(
        state_value,
        plan_sha256=plan_sha256,
        schedule=schedule,
    )
    if state["complete"]:
        return state
    step = schedule[len(state["history"])]
    evidence = _exact(
        executor.execute(step),
        {
            "attempts",
            "executor",
            "status",
            "transferred_bytes",
            "unexpected_errors",
        },
        "executor evidence",
    )
    transferred = evidence["transferred_bytes"]
    if (
        evidence["executor"] != "fixture"
        or evidence["status"] != "passed"
        or evidence["attempts"] != 1
        or evidence["unexpected_errors"] != 0
        or not isinstance(transferred, int)
        or isinstance(transferred, bool)
        or transferred < 0
        or transferred > step.transfer_ceiling_bytes
        or (step.kind not in ("profile", "ramp") and transferred != 0)
    ):
        raise OrchestratorError("executor evidence failed")
    previous_hash = (
        state["history"][-1]["entry_sha256"]
        if state["history"]
        else state["schedule_sha256"]
    )
    unsigned = {
        "evidence_sha256": _hash(evidence),
        "kind": step.kind,
        "name": step.name,
        "previous_sha256": previous_hash,
        "sequence": step.order,
        "transferred_bytes": transferred,
    }
    entry = {**unsigned, "entry_sha256": _hash(unsigned)}
    state["history"].append(entry)
    state["next_step"] += 1
    if step.kind == "profile":
        state["budgets"]["profiles"][step.name] += transferred
    elif step.kind == "ramp":
        state["budgets"]["ramp"] += transferred
        qualification_ceiling = next(
            entry["transfer_ceiling_bytes"]
            for entry in plan["profiles"]
            if entry["name"] == "qualification"
        )
        if state["budgets"]["ramp"] > qualification_ceiling:
            raise OrchestratorError("ramp transfer budget exceeded")
    state["complete"] = len(state["history"]) == len(schedule)
    return validate_state(
        state,
        plan_sha256=plan_sha256,
        schedule=schedule,
    )


def public_result(state: Mapping[str, Any]) -> dict[str, Any]:
    if state["complete"] is not True:
        raise OrchestratorError("orchestrator is incomplete")
    return {
        "adapter": "fixture",
        "budget_sha256": _hash(state["budgets"]),
        "history_sha256": _hash(state["history"]),
        "plan_sha256": state["plan_sha256"],
        "schema": RESULT_SCHEMA,
        "steps_completed": len(state["history"]),
        "synthetic": True,
    }


def _read_owner_file(path: Path, *, required: bool = True) -> bytes | None:
    if not path.is_absolute():
        raise CommandError("local-file-unavailable")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError:
        if not required:
            return None
        raise CommandError("local-file-unavailable") from None
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or details.st_size < 1
            or details.st_size > MAX_FILE_BYTES
        ):
            raise CommandError("local-file-unavailable")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(MAX_FILE_BYTES + 1)
    except CommandError:
        raise
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(payload) != details.st_size or b"\x00" in payload:
        raise CommandError("local-file-unavailable")
    return payload


def _validate_owner_path(path: Path, *, output: bool = False) -> None:
    if not path.is_absolute():
        raise CommandError(
            "output-unavailable" if output else "local-file-unavailable"
        )
    category = "output-unavailable" if output else "local-file-unavailable"
    try:
        parent = path.parent.lstat()
    except OSError as error:
        raise CommandError(category) from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.geteuid()
    ):
        raise CommandError(category)
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise CommandError(category) from error
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        raise CommandError(category)


def _atomic_json(path: Path, value: object, *, output: bool = False) -> None:
    _validate_owner_path(path, output=output)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise CommandError(
            "output-unavailable" if output else "local-file-unavailable"
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _validate_owner_path(path, output=output)


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    _validate_owner_path(path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
        ):
            raise CommandError("lock-unavailable")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise CommandError("lock-unavailable") from error
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise CommandError("lock-unavailable") from error
    try:
        yield
    finally:
        assert descriptor is not None
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _canonical_document(payload: bytes, category: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload)
        if payload != (
            json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8"):
            raise OrchestratorError(f"{category} is not canonical")
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OrchestratorError(f"{category} is invalid") from error
    if not isinstance(value, Mapping):
        raise OrchestratorError(f"{category} is invalid")
    return value


def execute_invocation(
    invocation_path: Path,
    *,
    executor: Executor | None = None,
    max_steps: int | None = None,
) -> bool:
    if (
        max_steps is not None
        and (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or max_steps < 0
        )
    ):
        raise CommandError("contract-refused")
    invocation_payload = _read_owner_file(invocation_path)
    assert invocation_payload is not None
    try:
        invocation = _exact(
            _canonical_document(
                invocation_payload,
                "orchestrator invocation",
            ),
            {
                "adapter",
                "lock_file",
                "output_file",
                "plan_file",
                "plan_file_sha256",
                "schema",
                "state_file",
                "topology_file",
            },
            "orchestrator invocation",
        )
        if (
            invocation["schema"] != INVOCATION_SCHEMA
            or invocation["adapter"] != "fixture"
            or not isinstance(invocation["plan_file_sha256"], str)
            or plan_contract.SHA256.fullmatch(
                invocation["plan_file_sha256"]
            )
            is None
        ):
            raise OrchestratorError("orchestrator invocation is invalid")
        for key in (
            "lock_file",
            "output_file",
            "plan_file",
            "state_file",
            "topology_file",
        ):
            if (
                not isinstance(invocation[key], str)
                or not Path(invocation[key]).is_absolute()
            ):
                raise OrchestratorError("orchestrator path is invalid")
        paths = [
            invocation_path.resolve(strict=False),
            *[
                Path(invocation[key]).resolve(strict=False)
                for key in (
                    "lock_file",
                    "output_file",
                    "plan_file",
                    "state_file",
                    "topology_file",
                )
            ],
        ]
        if len(paths) != len(set(paths)):
            raise OrchestratorError("orchestrator paths overlap")
        topology = plan_contract.state_machine.load_topology(
            Path(invocation["topology_file"])
        )
        plan_payload = _read_owner_file(Path(invocation["plan_file"]))
        assert plan_payload is not None
        if (
            "sha256:" + hashlib.sha256(plan_payload).hexdigest()
            != invocation["plan_file_sha256"]
        ):
            raise OrchestratorError("load plan file binding changed")
        envelope = _canonical_document(plan_payload, "load plan")
        plan = _validate_envelope(envelope, topology)
        schedule = build_schedule(plan)
    except (
        plan_contract.PlanError,
        plan_contract.state_machine.LoadSoakError,
        OrchestratorError,
    ) as error:
        raise CommandError("contract-refused") from error
    state_path = Path(invocation["state_file"])
    output_path = Path(invocation["output_file"])
    lock_path = Path(invocation["lock_file"])
    _validate_owner_path(state_path)
    _validate_owner_path(output_path, output=True)
    chosen_executor = executor or FixtureExecutor()
    with _lock(lock_path):
        state_payload = _read_owner_file(state_path, required=False)
        if state_payload is None:
            state = new_state(envelope["plan_sha256"], schedule)
        else:
            try:
                state = validate_state(
                    _canonical_document(state_payload, "orchestrator state"),
                    plan_sha256=envelope["plan_sha256"],
                    schedule=schedule,
                )
            except OrchestratorError as error:
                raise CommandError("contract-refused") from error
        output_payload = _read_owner_file(output_path, required=False)
        if output_payload is not None:
            if not state["complete"]:
                raise CommandError("contract-refused")
            try:
                if (
                    _canonical_document(
                        output_payload,
                        "orchestrator output",
                    )
                    != public_result(state)
                ):
                    raise OrchestratorError("orchestrator output changed")
            except OrchestratorError as error:
                raise CommandError("contract-refused") from error
        completed_this_run = 0
        while not state["complete"]:
            if max_steps is not None and completed_this_run >= max_steps:
                break
            try:
                state = advance(
                    state,
                    plan=plan,
                    plan_sha256=envelope["plan_sha256"],
                    schedule=schedule,
                    executor=chosen_executor,
                )
            except OrchestratorError as error:
                raise CommandError("execution-unavailable") from error
            _atomic_json(state_path, state)
            completed_this_run += 1
        if state["complete"]:
            _atomic_json(output_path, public_result(state), output=True)
        return bool(state["complete"])


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
        print("load orchestrator failed: invalid-arguments", file=stderr)
        return 2
    try:
        completed = execute_invocation(Path(arguments[1]))
    except CommandError as error:
        print(f"load orchestrator failed: {error.category}", file=stderr)
        return 1
    if not completed:
        print("load orchestrator checkpointed", file=stdout)
        return 3
    print("load orchestrator completed", file=stdout)
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
