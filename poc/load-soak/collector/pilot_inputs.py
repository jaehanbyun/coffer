from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
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
    "coffer_stage6_pilot_inputs_executor",
    DIRECTORY / "pilot_executor.py",
)
pilot_schedule = pilot_executor.pilot_schedule
rgw_live_adapter = pilot_schedule.rgw_live_adapter
control_artifacts = pilot_schedule.control_artifacts
render_target = pilot_schedule.render_target
native_target = pilot_schedule.native_target
pilot_phase_actions = _module(
    "coffer_stage6_pilot_inputs_phase_actions",
    DIRECTORY / "pilot_phase_actions.py",
)
phase_preparation = pilot_phase_actions.phase_preparation

REQUEST_SCHEMA = "coffer.stage6-pilot-deployment-input-request/v1"
RESULT_SCHEMA = "coffer.stage6-pilot-deployment-input-result/v1"
SOURCE_RESULT_SCHEMA = (
    "coffer.stage6-pilot-deployment-input-source-result/v1"
)
SOURCE_FILES = (
    DIRECTORY / "phase_preparation.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
    DIRECTORY / "pilot_phase_actions.py",
    DIRECTORY / "pilot_inputs.py",
)


class PilotInputError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotInputError(f"{category} boundary changed")
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


def renderer_source_sha256() -> str:
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
        raise PilotInputError(
            "pilot deployment input source is unavailable"
        ) from error
    return _hash({"files": files})


def _descriptor(
    value: object,
    category: str,
) -> tuple[dict[str, str], object, os.stat_result]:
    try:
        return pilot_phase_actions._descriptor(value, category)
    except pilot_phase_actions.PilotPhaseActionError as error:
        raise PilotInputError(f"{category} is invalid") from error


def _read_request(path: Path) -> tuple[object, bytes, os.stat_result]:
    try:
        return control_artifacts._read_owner_document(path)
    except control_artifacts.ControlArtifactError as error:
        raise PilotInputError(
            "pilot deployment input request is unavailable"
        ) from error


def _server(value: object) -> dict[str, Any]:
    try:
        server = phase_preparation._server_settings(value)
    except phase_preparation.PhasePreparationError as error:
        raise PilotInputError(
            "pilot evidence server settings are invalid"
        ) from error
    return {
        key: server[key]
        for key in (
            "bind_address",
            "certificate",
            "max_concurrency",
            "port",
            "private_key",
            "request_timeout_seconds",
            "server_name",
            "server_source_sha256",
        )
    }


def _phase(
    value: object,
    *,
    phase: str,
    config: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "collector_inputs",
            "evidence_server",
            "target",
        },
        f"{phase} pilot deployment inputs",
    )
    target, target_value, target_metadata = _descriptor(
        raw["target"],
        f"{phase} native target",
    )
    try:
        validated_target, _ = control_artifacts._validated_target(
            target_value
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotInputError(
            f"{phase} native target is invalid"
        ) from error
    if validated_target["target_sha256"] != config["target_sha256"]:
        raise PilotInputError(f"{phase} native target changed")
    inputs_raw = _exact(
        raw["collector_inputs"],
        pilot_phase_actions.COLLECTOR_INPUT_NAMES,
        f"{phase} static collector inputs",
    )
    inputs: dict[str, dict[str, str]] = {}
    metadata: list[tuple[Path, os.stat_result]] = [
        (Path(target["file"]), target_metadata)
    ]
    for name in sorted(inputs_raw):
        descriptor, document, details = _descriptor(
            inputs_raw[name],
            f"{phase} {name.replace('_', ' ')}",
        )
        if not isinstance(document, Mapping):
            raise PilotInputError(
                f"{phase} {name.replace('_', ' ')} is invalid"
            )
        bindings = {
            "phase": phase,
            "target_file": target["file"],
            "target_file_sha256": target["file_sha256"],
            "target_sha256": config["target_sha256"],
            "window_sha256": config["window_sha256"],
        }
        if any(
            key in document and document[key] != expected
            for key, expected in bindings.items()
        ):
            raise PilotInputError(
                f"{phase} {name.replace('_', ' ')} binding changed"
            )
        inputs[name] = descriptor
        metadata.append((Path(descriptor["file"]), details))
    try:
        control_artifacts._distinct_inputs(metadata)
    except control_artifacts.ControlArtifactError as error:
        raise PilotInputError(
            f"{phase} deployment inputs alias"
        ) from error
    return {
        "collector_inputs": inputs,
        "evidence_server": _server(raw["evidence_server"]),
        "materializer_source_sha256": (
            pilot_phase_actions.adapter_source_sha256()
        ),
        "phase": phase,
        "preparer_source_sha256": (
            phase_preparation.preparer_source_sha256()
        ),
        "schedule_sha256": schedule["schedule_sha256"],
        "schema": pilot_phase_actions.COLLECTOR_INPUT_SCHEMA,
        "target": target,
        "window_sha256": config["window_sha256"],
    }


def _request(
    value: object,
) -> tuple[
    Path,
    Path,
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    raw = _exact(
        value,
        {
            "phases",
            "readiness",
            "renderer_source_sha256",
            "schedule_directory",
            "schema",
        },
        "pilot deployment input request",
    )
    if (
        raw["schema"] != REQUEST_SCHEMA
        or raw["renderer_source_sha256"] != renderer_source_sha256()
    ):
        raise PilotInputError(
            "pilot deployment input request binding changed"
        )
    try:
        readiness, _, _, _ = pilot_schedule._owner_document(
            raw["readiness"],
            "pilot deployment readiness",
        )
    except pilot_schedule.PilotScheduleError as error:
        raise PilotInputError(
            "pilot deployment readiness is invalid"
        ) from error
    try:
        schedule_directory = control_artifacts._absolute_path(
            raw["schedule_directory"],
            "pilot schedule directory",
        )
        schedule, _ = pilot_executor._schedule_output(
            schedule_directory,
            Path(readiness["file"]),
        )
    except (
        control_artifacts.ControlArtifactError,
        pilot_executor.PilotExecutorError,
    ) as error:
        raise PilotInputError(
            "pilot deployment schedule is unavailable"
        ) from error
    phases_raw = _exact(
        raw["phases"],
        set(native_target.PHASES),
        "pilot deployment phase set",
    )
    phases: dict[str, dict[str, Any]] = {}
    for phase in native_target.PHASES:
        try:
            config, _, _ = rgw_live_adapter._read_config(
                schedule_directory
                / pilot_schedule.PHASE_CONFIG_FILES[phase]
            )
        except rgw_live_adapter.RgwLiveAdapterError as error:
            raise PilotInputError(
                f"{phase} pilot configuration is unavailable"
            ) from error
        phases[phase] = _phase(
            phases_raw[phase],
            phase=phase,
            config=config,
            schedule=schedule,
        )
    runtime = Path(schedule["runtime_directory"])
    if runtime.name in {"", ".", ".."}:
        raise PilotInputError(
            "pilot deployment runtime is invalid"
        )
    return schedule_directory, runtime, schedule, phases


def _write(path: Path, value: object) -> None:
    try:
        render_target._atomic_write(path, _canonical(value))
    except render_target.RenderError as error:
        raise PilotInputError(
            "pilot deployment input output is unavailable"
        ) from error


def _result(
    *,
    phases: Mapping[str, Mapping[str, Any]],
    request_file_sha256: str,
    schedule: Mapping[str, Any],
) -> dict[str, Any]:
    unsigned = {
        "complete": True,
        "files_sha256": {
            phase: _payload_hash(_canonical(phases[phase]))
            for phase in native_target.PHASES
        },
        "renderer_source_sha256": renderer_source_sha256(),
        "request_file_sha256": request_file_sha256,
        "schedule_sha256": schedule["schedule_sha256"],
        "schema": RESULT_SCHEMA,
        "synthetic": False,
        "target_sha256": schedule["target_sha256"],
    }
    return {**unsigned, "result_sha256": _hash(unsigned)}


def _validate_existing(
    runtime: Path,
    *,
    phases: Mapping[str, Mapping[str, Any]],
    result: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        pilot_executor._runtime(
            schedule,
            allow_phase_directories=True,
        )
        actual_result, result_payload, _ = (
            control_artifacts._read_owner_document(
                runtime / pilot_executor.DEPLOYMENT_INPUT_RESULT_FILE
            )
        )
    except (
        pilot_executor.PilotExecutorError,
        control_artifacts.ControlArtifactError,
    ) as error:
        raise PilotInputError(
            "pilot deployment input runtime is invalid"
        ) from error
    if actual_result != result or result_payload != _canonical(result):
        raise PilotInputError(
            "pilot deployment input result changed"
        )
    for phase in native_target.PHASES:
        try:
            value, payload, _ = control_artifacts._read_owner_document(
                runtime / phase / "collector-inputs.json"
            )
        except control_artifacts.ControlArtifactError as error:
            raise PilotInputError(
                f"{phase} pilot deployment inputs are unavailable"
            ) from error
        if value != phases[phase] or payload != _canonical(phases[phase]):
            raise PilotInputError(
                f"{phase} pilot deployment inputs changed"
            )
    return json.loads(
        json.dumps(result, separators=(",", ":"), sort_keys=True)
    )


def _remove(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise PilotInputError(
            "pilot deployment input cleanup failed"
        ) from error


def render_file(request_path: Path) -> dict[str, Any]:
    try:
        request_path = control_artifacts._absolute_path(
            str(request_path),
            "pilot deployment input request",
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotInputError(
            "pilot deployment input request is invalid"
        ) from error
    value, request_payload, _ = _read_request(request_path)
    _, runtime, schedule, phases = _request(value)
    result = _result(
        phases=phases,
        request_file_sha256=_payload_hash(request_payload),
        schedule=schedule,
    )
    if runtime.exists() or runtime.is_symlink():
        return _validate_existing(
            runtime,
            phases=phases,
            result=result,
            schedule=schedule,
        )
    try:
        parent = runtime.parent.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700
            or parent.st_uid != os.getuid()
        ):
            raise PilotInputError(
                "pilot deployment runtime parent is unsafe"
            )
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{runtime.name}.pilot-inputs.",
                dir=runtime.parent,
            )
        )
        staging.chmod(0o700)
    except OSError as error:
        raise PilotInputError(
            "pilot deployment input staging is unavailable"
        ) from error
    published = False
    try:
        for phase in native_target.PHASES:
            phase_directory = staging / phase
            phase_directory.mkdir(mode=0o700)
            _write(
                phase_directory / "collector-inputs.json",
                phases[phase],
            )
        _write(
            staging / pilot_executor.DEPLOYMENT_INPUT_RESULT_FILE,
            result,
        )
        os.replace(staging, runtime)
        published = True
        directory = os.open(
            runtime.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        validated = _validate_existing(
            runtime,
            phases=phases,
            result=result,
            schedule=schedule,
        )
        if validated != result:
            raise PilotInputError(
                "pilot deployment input publication changed"
            )
        return validated
    except BaseException:
        if published and runtime.exists() and not staging.exists():
            try:
                os.replace(runtime, staging)
            except OSError as error:
                raise PilotInputError(
                    "pilot deployment input rollback failed"
                ) from error
        _remove(staging)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_hash = renderer_source_sha256()
        except PilotInputError:
            print("pilot-inputs-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "renderer_source_sha256": source_hash,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 2 or arguments[0] != "render":
        print("pilot-inputs-refused", file=sys.stderr)
        return 2
    try:
        result = render_file(Path(arguments[1]))
    except (
        PilotInputError,
        pilot_executor.PilotExecutorError,
        pilot_schedule.PilotScheduleError,
        pilot_phase_actions.PilotPhaseActionError,
        phase_preparation.PhasePreparationError,
        control_artifacts.ControlArtifactError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        print("pilot-inputs-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "result_sha256": result["result_sha256"],
                "schema": RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
