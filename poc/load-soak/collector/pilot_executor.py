from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Iterator, Mapping, Protocol, Sequence


DIRECTORY = Path(__file__).resolve().parent
ROOT_DIRECTORY = DIRECTORY.parents[2]


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


pilot_schedule = _module(
    "coffer_stage6_pilot_executor_schedule",
    DIRECTORY / "pilot_schedule.py",
)
rgw_live_adapter = pilot_schedule.rgw_live_adapter
control_artifacts = pilot_schedule.control_artifacts
render_target = pilot_schedule.render_target
native_target = pilot_schedule.native_target

STATE_SCHEMA = "coffer.stage6-pilot-executor-state/v1"
RESULT_SCHEMA = "coffer.stage6-pilot-executor-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.stage6-pilot-executor-source-result/v1"
STATE_FILE = ".pilot-executor-state.json"
RESULT_FILE = ".pilot-executor-result.json"
LOCK_FILE = ".pilot-executor.lock"
RUNTIME_FILES = frozenset({STATE_FILE, RESULT_FILE, LOCK_FILE})
FIXTURE_ADAPTER_CONTRACT = "coffer.stage6-pilot-fixture-adapter/v1"
PILOT_ADAPTER_CONTRACT = "coffer.stage6-pilot-action-adapter/v1"
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
)
FIXED_FAILURES = frozenset(
    {
        "contract-refused",
        "execution-unavailable",
        "invalid-arguments",
        "lock-unavailable",
    }
)


class PilotExecutorError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURES:
            raise ValueError("pilot executor failure category is not fixed")
        super().__init__(category)
        self.category = category


class ActionAdapter(Protocol):
    contract: str
    name: str
    source_sha256: str
    synthetic: bool

    def execute(self, action: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def reconcile(
        self,
        action: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotExecutorError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def executor_source_sha256() -> str:
    files: list[dict[str, str]] = []
    try:
        for path in SOURCE_FILES:
            files.append(
                {
                    "path": str(path.relative_to(ROOT_DIRECTORY)),
                    "sha256": _payload_hash(path.read_bytes()),
                }
            )
    except OSError as error:
        raise PilotExecutorError(
            "pilot executor source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise PilotExecutorError(f"{category} is invalid")
    return value


def _owner_json(
    path: Path,
    category: str,
    *,
    canonical: bool = True,
) -> tuple[object, bytes, os.stat_result]:
    try:
        path = control_artifacts._absolute_path(str(path), category)
        payload, metadata = control_artifacts._read_owner_bytes(
            path,
            maximum_bytes=1024 * 1024,
        )
        value = json.loads(payload)
    except (
        control_artifacts.ControlArtifactError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise PilotExecutorError(f"{category} is unavailable") from error
    if canonical and payload != _canonical(value):
        raise PilotExecutorError(f"{category} is not canonical")
    return value, payload, metadata


def _schedule_output(
    directory: Path,
    readiness_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        directory = control_artifacts._absolute_path(
            str(directory),
            "pilot schedule directory",
        )
        metadata = directory.stat(follow_symlinks=False)
        names = {path.name for path in directory.iterdir()}
    except (control_artifacts.ControlArtifactError, OSError) as error:
        raise PilotExecutorError(
            "pilot schedule directory is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or names != set(pilot_schedule.OUTPUT_FILES)
    ):
        raise PilotExecutorError("pilot schedule directory is unsafe")
    documents: dict[str, object] = {}
    payloads: dict[str, bytes] = {}
    inputs: list[tuple[Path, os.stat_result]] = []
    for name in pilot_schedule.OUTPUT_FILES:
        path = directory / name
        document, payload, details = _owner_json(
            path,
            f"pilot schedule {name}",
        )
        documents[name] = document
        payloads[name] = payload
        inputs.append((path, details))
    readiness_value, readiness_payload, readiness_stat = _owner_json(
        readiness_path,
        "upstream readiness",
        canonical=False,
    )
    readiness = pilot_schedule._readiness(readiness_value)
    inputs.append((readiness_path, readiness_stat))
    try:
        control_artifacts._distinct_inputs(inputs)
    except control_artifacts.ControlArtifactError as error:
        raise PilotExecutorError("pilot executor inputs alias") from error

    result = _exact(
        documents["result.json"],
        {
            "complete",
            "execution_source",
            "files_sha256",
            "readiness_evidence_sha256",
            "renderer_source_sha256",
            "request_file_sha256",
            "result_sha256",
            "schedule_sha256",
            "schema",
            "synthetic",
            "target_sha256",
        },
        "pilot schedule result",
    )
    result_unsigned = {
        key: value for key, value in result.items() if key != "result_sha256"
    }
    files = _exact(
        result["files_sha256"],
        set(pilot_schedule.RETAINED_FILES),
        "pilot schedule file hashes",
    )
    if (
        result["schema"] != pilot_schedule.RESULT_SCHEMA
        or result["complete"] is not True
        or result["execution_source"] != "pilot"
        or result["synthetic"] is not False
        or result["renderer_source_sha256"]
        != pilot_schedule.renderer_source_sha256()
        or result["readiness_evidence_sha256"]
        != _payload_hash(readiness_payload)
        or result["result_sha256"] != _hash(result_unsigned)
        or any(
            _sha256(files[name], f"{name} hash")
            != _payload_hash(payloads[name])
            for name in pilot_schedule.RETAINED_FILES
        )
    ):
        raise PilotExecutorError("pilot schedule result changed")
    schedule = _exact(
        documents["schedule.json"],
        {
            "action_count",
            "actions",
            "cleanup_contract",
            "credential_environment",
            "execution_source",
            "load_plan_file_sha256",
            "readiness_evidence_sha256",
            "runtime_directory",
            "schedule_sha256",
            "schema",
            "synthetic",
            "target_sha256",
        },
        "pilot schedule",
    )
    schedule_unsigned = {
        key: value
        for key, value in schedule.items()
        if key != "schedule_sha256"
    }
    actions = schedule["actions"]
    if (
        schedule["schema"] != pilot_schedule.SCHEDULE_SCHEMA
        or schedule["execution_source"] != "pilot"
        or schedule["synthetic"] is not False
        or schedule["readiness_evidence_sha256"]
        != result["readiness_evidence_sha256"]
        or schedule["target_sha256"] != result["target_sha256"]
        or schedule["schedule_sha256"] != _hash(schedule_unsigned)
        or schedule["schedule_sha256"] != result["schedule_sha256"]
        or schedule["action_count"] != 53
        or not isinstance(actions, list)
        or len(actions) != 53
        or [action.get("order") for action in actions]
        != list(range(1, 54))
        or any(
            set(action) != set(pilot_schedule.ACTION_KEYS)
            for action in actions
        )
    ):
        raise PilotExecutorError("pilot schedule changed")
    configs: dict[str, dict[str, Any]] = {}
    for phase, name in pilot_schedule.PHASE_CONFIG_FILES.items():
        try:
            config = rgw_live_adapter._config(documents[name])
        except rgw_live_adapter.RgwLiveAdapterError as error:
            raise PilotExecutorError(
                "pilot phase configuration changed"
            ) from error
        if (
            config["phase"] != phase
            or Path(actions[0]["config_file"]).parent != directory
        ):
            raise PilotExecutorError(
                "pilot phase configuration changed"
            )
        configs[phase] = config
    _validate_actions(schedule, configs, directory)
    return dict(schedule), readiness


def _expected_signatures(
    configs: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str, int, str]]:
    signatures: list[tuple[str, str, int, str]] = []
    no_fault = rgw_live_adapter.NO_FAULT_SHA256
    for phase in native_target.PHASES:
        signatures.append((phase, "open-phase", -1, no_fault))
        for index in range(len(rgw_live_adapter.HEALTHY_OPERATION_ORDER)):
            signatures.append(
                (phase, "collect-rgw-step", index, no_fault)
            )
        if phase == "during":
            fault_pairs = (
                (
                    "wrong-key",
                    7,
                    8,
                    configs[phase]["steps"][7][
                        "fault_evidence_sha256"
                    ],
                ),
                (
                    "kms-outage",
                    9,
                    10,
                    configs[phase]["steps"][9][
                        "fault_evidence_sha256"
                    ],
                ),
            )
            for name, fault_index, recovery_index, fault_hash in fault_pairs:
                signatures.extend(
                    (
                        (phase, f"apply-{name}", -1, fault_hash),
                        (
                            phase,
                            "collect-rgw-step",
                            fault_index,
                            fault_hash,
                        ),
                        (phase, f"recover-{name}", -1, no_fault),
                        (
                            phase,
                            "collect-rgw-step",
                            recovery_index,
                            no_fault,
                        ),
                    )
                )
        signatures.extend(
            (
                (phase, "compile-rgw-probe", -1, no_fault),
                (phase, "collect-rgw-multipart", -1, no_fault),
                (phase, "cleanup-rgw-prefix", -1, no_fault),
                (phase, "verify-rgw-cleanup", -1, no_fault),
                (
                    phase,
                    "render-phase-preparation-request",
                    -1,
                    no_fault,
                ),
                (phase, "prepare-phase-atomically", -1, no_fault),
                (phase, "complete-phase", -1, no_fault),
            )
        )
    return signatures


def _within(path_value: object, parent: Path, category: str) -> Path:
    try:
        path = control_artifacts._absolute_path(path_value, category)
    except control_artifacts.ControlArtifactError as error:
        raise PilotExecutorError(f"{category} is invalid") from error
    if path != parent and parent not in path.parents:
        raise PilotExecutorError(f"{category} escaped its root")
    return path


def _validate_actions(
    schedule: Mapping[str, Any],
    configs: Mapping[str, Mapping[str, Any]],
    schedule_directory: Path,
) -> None:
    runtime = Path(schedule["runtime_directory"])
    expected = _expected_signatures(configs)
    observed = [
        (
            action["phase"],
            action["action"],
            action["step_index"],
            action["fault_evidence_sha256"],
        )
        for action in schedule["actions"]
    ]
    if observed != expected:
        raise PilotExecutorError("pilot action sequence changed")
    for action in schedule["actions"]:
        phase = action["phase"]
        expected_config = (
            schedule_directory
            / pilot_schedule.PHASE_CONFIG_FILES[phase]
        )
        if Path(action["config_file"]) != expected_config:
            raise PilotExecutorError("pilot action config changed")
        _within(action["output_file"], runtime, "pilot action output")
        input_path = Path(action["input_file"])
        if (
            input_path != expected_config
            and input_path != runtime
            and runtime not in input_path.parents
        ):
            raise PilotExecutorError("pilot action input escaped its root")
    cleanup = _exact(
        schedule["cleanup_contract"],
        set(native_target.PHASES),
        "pilot cleanup contract",
    )
    if any(
        cleanup[phase]
        != {
            "probe_prefix": configs[phase]["probe_prefix"],
            "require_zero_multipart_uploads": True,
            "require_zero_objects": True,
        }
        for phase in native_target.PHASES
    ):
        raise PilotExecutorError("pilot cleanup contract changed")


def _action_hash(action: Mapping[str, Any]) -> str:
    return _hash(action)


def _result_for(
    action: Mapping[str, Any],
    *,
    adapter_name: str,
    synthetic: bool,
) -> dict[str, Any]:
    unsigned = {
        "action_sha256": _action_hash(action),
        "adapter": adapter_name,
        "order": action["order"],
        "phase": action["phase"],
        "status": "passed",
        "synthetic": synthetic,
    }
    return {**unsigned, "result_sha256": _hash(unsigned)}


@dataclass
class FixtureActionAdapter:
    fail_before_order: int | None = None
    apply_then_raise_order: int | None = None
    name: str = "fixture"
    synthetic: bool = True
    contract: str = FIXTURE_ADAPTER_CONTRACT
    source_sha256: str = field(default_factory=executor_source_sha256)
    applied: dict[int, dict[str, Any]] = field(default_factory=dict)
    execute_calls: list[int] = field(default_factory=list)
    reconcile_calls: list[int] = field(default_factory=list)

    def execute(self, action: Mapping[str, Any]) -> Mapping[str, Any]:
        order = int(action["order"])
        self.execute_calls.append(order)
        if self.fail_before_order == order:
            raise PilotExecutorError("fixture action failed before apply")
        result = _result_for(
            action,
            adapter_name=self.name,
            synthetic=self.synthetic,
        )
        self.applied[order] = result
        if self.apply_then_raise_order == order:
            self.apply_then_raise_order = None
            raise PilotExecutorError("fixture action outcome is ambiguous")
        return result

    def reconcile(
        self,
        action: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        order = int(action["order"])
        self.reconcile_calls.append(order)
        return self.applied.get(order)


def _validated_adapter_result(
    value: object,
    *,
    action: Mapping[str, Any],
    adapter: ActionAdapter,
) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "action_sha256",
            "adapter",
            "order",
            "phase",
            "result_sha256",
            "status",
            "synthetic",
        },
        "pilot action result",
    )
    unsigned = {
        key: value for key, value in raw.items() if key != "result_sha256"
    }
    if (
        raw["action_sha256"] != _action_hash(action)
        or raw["adapter"] != adapter.name
        or raw["order"] != action["order"]
        or raw["phase"] != action["phase"]
        or raw["status"] != "passed"
        or raw["synthetic"] is not adapter.synthetic
        or raw["result_sha256"] != _hash(unsigned)
    ):
        raise PilotExecutorError("pilot action result changed")
    return dict(raw)


def _state_unsigned(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: value for key, value in state.items() if key != "state_sha256"
    }


def _new_state(
    schedule: Mapping[str, Any],
    readiness_sha256: str,
    adapter: ActionAdapter,
) -> dict[str, Any]:
    unsigned = {
        "adapter": adapter.name,
        "adapter_contract": adapter.contract,
        "adapter_source_sha256": adapter.source_sha256,
        "complete": False,
        "executor_source_sha256": executor_source_sha256(),
        "history": [],
        "next_order": 1,
        "pending_action_sha256": None,
        "pending_order": None,
        "readiness_evidence_sha256": readiness_sha256,
        "schedule_sha256": schedule["schedule_sha256"],
        "schema": STATE_SCHEMA,
        "synthetic": adapter.synthetic,
    }
    return {**unsigned, "state_sha256": _hash(unsigned)}


def _validate_state(
    value: object,
    *,
    schedule: Mapping[str, Any],
    readiness_sha256: str,
    adapter: ActionAdapter,
) -> dict[str, Any]:
    state = dict(
        _exact(
            value,
            {
                "adapter",
                "adapter_contract",
                "adapter_source_sha256",
                "complete",
                "executor_source_sha256",
                "history",
                "next_order",
                "pending_action_sha256",
                "pending_order",
                "readiness_evidence_sha256",
                "schedule_sha256",
                "schema",
                "state_sha256",
                "synthetic",
            },
            "pilot executor state",
        )
    )
    history = state["history"]
    if (
        state["schema"] != STATE_SCHEMA
        or state["adapter"] != adapter.name
        or state["adapter_contract"] != adapter.contract
        or state["adapter_source_sha256"] != adapter.source_sha256
        or _sha256(
            state["adapter_source_sha256"],
            "pilot adapter source hash",
        )
        != state["adapter_source_sha256"]
        or state["synthetic"] is not adapter.synthetic
        or state["executor_source_sha256"] != executor_source_sha256()
        or state["readiness_evidence_sha256"] != readiness_sha256
        or state["schedule_sha256"] != schedule["schedule_sha256"]
        or not isinstance(history, list)
        or len(history) > len(schedule["actions"])
        or state["next_order"] != len(history) + 1
        or state["complete"] != (len(history) == len(schedule["actions"]))
        or state["state_sha256"] != _hash(_state_unsigned(state))
    ):
        raise PilotExecutorError("pilot executor state changed")
    for index, item in enumerate(history):
        _validated_adapter_result(
            item,
            action=schedule["actions"][index],
            adapter=adapter,
        )
    pending_order = state["pending_order"]
    pending_hash = state["pending_action_sha256"]
    if pending_order is None:
        if pending_hash is not None:
            raise PilotExecutorError("pilot pending checkpoint changed")
    elif (
        state["complete"]
        or pending_order != state["next_order"]
        or pending_order < 1
        or pending_order > len(schedule["actions"])
        or pending_hash
        != _action_hash(schedule["actions"][pending_order - 1])
    ):
        raise PilotExecutorError("pilot pending checkpoint changed")
    return state


def _write(path: Path, value: object) -> None:
    try:
        render_target._atomic_write(path, _canonical(value))
    except render_target.RenderError as error:
        raise PilotExecutorError(
            "pilot executor state is unavailable"
        ) from error


def _save_state(path: Path, state: dict[str, Any]) -> None:
    state["state_sha256"] = _hash(_state_unsigned(state))
    _write(path, state)


def _owner_runtime_file(path: Path) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise PilotExecutorError(
            "pilot runtime entry is unavailable"
        ) from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise PilotExecutorError("pilot runtime entry is unsafe")


def _phase_runtime(
    path: Path,
    *,
    phase: str,
    schedule: Mapping[str, Any],
) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
        children = list(path.iterdir())
    except OSError as error:
        raise PilotExecutorError(
            "pilot phase runtime is unavailable"
        ) from error
    allowed = {
        "collector-inputs.json",
        "rgw-artifact-config.json",
        "rgw-step-set.json",
    }
    for action in schedule["actions"]:
        if action["phase"] != phase:
            continue
        for field in ("input_file", "output_file"):
            candidate = Path(action[field])
            try:
                relative = candidate.relative_to(path)
            except ValueError:
                continue
            if relative.parts:
                allowed.add(relative.parts[0])
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or any(child.name not in allowed for child in children)
    ):
        raise PilotExecutorError("pilot phase runtime is unsafe")
    for child in children:
        details = child.stat(follow_symlinks=False)
        if stat.S_ISDIR(details.st_mode):
            if (
                child.name != "phase-evidence"
                or stat.S_IMODE(details.st_mode) != 0o700
                or details.st_uid != os.getuid()
            ):
                raise PilotExecutorError(
                    "pilot phase runtime is unsafe"
                )
            for retained in child.iterdir():
                _owner_runtime_file(retained)
        else:
            _owner_runtime_file(child)


def _runtime(
    schedule: Mapping[str, Any],
    *,
    allow_phase_directories: bool = False,
) -> Path:
    runtime = Path(schedule["runtime_directory"])
    try:
        if not runtime.exists() and not runtime.is_symlink():
            runtime.mkdir(mode=0o700)
        metadata = runtime.stat(follow_symlinks=False)
        names = {path.name for path in runtime.iterdir()}
    except OSError as error:
        raise PilotExecutorError(
            "pilot runtime directory is unavailable"
        ) from error
    allowed = set(RUNTIME_FILES)
    if allow_phase_directories:
        allowed.update(native_target.PHASES)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or not names <= allowed
    ):
        raise PilotExecutorError("pilot runtime directory is unsafe")
    if allow_phase_directories:
        for phase in native_target.PHASES:
            path = runtime / phase
            if path.exists() or path.is_symlink():
                _phase_runtime(
                    path,
                    phase=phase,
                    schedule=schedule,
                )
    return runtime


@contextmanager
def _lock(runtime: Path) -> Iterator[None]:
    path = runtime / LOCK_FILE
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise CommandError("lock-unavailable")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CommandError("lock-unavailable") from error
        yield
    except CommandError:
        raise
    except OSError as error:
        raise CommandError("lock-unavailable") from error
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _load_or_new_state(
    path: Path,
    *,
    schedule: Mapping[str, Any],
    readiness_sha256: str,
    adapter: ActionAdapter,
) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        state = _new_state(schedule, readiness_sha256, adapter)
        _save_state(path, state)
        return state
    value, _, _ = _owner_json(path, "pilot executor state")
    return _validate_state(
        value,
        schedule=schedule,
        readiness_sha256=readiness_sha256,
        adapter=adapter,
    )


def _completion_result(
    state: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> dict[str, Any]:
    unsigned = {
        "complete": True,
        "executor_source_sha256": state["executor_source_sha256"],
        "history_sha256": _hash(
            [item["result_sha256"] for item in state["history"]]
        ),
        "readiness_evidence_sha256": state[
            "readiness_evidence_sha256"
        ],
        "schedule_sha256": schedule["schedule_sha256"],
        "schema": RESULT_SCHEMA,
        "state_sha256": state["state_sha256"],
        "synthetic": state["synthetic"],
    }
    return {**unsigned, "result_sha256": _hash(unsigned)}


def execute(
    schedule_directory: Path,
    readiness_path: Path,
    *,
    adapter: ActionAdapter,
) -> dict[str, Any]:
    fixture = (
        adapter.synthetic is True
        and adapter.name == "fixture"
        and adapter.contract == FIXTURE_ADAPTER_CONTRACT
    )
    pilot = (
        adapter.synthetic is False
        and adapter.name == "pilot"
        and adapter.contract == PILOT_ADAPTER_CONTRACT
    )
    if not fixture and not pilot:
        raise PilotExecutorError(
            "pilot executor adapter is unsupported"
        )
    _sha256(adapter.source_sha256, "pilot adapter source hash")
    schedule, _ = _schedule_output(
        schedule_directory,
        readiness_path,
    )
    runtime = _runtime(
        schedule,
        allow_phase_directories=pilot,
    )
    state_path = runtime / STATE_FILE
    result_path = runtime / RESULT_FILE
    readiness_sha256 = schedule["readiness_evidence_sha256"]
    with _lock(runtime):
        state = _load_or_new_state(
            state_path,
            schedule=schedule,
            readiness_sha256=readiness_sha256,
            adapter=adapter,
        )
        while not state["complete"]:
            order = state["next_order"]
            action = schedule["actions"][order - 1]
            if state["pending_order"] is None:
                state["pending_order"] = order
                state["pending_action_sha256"] = _action_hash(action)
                _save_state(state_path, state)
                recovered = None
            else:
                recovered = adapter.reconcile(action)
            raw_result = (
                adapter.execute(action)
                if recovered is None
                else recovered
            )
            result = _validated_adapter_result(
                raw_result,
                action=action,
                adapter=adapter,
            )
            state["history"].append(result)
            state["next_order"] = order + 1
            state["pending_order"] = None
            state["pending_action_sha256"] = None
            state["complete"] = (
                len(state["history"]) == len(schedule["actions"])
            )
            _save_state(state_path, state)
        result = _completion_result(state, schedule)
        if result_path.exists() or result_path.is_symlink():
            value, payload, _ = _owner_json(
                result_path,
                "pilot executor result",
            )
            if payload != _canonical(result) or value != result:
                raise PilotExecutorError(
                    "pilot executor result changed"
                )
        else:
            _write(result_path, result)
        return result


def run(
    arguments: Sequence[str],
    *,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    if (
        len(arguments) not in {5, 7}
        or arguments[0] != "--fixture"
        or arguments[1] != "--schedule"
        or arguments[3] != "--readiness"
        or any(not value for value in arguments[2:5:2])
        or (
            len(arguments) == 7
            and (
                arguments[5] != "--fail-before-order"
                or not arguments[6].isdigit()
            )
        )
    ):
        print("pilot executor failed: invalid-arguments", file=stderr)
        return 2
    fail_order = int(arguments[6]) if len(arguments) == 7 else None
    try:
        result = execute(
            Path(arguments[2]),
            Path(arguments[4]),
            adapter=FixtureActionAdapter(fail_before_order=fail_order),
        )
    except CommandError as error:
        print(f"pilot executor failed: {error.category}", file=stderr)
        return 1
    except (
        PilotExecutorError,
        pilot_schedule.PilotScheduleError,
        rgw_live_adapter.RgwLiveAdapterError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        print("pilot executor failed: execution-unavailable", file=stderr)
        return 1
    print(
        json.dumps(
            {
                "result_sha256": result["result_sha256"],
                "schema": RESULT_SCHEMA,
                "synthetic": result["synthetic"],
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        file=stdout,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_hash = executor_source_sha256()
        except PilotExecutorError:
            print("pilot-executor-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "executor_source_sha256": source_hash,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    return run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
