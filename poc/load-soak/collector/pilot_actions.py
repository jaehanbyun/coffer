from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


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
    "coffer_stage6_pilot_actions_executor",
    DIRECTORY / "pilot_executor.py",
)
pilot_schedule = pilot_executor.pilot_schedule
control_artifacts = pilot_schedule.control_artifacts
native_target = pilot_schedule.native_target
pilot_rgw_actions = _module(
    "coffer_stage6_pilot_actions_rgw",
    DIRECTORY / "pilot_rgw_actions.py",
)
pilot_fault_actions = _module(
    "coffer_stage6_pilot_actions_fault",
    DIRECTORY / "pilot_fault_actions.py",
)
pilot_phase_actions = _module(
    "coffer_stage6_pilot_actions_phase",
    DIRECTORY / "pilot_phase_actions.py",
)

SOURCE_RESULT_SCHEMA = "coffer.stage6-pilot-actions-source-result/v1"
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "rgw_cleanup.py",
    DIRECTORY / "phase_preparation.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
    DIRECTORY / "pilot_rgw_actions.py",
    DIRECTORY / "pilot_fault_actions.py",
    DIRECTORY / "pilot_phase_actions.py",
    DIRECTORY / "pilot_actions.py",
)


class PilotActionError(RuntimeError):
    pass


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
        raise PilotActionError(
            "pilot action source is unavailable"
        ) from error
    return _hash({"files": files})


class PilotActionAdapter:
    contract = pilot_executor.PILOT_ADAPTER_CONTRACT
    name = "pilot"
    synthetic = False

    def __init__(
        self,
        *,
        clocks: Mapping[str, pilot_rgw_actions.rgw_live_adapter.Clock],
        fault: pilot_fault_actions.PilotFaultActionAdapter,
        phase: pilot_phase_actions.PilotPhaseActionAdapter,
        rgw: pilot_rgw_actions.PilotRgwActionAdapter,
        schedule: Mapping[str, Any],
    ) -> None:
        self.clocks = clocks
        self.fault = fault
        self.phase = phase
        self.rgw = rgw
        self.schedule = schedule
        self.source_sha256 = adapter_source_sha256()

    @classmethod
    def load(
        cls,
        schedule_directory: Path,
        readiness_path: Path,
        *,
        controller: pilot_fault_actions.FaultController,
        client_factory: pilot_rgw_actions.ClientFactory = (
            pilot_rgw_actions.default_client_factory
        ),
        clocks: Mapping[
            str,
            pilot_rgw_actions.rgw_live_adapter.Clock,
        ]
        | None = None,
    ) -> PilotActionAdapter:
        try:
            schedule_directory = control_artifacts._absolute_path(
                str(schedule_directory),
                "pilot action schedule directory",
            )
            schedule, _ = pilot_executor._schedule_output(
                schedule_directory,
                readiness_path,
            )
            rgw = pilot_rgw_actions.PilotRgwActionAdapter.load(
                schedule_directory,
                readiness_path,
                client_factory=client_factory,
            )
            fault = pilot_fault_actions.PilotFaultActionAdapter.load(
                schedule_directory,
                readiness_path,
                controller=controller,
            )
            phase = pilot_phase_actions.PilotPhaseActionAdapter.load(
                schedule_directory,
                readiness_path,
            )
        except (
            control_artifacts.ControlArtifactError,
            pilot_executor.PilotExecutorError,
            pilot_rgw_actions.PilotRgwActionError,
            pilot_fault_actions.PilotFaultActionError,
            pilot_phase_actions.PilotPhaseActionError,
        ) as error:
            raise PilotActionError(
                "pilot action adapter inputs are unavailable"
            ) from error
        if any(
            adapter.schedule["schedule_sha256"]
            != schedule["schedule_sha256"]
            for adapter in (rgw, fault, phase)
        ):
            raise PilotActionError("pilot action schedules diverged")
        selected_clocks = (
            {phase: time.time for phase in native_target.PHASES}
            if clocks is None
            else dict(clocks)
        )
        if (
            set(selected_clocks) != set(native_target.PHASES)
            or any(
                not callable(clock)
                for clock in selected_clocks.values()
            )
        ):
            raise PilotActionError("pilot action clocks changed")
        return cls(
            clocks=selected_clocks,
            fault=fault,
            phase=phase,
            rgw=rgw,
            schedule=schedule,
        )

    def _adapter(
        self,
        action: Mapping[str, Any],
    ) -> tuple[Any, Any]:
        kind = action.get("action")
        memberships = [
            (
                kind in pilot_rgw_actions.SUPPORTED_ACTIONS,
                self.rgw,
                pilot_rgw_actions,
            ),
            (
                kind in pilot_fault_actions.SUPPORTED_ACTIONS,
                self.fault,
                pilot_fault_actions,
            ),
            (
                kind in pilot_phase_actions.SUPPORTED_ACTIONS,
                self.phase,
                pilot_phase_actions,
            ),
        ]
        selected = [
            (adapter, module)
            for supported, adapter, module in memberships
            if supported
        ]
        if len(selected) != 1:
            raise PilotActionError(
                "pilot action route is unsupported"
            )
        order = action.get("order")
        if (
            not isinstance(order, int)
            or isinstance(order, bool)
            or not 1 <= order <= len(self.schedule["actions"])
            or action != self.schedule["actions"][order - 1]
        ):
            raise PilotActionError("pilot action changed")
        adapter, module = selected[0]
        if adapter is self.rgw:
            self.rgw.clock = self.clocks[action["phase"]]
        return adapter, module

    def _result(
        self,
        action: Mapping[str, Any],
        adapter: Any,
        module: Any,
        value: object,
    ) -> dict[str, Any]:
        try:
            module.pilot_executor._validated_adapter_result(
                value,
                action=action,
                adapter=adapter,
            )
        except (
            module.pilot_executor.PilotExecutorError,
            AttributeError,
            TypeError,
            ValueError,
        ) as error:
            raise PilotActionError(
                "pilot routed action result changed"
            ) from error
        return pilot_executor._result_for(
            action,
            adapter_name=self.name,
            synthetic=self.synthetic,
        )

    def execute(
        self,
        action: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        adapter, module = self._adapter(action)
        return self._result(
            action,
            adapter,
            module,
            adapter.execute(action),
        )

    def reconcile(
        self,
        action: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        adapter, module = self._adapter(action)
        result = adapter.reconcile(action)
        if result is None:
            return None
        return self._result(action, adapter, module, result)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["source-hash"]:
        print("pilot-actions-refused", file=sys.stderr)
        return 2
    try:
        source_hash = adapter_source_sha256()
    except PilotActionError:
        print("pilot-actions-refused", file=sys.stderr)
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
