from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Protocol, Sequence


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


pilot_executor = _module(
    "coffer_stage6_pilot_fault_executor",
    DIRECTORY / "pilot_executor.py",
)
pilot_schedule = pilot_executor.pilot_schedule
rgw_live_adapter = pilot_schedule.rgw_live_adapter
control_artifacts = pilot_schedule.control_artifacts
render_target = pilot_schedule.render_target

ACTION_SCHEMA = "coffer.load-pilot-fault-action-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-pilot-fault-actions-source-result/v1"
FAULTS = ("kms-outage", "wrong-key")
STATES = ("applied", "recovered")
SUPPORTED_ACTIONS = frozenset(
    {
        "apply-kms-outage",
        "apply-wrong-key",
        "recover-kms-outage",
        "recover-wrong-key",
    }
)
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
    DIRECTORY / "pilot_fault_actions.py",
)


class PilotFaultActionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FaultObservation:
    completed_at_seconds: float
    evidence_sha256: str
    fault: str
    started_at_seconds: float
    state: str


class FaultController(Protocol):
    name: str
    source_sha256: str

    def apply(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> FaultObservation: ...

    def recover(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> FaultObservation: ...

    def observe(
        self,
        fault: str,
        state: str,
        evidence_sha256: str,
    ) -> FaultObservation | None: ...


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotFaultActionError(f"{category} boundary changed")
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


def adapter_source_sha256() -> str:
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
        raise PilotFaultActionError(
            "pilot fault action source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    try:
        return rgw_live_adapter._sha256(value, category)
    except rgw_live_adapter.RgwLiveAdapterError as error:
        raise PilotFaultActionError(f"{category} is invalid") from error


def _write(path: Path, value: object) -> None:
    try:
        render_target._atomic_write(path, _canonical(value))
    except render_target.RenderError as error:
        raise PilotFaultActionError(
            "pilot fault action output is unavailable"
        ) from error


def _owner_document(path: Path, category: str) -> object:
    try:
        value, _, _ = control_artifacts._read_owner_document(path)
    except control_artifacts.ControlArtifactError as error:
        raise PilotFaultActionError(f"{category} is unavailable") from error
    return value


def _observation(
    value: object,
    *,
    config: Mapping[str, Any],
    evidence_sha256: str,
    fault: str,
    state: str,
) -> FaultObservation:
    expected_fields = {
        "completed_at_seconds",
        "evidence_sha256",
        "fault",
        "started_at_seconds",
        "state",
    }
    if (
        not is_dataclass(value)
        or isinstance(value, type)
        or {field.name for field in fields(value)} != expected_fields
    ):
        raise PilotFaultActionError("fault-controller observation changed")
    started = rgw_live_adapter._number(
        value.started_at_seconds,
        "fault observation start",
    )
    completed = rgw_live_adapter._number(
        value.completed_at_seconds,
        "fault observation completion",
    )
    try:
        rgw_live_adapter._inside_window(config, started, completed)
    except rgw_live_adapter.RgwLiveAdapterError as error:
        raise PilotFaultActionError(
            "fault observation escaped its window"
        ) from error
    if (
        value.fault != fault
        or value.state != state
        or value.evidence_sha256 != evidence_sha256
    ):
        raise PilotFaultActionError("fault-controller observation changed")
    return FaultObservation(
        completed_at_seconds=completed,
        evidence_sha256=_sha256(
            value.evidence_sha256,
            "fault evidence hash",
        ),
        fault=fault,
        started_at_seconds=started,
        state=state,
    )


def _fault_result(
    *,
    action: Mapping[str, Any],
    config: Mapping[str, Any],
    controller: FaultController,
    evidence_sha256: str,
    observation: FaultObservation,
    schedule_sha256: str,
) -> dict[str, Any]:
    fault = str(action["action"]).removeprefix("apply-").removeprefix(
        "recover-"
    )
    state = (
        "applied"
        if str(action["action"]).startswith("apply-")
        else "recovered"
    )
    observed = _observation(
        observation,
        config=config,
        evidence_sha256=evidence_sha256,
        fault=fault,
        state=state,
    )
    unsigned = {
        "action_sha256": pilot_executor._action_hash(action),
        "completed_at_seconds": observed.completed_at_seconds,
        "controller": controller.name,
        "controller_source_sha256": _sha256(
            controller.source_sha256,
            "fault controller source hash",
        ),
        "fault": fault,
        "fault_evidence_sha256": evidence_sha256,
        "phase": config["phase"],
        "schedule_sha256": schedule_sha256,
        "schema": ACTION_SCHEMA,
        "started_at_seconds": observed.started_at_seconds,
        "state": state,
        "synthetic": False,
        "target_sha256": config["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "fault_action_sha256": _hash(unsigned)}


def _validate_fault_result(
    value: object,
    *,
    action: Mapping[str, Any],
    config: Mapping[str, Any],
    controller: FaultController,
    evidence_sha256: str,
    schedule_sha256: str,
) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "action_sha256",
            "completed_at_seconds",
            "controller",
            "controller_source_sha256",
            "fault",
            "fault_action_sha256",
            "fault_evidence_sha256",
            "phase",
            "schedule_sha256",
            "schema",
            "started_at_seconds",
            "state",
            "synthetic",
            "target_sha256",
            "window_sha256",
        },
        "pilot fault action result",
    )
    expected_state = (
        "applied"
        if str(action["action"]).startswith("apply-")
        else "recovered"
    )
    fault = str(action["action"]).removeprefix("apply-").removeprefix(
        "recover-"
    )
    started = rgw_live_adapter._number(
        raw["started_at_seconds"],
        "fault action start",
    )
    completed = rgw_live_adapter._number(
        raw["completed_at_seconds"],
        "fault action completion",
    )
    try:
        rgw_live_adapter._inside_window(config, started, completed)
    except rgw_live_adapter.RgwLiveAdapterError as error:
        raise PilotFaultActionError(
            "pilot fault action escaped its window"
        ) from error
    unsigned = {
        key: raw[key] for key in raw if key != "fault_action_sha256"
    }
    if (
        raw["schema"] != ACTION_SCHEMA
        or raw["synthetic"] is not False
        or raw["action_sha256"] != pilot_executor._action_hash(action)
        or raw["controller"] != controller.name
        or raw["controller_source_sha256"] != controller.source_sha256
        or raw["fault"] != fault
        or raw["fault_evidence_sha256"] != evidence_sha256
        or raw["phase"] != "during"
        or raw["schedule_sha256"] != schedule_sha256
        or raw["state"] != expected_state
        or raw["target_sha256"] != config["target_sha256"]
        or raw["window_sha256"] != config["window_sha256"]
        or raw["fault_action_sha256"] != _hash(unsigned)
    ):
        raise PilotFaultActionError("pilot fault action result changed")
    return dict(raw)


@dataclass
class PilotFaultActionAdapter:
    controller: FaultController
    schedule_directory: Path
    schedule: Mapping[str, Any]
    name: str = "pilot-fault"
    synthetic: bool = False

    @classmethod
    def load(
        cls,
        schedule_directory: Path,
        readiness_path: Path,
        *,
        controller: FaultController,
    ) -> PilotFaultActionAdapter:
        try:
            schedule_directory = control_artifacts._absolute_path(
                str(schedule_directory),
                "pilot fault schedule directory",
            )
            schedule, _ = pilot_executor._schedule_output(
                schedule_directory,
                readiness_path,
            )
            _sha256(
                controller.source_sha256,
                "fault controller source hash",
            )
        except (
            control_artifacts.ControlArtifactError,
            pilot_executor.PilotExecutorError,
            pilot_schedule.PilotScheduleError,
            PilotFaultActionError,
        ) as error:
            raise PilotFaultActionError(
                "pilot fault adapter inputs are unavailable"
            ) from error
        if (
            not isinstance(controller.name, str)
            or not controller.name
            or len(controller.name) > 128
        ):
            raise PilotFaultActionError("fault controller name is invalid")
        return cls(
            controller=controller,
            schedule_directory=schedule_directory,
            schedule=schedule,
        )

    def _action(
        self,
        value: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], str, str]:
        raw = dict(
            _exact(
                value,
                pilot_schedule.ACTION_KEYS,
                "pilot fault action",
            )
        )
        order = raw["order"]
        if (
            not isinstance(order, int)
            or isinstance(order, bool)
            or not 1 <= order <= len(self.schedule["actions"])
            or raw != self.schedule["actions"][order - 1]
            or raw["action"] not in SUPPORTED_ACTIONS
            or raw["phase"] != "during"
        ):
            raise PilotFaultActionError(
                "pilot fault action is unsupported"
            )
        config_path = (
            self.schedule_directory
            / pilot_schedule.PHASE_CONFIG_FILES["during"]
        )
        if Path(raw["config_file"]) != config_path:
            raise PilotFaultActionError(
                "pilot fault action configuration changed"
            )
        try:
            config, _, _ = rgw_live_adapter._read_config(config_path)
        except rgw_live_adapter.RgwLiveAdapterError as error:
            raise PilotFaultActionError(
                "pilot fault action configuration changed"
            ) from error
        fault = str(raw["action"]).removeprefix("apply-").removeprefix(
            "recover-"
        )
        if fault not in FAULTS:
            raise PilotFaultActionError(
                "pilot fault action is unsupported"
            )
        if str(raw["action"]).startswith("apply-"):
            evidence_hash = _sha256(
                raw["fault_evidence_sha256"],
                "fault evidence hash",
            )
            if evidence_hash == rgw_live_adapter.NO_FAULT_SHA256:
                raise PilotFaultActionError(
                    "pilot fault action evidence changed"
                )
        else:
            if (
                raw["fault_evidence_sha256"]
                != rgw_live_adapter.NO_FAULT_SHA256
            ):
                raise PilotFaultActionError(
                    "pilot fault recovery evidence changed"
                )
            applied = _owner_document(
                Path(raw["input_file"]),
                "pilot applied fault",
            )
            applied_raw = _exact(
                applied,
                {
                    "action_sha256",
                    "completed_at_seconds",
                    "controller",
                    "controller_source_sha256",
                    "fault",
                    "fault_action_sha256",
                    "fault_evidence_sha256",
                    "phase",
                    "schedule_sha256",
                    "schema",
                    "started_at_seconds",
                    "state",
                    "synthetic",
                    "target_sha256",
                    "window_sha256",
                },
                "pilot applied fault",
            )
            evidence_hash = _sha256(
                applied_raw["fault_evidence_sha256"],
                "fault evidence hash",
            )
            apply_action = next(
                item
                for item in self.schedule["actions"]
                if item["action"] == f"apply-{fault}"
            )
            _validate_fault_result(
                applied_raw,
                action=apply_action,
                config=config,
                controller=self.controller,
                evidence_sha256=evidence_hash,
                schedule_sha256=self.schedule["schedule_sha256"],
            )
        return raw, config, fault, evidence_hash

    def _materialize(
        self,
        *,
        action: Mapping[str, Any],
        config: Mapping[str, Any],
        evidence_sha256: str,
        fault: str,
        observation: FaultObservation,
    ) -> dict[str, Any]:
        result = _fault_result(
            action=action,
            config=config,
            controller=self.controller,
            evidence_sha256=evidence_sha256,
            observation=observation,
            schedule_sha256=self.schedule["schedule_sha256"],
        )
        _write(Path(action["output_file"]), result)
        return result

    def execute(
        self,
        action_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        action, config, fault, evidence_hash = self._action(action_value)
        output = Path(action["output_file"])
        if output.exists() or output.is_symlink():
            raise PilotFaultActionError(
                "pilot fault action output already exists"
            )
        if not output.parent.exists():
            raise PilotFaultActionError(
                "pilot fault phase is unavailable"
            )
        observation = (
            self.controller.apply(fault, evidence_hash)
            if str(action["action"]).startswith("apply-")
            else self.controller.recover(fault, evidence_hash)
        )
        self._materialize(
            action=action,
            config=config,
            evidence_sha256=evidence_hash,
            fault=fault,
            observation=observation,
        )
        return pilot_executor._result_for(
            action,
            adapter_name=self.name,
            synthetic=self.synthetic,
        )

    def reconcile(
        self,
        action_value: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        action, config, fault, evidence_hash = self._action(action_value)
        output = Path(action["output_file"])
        if not output.exists() and not output.is_symlink():
            state = (
                "applied"
                if str(action["action"]).startswith("apply-")
                else "recovered"
            )
            observation = self.controller.observe(
                fault,
                state,
                evidence_hash,
            )
            if observation is None:
                return None
            self._materialize(
                action=action,
                config=config,
                evidence_sha256=evidence_hash,
                fault=fault,
                observation=observation,
            )
        value = _owner_document(output, "pilot fault action output")
        _validate_fault_result(
            value,
            action=action,
            config=config,
            controller=self.controller,
            evidence_sha256=evidence_hash,
            schedule_sha256=self.schedule["schedule_sha256"],
        )
        return pilot_executor._result_for(
            action,
            adapter_name=self.name,
            synthetic=self.synthetic,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["source-hash"]:
        print("pilot-fault-actions-refused", file=sys.stderr)
        return 2
    try:
        source_hash = adapter_source_sha256()
    except PilotFaultActionError:
        print("pilot-fault-actions-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "adapter_source_sha256": source_hash,
                "schema": SOURCE_RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
