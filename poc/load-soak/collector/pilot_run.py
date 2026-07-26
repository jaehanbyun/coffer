from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence


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


pilot_actions = _module(
    "coffer_stage6_pilot_run_actions",
    DIRECTORY / "pilot_actions.py",
)
pilot_executor = pilot_actions.pilot_executor
pilot_schedule = pilot_executor.pilot_schedule
control_artifacts = pilot_schedule.control_artifacts
native_target = pilot_schedule.native_target
pilot_inputs = _module(
    "coffer_stage6_pilot_run_inputs",
    DIRECTORY / "pilot_inputs.py",
)
pilot_fault_controller = _module(
    "coffer_stage6_pilot_run_fault_controller",
    DIRECTORY / "pilot_fault_controller.py",
)

REQUEST_SCHEMA = "coffer.stage6-pilot-live-invocation/v1"
SOURCE_RESULT_SCHEMA = "coffer.stage6-pilot-live-source-result/v1"
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "rgw_cleanup.py",
    DIRECTORY / "phase_preparation.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
    DIRECTORY / "pilot_rgw_actions.py",
    DIRECTORY / "pilot_fault_actions.py",
    DIRECTORY / "pilot_fault_controller.py",
    DIRECTORY / "pilot_phase_actions.py",
    DIRECTORY / "pilot_inputs.py",
    DIRECTORY / "pilot_actions.py",
    DIRECTORY / "pilot_run.py",
)


class PilotRunError(RuntimeError):
    pass


ControllerLoader = Callable[
    [Path],
    pilot_fault_controller.CommandFaultController,
]


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotRunError(f"{category} boundary changed")
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


def runner_source_sha256() -> str:
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
        raise PilotRunError("pilot run source is unavailable") from error
    return _hash({"files": files})


def _owner_request(
    path: Path,
) -> tuple[object, bytes, Any]:
    try:
        path = control_artifacts._absolute_path(
            str(path),
            "pilot live invocation",
        )
        return control_artifacts._read_owner_document(path)
    except control_artifacts.ControlArtifactError as error:
        raise PilotRunError(
            "pilot live invocation is unavailable"
        ) from error


def _descriptor(
    value: object,
    category: str,
) -> tuple[dict[str, str], Any]:
    raw = _exact(value, {"file", "file_sha256"}, category)
    try:
        path = control_artifacts._absolute_path(
            raw["file"],
            f"{category} file",
        )
        payload, metadata = control_artifacts._read_owner_bytes(
            path,
            maximum_bytes=1024 * 1024,
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotRunError(f"{category} is unavailable") from error
    descriptor = {
        "file": str(path),
        "file_sha256": _payload_hash(payload),
    }
    if raw != descriptor:
        raise PilotRunError(f"{category} changed")
    return descriptor, metadata


def _request(
    value: object,
) -> tuple[
    Path,
    Path,
    Path,
    Path,
    Mapping[str, Any],
]:
    raw = _exact(
        value,
        {
            "controller",
            "deployment_inputs",
            "readiness",
            "runner_source_sha256",
            "schedule_directory",
            "schema",
        },
        "pilot live invocation",
    )
    if (
        raw["schema"] != REQUEST_SCHEMA
        or raw["runner_source_sha256"] != runner_source_sha256()
    ):
        raise PilotRunError("pilot live invocation binding changed")

    # Readiness and the qualified schedule are deliberately checked before
    # controller configuration, boto3, or credential environment access.
    readiness, readiness_metadata = _descriptor(
        raw["readiness"],
        "pilot live readiness",
    )
    try:
        schedule_directory = control_artifacts._absolute_path(
            raw["schedule_directory"],
            "pilot live schedule directory",
        )
        schedule, _ = pilot_executor._schedule_output(
            schedule_directory,
            Path(readiness["file"]),
        )
    except (
        control_artifacts.ControlArtifactError,
        pilot_executor.PilotExecutorError,
        pilot_schedule.PilotScheduleError,
    ) as error:
        raise PilotRunError(
            "pilot live schedule is not qualified"
        ) from error

    deployment, deployment_metadata = _descriptor(
        raw["deployment_inputs"],
        "pilot deployment input request",
    )
    controller, controller_metadata = _descriptor(
        raw["controller"],
        "pilot fault controller configuration",
    )
    try:
        control_artifacts._distinct_inputs(
            [
                (Path(readiness["file"]), readiness_metadata),
                (Path(deployment["file"]), deployment_metadata),
                (Path(controller["file"]), controller_metadata),
            ]
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotRunError("pilot live inputs alias") from error
    return (
        schedule_directory,
        Path(readiness["file"]),
        Path(deployment["file"]),
        Path(controller["file"]),
        schedule,
    )


def run_file(
    invocation_path: Path,
    *,
    client_factory: pilot_actions.pilot_rgw_actions.ClientFactory = (
        pilot_actions.pilot_rgw_actions.default_client_factory
    ),
    clocks: Mapping[
        str,
        pilot_actions.pilot_rgw_actions.rgw_live_adapter.Clock,
    ]
    | None = None,
    controller_loader: ControllerLoader = (
        pilot_fault_controller.CommandFaultController.load
    ),
) -> dict[str, Any]:
    value, invocation_payload, invocation_metadata = _owner_request(
        invocation_path
    )
    (
        schedule_directory,
        readiness_path,
        deployment_path,
        controller_path,
        schedule,
    ) = _request(value)
    try:
        control_artifacts._distinct_inputs(
            [
                (
                    control_artifacts._absolute_path(
                        str(invocation_path),
                        "pilot live invocation",
                    ),
                    invocation_metadata,
                ),
                (
                    deployment_path,
                    control_artifacts._read_owner_bytes(
                        deployment_path,
                        maximum_bytes=1024 * 1024,
                    )[1],
                ),
                (
                    controller_path,
                    control_artifacts._read_owner_bytes(
                        controller_path,
                        maximum_bytes=1024 * 1024,
                    )[1],
                ),
                (
                    readiness_path,
                    control_artifacts._read_owner_bytes(
                        readiness_path,
                        maximum_bytes=1024 * 1024,
                    )[1],
                ),
            ]
        )
        deployment_result = pilot_inputs.render_file(deployment_path)
        controller = controller_loader(controller_path)
        adapter = pilot_actions.PilotActionAdapter.load(
            schedule_directory,
            readiness_path,
            client_factory=client_factory,
            controller=controller,
            clocks=clocks,
        )
    except (
        control_artifacts.ControlArtifactError,
        pilot_inputs.PilotInputError,
        pilot_fault_controller.PilotFaultControllerError,
        pilot_actions.PilotActionError,
    ) as error:
        raise PilotRunError(
            "pilot live dependencies are unavailable"
        ) from error
    if (
        deployment_result["schedule_sha256"]
        != schedule["schedule_sha256"]
    ):
        raise PilotRunError("pilot deployment schedule changed")
    adapter.source_sha256 = _hash(
        {
            "adapter_source_sha256": adapter.source_sha256,
            "invocation_file_sha256": _payload_hash(invocation_payload),
            "runner_source_sha256": runner_source_sha256(),
        }
    )
    try:
        return pilot_executor.execute(
            schedule_directory,
            readiness_path,
            adapter=adapter,
        )
    except (
        pilot_executor.PilotExecutorError,
        pilot_schedule.PilotScheduleError,
        pilot_actions.PilotActionError,
        pilot_actions.pilot_rgw_actions.PilotRgwActionError,
        pilot_actions.pilot_fault_actions.PilotFaultActionError,
        pilot_actions.pilot_phase_actions.PilotPhaseActionError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        raise PilotRunError("pilot live execution failed") from error


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_hash = runner_source_sha256()
        except PilotRunError:
            print("pilot-run-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "runner_source_sha256": source_hash,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 2 or arguments[0] != "run":
        print("pilot-run-refused", file=sys.stderr)
        return 2
    try:
        result = run_file(Path(arguments[1]))
    except PilotRunError:
        print("pilot-run-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "result_sha256": result["result_sha256"],
                "schema": pilot_executor.RESULT_SCHEMA,
                "synthetic": result["synthetic"],
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
